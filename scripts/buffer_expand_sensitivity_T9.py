"""敏感性附录 only: 约束（孔令标 2026），非创新点。

Fixed-y generate_plan (not CAW) for a feasible 40-cell appendix; no planning edits.
Island skip is unchanged. OFF uses original zone max-x as F: S_h == B-boundary.
Run: python3 scripts/buffer_expand_sensitivity_T9.py --workers 4
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import a_trial_heading as H
from a_trial_extra_runs import _boundary_offset
from a_trial_eval import evaluate
from planning import configuration, fingerprint, generate_plan
from planning.drift import resolve_effective_buffer
from planning.model import _digest

METRICS = ('A_extra_tau0', 'A_extra_tau0.5', 'A_extra_tau1',
           'A_excluded', 'violations', 'path_length', 'total_time')


def run(task):
    seed, U, expand, scheme = task
    row = dict(seed=seed, U=U, buffer_expand=expand, scheme=scheme, heading=0,
               eval_resolution=0.05, status='error', reason='')
    # Populate required columns even for failed cells; never substitute zero.
    row.update({k: None for k in (*METRICS, 'plan_hash', 'segment_digest', 'd_effective')})
    try:
        scene = H.scene0(seed)
        raw = {**H.JOB, 'swath': 2.0, 'drift_mode': 'sort', 'wind_speed': U,
               'wind_direction': 0.0, 'buffer_expand': expand, 'min_buffer': 0.0,
               'drift_buffer': 0.0}
        c = configuration(raw)
        d = resolve_effective_buffer(c)
        row['d_effective'] = d
        assert d == ({2: 10, 4: 16}[U] if expand else 0), (U, expand, d)
        if not expand:
            # _boundary_offset's diagnostic calls heuristic_offset(d=0), which
            # requires swept faces. Use its identical h=0 boundary formula.
            edge = max(v[0] for z in scene['no_spray_zones'] for v in z['footprint']['vertices'])
            xmin = min(t['geometry']['center'][0] - t['geometry']['radius'] for t in scene['targets'])
            offset = (xmin - edge) % c['swath']
        elif scheme == 'S_h':
            offset = H.heuristic_offset(scene, d, 0.0, c['swath'])[0]
        else:
            offset = _boundary_offset(scene, 0, d, c['swath'], row)[0]
        row['offset'] = offset
        H.install_lane_offset(offset)
        plan = generate_plan(scene, raw)
        row.update(status=plan.get('status'), reason=plan.get('reason', ''),
                   stage=plan.get('stage'), plan_hash=fingerprint(plan),
                   segment_digest=_digest(plan.get('segments', [])))
        if row['status'] == 'success':
            ev = evaluate(scene, plan['segments'], d, 0.0, c['swath'], c['speed'], c,
                          taus=(0.0, 0.5, 1.0), resolutions=(0.05,))
            row.update({k: ev[k] for k in METRICS})
    except Exception:
        row.update(status='error', reason=traceback.format_exc())
    return row


def contrasts(rows):
    lookup = {(r['seed'], r['U'], r['buffer_expand'], r['scheme']): r for r in rows}
    result = []
    for U in (2, 4):
        for tau in (0, 0.5, 1):
            key = f'A_extra_tau{tau:g}'
            entry = dict(U=U, tau=tau)
            for label, left, right in (
                ('S_h_minus_B_OFF', (0, 'S_h'), (0, 'B-boundary')),
                ('S_h_minus_B_ON', (1, 'S_h'), (1, 'B-boundary')),
                ('ON_minus_OFF_S_h', (1, 'S_h'), (0, 'S_h')),
                ('ON_minus_OFF_B', (1, 'B-boundary'), (0, 'B-boundary'))):
                pairs = [(lookup[(s, U, *left)], lookup[(s, U, *right)]) for s in range(5)]
                values = [a[key] - b[key] for a, b in pairs if a['status'] == b['status'] == 'success']
                entry[label] = dict(n=len(values), mean=statistics.mean(values) if values else None)
            result.append(entry)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    prefix = ROOT / 'results' / f'buffer_expand_sensitivity_T9_{sha[:7]}'
    sources = ['scripts/buffer_expand_sensitivity_T9.py', 'scripts/a_trial_heading.py',
               'scripts/a_trial_extra_runs.py', 'scripts/a_trial_eval.py',
               'planning/planner.py', 'planning/drift.py', 'planning/model.py']
    meta = dict(base_commit=sha, planner='fixed-y planning.generate_plan; not CAW',
                seeds=list(range(5)), U=[2, 4], heading=0, swath=2.0,
                buffer_expand=[0, 1], taus=[0, 0.5, 1], eval_resolution=0.05,
                workers=args.workers, job=H.JOB,
                OFF_definition='original no-spray max-x edge as F; S_h == B-boundary',
                labels='敏感性附录；约束（孔令标 2026）；非创新点；岛状禁喷不外扩语义未改',
                source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources})
    rows = []
    with prefix.with_suffix('.log').open('w') as log:
        def emit(value):
            line = json.dumps(value, ensure_ascii=False)
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()
        emit(meta)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run, (s, u, e, scheme)) for s in range(5)
                       for u in (2, 4) for e in (0, 1) for scheme in ('S_h', 'B-boundary')]
            for future in as_completed(futures):
                row = future.result()
                row['base_commit'] = sha
                rows.append(row)
                emit(row)
        rows.sort(key=lambda r: (r['seed'], r['U'], r['buffer_expand'], r['scheme']))
        with prefix.with_suffix('.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
            writer.writeheader()
            writer.writerows(rows)
        meta.update(contrasts=contrasts(rows), rows_full=rows,
                    failures=[r for r in rows if r['status'] != 'success'])
        prefix.with_suffix('.summary.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
        emit(dict(completed=len(rows), failures=len(meta['failures'])))
    return int(bool(meta['failures']))


if __name__ == '__main__':
    raise SystemExit(main())
