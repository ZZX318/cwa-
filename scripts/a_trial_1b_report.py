"""A 小试 1b 对照基线报告（只读已生成结果；描述统计 n≤5，无显著性检验）。

用法：
  python scripts/a_trial_1b_report.py MAIN_SHA OH_SHA BASE_SHA
    MAIN_SHA  results/a_trial_seeds0-4_MAIN_SHA.meta.json
    OH_SHA    results/a_trial_extra_oh_rot_h90_OH_SHA.meta.json（S3 的 90°/o_h）
    BASE_SHA  results/a_trial_extra_b_online_b_boundary_h0_90_BASE_SHA.meta.json

写：results/a_trial_1b_BASE_SHA.report.md
    results/a_trial_1b_BASE_SHA.overnight_section.md

这是参照文献的简化代理，不是原方法复现。张昆 2022 只读到摘要。
配对：每个 τ 独立；S3 用修正后定义（含 o_h）；B-boundary 主准则 = min total_time（两航向都保留，可改用 min path_length）。
|ΔA_extra|<1 m² 标「低于相位误差，不解读」，不计入胜负。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAUS = ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")
TLAB = {"A_extra_tau0": "τ=0", "A_extra_tau0.5": "τ=0.5", "A_extra_tau1": "τ=1.0"}
PHASE = 1.0  # m²；低于此的 ΔA_extra 不解读（见 item2 修正 2）


def f(x, n=4):
    return "-" if x is None else f"{x:.{n}f}"


def mmm(vs, d=4):
    return f"{st.mean(vs):.{d}f} [{min(vs):.{d}f}, {max(vs):.{d}f}]" if vs else "-"


def pick_min(pool, key_tau):
    return min(pool, key=lambda r: (r[key_tau], r["total_time"])) if pool else None


def pools_scheme(rows_ok, seed, U):
    """复用修正报告的 S1/S_h/S3/S3-grid4 候选定义。"""
    tr = [r for r in rows_ok if r["seed"] == seed and r["U"] == U]
    main = [r for r in tr if r["variant"] == "main"]
    heur = [r for r in tr if r["variant"] == "heuristic"]
    oh90 = [r for r in tr if r["variant"] == "oh_rot" and r["heading"] == 90]
    sh = [r for r in heur if r.get("heuristic_lane_found") is not False]
    return {
        "S1": [r for r in main if r["heading"] == 0 and r["offset"] == 0.0],
        "S_h": sh,
        "S3": main + heur + oh90,
        "S3-grid4": main,
    }


def lab(r):
    return f"{r['heading']}°/{r['offset']:.3g}"


def phase_tag(v):
    if v is None:
        return "不适用"
    if abs(v) <= 1e-12:
        return f(v)  # 真平
    if abs(v) < PHASE:
        return f"{f(v)}（低于相位误差，不解读）"
    return f(v)


def win_counts(vals, phase_aware=True):
    """胜/平/负；0<|Δ|<PHASE 记「不解读」不进胜负；精确 0 记平。"""
    w = t = l = skip = 0
    for v in vals:
        if v is None:
            continue
        if abs(v) <= 1e-12:
            t += 1
        elif phase_aware and abs(v) < PHASE:
            skip += 1
        elif v < 0:
            w += 1
        else:
            l += 1
    return w, t, l, skip


def main():
    msha, osha, bsha = sys.argv[1], sys.argv[2], sys.argv[3]
    M = json.loads((ROOT / f"results/a_trial_seeds0-4_{msha}.meta.json").read_text())
    O = json.loads((ROOT / f"results/a_trial_extra_oh_rot_h90_{osha}.meta.json").read_text())
    B = json.loads((ROOT / f"results/a_trial_extra_b_online_b_boundary_h0_90_{bsha}.meta.json").read_text())
    rows = M["rows_full"] + O["rows_full"] + B["rows_full"]
    ok = [r for r in rows if r.get("status") == "success"]
    seeds = sorted({r["seed"] for r in M["rows_full"]})
    tiers = (2.0, 4.0)

    # baselines available
    online_vars = sorted({r["variant"] for r in B["rows_full"] if r["variant"].startswith("b_online")})
    assert online_vars == ["b_online_c0.25", "b_online_c0.5"], online_vars
    b_bad = [r for r in B["rows_full"] if r.get("status") != "success"]
    b_viol = [r for r in B["rows_full"] if r.get("status") == "success" and r.get("violations")]

    # B-boundary selection by total_time / path_length (keep both)
    def b_boundary_choice(seed, U, by="total_time"):
        pool = [r for r in ok if r["seed"] == seed and r["U"] == U and r["variant"] == "b_boundary"]
        assert len(pool) == 2, (seed, U, len(pool))
        return min(pool, key=lambda r: (r[by], r["total_time"] if by != "total_time" else r["path_length"]))

    L = [f"# A 小试 1b 对照基线（数据 {msha} + {osha} + {bsha}）", "",
         "> **这是参照文献的简化代理，不是原方法复现。** B-online 简化自 Scagnellato 2022（几何代理；c∈{0.25,0.5} s 为未标定假设）。"
         "B-boundary 简化自张昆 2022《农机化研究》（**只读到摘要**）。", "",
         f"- 主批 S1/S_h/S3 候选：`scripts/a_trial_heading.py` @ {M['commit']} → `results/a_trial_seeds0-4_{msha}.csv`",
         f"- 90°/o_h：`scripts/a_trial_extra_runs.py --variants oh_rot` @ {O['commit']} → `results/a_trial_extra_oh_rot_h90_{osha}.csv`",
         f"- 基线：`scripts/a_trial_extra_runs.py --variants b_online,b_boundary --headings 0,90 --seeds 0-4` @ {B['commit']} → `results/a_trial_extra_b_online_b_boundary_h0_90_{bsha}.csv`",
         f"- 汇总：`scripts/a_trial_1b_report.py {msha} {osha} {bsha}`",
         "- 只做描述统计（n=5，S_h 在 U=4 为 n=4），无显著性检验。A_extra = 0.05 m 栅格。",
         f"- |ΔA_extra| < {PHASE:g} m² 标「低于相位误差，不解读」（item2 修正 2：0.05 m 栅格对长未覆盖边有约 ±1 m² 相位误差）。",
         "- B-boundary 主准则：两航向中 **total_time 最小**（平局比 path_length）；CSV 保留 0° 与 90° 两行，可改用 path_length 最小。",
         ""]

    # wind / U_parallel fact
    L += ["## B-online：风速分解与纵向项", "",
          "A-trial 设定：航向 0° 时航道沿 y，风向 wd=0（单位向量 +x）。"
          "故 U_⊥ = U（纯侧风），**U_∥ = 0**，纵向开关窗平移 c·U_∥ = 0（本代理未改喷洒窗口）。"
          "整组条带上风向平移 Δ = c·U_⊥；c∈{0.25,0.5} s 为未标定假设。"
          "不做阀门延迟 τ 补偿（与原文一致：原文补偿的是沉积时机，不是阀门硬件 τ）。", "",
          "| U | c | Δ=c·U_⊥ | Δ mod w | 与主批已有 0° 偏移的关系 |",
          "|---|---|---|---|---|",
          "| 2 | 0.25 | 0.5 | 0.5 | 即主批 0°/0.5 |",
          "| 2 | 0.5 | 1.0 | 1.0 | 即主批 0°/1.0 |",
          "| 4 | 0.25 | 1.0 | 1.0 | 即主批 0°/1.0 |",
          "| 4 | 0.5 | 2.0 | 0.0 | 相位同主批 0°/0（S1） |",
          ""]

    L += ["## B-boundary：地块边界对齐", "",
          "对齐的是**未外扩**禁喷区边界（h=0 取 x=−1；h=90 取旋转后 x′∈{5,95}），不是风致缓冲 F。"
          f"因 d∈{{10,16}} 均为 w=2 的整数倍，(xmin−x_zone) mod w = (xmin−x_F) mod w，"
          "**h=0 相位与 S_h 相同，h=90 相位与 oh_rot 相同**（跑批前断言 + 行内 `matches_oh_rot_or_heuristic=true`）。"
          "这是本设定下的几何事实，不是实现偷懒。", ""]

    L += ["## 跑批安全", "",
          f"- 基线行数 {len(B['rows_full'])}；status≠success {len(b_bad)}；success 但 violations>0：{len(b_viol)}", ""]
    if b_bad or b_viol:
        for r in b_bad + b_viol:
            L.append(f"  - seed {r['seed']} {r['variant']} U={r['U']:g} h={r['heading']} o={r['offset']:g} "
                     f"status={r.get('status')} viol={r.get('violations')} reason={r.get('reason')}")
        L.append("")
    else:
        L.append("- 无失败、无违规（violations 列全为 0）。未为通过而改规划。")
        L.append("")

    # per-row table of baselines
    L += ["## 基线各行（0.05 m）", "",
          "| seed | 方案 | U | h/o | A_extra τ0 | τ0.5 | τ1.0 | A_excluded | cut | 路径 | 时间 | viol |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(B["rows_full"], key=lambda r: (r["variant"], r["seed"], r["U"], r["heading"])):
        L.append(f"| {r['seed']} | {r['variant']} | {r['U']:g} | {lab(r)} | {f(r.get('A_extra_tau0'))} | "
                 f"{f(r.get('A_extra_tau0.5'))} | {f(r.get('A_extra_tau1'))} | {f(r.get('A_excluded'))} | "
                 f"{r.get('cut_segments')} | {f(r.get('path_length'),1)} | {f(r.get('total_time'),1)} | {r.get('violations')} |")
    L.append("")

    # paired deltas
    Osec = list(L[1:8])  # overnight head bits
    Osec += ["",
             "**结论先写（不淡化）**：合并 o_h 后，U=2 且 τ>0 时 S3 在 4/5 个 seed 上等于 S_h；"
             "搜索增益几乎全部来自几何边界对齐偏移，航向与离散偏移网格贡献很小。"
             "若 S_h−B 与 S3−B 近乎相同，则「联合搜索相对启发式没有实质增益」。", ""]

    for bname, bget in [
        ("B-online c=0.25", lambda s, U: next(r for r in ok if r["seed"] == s and r["U"] == U and r["variant"] == "b_online_c0.25")),
        ("B-online c=0.5", lambda s, U: next(r for r in ok if r["seed"] == s and r["U"] == U and r["variant"] == "b_online_c0.5")),
        ("B-boundary (min total_time)", lambda s, U: b_boundary_choice(s, U, "total_time")),
    ]:
        L += [f"## 配对：S_h−{bname} 与 S3−{bname}", ""]
        Osec += [f"### {bname}", ""]
        for U in tiers:
            for tk in TAUS:
                L += [f"### U={U:g} · {TLAB[tk]}", "",
                      "| seed | B A_extra | S_h | S3 | S_h−B | S3−B | |",
                      "|---|---|---|---|---|---|---|"]
                d_sh, d_s3 = [], []
                same = 0
                for s in seeds:
                    P = pools_scheme(ok, s, U)
                    sh = pick_min(P["S_h"], tk)
                    s3 = pick_min(P["S3"], tk)
                    b = bget(s, U)
                    v_sh = None if sh is None else sh[tk] - b[tk]
                    v_s3 = s3[tk] - b[tk]
                    d_sh.append(v_sh)
                    d_s3.append(v_s3)
                    if sh is not None and s3 is not None and sh is s3:
                        same += 1
                    L.append(f"| {s} | {f(b[tk])} @{lab(b)} | "
                             f"{'S_h 不适用' if sh is None else f(sh[tk]) + ' @' + lab(sh)} | "
                             f"{f(s3[tk])} @{lab(s3)} | {phase_tag(v_sh)} | {phase_tag(v_s3)} | "
                             f"{'S3=S_h' if sh is not None and s3 is sh else ''} |")
                vs_sh = [v for v in d_sh if v is not None]
                vs_s3 = [v for v in d_s3 if v is not None]
                # interpretable subset
                vs_sh_i = [v for v in vs_sh if abs(v) >= PHASE]
                vs_s3_i = [v for v in vs_s3 if abs(v) >= PHASE]
                wsh = win_counts(d_sh)
                ws3 = win_counts(d_s3)
                near = all(a is not None and b is not None and abs(a - b) < 1e-12
                           for a, b in zip(d_sh, d_s3) if not (a is None and b is None)) \
                    or (vs_sh and vs_s3 and abs(st.mean([v for v in vs_sh]) - st.mean(vs_s3)) < PHASE
                        and same >= 4)
                note = ""
                if same >= 4:
                    note = f"本格 {same}/5 个 seed 上 S3 选中行与 S_h 相同。"
                if near and same >= 4:
                    note += " **联合搜索相对启发式没有实质增益。**"
                L += ["",
                      f"- S_h−B：n={len(vs_sh)}，mean [min,max] = {mmm(vs_sh)}；"
                      f"可解读(|Δ|≥{PHASE:g}) n={len(vs_sh_i)} → {mmm(vs_sh_i) if vs_sh_i else '-'}；"
                      f"胜/平/负/不解读 = {wsh[0]}/{wsh[1]}/{wsh[2]}/{wsh[3]}",
                      f"- S3−B：n={len(vs_s3)}，mean [min,max] = {mmm(vs_s3)}；"
                      f"可解读 n={len(vs_s3_i)} → {mmm(vs_s3_i) if vs_s3_i else '-'}；"
                      f"胜/平/负/不解读 = {ws3[0]}/{ws3[1]}/{ws3[2]}/{ws3[3]}",
                      f"- {note}" if note else "- （S3 与 S_h 选中不完全相同）",
                      ""]
                Osec += [f"**U={U:g} {TLAB[tk]}**：S_h−B {mmm(vs_sh)}（胜/平/负/不解读 {wsh[0]}/{wsh[1]}/{wsh[2]}/{wsh[3]}）；"
                         f"S3−B {mmm(vs_s3)}（{ws3[0]}/{ws3[1]}/{ws3[2]}/{ws3[3]}）。{note}", ""]

        # path-criterion alternative for boundary
        if "boundary" in bname:
            L += ["### B-boundary 若改用 min path_length 选航向（对照主准则）", "",
                  "| seed | U | time 准则 | path 准则 | 是否相同 |",
                  "|---|---|---|---|---|"]
            n_diff = 0
            for s in seeds:
                for U in tiers:
                    a, b = b_boundary_choice(s, U, "total_time"), b_boundary_choice(s, U, "path_length")
                    same_ab = a is b
                    n_diff += not same_ab
                    L.append(f"| {s} | {U:g} | {lab(a)} t={f(a['total_time'],1)} L={f(a['path_length'],1)} | "
                             f"{lab(b)} t={f(b['total_time'],1)} L={f(b['path_length'],1)} | {'是' if same_ab else '否'} |")
            L += ["", f"两准则不同的 seed×档：{n_diff}/10。主报告用 total_time。", ""]

    # S3 vs S_h reminder
    L += ["## 附：S3 相对 S_h 的实质增益（回应「不淡化」要求）", "",
          "来自 item2 修正报告的结构事实（本脚本重算核对）：", ""]
    for U in tiers:
        for tk in TAUS:
            n_eq = n_sh = 0
            deltas = []
            for s in seeds:
                P = pools_scheme(ok, s, U)
                sh, s3 = pick_min(P["S_h"], tk), pick_min(P["S3"], tk)
                if sh is None:
                    continue
                n_sh += 1
                if sh is s3:
                    n_eq += 1
                deltas.append(s3[tk] - sh[tk])
            L.append(f"- U={U:g} {TLAB[tk]}：S3 与 S_h 同计划 {n_eq}/{n_sh}；ΔA_extra mean [min,max]={mmm(deltas)}")
    L += ["",
          "U=2 且 τ∈{0.5,1.0} 时同计划为 4/5：搜索增益几乎全部来自几何边界对齐（o_h），"
          "航向与 {0,0.5,1,1.5} 离散网格贡献很小。", ""]

    out = ROOT / f"results/a_trial_1b_{bsha}.report.md"
    out.write_text("\n".join(L), encoding="utf8")
    sec = ROOT / f"results/a_trial_1b_{bsha}.overnight_section.md"
    head = [
        f"## 1b. 对照基线（简化代理，不是原方法复现）",
        "",
        f"> B-online ← Scagnellato 2022 几何代理（c∈{{0.25,0.5}} s 未标定假设）；B-boundary ← 张昆 2022（**摘要 only**）。"
        f"来源：`scripts/a_trial_extra_runs.py` @ {B['commit']} → `results/a_trial_extra_b_online_b_boundary_h0_90_{bsha}.csv`；"
        f"汇总 `scripts/a_trial_1b_report.py {msha} {osha} {bsha}` → `results/a_trial_1b_{bsha}.report.md`。",
        "",
        f"- 基线 {len(B['rows_full'])} 行；失败 {len(b_bad)}；violations>0：{len(b_viol)}。",
        "- U_∥=0（纯侧风），B-online 纵向平移项为 0。",
        "- B-boundary 因 d=k·w，相位与 S_h / 90°/o_h 相同（几何事实）。",
        f"- |ΔA_extra|<{PHASE:g} m² →「低于相位误差，不解读」。",
        "- **不淡化**：U=2 τ>0 时 S3 在 4/5 seed 上等于 S_h；增益几乎全来自 o_h。",
        "",
    ]
    sec.write_text("\n".join(head + Osec), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
