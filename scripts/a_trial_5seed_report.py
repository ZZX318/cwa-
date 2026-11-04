"""A 小试 5-seed 汇总报告（只读已生成的结果文件，不跑规划，不做显著性检验）。
用法：python scripts/a_trial_5seed_report.py SHA
  读  results/a_trial_seeds0-4_SHA.{summary,meta}.json
  写  results/a_trial_seeds0-4_SHA.report.md（完整报告）
      results/a_trial_seeds0-4_SHA.overnight_section.md（RESULTS_overnight.md 第 1 节用的精简表）
方案的 A_excluded / cut_segments / path_length / total_time 均取被选中那一行（rows_full）的原值。
"""
from __future__ import annotations

import csv
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAUS = ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")
TLAB = {"A_extra_tau0": "τ=0", "A_extra_tau0.5": "τ=0.5", "A_extra_tau1": "τ=1.0"}
SCH = ("S1", "S_h", "S2", "S2'", "S3")
REFS = ("S1", "S2", "S2'", "S_h")
CTRL = ("no_zone", "wind_away", "rot180", "rot180_aligned")
TIERLAB = {"U=2": "U=2 m/s, d=10 m", "U=4": "U=4 m/s, d=16 m"}


def f(x, n=4):
    return "-" if x is None else (f"{x:.{n}f}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x))


def agg(vs, n=4):
    return [f(st.mean(vs), n), f(min(vs), n), f(max(vs), n)] if vs else ["-"] * 3


def main():
    sha = sys.argv[1]
    pre = ROOT / f"results/a_trial_seeds0-4_{sha}"
    S = json.loads(Path(str(pre) + ".summary.json").read_text())
    M = json.loads(Path(str(pre) + ".meta.json").read_text())
    rows = M["rows_full"]
    csv_rel = f"results/a_trial_seeds0-4_{sha}.csv"
    seeds = sorted(int(k) for k in S if k.isdigit())
    tiers = sorted(S[str(seeds[0])]["tiers"].keys(), key=lambda t: float(t.split("=")[1]))

    def row_of(seed, tier, name, sel):
        U = float(tier.split("=")[1])
        var = "heuristic" if name == "S_h" else "main"
        c = [r for r in rows if r["seed"] == seed and r["U"] == U and r["variant"] == var and r.get("status") == "success"
             and r["heading"] == sel["heading"] and abs(r["offset"] - sel["offset"]) < 1e-12]
        assert len(c) == 1, (seed, tier, name, sel, len(c))
        return c[0]

    # 选中行：sel[(tier, tk, seed, name)] = row
    sel = {}
    for tier in tiers:
        for tk in TAUS:
            for s in seeds:
                for n in SCH:
                    x = S[str(s)]["tiers"][tier]["by_tau"][tk]["schemes"].get(n)
                    sel[(tier, tk, s, n)] = None if x is None else row_of(s, tier, n, x)

    cite = f"来源：`scripts/a_trial_heading.py --seeds 0-4 --workers 7` @ commit {M['commit']} → `{csv_rel}`（+ .summary.json/.meta.json）；汇总 `scripts/a_trial_5seed_report.py {sha}`"
    head = [f"- {cite}",
            f"- commit {M['commit']}，worktree_dirty_tracked={M['worktree_dirty_tracked']}，wall {M['wall_seconds']} s，workers {M['workers']}，n=5 seeds（{seeds}），只做描述统计，无显著性检验",
            f"- 选择规则：{S[str(seeds[0])]['rule']}", f"- {M['sh_formula']}", f"- {M['tau_note']}",
            "- 面积单位 m²（评估器 0.05 m 栅格），时间 s，路径 m。cut = 关喷切段数（cut_segments）。差值 = S3 − 参照，同一 τ 下各自独立选择。", ""]
    L = [f"# A 小试 5-seed 汇总（{sha}）", ""] + head
    O = []  # overnight 精简节

    # 安全
    fails = [r for r in rows if r.get("status") != "success"]
    viol = [r for r in rows if r.get("status") == "success" and r.get("violations")]
    main_ok = [r for r in rows if r["variant"] == "main"]
    L += ["## 安全/违规", "", f"- 总行数 {len(rows)}（main {len(main_ok)}）；status≠success {len(fails)}；成功但 violations>0：{len(viol)}"]
    for r in fails + viol:
        L.append(f"  - seed {r['seed']} {r['variant']} U={r['U']:g} h={r['heading']} o={r['offset']:g} status={r.get('status')} stage={r.get('stage')} viol={r.get('violations')} reason={r.get('reason')}")
    cnt = {}
    for r in rows:
        cnt[(r["seed"], r["U"], r["variant"])] = cnt.get((r["seed"], r["U"], r["variant"]), 0) + 1
    miss = [(s, U, v, n) for s in seeds for U in (2.0, 4.0) for v, n in (("main", 8), ("heuristic", 1), *((c, 1) for c in CTRL))
            if cnt.get((s, U, v), 0) != n]
    L += [f"- 完整性（每 seed×档：main 8、heuristic 1、对照 4 种各 1）：缺/多 {miss if miss else '无'}", ""]
    O += [f"**安全**：{len(rows)} 行（main {len(main_ok)}），status≠success {len(fails)}，violations>0 {len(viol)}；行数完整性缺/多：{miss if miss else '无'}。", ""]

    # S_h
    L += ["## S_h 偏移（几何计算，无搜索）", "", "| seed | 档 | o_h | x_F | 首航道中心 | lane_found | grid_aligned |", "|---|---|---|---|---|---|---|"]
    for r in sorted([r for r in rows if r["variant"] == "heuristic"], key=lambda r: (r["seed"], r["U"])):
        L.append(f"| {r['seed']} | U={r['U']:g} | {f(r['offset'])} | {f(r.get('heuristic_x_F'))} | {f(r.get('heuristic_first_lane_center'))} | {r.get('heuristic_lane_found')} | {r.get('heuristic_grid_aligned')} |")
    L.append("")

    # 各 seed 选择（全指标）
    for tier in tiers:
        for tk in TAUS:
            L += [f"## {TIERLAB.get(tier, tier)} · 按 {TLAB[tk]} 选择：各方案选中行", "",
                  "| seed | 方案 | 航向/偏移 | A_extra τ0 | τ0.5 | τ1.0 | A_excluded | cut | 路径 m | 时间 s |", "|---|---|---|---|---|---|---|---|---|---|"]
            for s in seeds:
                for n in SCH:
                    r = sel[(tier, tk, s, n)]
                    if r is None:
                        L.append(f"| {s} | {n} | - | - | - | - | - | - | - | - |")
                        continue
                    L.append(f"| {s} | {n} | {r['heading']}°/{r['offset']:.3g} | {f(r['A_extra_tau0'])} | {f(r['A_extra_tau0.5'])} | {f(r['A_extra_tau1'])} | {f(r['A_excluded'])} | {r['cut_segments']} | {f(r['path_length'],1)} | {f(r['total_time'],1)} |")
            L.append("")
            # 方案均值（5 seed）
            L += [f"### {tier} {TLAB[tk]}：各方案 5-seed 均值 [min, max]", "",
                  f"| 方案 | A_extra@{TLAB[tk]} | A_excluded | cut | 路径 m | 时间 s |", "|---|---|---|---|---|---|"]
            ov = [f"#### {TIERLAB.get(tier, tier)} · {TLAB[tk]}", "", f"| 方案 | A_extra@{TLAB[tk]} 均值 [min,max] | A_excluded 均值 | cut 均值 | 路径 m 均值 | 时间 s 均值 [min,max] |", "|---|---|---|---|---|---|"]
            for n in SCH:
                rs = [sel[(tier, tk, s, n)] for s in seeds if sel[(tier, tk, s, n)] is not None]
                def mm(k, d=4):
                    v = [r[k] for r in rs]
                    return f"{st.mean(v):.{d}f} [{min(v):.{d}f}, {max(v):.{d}f}]" if v else "-"
                L.append(f"| {n} | {mm(tk)} | {mm('A_excluded',2)} | {mm('cut_segments',1)} | {mm('path_length',1)} | {mm('total_time',1)} |")
                v = lambda k: st.mean([r[k] for r in rs]) if rs else None  # noqa: E731
                ov.append(f"| {n} | {mm(tk)} | {f(v('A_excluded'),2)} | {f(v('cut_segments'),1)} | {f(v('path_length'),1)} | {mm('total_time',1)} |")
            L.append("")
            # 差值
            L += [f"### {tier} {TLAB[tk]}：S3 − 参照（逐 seed + mean/min/max）", "",
                  "| 差值 | " + " | ".join(f"seed {s}" for s in seeds) + " | mean | min | max |", "|---" * (len(seeds) + 4) + "|"]
            ov += ["", f"S3 − 参照（mean [min, max]，n=5）：", "", "| 参照 | ΔA_extra@该τ | Δcut | Δ路径 m | Δ时间 s |", "|---|---|---|---|---|"]
            for ref in REFS:
                ocells = []
                for m, lab, d in ((tk, "ΔA_extra", 4), ("cut_segments", "Δcut", 0), ("path_length", "Δ路径", 1), ("total_time", "Δtime", 1)):
                    vals = []
                    for s in seeds:
                        a, b = sel[(tier, tk, s, "S3")], sel[(tier, tk, s, ref)]
                        vals.append(None if a is None or b is None else a[m] - b[m])
                    vs = [v for v in vals if v is not None]
                    L.append(f"| S3−{ref} {lab} | " + " | ".join(f(v, d) for v in vals) + " | " + " | ".join(agg(vs, d)) + " |")
                    ocells.append(f"{st.mean(vs):.{d}f} [{min(vs):.{d}f}, {max(vs):.{d}f}]" if vs else "-")
                ov.append(f"| {ref} | " + " | ".join(ocells) + " |")
            L.append("")
            O += ov + [""]

    # 0 vs 90
    C = S["heading_compare_counts"]
    hv = ["## 0° vs 90°（各自取该 τ 下 A_extra 最小的偏移，平局比时间不计入胜负；|Δ|≤1e-12 记平）", "",
          "| 档 | τ | 0° 胜 | 90° 胜 | 平 | 逐 seed（0° 值@偏移 / 90° 值@偏移 → 胜者） |", "|---|---|---|---|---|---|"]
    for tier in tiers:
        for tk in TAUS:
            c = C[tier][tk]
            per = "; ".join(f"s{p['seed']}: {f(p['per_heading']['0']['value'])}@{p['per_heading']['0']['offset']:g} / {f(p['per_heading']['90']['value'])}@{p['per_heading']['90']['offset']:g} → {p['better']}" for p in sorted(c["per_seed"], key=lambda p: p["seed"]))
            hv.append(f"| {tier} | {TLAB[tk]} | {c['0']} | {c['90']} | {c['tie']} | {per} |")
    hv.append("")
    L += hv
    O += hv

    # 对照
    ct = ["## 对照", "", "| seed | 档 | 对照 | status | A_excluded | A_extra τ0/0.5/1.0 | cut | 路径 m | 时间 s | viol |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s in seeds:
        for tier in tiers:
            U = float(tier.split("=")[1])
            for v in CTRL:
                x = [r for r in rows if r["seed"] == s and r["U"] == U and r["variant"] == v]
                if not x:
                    ct.append(f"| {s} | {tier} | {v} | MISSING | | | | | | |")
                    continue
                x = x[0]
                ct.append(f"| {s} | {tier} | {v}{' o=' + format(x['offset'], '.3g') if v == 'rot180_aligned' else ''} | {x['status']} | {f(x.get('A_excluded'))} | {'/'.join(f(x.get(t)) for t in TAUS)} | {x.get('cut_segments')} | {f(x.get('path_length'),1)} | {f(x.get('total_time'),1)} | {x.get('violations')} |")
    ct.append("")
    L += ct
    O += ct

    # 收敛
    cv = ["## 栅格收敛 0.2 / 0.1 / 0.05 m（所有成功行）", "", "| 对比 | 指标 | max abs (m²) | max rel | rel>1% 行数 | rel>1% 中 abs 最大者 |", "|---|---|---|---|---|---|"]
    ok = [r for r in rows if r.get("status") == "success"]
    for pair in ("0.2_vs_0.05", "0.1_vs_0.05", "0.2_vs_0.1"):
        for m in ("A_C", "A_excluded", *TAUS):
            vals = [(r["conv_pairs"][pair][m]["abs_diff"], r["conv_pairs"][pair][m]["rel_diff"], r) for r in ok]
            big = [v for v in vals if v[1] is not None and v[1] > 0.01]
            worst = max(big, key=lambda v: v[0]) if big else None
            w = "-" if not worst else f"s{worst[2]['seed']} {worst[2]['variant']} U={worst[2]['U']:g} h={worst[2]['heading']} o={worst[2]['offset']:.3g}: abs {worst[0]:.4f}, rel {worst[1]:.3f}"
            rels = [v[1] for v in vals if v[1] is not None]
            cv.append(f"| {pair} | {m} | {max(v[0] for v in vals):.4f} | {max(rels) if rels else float('nan'):.4f} | {len(big)}/{len(vals)} | {w} |")
    cv.append("")
    # 选择稳健性：用 0.2 / 0.1 m 栅格的 A_extra 重做同样的选择（平局比时间），与 0.05 m 结果比较
    def pick(pool, tk, res):
        return min(pool, key=lambda r: (r["by_resolution"][res][tk], r["total_time"])) if pool else None
    cv += ["### 选择稳健性：换用 0.2 / 0.1 m 栅格重做方案选择与 0°/90° 判定（与 0.05 m 比较）", "",
           "| 栅格 | 方案选中行改变数（共 5 seed×2 档×3 τ×5 方案=150） | 改变明细 | 0°/90° 判定改变数（共 30） | 改变明细 |", "|---|---|---|---|---|"]
    for res in ("0.2", "0.1"):
        ch, chd, hw, hwd = 0, [], 0, []
        for s in seeds:
            for tier in tiers:
                U = float(tier.split("=")[1])
                tr = [r for r in rows if r["seed"] == s and r["U"] == U and r.get("status") == "success"]
                okm = [r for r in tr if r["variant"] == "main"]
                pools = {"S1": [r for r in okm if r["heading"] == 0 and r["offset"] == 0.0],
                         "S_h": [r for r in tr if r["variant"] == "heuristic"],
                         "S2": [r for r in okm if r["offset"] == 0.0],
                         "S2'": [r for r in okm if r["heading"] == 0], "S3": okm}
                for tk in TAUS:
                    for n, pool in pools.items():
                        a, b = pick(pool, tk, "0.05"), pick(pool, tk, res)
                        if a is not b:
                            ch += 1
                            chd.append(f"s{s} {tier} {TLAB[tk]} {n}: {a['heading']}°/{a['offset']:.3g}→{b['heading']}°/{b['offset']:.3g}")
                    def win(rr):
                        v = {h: min(r["by_resolution"][rr][tk] for r in okm if r["heading"] == h) for h in (0, 90)}
                        d = v[0] - v[90]
                        return "tie" if abs(d) <= 1e-12 else ("0" if d < 0 else "90")
                    wa, wb = win("0.05"), win(res)
                    if wa != wb:
                        hw += 1
                        hwd.append(f"s{s} {tier} {TLAB[tk]}: {wa}→{wb}")
        cv.append(f"| {res} m | {ch} | {'; '.join(chd) or '-'} | {hw} | {'; '.join(hwd) or '-'} |")
    cv.append("")
    L += cv
    O += cv

    # seed0 复现
    p0 = ROOT / "results/a_trial_seed0_70db42d.csv"
    if p0.exists():
        old = {}
        for r in csv.DictReader(open(p0, encoding="utf8")):
            old[(r["variant"], float(r["U"]), int(float(r["heading"])), round(float(r["offset"]), 6))] = r
        same = diff = 0
        dl = []
        for r in [r for r in rows if r["seed"] == 0]:
            k = (r["variant"], float(r["U"]), int(r["heading"]), round(float(r["offset"]), 6))
            if k in old:
                if old[k]["plan_hash"]:
                    eq = old[k]["plan_hash"] == (r.get("plan_hash") or "") and all(
                        abs(float(old[k][t]) - r[t]) < 1e-9 for t in (*TAUS, "A_excluded", "total_time"))
                else:
                    eq = old[k]["status"] == r["status"]
                same += eq
                diff += not eq
                if not eq:
                    dl.append(str(k))
        line = f"- seed 0 与 70db42d（`results/a_trial_seed0_70db42d.csv`）共同行 {same + diff}：plan_hash+指标完全一致 {same}，不一致 {diff} {dl}"
        L += ["## seed 0 与 70db42d 复现", "", line, ""]
        O += [line, ""]

    Path(str(pre) + ".report.md").write_text("\n".join(L), encoding="utf8")
    Path(str(pre) + ".overnight_section.md").write_text("\n".join(head + O), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
