#!/usr/bin/env python3
"""T6 paired CAW benchmark. Append/flush each row; reruns resume existing keys.

Examples:
  python3 scripts/t6_nn_astar_bench.py --seeds 0-29 --styles random_obstacles_zones
  python3 scripts/t6_nn_astar_bench.py --seeds 0-2 --styles random_obstacles_zones,jitter_rows

Times measure cold-cache planning only. Safety uses execution.build's planning
check; failures retain null metrics. Statistics use paired successful scenes,
with two-sided Student t and signed-rank tests (zeros dropped, ties averaged).
Baseline JSON maps 'style/seed' to the default plan fingerprint, including failed
plans. Existing CSV rows are trusted on resume; use a fresh --out after changes.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import at, build as evaluate
from execution import build
from planning import configuration, fingerprint
from planning.planner import fixed_y_lanes
from planning.routing3d import clear_cache
from planner_api import make_planner
from random_scene import generate_with_report

STYLES = ('random_obstacles_zones', 'jitter_rows', 'clusters_gaps', 'size_mix')
STRATEGIES = ('nn+2opt', 'nn_astar')
METRICS = ('path_length', 'total_time', 'transit_time')
FIELDS = ('style seed seed_used strategy status reason plan_hash repeat_plan_hash '
          'deterministic path_length total_time spray_seconds transit_time transit_length '
          'safety safety_violations search_nodes matrix_mode order order_cost n_lanes '
          'wall_seconds').split()


def seeds(text):
    if '-' in text:
        a, b = map(int, text.split('-'))
        values = list(range(a, b + 1))
    else:
        values = list(dict.fromkeys(map(int, text.split(','))))
    if not values or min(values) < 0:
        raise argparse.ArgumentTypeError('seeds 必须为非负整数或递增范围')
    return values


def beta_fraction(a, b, x):
    """Continued fraction for the regularized incomplete beta (Student t CDF)."""
    tiny = 1e-300
    c = 1.0
    d = 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 501):
        for aa in (m * (b - m) * x / ((a + 2*m - 1) * (a + 2*m)),
                   -(a + m) * (a + b + m) * x / ((a + 2*m) * (a + 2*m + 1))):
            d = 1 + aa * d
            c = 1 + aa / c
            d = 1 / (d if abs(d) > tiny else tiny)
            c = c if abs(c) > tiny else tiny
            delta = d * c
            h *= delta
        if abs(delta - 1) < 3e-14:
            return h
    raise ArithmeticError('incomplete beta did not converge')


def beta_cdf(x, a, b):
    if x <= 0 or x >= 1:
        return float(x >= 1)
    front = math.exp(math.lgamma(a+b) - math.lgamma(a) - math.lgamma(b)
                     + a*math.log(x) + b*math.log1p(-x))
    if x < (a+1)/(a+b+2):
        return front * beta_fraction(a, b, x) / a
    return 1 - front * beta_fraction(b, a, 1-x) / b


def describe(values):
    return dict(n=len(values), mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values) > 1 else (0.0 if values else None))


def paired_tests(deltas):
    result = dict(delta=describe(deltas), paired_t=None, wilcoxon=None)
    n = len(deltas)
    if n > 1:
        mean, sd = statistics.mean(deltas), statistics.stdev(deltas)
        t = mean / (sd / math.sqrt(n)) if sd else None
        p = beta_cdf((n-1)/(n-1+t*t), (n-1)/2, 0.5) if sd else float(mean == 0)
        result['paired_t'] = dict(t=t, df=n-1, p_two_sided=p,
                                  degenerate=sd == 0)
    nonzero = sorted((abs(d), d > 0) for d in deltas if d != 0)
    ranks = []
    i = 0
    while i < len(nonzero):
        j = i + 1
        while j < len(nonzero) and nonzero[j][0] == nonzero[i][0]:
            j += 1
        ranks.extend(((i + 1 + j) / 2, sign) for _, sign in nonzero[i:j])
        i = j
    if not n:
        return result
    positive = sum(r for r, sign in ranks if sign)
    total = sum(r for r, _ in ranks)
    w = min(positive, total-positive)
    if len(ranks) <= 20:
        # Integer doubled ranks permit exact enumeration with ties.
        counts = {0: 1}
        for rank, _ in ranks:
            shifted = dict(counts)
            for value, count in counts.items():
                key = value + int(2*rank)
                shifted[key] = shifted.get(key, 0) + count
            counts = shifted
        p = min(1.0, 2 * sum(c for v, c in counts.items() if v <= round(2*w)) / 2**len(ranks))
        method = 'exact sign permutations'
    else:
        variance = sum(r*r for r, _ in ranks) / 4
        z = max(0, abs(positive-total/2)-0.5) / math.sqrt(variance)
        p = math.erfc(z/math.sqrt(2))
        method = 'normal, tie-adjusted variance, continuity correction'
    result['wilcoxon'] = dict(w=w, n_nonzero=len(ranks), p_two_sided=p, method=method)
    return result


def run_one(scene, report, style, seed, strategy):
    row = dict(style=style, seed=seed, seed_used=report['seed_used'], strategy=strategy,
               status='failed', reason='', safety='not_run', safety_violations=0)
    config = configuration({})
    row['n_lanes'] = len(fixed_y_lanes(scene, config)['lanes'])
    options = dict(order_strategy=strategy, step_xy=1.0, objective='time')
    clear_cache()
    start = time.perf_counter()
    try:
        plan = make_planner('caw').plan(scene, config, options=options)
    finally:
        row['wall_seconds'] = time.perf_counter() - start
    row.update(status=plan['status'], reason=plan.get('reason', ''), plan_hash=fingerprint(plan))
    if style == STYLES[0] and strategy == STRATEGIES[0]:
        clear_cache()
        # Omit strategy on the repeat to also verify the default option path.
        repeat = make_planner('caw').plan(scene, config, options=dict(step_xy=1.0, objective='time'))
        row['repeat_plan_hash'] = fingerprint(repeat)
        row['deterministic'] = row['plan_hash'] == row['repeat_plan_hash']
    order = plan.get('order_search', {})
    row.update(search_nodes=plan.get('search', {}).get('expanded'),
               matrix_mode=order.get('matrix_mode'),
               order=json.dumps(order.get('order', plan.get('order'))))
    bound, gap = order.get('lower_bound'), order.get('gap_to_bound_abs')
    row['order_cost'] = order.get('order_cost')
    if row['order_cost'] is None and bound is not None and gap is not None:
        row['order_cost'] = bound + gap
    if plan['status'] != 'success':
        return row
    try:
        timeline = build(scene, plan)  # includes full safety/geometry check
    except ValueError as error:
        row.update(status='failed', reason=str(error), safety='fail', safety_violations=1)
        return row
    metrics = at(evaluate(scene, plan, timeline), timeline, timeline['duration'])
    row.update(safety='pass', total_time=timeline['duration'],
               spray_seconds=metrics['spray_seconds'],
               path_length=sum(s['length'] for s in timeline['segments']),
               transit_length=sum(s['length'] for s in timeline['segments'] if not s['spray']),
               transit_time=timeline['duration']-metrics['spray_seconds'])
    if row['order_cost'] is None:
        # Failed matrix edges can disable the lower bound. Reuse cached routes
        # only in this uncommon case; never include this in planning runtime.
        from planning.order import solve_order
        from planning.drift import expand_sensitive_inward
        effective_scene = expand_sensitive_inward(scene, config)
        layout = fixed_y_lanes(effective_scene, config)
        row['order_cost'] = solve_order(effective_scene, config, layout['lanes'],
                                       strategy=strategy,
                                       home=[*plan["segments"][0]["start"][:2], layout["work_height"]])['order_cost']
    return row


def summarize(rows):
    output = {}
    for style in sorted({r['style'] for r in rows}):
        selected = [r for r in rows if r['style'] == style]
        summary = dict(strategies={}, paired={})
        for strategy in STRATEGIES:
            group = [r for r in selected if r['strategy'] == strategy]
            ok = [r for r in group if r['status'] == 'success']
            summary['strategies'][strategy] = dict(
                count=len(group), successes=len(ok), failures=len(group)-len(ok),
                safety_violations=sum(int(r['safety_violations']) for r in group),
                runtime_sum=sum(float(r['wall_seconds'] or 0) for r in group),
                metrics={k: describe([float(r[k]) for r in ok if r[k] != '']) for k in METRICS})
        pairs = {s: {r['seed']: r for r in selected if r['strategy'] == s and r['status'] == 'success'} for s in STRATEGIES}
        common = sorted(pairs[STRATEGIES[0]].keys() & pairs[STRATEGIES[1]].keys(), key=int)
        for key in METRICS:
            summary['paired'][key] = paired_tests([float(pairs[STRATEGIES[1]][s][key])-float(pairs[STRATEGIES[0]][s][key]) for s in common])
        output[style] = summary
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=seeds, default=seeds('0-29'))
    parser.add_argument('--styles', default=','.join(STYLES))
    parser.add_argument('--out', type=Path, default=ROOT/'results/t6_nn_astar_rows.csv')
    parser.add_argument('--stats', type=Path, default=ROOT/'results/t6_nn_astar_stats.json')
    parser.add_argument('--hash-baseline', type=Path)
    parser.add_argument('--write-baseline', type=Path)
    args = parser.parse_args()
    styles = list(dict.fromkeys(args.styles.split(',')))
    if not styles or any(s not in STYLES for s in styles):
        parser.error('未知场景样式')
    rows = []
    if args.out.exists():
        with args.out.open(newline='', encoding='utf8') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != FIELDS:
                parser.error('已有 CSV 列不匹配；请使用新的 --out')
            rows = list(reader)
    done = {(r['style'], int(r['seed']), r['strategy']) for r in rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('a', newline='', encoding='utf8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
            stream.flush()
        for style in styles:
            for seed in args.seeds:
                pending = [s for s in STRATEGIES if (style, seed, s) not in done]
                print(f'{style} seed={seed}: {pending or "resume skip"}', flush=True)
                if not pending:
                    continue
                try:
                    # Matches generate()/existing benches: geometry retries for
                    # random_obstacles_zones, no reachability-based seed filtering.
                    scene, report = generate_with_report(style, seed, require_reachable=False)
                    generation_error = None
                except ValueError as error:
                    generation_error = str(error)
                for strategy in pending:
                    print(f'  planning {strategy} ...', flush=True)
                    try:
                        if generation_error is not None:
                            raise ValueError(generation_error)
                        row = run_one(scene, report, style, seed, strategy)
                    except (ValueError, KeyError, TypeError) as error:
                        row = dict(style=style, seed=seed, strategy=strategy, status='failed',
                                   reason=str(error), safety='not_run', safety_violations=0)
                    writer.writerow(row)
                    stream.flush()
                    rows.append({k: '' if row.get(k) is None else str(row[k]) for k in FIELDS})
                    print(f'  {row["status"]}: wall={row.get("wall_seconds")} reason={row["reason"]}', flush=True)
    selected = [r for r in rows if r['style'] in styles and int(r['seed']) in args.seeds]
    hashes = {f'{r["style"]}/{r["seed"]}': r['plan_hash'] for r in selected
              if r['style'] == STYLES[0] and r['strategy'] == STRATEGIES[0] and r['plan_hash']}
    mismatches = []
    if args.hash_baseline:
        baseline = json.loads(args.hash_baseline.read_text())
        mismatches = [k for k, value in hashes.items() if baseline.get(k) != value]
        mismatches += [f'{STYLES[0]}/{s}' for s in args.seeds
                       if STYLES[0] in styles and f'{STYLES[0]}/{s}' not in hashes]
    if args.write_baseline:
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(json.dumps(hashes, indent=2)+'\n')
    stats = dict(styles=summarize(selected), baseline_mismatches=mismatches,
                 deterministic=all(r['deterministic'] == 'True' for r in selected
                                   if r['style'] == STYLES[0] and r['strategy'] == STRATEGIES[0]),
                 note='Sample SD; paired differences nn_astar - nn+2opt; successful pairs only. '
                      'Cold planning runtime excludes generation, hash repeat and evaluation. '
                      'Safety violations count failed safety checks, not individual collisions.')
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, allow_nan=False)+'\n')
    print('\n| Style | Strategy | Success | Safety violations | Planning seconds |')
    print('|---|---|---:|---:|---:|')
    for style, summary in stats['styles'].items():
        for strategy, s in summary['strategies'].items():
            print(f'| {style} | {strategy} | {s["successes"]}/{s["count"]} | {s["safety_violations"]} | {s["runtime_sum"]:.3f} |')
        for key, test in summary['paired'].items():
            d = test['delta']
            print(f'\n{style} Δ {key}: {d["mean"]} ± {d["sd"]} (n={d["n"]})')
    print(f'\nCSV: {args.out}\nStats: {args.stats}\nHash mismatches: {mismatches}')
    return int(bool(mismatches) or not stats['deterministic'] or
               any(r['safety'] == 'fail' for r in selected))


if __name__ == '__main__':
    raise SystemExit(main())
