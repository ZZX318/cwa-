"""A 小试 5-seed 修正报告（item 2 修正 1–3；只读已生成结果，不跑规划，只做描述统计，n≤5，无显著性检验）。
用法：python scripts/a_trial_5seed_fix_report.py MAIN_SHA EXTRA_SHA [PROBE_JSON]
  读  results/a_trial_seeds0-4_MAIN_SHA.{summary,meta}.json        （主批 130 行，含 S_h=0°/o_h 行）
      results/a_trial_extra_oh_rot_h90_EXTRA_SHA.meta.json          （90°/o_h 新跑，scripts/a_trial_extra_runs.py）
      PROBE_JSON（可选，seed1 栅格探针，scripts/a_trial_raster_probe.py）
  写  results/a_trial_seeds0-4_fix_MAIN_SHA+EXTRA_SHA.report.md
修正 1：S3 候选 = {0°,90°} × {0,0.5,1.0,1.5,o_h}；0°/o_h 复用 heuristic 行，90°/o_h 取 oh_rot 行；旧 S3 改名 S3-grid4。
修正 2：A_extra 只报 0.05 m；0.2/0.1 m 仅用于选择稳健性检查。
修正 3：heuristic_lane_found=False 的 (seed,档) 记「S_h 不适用」，不进 S_h 均值与 S3−S_h 差值（n 随之标注）。
选择规则同主批：每个 τ 独立取 A_extra(0.05 m) 最小，平局比 total_time（元组精确比较），仅 status=success。
扩展（1b）：在 POOLS 里加一个方案名→候选行函数即可。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAUS = ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")
TLAB = {"A_extra_tau0": "τ=0", "A_extra_tau0.5": "τ=0.5", "A_extra_tau1": "τ=1.0"}
SCH = ("S1", "S_h", "S2", "S2'", "S3-grid4", "S3")
REFS = ("S1", "S2", "S2'", "S_h", "S3-grid4")
TIERLAB = {2.0: "U=2 m/s, d=10 m", 4.0: "U=4 m/s, d=16 m"}


def f(x, n=4):
    return "-" if x is None else f"{x:.{n}f}"


def mmm(vs, d=4):
    return f"{st.mean(vs):.{d}f} [{min(vs):.{d}f}, {max(vs):.{d}f}]" if vs else "-"


def pools_for(tr):
    """tr: 某 seed×档 的全部成功行（主批 + 新跑）。返回 方案名 → 候选行列表。"""
    main = [r for r in tr if r["variant"] == "main"]
    heur = [r for r in tr if r["variant"] == "heuristic"]
    oh90 = [r for r in tr if r["variant"] == "oh_rot" and r["heading"] == 90]
    sh_ok = [r for r in heur if r.get("heuristic_lane_found") is not False]
    return {
        "S1": [r for r in main if r["heading"] == 0 and r["offset"] == 0.0],
        "S_h": sh_ok,  # lane_found=False → 空 → 「S_h 不适用」
        "S2": [r for r in main if r["offset"] == 0.0],
        "S2'": [r for r in main if r["heading"] == 0],
        "S3-grid4": main,
        "S3": main + heur + oh90,  # 0°/o_h 计划本身有效，即使 S_h 不适用也保留为候选
    }


def pick(pool, tk, res="0.05"):
    if not pool:
        return None
    if res == "0.05":
        return min(pool, key=lambda r: (r[tk], r["total_time"]))
    return min(pool, key=lambda r: (r["by_resolution"][res][tk], r["total_time"]))


def lab(r):
    tag = {"heuristic": "o_h", "oh_rot": "o_h"}.get(r["variant"], "")
    return f"{r['heading']}°/{r['offset']:.3g}{'(' + tag + ')' if tag else ''}"


def main():
    msha, esha = sys.argv[1], sys.argv[2]
    probe = (ROOT / sys.argv[3]).resolve() if len(sys.argv) > 3 else None
    S = json.loads((ROOT / f"results/a_trial_seeds0-4_{msha}.summary.json").read_text())
    M = json.loads((ROOT / f"results/a_trial_seeds0-4_{msha}.meta.json").read_text())
    E = json.loads((ROOT / f"results/a_trial_extra_oh_rot_h90_{esha}.meta.json").read_text())
    rows = M["rows_full"] + E["rows_full"]
    seeds = sorted({r["seed"] for r in M["rows_full"]})
    tiers = (2.0, 4.0)
    ex_bad = [r for r in E["rows_full"] if r.get("status") != "success" or r.get("violations")]
    ok = [r for r in rows if r.get("status") == "success"]

    sel, pools_all = {}, {}
    for s in seeds:
        for U in tiers:
            P = pools_for([r for r in ok if r["seed"] == s and r["U"] == U])
            pools_all[(s, U)] = P
            for tk in TAUS:
                for n in SCH:
                    sel[(U, tk, s, n)] = pick(P[n], tk)
    # 自检：旧方案的选择须与主批 summary.json 完全一致（S3-grid4 = 旧 S3）
    mism = []
    for s in seeds:
        for U in tiers:
            for tk in TAUS:
                for n, old in (("S1", "S1"), ("S2", "S2"), ("S2'", "S2'"), ("S3-grid4", "S3"), ("S_h", "S_h")):
                    o = S[str(s)]["tiers"][f"U={U:g}"]["by_tau"][tk]["schemes"].get(old)
                    r = sel[(U, tk, s, n)]
                    if n == "S_h" and r is None:
                        continue  # 修正 3 有意排除
                    if o is None or r is None or o["heading"] != r["heading"] or abs(o["offset"] - r["offset"]) > 1e-12:
                        mism.append((s, U, tk, n))
    assert not mism, mism

    na = [(s, U) for s in seeds for U in tiers if not pools_all[(s, U)]["S_h"]]
    out = ROOT / f"results/a_trial_seeds0-4_fix_{msha}+{esha}.report.md"
    L = [f"# A 小试 5-seed 修正报告（item 2：修正 1–3；数据 {msha} + {esha}）", "",
         f"- 主批：`scripts/a_trial_heading.py --seeds 0-4 --workers 7` @ {M['commit']} → `results/a_trial_seeds0-4_{msha}.csv`（+.meta/.summary.json）",
         f"- 90°/o_h 新跑：`scripts/a_trial_extra_runs.py --variants oh_rot --headings 90 --seeds 0-4 --workers 7` @ {E['commit']} → `results/a_trial_extra_oh_rot_h90_{esha}.csv`（+.meta.json/.geom.json/.log）",
         f"- 汇总：`scripts/a_trial_5seed_fix_report.py {msha} {esha}{' ' + str(probe.relative_to(ROOT)) if probe else ''}`",
         "- 只做描述统计（n=5 或 4），无显著性检验。A_extra 一律为评估器 0.05 m 栅格值（m²）；0.2/0.1 m 只用于选择稳健性检查。",
         "- 选择规则：每个 τ 独立取 A_extra(0.05 m) 最小，平局比 total_time；仅 status=success 行。",
         "- S3 = {0°,90°}×{0,0.5,1.0,1.5,o_h}（12 候选）；S3-grid4 = 旧 S3 = {0°,90°}×{0,0.5,1.0,1.5}（8 候选）。0°/o_h = 主批 heuristic 行；90°/o_h = oh_rot 新跑行。",
         f"- 自检：S1/S2/S2′/S3-grid4/S_h 的重选结果与 `results/a_trial_seeds0-4_{msha}.summary.json` 逐项一致（不一致 0 项，修正 3 排除项除外）。",
         ""]

    # 90° o_h 计算
    L += ["## 修正 1：90°/o_h 的计算与新跑结果", "",
          "o_h(90°)：在规划坐标系（场景绕地块中心 (50,50) 旋转 90°）里取扫掠缓冲 F′（`a_trial_eval.buffer_set`），"
          "取 F′ 落在目标 x′ 范围内部的、垂直于航道法向的边 e，o_h = (xmin′ − e) mod w（w=2 m）；多条边须给出同一 o_h，否则报错。"
          "实现 `scripts/a_trial_extra_runs.py::oh_rot`；h=0 时与主批 `heuristic_offset` 逐 seed×档 相等（断言通过）。"
          "90° 时这些边就是禁喷区的 y 边（y=95→x′=5，y=5→x′=95），与 d 无关，故两档 o_h 相同；95−5=90=45w，两边给出同一 o_h。", "",
          f"新跑 {len(E['rows_full'])} 行；status≠success 或 violations>0：{len(ex_bad)} 行。", "",
          "| seed | 档 | o_h(90°) | 对齐边 x′ | 相邻条带目标数 | A_extra τ0 | τ0.5 | τ1.0 | A_excluded | cut | 路径 m | 时间 s | viol |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(E["rows_full"], key=lambda r: (r["seed"], r["U"])):
        L.append(f"| {r['seed']} | U={r['U']:g} | {r['offset']:.4g} | {', '.join(format(e, 'g') for e in r['extra_info']['aligned_edges'])} | {[a['n_targets'] for a in r['extra_info']['adjacent_strips']]} | {f(r.get('A_extra_tau0'))} | {f(r.get('A_extra_tau0.5'))} | {f(r.get('A_extra_tau1'))} | {f(r.get('A_excluded'))} | {r.get('cut_segments')} | {f(r.get('path_length'),1)} | {f(r.get('total_time'),1)} | {r.get('violations')} |")
    L.append("")

    # 修正 3
    L += ["## 修正 3：S_h 适用性", "",
          f"- heuristic_lane_found=False 的 (seed, 档)：{na or '无'} → 记「S_h 不适用」，不进 S_h 均值与 S3−S_h 差值；该档 S_h 的 n=4。"
          "其 0°/o_h 计划本身合法（成功、0 违规），仍作为 S3 候选。", ""]

    # 选择表 + 均值 + 差值
    summ = {}
    for U in tiers:
        for tk in TAUS:
            L += [f"## {TIERLAB[U]} · 按 {TLAB[tk]} 选择", "",
                  "| seed | " + " | ".join(SCH) + " |", "|---" * (len(SCH) + 1) + "|"]
            for s in seeds:
                cells = []
                for n in SCH:
                    r = sel[(U, tk, s, n)]
                    cells.append("S_h 不适用" if r is None else f"{f(r[tk])} @{lab(r)}")
                L.append(f"| {s} | " + " | ".join(cells) + " |")
            L += ["", f"各方案均值 [min, max]（A_extra@{TLAB[tk]}，0.05 m；以及选中行的 A_excluded / cut / 路径 / 时间）：", "",
                  "| 方案 | n | A_extra | A_excluded | cut | 路径 m | 时间 s |", "|---|---|---|---|---|---|---|"]
            for n in SCH:
                rs = [sel[(U, tk, s, n)] for s in seeds if sel[(U, tk, s, n)] is not None]
                L.append(f"| {n} | {len(rs)} | {mmm([r[tk] for r in rs])} | {mmm([r['A_excluded'] for r in rs],2)} | {mmm([r['cut_segments'] for r in rs],1)} | {mmm([r['path_length'] for r in rs],1)} | {mmm([r['total_time'] for r in rs],1)} |")
                summ[(U, tk, n)] = (len(rs), [r[tk] for r in rs])
            L += ["", "S3 − 参照（逐 seed；mean [min, max]；S3 胜/平/负 = 差值 <0 / =0 / >0 的 seed 数）：", "",
                  "| 参照 | 指标 | " + " | ".join(f"s{s}" for s in seeds) + " | n | mean [min, max] | 胜/平/负 |", "|---" * (len(seeds) + 5) + "|"]
            for ref in REFS:
                for m, ml, d in ((tk, "ΔA_extra", 4), ("cut_segments", "Δcut", 0), ("path_length", "Δ路径", 1), ("total_time", "Δ时间", 1)):
                    vals = []
                    for s in seeds:
                        a, b = sel[(U, tk, s, "S3")], sel[(U, tk, s, ref)]
                        vals.append(None if a is None or b is None else a[m] - b[m])
                    vs = [v for v in vals if v is not None]
                    wl = f"{sum(v < -1e-12 for v in vs)}/{sum(abs(v) <= 1e-12 for v in vs)}/{sum(v > 1e-12 for v in vs)}" if m == tk else ""
                    L.append(f"| S3−{ref} | {ml} | " + " | ".join("不适用" if v is None else f(v, d) for v in vals) + f" | {len(vs)} | {mmm(vs, max(d, 1))} | {wl} |")
                    summ[(U, tk, "Δ" + ref, m)] = (len(vs), vs)
            L.append("")

    # 新 S3 选中来源统计
    L += ["## 新 S3 选中候选的来源（30 次选择 = 5 seed × 2 档 × 3 τ）", "", "| 档 | τ | 0°/grid4 | 90°/grid4 | 0°/o_h | 90°/o_h | 与 S3-grid4 不同的 seed |", "|---|---|---|---|---|---|---|"]
    for U in tiers:
        for tk in TAUS:
            c = {"0g": 0, "90g": 0, "0o": 0, "90o": 0}
            dif = []
            for s in seeds:
                r = sel[(U, tk, s, "S3")]
                c[f"{r['heading']}{'g' if r['variant'] == 'main' else 'o'}"] += 1
                if r is not sel[(U, tk, s, "S3-grid4")]:
                    g = sel[(U, tk, s, "S3-grid4")]
                    dif.append(f"s{s}: {lab(g)} {f(g[tk])} → {lab(r)} {f(r[tk])}")
            L.append(f"| U={U:g} | {TLAB[tk]} | {c['0g']} | {c['90g']} | {c['0o']} | {c['90o']} | {'; '.join(dif) or '-'} |")
    L.append("")

    # 0 vs 90（含 o_h）
    L += ["## 0° vs 90°（各航向在 {0,0.5,1.0,1.5,o_h} 中取该 τ 的 A_extra 最小；|Δ|≤1e-12 记平）", "",
          "| 档 | τ | 0° 胜 | 90° 胜 | 平 | 逐 seed（0° 值@偏移 / 90° 值@偏移） | 旧计数（grid4，summary.json） 0°/90°/平 |", "|---|---|---|---|---|---|---|"]
    for U in tiers:
        for tk in TAUS:
            w = {"0": 0, "90": 0, "tie": 0}
            per = []
            for s in seeds:
                P = pools_all[(s, U)]["S3"]
                b = {h: pick([r for r in P if r["heading"] == h], tk) for h in (0, 90)}
                d = b[0][tk] - b[90][tk]
                k = "tie" if abs(d) <= 1e-12 else ("0" if d < 0 else "90")
                w[k] += 1
                per.append(f"s{s}: {f(b[0][tk])}@{lab(b[0])} / {f(b[90][tk])}@{lab(b[90])}")
            oc = S["heading_compare_counts"][f"U={U:g}"][tk]
            L.append(f"| U={U:g} | {TLAB[tk]} | {w['0']} | {w['90']} | {w['tie']} | {'; '.join(per)} | {oc['0']}/{oc['90']}/{oc['tie']} |")
    L.append("")

    # 选择稳健性
    L += ["## 选择稳健性：用 0.2 / 0.1 m 栅格的 A_extra 重做选择（含新候选），与 0.05 m 比较", "",
          f"| 栅格 | 方案选中行改变数（共 {len(seeds)}×2×3×{len(SCH)} 次，S_h 不适用者不计） | 明细 |", "|---|---|---|"]
    for res in ("0.2", "0.1"):
        ch, tot, det = 0, 0, []
        for s in seeds:
            for U in tiers:
                for tk in TAUS:
                    for n in SCH:
                        P = pools_all[(s, U)][n]
                        if not P:
                            continue
                        tot += 1
                        a, b = pick(P, tk), pick(P, tk, res)
                        if a is not b:
                            ch += 1
                            det.append(f"s{s} U={U:g} {TLAB[tk]} {n}: {lab(a)}→{lab(b)}")
        L.append(f"| {res} m | {ch}/{tot} | {'; '.join(det) or '-'} |")
    L.append("")

    # 修正 2：seed1 探针
    if probe and probe.exists():
        Pj = json.loads(probe.read_text())
        ex = Pj["exact"]
        L += ["## 修正 2：seed 1 U=2 0°/0 的栅格不单调（证据）", "",
              f"来源：`{probe.relative_to(ROOT)}`（`scripts/a_trial_raster_probe.py`）。", "",
              "| 量 | 0.2 m | 0.1 m | 0.05 m | 精确（半解析） |", "|---|---|---|---|---|"]
        rb = Pj["reeval_by_resolution"]
        for k in TAUS + ("A_excluded", "A_C"):
            e = ex[k]["panel_0p005"] if isinstance(ex[k], dict) else ex[k]
            L.append(f"| {k} | {f(rb['0.2'][k])} | {f(rb['0.1'][k])} | {f(rb['0.05'][k])} | {f(e)} |")
        L += ["", f"- 0.05 m 重评与 CSV 一致：{Pj['reeval_matches_csv_0.05']}",
              f"- 精确值两种面板宽度（0.02/0.005 m）之差：τ0 {ex['A_extra_tau0']['diff']:.2e} m²",
              "- 相位模型（未覆盖竖边：" + "; ".join(f"x={e['x']:g} 跳变 {e['jump']:.3f} m" for e in Pj["uncovered_vertical_edges_tau0"]) + "）预测 τ0：" +
              ", ".join(f"{k} m→{v['pred_A_extra_tau0']:.2f}" for k, v in Pj["phase_model"].items()), ""]
        if "origin_sweep" in Pj:
            L += ["栅格原点亚像元平移扫描（A_extra τ0，min–max）：", "", "| 栅格 | 平移数 | min | max | 极差 |", "|---|---|---|---|---|"]
            by = {}
            for k, x in Pj["origin_sweep"].items():
                by.setdefault(k.split()[0].split("=")[1], []).append(x["A_extra_tau0"])
            for res, v in by.items():
                L.append(f"| {res} m | {len(v)} | {min(v):.4f} | {max(v):.4f} | {max(v)-min(v):.4f} |")
            L.append("")
    out.write_text("\n".join(L), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
