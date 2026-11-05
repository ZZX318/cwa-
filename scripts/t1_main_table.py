"""Compute paired T1 tables from CSVs and hard-check the existing 1b report.

Run: python3 scripts/t1_main_table.py
Only the four named T1 outputs are written; input files are read-only.
"""
from __future__ import annotations

import csv
import itertools
import re
import statistics as st
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ('results/a_trial_seeds0-4_2ff2df1.csv', '2ff2df1'),
    ('results/a_trial_extra_oh_rot_h90_58024ac.csv', '58024ac'),
    ('results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv', '0e0715a'),
)
REFERENCE = 'results/a_trial_1b_0e0715a.report.md'
TAUS = ('A_extra_tau0', 'A_extra_tau0.5', 'A_extra_tau1')
TLAB = ('0', '0.5', '1.0')
COMPARISONS = ('min_time', 'heading_0')
TITLES = ('表 a: S_h vs B-boundary 主准则 min time', '表 b: S_h vs B-boundary(0°)')
PHASE = 1.0
ZERO = 1e-12
TIE = 1e-9
MIN_NOTE = ('n=5 时双侧 Wilcoxon 精确检验可达最小 p = 0.0625（n=4 时 0.125），'
            '任何格都不可能 <0.05；本表 p 值仅作描述，不作显著性结论。')
NA = '不适用（Δ 全为 0）'
CLASSES = ('win', 'tie', 'loss', 'not_interpreted')
CLASS_CN = dict(zip(CLASSES, ('胜', '平', '负', '不解读')))
CLASS_CN['not_applicable'] = 'S_h 不适用'


def f(value, digits=4):
    return '-' if value is None else f'{value:.{digits}f}'


def lab(row):
    return f"{row['heading']}°/{row['offset']:.3g}"


def load_rows():
    rows = []
    text_fields = {'variant', 'status', 'stage', 'matrix_mode', 'order_strategy',
                   'plan_hash', 'reason'}
    for path, _ in SOURCES:
        with (ROOT / path).open(encoding='utf-8', newline='') as stream:
            for raw in csv.DictReader(stream):
                if raw['status'] != 'success':
                    continue
                row = {}
                for key, value in raw.items():
                    if key in text_fields:
                        row[key] = value
                    elif key in ('heuristic_lane_found', 'heuristic_grid_aligned'):
                        assert value in ('True', 'False', ''), (key, value)
                        row[key] = {'True': True, 'False': False, '': None}[value]
                    elif key in ('heading', 'seed'):
                        row[key] = int(value)
                    else:
                        row[key] = float(value) if value else None
                rows.append(row)
    return rows  # Includes main, oh_rot and both b_online variants for completeness.


def pick_min(pool, tk):
    return min(pool, key=lambda r: (r[tk], r['total_time'])) if pool else None


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
    assert [classify(d) for d in (None, 0, -0.5, -1, 1)] == [
        'not_applicable', 'tie', 'not_interpreted', 'win', 'loss']


def compute(rows):
    records, summaries = [], []
    for comparison in COMPARISONS:
        for U in (2.0, 4.0):
            for tk, tau in zip(TAUS, TLAB):
                cell = []
                for seed in range(5):
                    pool = [r for r in rows if r['seed'] == seed and r['U'] == U]
                    sh = pick_min([r for r in pool if r['variant'] == 'heuristic'
                                   and r.get('heuristic_lane_found') is not False], tk)
                    boundaries = [r for r in pool if r['variant'] == 'b_boundary']
                    assert len(boundaries) == 2, (seed, U, boundaries)
                    assert {r['heading'] for r in boundaries} == {0, 90}
                    zero = [r for r in boundaries if r['heading'] == 0]
                    assert len(zero) == 1
                    b = (min(boundaries, key=lambda r: (r['total_time'], r['path_length']))
                         if comparison == 'min_time' else zero[0])
                    delta = None if sh is None else sh[tk] - b[tk]
                    cell.append(dict(comparison=comparison, U=U, tau=tau, seed=seed,
                                     B_label=lab(b), B_A_extra=b[tk],
                                     Sh_label=None if sh is None else lab(sh),
                                     Sh_A_extra=None if sh is None else sh[tk],
                                     delta=delta, **{'class': classify(delta)}))
                paired = [r for r in cell if r['delta'] is not None]
                summary = dict(comparison=comparison, U=U, tau=tau, n=len(paired))
                for prefix, column in (('Sh', 'Sh_A_extra'), ('B', 'B_A_extra'), ('delta', 'delta')):
                    values = [r[column] for r in paired]
                    summary[prefix + '_mean'] = st.mean(values) if values else None
                    summary[prefix + '_sd'] = st.stdev(values) if len(values) >= 2 else None
                ds = [r['delta'] for r in paired]
                summary.update(delta_min=min(ds) if ds else None, delta_max=max(ds) if ds else None)
                summary.update({c: sum(r['class'] == c for r in cell) for c in CLASSES})
                n, w, p, pmin = wilcoxon(ds)
                summary.update(n_nonzero=n, W_plus=w, p_exact_two_sided=p,
                               p_min_achievable=pmin,
                               note='；'.join(x for x in (
                                   'n=4：U=4 seed 4 的 S_h 不适用' if len(paired) == 4 else '',
                                   NA if p is None else '') if x))
                records.extend(cell)
                summaries.append(summary)
    return records, summaries


def section(text, heading):
    parts = text.split(heading + '\n')
    assert len(parts) == 2, heading
    return parts[1].split('\n## ', 1)[0]


def check_reference(records, summaries):
    text = (ROOT / REFERENCE).read_text(encoding='utf-8')
    paired_section = section(text, '## 配对：S_h−B-boundary (min total_time) 与 S3−B-boundary (min total_time)')
    baseline_section = section(text, '## 基线各行（0.05 m）')
    paired_cells, summary_cells, baseline_cells = {}, {}, {}
    current = None
    for line in paired_section.splitlines():
        match = re.fullmatch(r'### U=(2|4) · τ=(0|0\.5|1\.0)', line)
        if match:
            current = (float(match[1]), match[2])
        elif line.startswith('### '):
            current = None
        elif current and re.match(r'^\| [0-4] \|', line):
            cells = [c.strip() for c in line.strip('|').split('|')]
            key = (*current, int(cells[0]))
            assert key not in paired_cells
            paired_cells[key] = cells
        elif current and line.startswith('- S_h−B：'):
            assert current not in summary_cells
            summary_cells[current] = line
    for line in baseline_section.splitlines():
        if not re.match(r'^\| [0-4] \|', line):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells[1] == 'b_boundary' and cells[3].startswith('0°/'):
            key = (float(cells[2]), int(cells[0]))
            assert key not in baseline_cells
            baseline_cells[key] = cells
    assert len(paired_cells) == 30 and len(summary_cells) == 6 and len(baseline_cells) == 10
    count = 0

    def equal(actual, expected, context):
        nonlocal count
        # Explicit raise also preserves hard checks under python -O.
        if actual != expected:
            raise AssertionError(f'{context}: computed {actual!r}, report {expected!r}')
        count += 1

    def value_label(value, label, cell, context):
        if value is None:
            equal(cell, 'S_h 不适用', context)
        else:
            number, ref_label = cell.split(' @')
            equal(f(value), number, context + ' value')
            equal(label, ref_label, context + ' label')

    for r in records:
        key = (r['U'], r['tau'], r['seed'])
        cells = paired_cells[key]
        context = str((r['comparison'], *key))
        value_label(r['Sh_A_extra'], r['Sh_label'], cells[2], context + ' Sh')
        if r['comparison'] == 'min_time':
            value_label(r['B_A_extra'], r['B_label'], cells[1], context + ' B')
            ref_delta = cells[4].removesuffix('（低于相位误差，不解读）')
            equal('不适用' if r['delta'] is None else f(r['delta']), ref_delta, context + ' delta')
        else:
            baseline = baseline_cells[(r['U'], r['seed'])]
            equal(r['B_label'], baseline[3], context + ' B label')
            equal(f(r['B_A_extra']), baseline[4 + TLAB.index(r['tau'])], context + ' B value')
    for s in summaries:
        if s['comparison'] != 'min_time':
            continue
        line = summary_cells[(s['U'], s['tau'])]
        match = re.fullmatch(
            r'- S_h−B：n=(\d+)，mean \[min,max\] = (\S+) \[(\S+), (\S+)\]；'
            r'可解读\(\|Δ\|≥1\) n=(\d+) → .*；胜/平/负/不解读 = (\d+)/(\d+)/(\d+)/(\d+)', line)
        assert match, line
        equal(s['n'], int(match[1]), line)
        for key, group in zip(('delta_mean', 'delta_min', 'delta_max'), (2, 3, 4)):
            equal(f(s[key]), match[group], key)
        equal(s['win'] + s['loss'], int(match[5]), 'interpretable n')
        for key, group in zip(CLASSES, range(6, 10)):
            equal(s[key], int(match[group]), key)
    return count


def markdown_table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |',
            '|' + '|'.join('---' for _ in headers) + '|'] + [
                '| ' + ' | '.join(map(str, row)) + ' |' for row in rows]


def summary_table(summaries, digits):
    headers = ['U (m/s)', 'τ (s)', 'n', 'S_h A_extra/m² (mean±SD)',
               'B A_extra/m² (mean±SD)', 'ΔA_extra/m² mean±SD [min,max]',
               '胜/平/负/不解读', 'Wilcoxon p (exact, two-sided)']
    rows = []
    for s in summaries:
        def ms(prefix):
            return f(s[prefix + '_mean'], digits) + '±' + f(s[prefix + '_sd'], digits)
        rows.append([f"{s['U']:g}", s['tau'], str(s['n']), ms('Sh'), ms('B'),
                     ms('delta') + f" [{f(s['delta_min'], digits)},{f(s['delta_max'], digits)}]",
                     '/'.join(str(s[c]) for c in CLASSES),
                     NA if s['p_exact_two_sided'] is None else f(s['p_exact_two_sided'], 4)])
    return headers, rows


def plain_table(headers, rows):
    # Display widths account for Chinese characters in the HTML-free version.
    import unicodedata
    def width(text):
        return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
    widths = [max(width(row[i]) for row in [headers] + rows) for i in range(len(headers))]
    def line(row):
        return '  '.join(s + ' ' * (w - width(s)) for s, w in zip(row, widths)).rstrip()
    rule = '━' * (sum(widths) + 2 * (len(headers) - 1))
    return ['```text', rule, line(headers), rule, *map(line, rows), rule, '```']


def render(records, summaries, checks):
    notes = [
        'Δ=S_h−B；负值表示 S_h 额外面积更少。',
        '0<|Δ|<1 m² 不解读（0.05 m 栅格相位误差约 ±1 m²）；|Δ|≤1e-12 计平。',
        'n=4 的格：U=4 时 seed 4 的 S_h 不适用；所有均值与样本 SD 使用同一组配对 seed。',
        MIN_NOTE,
        'τ=1.0 s 为假设值；B-boundary 是张昆 2022 的简化代理（只读到摘要）。',
        'Wilcoxon 用全部非零配对 Δ（含 0<|Δ|<1 的不解读项，如 U=2 τ=0.5 seed 3 的 −0.67）；p 值保留 4 位小数。',
        'B-boundary(0°) 与 S_h 相位相同，因为 d=k·w；见原报告 B-boundary 节。',
    ]
    main = ['# T1 主表', '', '## 来源与定义', '']
    main += [f'- `{path}`，commit `{commit}`。' for path, commit in SOURCES]
    main += [f'- 核对报告：`{REFERENCE}`。', '- 命令：`python3 scripts/t1_main_table.py`。', '',
             '仅保留 status==success；seed=0..4，U∈{2,4}。oh_rot 与其他成功行一并载入保留。',
             'S_h 候选为 heuristic 且 heuristic_lane_found 不为 False（空值保留）；'
             '每个 τ 按 (A_extra, total_time) 取最小；空池不适用。',
             'B-boundary 主准则在 0°、90° 两行按 (total_time, path_length) 取最小；'
             'B-boundary(0°) 固定选唯一的 0° 行。',
             'PHASE=1.0 m²；先判精确平，再判相位误差；Δ≤−1 为胜，Δ≥1 为负。',
             'SD=statistics.stdev（样本 SD）；n<2 时 SD 为“-”。',
             'Wilcoxon 使用全部非缺失 Δ（包括不解读项），删除 |Δ|≤1e-12 的零差；'
             '绝对值排序，同值容差 1e-9，组内平均秩。W+ 为正差秩和；'
             '以 Fraction 枚举 2^n_eff 种符号分配，p=min(1,2·min(P(W+≤obs),P(W+≥obs)))。'
             'n_eff=0 时检验及最小 p 不适用；否则最小双侧 p=2/2^n_eff。', '']
    main += notes + ['', f'逐格断言通过：{checks} 项（数值保留 4 位小数，标签逐字核对）。', '']
    paper = ['# T1 三线表', '', '面积及统计量保留 2 位小数；精确 p 的未舍入值见汇总 CSV。', '']
    for comp, title in zip(COMPARISONS, TITLES):
        ss = [s for s in summaries if s['comparison'] == comp]
        main += ['## ' + title, '', '### 汇总', '']
        main += markdown_table(*summary_table(ss, 4)) + ['']
        main += markdown_table(['U', 'τ', 'n_nonzero', 'W+', '最小双侧 p', '备注'], [
            [f"{s['U']:g}", s['tau'], str(s['n_nonzero']), f(s['W_plus']),
             f(s['p_min_achievable']), s['note'] or '-'] for s in ss]) + ['']
        for s in ss:
            cell = [r for r in records if (r['comparison'], r['U'], r['tau']) == (comp, s['U'], s['tau'])]
            main += [f"### U={s['U']:g} · τ={s['tau']} · n={s['n']}", '']
            main += markdown_table(['seed', 'B 标签', 'B A_extra', 'S_h 标签', 'S_h A_extra', 'Δ', '分类'], [
                [str(r['seed']), r['B_label'], f(r['B_A_extra']), r['Sh_label'] or 'S_h 不适用',
                 f(r['Sh_A_extra']), f(r['delta']), CLASS_CN[r['class']]] for r in cell]) + ['']
        headers, table_rows = summary_table(ss, 2)
        paper += ['## ' + title, ''] + markdown_table(headers, table_rows) + ['']
        paper += plain_table(headers, table_rows) + ['']
    paper += ['注：', ''] + notes + ['']
    return '\n'.join(main), '\n'.join(paper)


def main():
    self_test()
    rows = load_rows()
    records, summaries = compute(rows)
    checks = check_reference(records, summaries)
    main_md, paper_md = render(records, summaries, checks)
    for name, data in (('T1_main_table.csv', records), ('T1_main_table_summary.csv', summaries)):
        with (ROOT / 'results' / name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    for name, content in (('T1_main_table.md', main_md), ('T1_three_line_table.md', paper_md)):
        (ROOT / 'results' / name).write_text(content, encoding='utf-8')
    print(f'成功行 {len(rows)}；配对明细 {len(records)} 行；汇总 {len(summaries)} 格。')
    for comp, title in zip(COMPARISONS, TITLES):
        print(title)
        print('\n'.join(markdown_table(*summary_table([s for s in summaries if s['comparison'] == comp], 4))))
    print(f'ASSERT OK: {checks} cell checks')


if __name__ == '__main__':
    main()
