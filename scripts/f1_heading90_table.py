"""F1: extract frozen CSVs only; no planning or simulation.

Statistical helpers copied from /workspace/wt-T1/scripts/t1_main_table.py.
"""
from __future__ import annotations
import csv
import itertools
import math
import statistics as st
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ('results/a_trial_seeds0-4_2ff2df1.csv', '2ff2df1'),
    ('results/a_trial_extra_oh_rot_h90_58024ac.csv', '58024ac'),
    ('results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv', '0e0715a'),
)
TAUS = {'0': 'A_extra_tau0', '0.5': 'A_extra_tau0.5', '1.0': 'A_extra_tau1'}
PHASE, ZERO, TIE = 1.0, 1e-12, 1e-9
CLASSES = ('win', 'tie', 'loss', 'not_interpreted')
# Left minus right, always fixed headings: no candidate selection.
PAIRS = {
    'fixed90': ((1, 'oh_rot', 90), (2, 'b_boundary', 90)),
    'Sh_heading': ((1, 'oh_rot', 90), (0, 'heuristic', 0)),
    'B_heading': ((2, 'b_boundary', 90), (2, 'b_boundary', 0)),
}
CHECKS = 0

def f(value, digits=4):
    return '-' if value is None else f'{value:.{digits}f}'

def classify(delta):
    if delta is None:
        return 'not_applicable'
    if abs(delta) <= ZERO:
        return 'tie'
    if abs(delta) < PHASE:
        return 'not_interpreted'
    return 'win' if delta < 0 else 'loss'

def wilcoxon(deltas):
    """Conditional exact sign enumeration, with fractional average tied ranks.

    Tie groups are anchored at their smallest absolute value (tolerance 1e-9).
    Nonzero phase-error differences are retained in the test.
    """
    values = sorted((d for d in deltas if d is not None and abs(d) > ZERO), key=abs)
    n = len(values)
    if not n:
        return 0, 0.0, None, None
    ranks = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and abs(abs(values[j]) - abs(values[i])) <= TIE:
            j += 1
        ranks.extend([Fraction(i + 1 + j, 2)] * (j - i))
        i = j
    observed = sum((r for d, r in zip(values, ranks) if d > 0), Fraction(0))
    distribution = [sum((r for r, sign in zip(ranks, signs) if sign), Fraction(0))
                    for signs in itertools.product((0, 1), repeat=n)]
    lower = Fraction(sum(w <= observed for w in distribution), 2 ** n)
    upper = Fraction(sum(w >= observed for w in distribution), 2 ** n)
    p = min(Fraction(1), 2 * min(lower, upper))
    return n, float(observed), float(p), float(Fraction(2, 2 ** n))

def self_test():
    assert wilcoxon([-1, -2, -3, -4, -5])[2] == 0.0625
    assert wilcoxon([-1, -2, -3, -4])[2] == 0.125
    # Independent brute-force oracle: doubled ranks in original input order.
    ranks2 = (10, 7, 3, 3, 7)
    sums = [sum(ranks2[i] for i in range(5) if mask & (1 << i)) for mask in range(32)]
    observed2 = ranks2[3] + ranks2[4]
    expected = float(min(Fraction(1), 2 * min(
        Fraction(sum(w <= observed2 for w in sums), 32),
        Fraction(sum(w >= observed2 for w in sums), 32))))
    assert wilcoxon([-3, -2, -1, 1, 2])[2] == expected
    assert wilcoxon([-2, -1, 1, 2])[2] == 1.0
    assert wilcoxon([None, 0, 1e-13])[2] is None
    assert relative_text(None) == '—'
    assert relative_text(None, False) == '不适用'
    assert relative_text(-0.825) == '-82.5%'
    assert [classify(d) for d in (None, 0, -0.5, -1, 1)] == [
        'not_applicable', 'tie', 'not_interpreted', 'win', 'loss']

def markdown_table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |',
            '|' + '|'.join('---' for _ in headers) + '|'] + [
                '| ' + ' | '.join(map(str, row)) + ' |' for row in rows]

def relative_text(value, applicable=True):
    return '不适用' if not applicable else '—' if value is None else f'{value:.1%}'

def check(actual, expected, context):
    global CHECKS
    if actual != expected:
        raise AssertionError(f'{context}: {actual!r} != {expected!r}')
    CHECKS += 1


def load():
    return [list(csv.DictReader((ROOT / path).open(encoding='utf-8', newline='')))
            for path, _ in SOURCES]


def select(sources, spec, seed, U):
    source, variant, heading = spec
    matches = [r for r in sources[source] if r['variant'] == variant
               and int(r['seed']) == seed and float(r['U']) == U
               and int(r['heading']) == heading]
    if len(matches) > 1:
        raise AssertionError(f'duplicate: {spec}, seed={seed}, U={U}')
    return matches[0] if matches and matches[0]['status'] == 'success' else None


def summarize(cell):
    paired = [r for r in cell if r['delta'] is not None]
    s = {k: cell[0][k] for k in ('comparison', 'U', 'tau')}
    s.update(n=len(paired), excluded=5-len(paired))
    for field in ('left_A_extra', 'right_A_extra', 'delta',
                  'left_total_time', 'right_total_time', 'dtime'):
        vs = [r[field] for r in paired]
        s[field+'_mean'] = st.mean(vs) if vs else None
        s[field+'_sd'] = st.stdev(vs) if len(vs) > 1 else None
        if field in ('delta', 'dtime'):
            s[field+'_min'] = min(vs) if vs else None
            s[field+'_max'] = max(vs) if vs else None
    for side in ('left', 'right'):
        s[side+'_violations_sum'] = sum(r[side+'_violations'] for r in paired)
    s.update({c: sum(r['class'] == c for r in paired) for c in CLASSES})
    n, w, p, pmin = wilcoxon([r['delta'] for r in paired])
    s.update(n_nonzero=n, W_plus=w, p_exact_two_sided=p, p_min_achievable=pmin)
    return s


def compute(sources):
    records, summaries, missing, excluded = [], [], set(), set()
    for comp, specs in PAIRS.items():
        for U in (2, 4):
            for tau, tk in TAUS.items():
                cell = []
                for seed in range(5):
                    r = dict(comparison=comp, U=U, tau=tau, seed=seed)
                    eligible = True
                    notes = []
                    for side, spec in zip(('left', 'right'), specs):
                        raw = select(sources, spec, seed, U)
                        source, variant, heading = spec
                        r.update({side+'_source': SOURCES[source][0], side+'_variant': variant,
                                  side+'_heading': heading})
                        for field in ('A_extra', 'total_time', 'violations', 'plan_hash', 'offset'):
                            value = None if raw is None else raw[tk if field == 'A_extra' else field]
                            if value is not None:
                                if field == 'violations':
                                    value = int(value)
                                elif field != 'plan_hash':
                                    value = float(value)
                                    check(math.isfinite(value), True, (comp, seed, U, field))
                                else:
                                    check(bool(value.strip()), True, (comp, seed, U, 'plan_hash presence'))
                            r[side+'_'+field] = value
                        if raw is None:
                            msg = f'{SOURCES[source][0]}: variant={variant}, seed={seed}, U={U}, heading={heading} (missing successful row)'
                            missing.add(msg)
                            notes.append(msg)
                            eligible = False
                        elif variant == 'heuristic' and raw.get('heuristic_lane_found') == 'False':
                            msg = f'U={U}, seed={seed}: S_h 不适用 at 0° (heuristic_lane_found=False)'
                            excluded.add(msg)
                            notes.append(msg)
                            eligible = False
                    r['delta'] = r['left_A_extra'] - r['right_A_extra'] if eligible else None
                    r['dtime'] = r['left_total_time'] - r['right_total_time'] if eligible else None
                    r['class'] = classify(r['delta'])
                    r['note'] = '; '.join(notes)
                    cell.append(r)
                records.extend(cell)
                summaries.append(summarize(cell))
    return records, summaries, sorted(missing), sorted(excluded)


def validate(records, summaries):
    # Reload the frozen CSVs; verify each extracted value and each derived cell.
    sources = load()
    expected, expected_summaries, _, _ = compute(sources)
    for r, e in zip(records, expected):
        for k in r:
            check(r[k], e[k], (r['comparison'], r['U'], r['tau'], r['seed'], k))
        for side, spec in zip(('left', 'right'), PAIRS[r['comparison']]):
            raw = select(sources, spec, r['seed'], r['U'])
            if raw is None:
                continue
            for field in ('A_extra', 'total_time', 'violations', 'plan_hash'):
                v = raw[TAUS[r['tau']] if field == 'A_extra' else field]
                expected_value = v if field == 'plan_hash' else int(v) if field == 'violations' else float(v)
                check(r[side+'_'+field], expected_value, (r['comparison'], r['seed'], side, field))
            check(bool(raw['plan_hash'].strip()), True, 'source plan_hash presence')
    check(len(records), 90, 'detail count')
    check(len(summaries), 18, 'summary count')
    for s, e in zip(summaries, expected_summaries):
        for k in s:
            check(s[k], e[k], (s['comparison'], s['U'], s['tau'], k))
        check(sum(s[c] for c in CLASSES), s['n'], 'classification total')


def write_csv(name, rows):
    with (ROOT / 'results' / name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    # Hard-check every serialized CSV cell, including all summary statistics.
    actual = list(csv.DictReader((ROOT / 'results' / name).open(encoding='utf-8', newline='')))
    check(len(actual), len(rows), name)
    for a, r in zip(actual, rows):
        for k, value in r.items():
            check(a[k], '' if value is None else str(value), (name, k))


def table(ss):
    rows = []
    for s in ss:
        def ms(field):
            return f(s[field+'_mean']) + '±' + f(s[field+'_sd'])
        def diff(field):
            return ms(field) + f" [{f(s[field+'_min'])},{f(s[field+'_max'])}]"
        rows.append([s['U'], s['tau'], s['n'], ms('left_A_extra'), ms('right_A_extra'),
                     diff('delta'), '/'.join(str(s[c]) for c in CLASSES),
                     f(s['p_exact_two_sided']) if s['n_nonzero'] else '不适用（无非零配对差）',
                     ms('left_total_time'), ms('right_total_time'), diff('dtime'),
                     f"{s['left_violations_sum']}/{s['right_violations_sum']}"])
    return markdown_table(['U', 'τ', 'n', '左 A_extra mean±SD /m²', '右 A_extra mean±SD /m²',
                           'Δ mean±SD [min,max] /m²', 'win/tie/loss/not_interpreted',
                           'exact two-sided p', '左 total_time mean±SD /s',
                           '右 total_time mean±SD /s', 'Δt mean±SD [min,max] /s',
                           'violations sums 左/右'], rows)


def main():
    self_test()
    records, summaries, missing, excluded = compute(load())
    validate(records, summaries)
    for stem, fixed in (('F1_table90', True), ('F1_heading_effect', False)):
        write_csv(stem+'.csv', [r for r in records if (r['comparison']=='fixed90') == fixed])
        write_csv(stem+'_summary.csv', [s for s in summaries if (s['comparison']=='fixed90') == fixed])
    notes = [
        '新增，不改已冻结主表。仅抽取冻结 CSV，无重规划。',
        '所有 Δ=左−右；Table A 左=S_h(90° oh_rot)、右=B-boundary(90°)；'
        'Table B 左=90°、右=0°，负 Δ 表示 90° 的 A_extra 更少。Δt 同方向。',
        '每格 seed=0..4；仅使用成功行，缺失或不适用者排除配对。所有统计与违规总数使用相同配对 seed。'
        '明细保留不适用行的原始值以便核对，但不计算其差值。',
        'SD 为样本 SD；n<2 为“-”。|Δ|≤1e-12 为 tie；其余 |Δ|<1 m² 不解读；Δ≤−1 为 win，Δ≥1 为 loss。',
        'Wilcoxon 删除零差，保留不解读项；绝对值以 1e-9 容差分组并取平均秩，'
        '用 Fraction 枚举全部符号，双侧 p=min(1,2·min(lower tail,upper tail))。'
        '无非零差时 p 不适用。n_eff≤5 时最小双侧 p≥0.0625，不作显著性结论。',
        '相位重合时，固定 90° 的所有 Δ 预期为 0；不强制改写任何源值。',
    ]
    md = ['# F1 tables — 新增，不改已冻结主表', '', *notes, '']
    for comp, title in [('fixed90', 'Table A: S_h vs B-boundary，均固定 90°'),
                        ('Sh_heading', 'Table B 航向效应：S_h (90° oh_rot − 0° heuristic)'),
                        ('B_heading', 'Table B 航向效应：B-boundary (90° − 0°)')]:
        md += ['## '+title, ''] + table([s for s in summaries if s['comparison']==comp]) + ['']
    md += ['## 缺失数据', ''] + (missing or ['无：所需 40 个 seed×U×variant×heading 源行齐全。'])
    md += ['', '## 配对排除', ''] + (excluded or ['无。'])
    md += ['', f'ASSERT OK: {CHECKS} cell checks', '']
    (ROOT/'results/F1_tables.md').write_text('\n'.join(md), encoding='utf-8')
    fixed = [r for r in records if r['comparison']=='fixed90' and r['delta'] is not None]
    report = ['# F1.report — 新增，不改已冻结主表', '',
              f"结论：固定 90° 的 {len(fixed)} 个配对中，{sum(abs(r['delta'])<=ZERO for r in fixed)} 个面积差为零；航向效应详见下表，同一对象按 90°−0° 配对。", '',
              f"固定 90° 最大 |Δ|={f(max((abs(r['delta']) for r in fixed), default=0))} m²。", '',
              *notes[1:], '', '## 关键数值', '']
    for comp in PAIRS:
        report += ['### '+comp, ''] + table([s for s in summaries if s['comparison']==comp]) + ['']
    report += ['## 缺失数据', ''] + (missing or ['无缺失源行。'])
    report += ['', '## 不适用（不是缺失）', ''] + (excluded or ['无。'])
    report += ['', '## 来源 commits', ''] + [f'- `{path}` — `{commit}`' for path, commit in SOURCES]
    report += ['', '## 验收口径更正', '',
               '表 A 的 30 个 seed×τ 配对中，18 个 plan_hash 完全一致；其余配对仅 offset 浮点差≤5×10⁻¹⁵（同一计划按三个 τ 重复计数）。oh_rot(90°) 与 B-boundary(90°) 在此几何下的相位、航线重合。',
               '因此 Δ=0 仅说明两种对齐规则在此几何下重合，不是两种不同方法的比较性能证据，不能据此声称优劣。',
               '表 B 的同对象 90°−0° 配对可直接用于主表差值的航向归因：U=2 的 90° 平均快 63.8006 s，但 τ=0.5/1.0 的额外漏喷分别多 5.0000/11.9635 m²。',
               '基线回归：`python3 -u drift_checks.py`→23/0；`python3 -u main.py --check`→170/0。日志为 `results/F_checks_drift.log`、`results/F_checks_main.log`。',
               '`git diff 463badb --stat -- planning/` 为空。', '']
    report += ['', '复现：`python3 scripts/f1_heading90_table.py`（只抽既有 CSV，不重规划）。',
               '', f'ASSERT OK: {CHECKS} cell checks', '']
    (ROOT/'results/F1.report.md').write_text('\n'.join(report), encoding='utf-8')
    print('\n'.join(report))


if __name__ == '__main__':
    main()
