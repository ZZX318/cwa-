"""A 小试 1c 喷幅敏感性报告（w=3 m，假设值；只读已生成结果；描述统计 n≤5，无显著性检验）。

用法：
  python scripts/a_trial_1c_report.py SHA [W]
    读 results/a_trial_seeds0-4_{SHA}_w{W}.meta.json                     （S1 / S_h / S3 的 0°、90° × {0,w/4,w/2,3w/4} 与 heuristic）
       results/a_trial_extra_oh_rot_h90_{SHA}_w{W}.meta.json               （S3 的 90°/o_h）
       results/a_trial_extra_b_online_b_boundary_h0_90_{SHA}_w{W}.meta.json（基线）
  写 results/a_trial_1c_{SHA}_w{W}.report.md 与 .overnight_section.md

S3 = {0, w/4, w/2, 3w/4, o_h} × {0°, 90°}，每个 τ 独立重选（平局比 total_time）。
B-boundary 两航向行都保留：主准则 min total_time，另报 min path_length。
|ΔA_extra| < 1 m²（非精确 0）标「低于相位误差，不解读」，不计胜负；精确 0 记平。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAUS = ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")
TLAB = {"A_extra_tau0": "τ=0", "A_extra_tau0.5": "τ=0.5", "A_extra_tau1": "τ=1.0"}
PHASE = 1.0
TIERS = (2.0, 4.0)


def f(x, n=3):
    return "-" if x is None else f"{x:.{n}f}"


def mmm(vs, d=3):
    vs = [v for v in vs if v is not None]
    return f"{st.mean(vs):+.{d}f} [{min(vs):+.{d}f}, {max(vs):+.{d}f}]" if vs else "-"


def wtl(vals):
    w = t = l = skip = 0
    for v in vals:
        if v is None:
            continue
        if abs(v) <= 1e-12:
            t += 1
        elif abs(v) < PHASE:
            skip += 1
        elif v < 0:
            w += 1
        else:
            l += 1
    return f"{w}/{t}/{l}/{skip}"


def tag(v):
    if v is None:
        return "不适用"
    if abs(v) <= 1e-12:
        return "0（平）"
    if abs(v) < PHASE:
        return f"{v:+.3f}（低于相位误差，不解读）"
    return f"{v:+.3f}"


def lab(r):
    return f"{r['heading']}°/{r['offset']:.4g}"


def pick(pool, k):
    return min(pool, key=lambda r: (r[k], r["total_time"])) if pool else None


def main():
    sha = sys.argv[1]
    W = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    wt = f"_w{W:g}"
    pM = f"results/a_trial_seeds0-4_{sha}{wt}"
    pO = f"results/a_trial_extra_oh_rot_h90_{sha}{wt}"
    pB = f"results/a_trial_extra_b_online_b_boundary_h0_90_{sha}{wt}"
    M = json.loads((ROOT / f"{pM}.meta.json").read_text())
    O = json.loads((ROOT / f"{pO}.meta.json").read_text())
    B = json.loads((ROOT / f"{pB}.meta.json").read_text())
    for X in (M, O, B):
        assert float(X["swath"]) == W, X.get("swath")
        assert not X["worktree_dirty_tracked"], "dirty tree"
    rows = M["rows_full"] + O["rows_full"] + B["rows_full"]
    ok = [r for r in rows if r.get("status") == "success"]
    bad = [r for r in rows if r.get("status") != "success"]
    viol = [r for r in ok if r.get("violations")]
    seeds = sorted({r["seed"] for r in M["rows_full"]})
    grid = sorted({r["offset"] for r in M["rows_full"] if r["variant"] == "main"})

    def P(s, U):
        tr = [r for r in ok if r["seed"] == s and r["U"] == U]
        main_ = [r for r in tr if r["variant"] == "main"]
        heur = [r for r in tr if r["variant"] == "heuristic"]
        oh90 = [r for r in tr if r["variant"] == "oh_rot" and r["heading"] == 90]
        bb = [r for r in tr if r["variant"] == "b_boundary"]
        return dict(
            S1=[r for r in main_ if r["heading"] == 0 and r["offset"] == 0.0],
            S_h=[r for r in heur if r.get("heuristic_lane_found") is not False],
            S3=main_ + heur + oh90,
            Bon25=[r for r in tr if r["variant"] == "b_online_c0.25"],
            Bon50=[r for r in tr if r["variant"] == "b_online_c0.5"],
            Bb_time=[min(bb, key=lambda r: (r["total_time"], r["path_length"]))] if len(bb) == 2 else [],
            Bb_path=[min(bb, key=lambda r: (r["path_length"], r["total_time"]))] if len(bb) == 2 else [],
            Bb_h0=[r for r in bb if r["heading"] == 0],
            heur_all=heur, bb=bb, oh90=oh90)

    def sel(s, U, name, k):
        pool = P(s, U)[name]
        return pick(pool, k) if name in ("S3",) else (pool[0] if pool else None)

    src = [f"- 主批：`python scripts/a_trial_heading.py --seeds 0-4 --swath {W:g} --no-controls` @ {M['commit']} → `{pM}.csv`",
           f"- 90°/o_h：`python scripts/a_trial_extra_runs.py --variants oh_rot --headings 90 --swath {W:g}` @ {O['commit']} → `{pO}.csv`",
           f"- 基线：`python scripts/a_trial_extra_runs.py --variants b_online,b_boundary --headings 0,90 --swath {W:g}` @ {B['commit']} → `{pB}.csv`",
           f"- 汇总：`python scripts/a_trial_1c_report.py {sha} {W:g}` → `results/a_trial_1c_{sha}{wt}.report.md`"]
    L = [f"# 1c. 喷幅敏感性（w={W:g}，假设值）", "",
         f"> **w={W:g} m 为假设值，未对应具体机型；不替代 w=2 主结果。** 场景、d=10/16 查表、缓冲 F、安全硬校验均不变；禁喷区不平移。"
         f"d mod w：d=10→{10 % W:g}，d=16→{16 % W:g}。B-online/B-boundary 仍是参照文献的简化代理，不是原方法复现。", ""] + src + [
         "- 描述统计（n=5），无显著性检验；A_extra = 0.05 m 栅格；|Δ|<1 m² 标「低于相位误差，不解读」不计胜负（精确 0 记平）。",
         f"- S3 = {{{', '.join(f'{g:g}' for g in grid)}, o_h}} × {{0°, 90°}}，每个 τ 独立重选（平局比 total_time）。",
         "- 胜/平/负/不解读：Δ<0 为前者胜（A_extra 更小）。", ""]

    # safety
    L += ["## 跑批安全", "", f"- 总行数 {len(rows)}；status≠success：{len(bad)}；success 但 violations>0：{len(viol)}。"]
    for r in bad + viol:
        L.append(f"  - seed {r['seed']} {r['variant']} U={r['U']:g} {lab(r)} status={r.get('status')} "
                 f"viol={r.get('violations')} reason={r.get('reason')}")
    L += ["- 未为通过而改任何方案的规划。", ""]

    # geometry facts
    L += ["## 几何核对（每 seed×U）", "",
          "| seed | U | d | o_h(0°) | B-boundary 0° 偏移 | 差 mod w | B-b 0°≡S_h 相位? | oh_rot 90° | B-b 90° 偏移 | 90° 相同? | S_h lane_found | B-online Δ(c=.25/.5) mod w |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in seeds:
        for U in TIERS:
            p = P(s, U)
            h = p["heur_all"][0] if p["heur_all"] else None
            b0 = next((r for r in p["bb"] if r["heading"] == 0), None)
            b9 = next((r for r in p["bb"] if r["heading"] == 90), None)
            o9 = p["oh90"][0] if p["oh90"] else None
            on = [x[0]["extra_info"] for x in (p["Bon25"], p["Bon50"]) if x]
            dd = None if not (h and b0) else (b0["offset"] - h["offset"]) % W
            L.append(f"| {s} | {U:g} | {h['d'] if h else '-'} | {f(h and h['offset'])} | {f(b0 and b0['offset'])} | {f(dd)} | "
                     f"{'是' if b0 and b0['extra_info'].get('matches_oh_rot_or_heuristic') else '否'} | {f(o9 and o9['offset'])} | "
                     f"{f(b9 and b9['offset'])} | {'是' if (o9 and b9 and abs(o9['offset'] - b9['offset']) < 1e-9) else '否'} | "
                     f"{h.get('heuristic_lane_found') if h else '-'} | {'/'.join(f'{i['delta']:g}→{i['delta_mod_w']:g}' for i in on)} |")
    L.append("")

    pairs = [("S_h", "Bb_time", "S_h−B-boundary(min time)"),
             ("S_h", "Bb_path", "S_h−B-boundary(min path)"),
             ("S_h", "Bb_h0", "S_h−B-boundary(0° 行)"),
             ("S3", "Bb_time", "S3−B-boundary(min time)"),
             ("S3", "Bb_path", "S3−B-boundary(min path)"),
             ("S_h", "Bon25", "S_h−B-online c=0.25"),
             ("S_h", "Bon50", "S_h−B-online c=0.5"),
             ("S3", "Bon25", "S3−B-online c=0.25"),
             ("S3", "Bon50", "S3−B-online c=0.5"),
             ("S3", "S_h", "S3−S_h"),
             ("S_h", "S1", "S_h−S1")]

    # main summary table
    L += ["## 主表：ΔA_extra（0.05 m，m²）", "",
          "| 对比 | U | τ | mean [min, max] | 胜/平/负/不解读 | 逐 seed |", "|---|---|---|---|---|---|"]
    O_main = []
    for a_, b_, name in pairs:
        for U in TIERS:
            for k in TAUS:
                ds = []
                for s in seeds:
                    A, Bx = sel(s, U, a_, k), sel(s, U, b_, k)
                    ds.append(None if A is None or Bx is None else A[k] - Bx[k])
                line = f"| {name} | {U:g} | {TLAB[k]} | {mmm(ds)} | {wtl(ds)} | {'; '.join(tag(d) for d in ds)} |"
                L.append(line)
                if name.startswith(("S_h−B-boundary(min time)", "S3−B-boundary(min time)", "S_h−B-online", "S3−S_h", "S_h−S1",
                                    "S_h−B-boundary(0°")):
                    O_main.append(line)
    L.append("")

    # time/path/cut table for picked rows
    L += ["## 选中行：时间 / 路径 / 切段 / 违规", "",
          "| seed | U | τ | 方案 | 选中 | A_extra | 时间 s | 路径 m | cut | viol |", "|---|---|---|---|---|---|---|---|---|---|"]
    for U in TIERS:
        for k in TAUS:
            for s in seeds:
                for nm in ("S1", "S_h", "S3", "Bb_time", "Bb_path", "Bon25", "Bon50"):
                    r = sel(s, U, nm, k)
                    if r is None:
                        L.append(f"| {s} | {U:g} | {TLAB[k]} | {nm} | 不适用 | - | - | - | - | - |")
                        continue
                    L.append(f"| {s} | {U:g} | {TLAB[k]} | {nm} | {r['variant']} {lab(r)} | {f(r[k])} | {f(r['total_time'], 1)} | "
                             f"{f(r['path_length'], 1)} | {r['cut_segments']} | {r['violations']} |")
    L.append("")
    # Δ time/path for S_h−Bb_time and S3-Bb_time
    L += ["## Δ时间 / Δ路径 / Δcut（mean [min,max]）", "", "| 对比 | U | τ | Δtime s | Δpath m | Δcut |", "|---|---|---|---|---|---|"]
    for a_, b_, name in pairs:
        for U in TIERS:
            for k in TAUS:
                dt, dp, dc = [], [], []
                for s in seeds:
                    A, Bx = sel(s, U, a_, k), sel(s, U, b_, k)
                    if A is None or Bx is None:
                        continue
                    dt.append(A["total_time"] - Bx["total_time"]); dp.append(A["path_length"] - Bx["path_length"])
                    dc.append(A["cut_segments"] - Bx["cut_segments"])
                L.append(f"| {name} | {U:g} | {TLAB[k]} | {mmm(dt, 1)} | {mmm(dp, 1)} | {mmm(dc, 1)} |")
    L.append("")

    # S3 = S_h counts
    L += ["## S3 是否等于 S_h（同一行）", ""]
    for U in TIERS:
        for k in TAUS:
            n = sum(1 for s in seeds if sel(s, U, "S_h", k) is not None and sel(s, U, "S3", k) is sel(s, U, "S_h", k))
            nn = sum(1 for s in seeds if sel(s, U, "S_h", k) is not None)
            picks = ", ".join(f"s{s}:{lab(sel(s, U, 'S3', k))}" for s in seeds)
            L.append(f"- U={U:g} {TLAB[k]}：S3=S_h {n}/{nn}；S3 选中 {picks}")
    L.append("")

    out = ROOT / f"results/a_trial_1c_{sha}{wt}.report.md"
    out.write_text("\n".join(L), encoding="utf8")
    sec = [f"## 1c. 喷幅敏感性（w={W:g}，假设值）", "",
           f"> w={W:g} m 为假设值，未对应具体机型，不替代 w=2 主结果。d mod w = 1（d=10、16）。基线仍为简化代理，不是原方法复现。", ""] + src + [
           "", f"- 行数 {len(rows)}；失败 {len(bad)}；violations>0：{len(viol)}。", "",
           "| 对比 | U | τ | mean [min, max] | 胜/平/负/不解读 | 逐 seed |", "|---|---|---|---|---|---|"] + O_main + [""]
    (ROOT / f"results/a_trial_1c_{sha}{wt}.overnight_section.md").write_text("\n".join(sec), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
