"""A 小试 1c-sweep：喷幅余数扫描报告（0° 下 S1 / S_h / B-boundary；描述统计 n=5，无显著性检验）。

用法：
  python scripts/a_trial_1c_sweep_report.py SWEEP_SHA C1_SHA
数据（只读）：
  w=2   ：results/a_trial_seeds0-4_2ff2df1.meta.json（S1=main 0°/0，S_h=heuristic）+ results/a_trial_seed{s}_2ff2df1.geom.json
          results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.{meta,geom}.json（B-boundary 0° 行）——复用，不重跑
  w=3   ：1c 主批 results/a_trial_seeds0-4_{C1_SHA}_w3.* 与 results/a_trial_extra_b_online_b_boundary_h0_90_{C1_SHA}_w3.*
          的 0° 行（复用前与 sweep0 的 w=3 seed0 抽检行逐项比对 plan_hash，见 SWEEP_SHA 下 _w3 文件）
  其他 w：results/a_trial_extra_sweep0_h0_{SWEEP_SHA}_w{w}.{meta,geom}.json
全冠层覆盖：对每个选中计划的保存几何（geom.json，原坐标系）用 a_trial_eval.evaluate(..., resolutions=(0.05,), extra_cov=True)
  重新栅格化，覆盖率 = |C ∩ P_τ| / |C|（分母固定为全部冠层格，含 F 内冠层）。重算的 A_extra 与 CSV 逐行核对。
写：results/a_trial_1c_sweep_{SWEEP_SHA}.{report.md,overnight_section.md,rows.csv,table.csv}
    results/a_trial_1c_sweep_{SWEEP_SHA}_r.png, results/a_trial_1c_sweep_{SWEEP_SHA}_rw.png
"""
from __future__ import annotations

import csv
import json
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
TAUS = (0.0, 0.5, 1.0)
TK = {0.0: "A_extra_tau0", 0.5: "A_extra_tau0.5", 1.0: "A_extra_tau1"}
PHASE = 1.0
WS = (2.0, 2.5, 3.0, 3.5, 4.0)
TIERS = {2.0: 10.0, 4.0: 16.0}
SEEDS = (0, 1, 2, 3, 4)


def gkey(prefix, r):
    return f'{prefix}U{r["U"]:g}_h{r["heading"]}_o{r["offset"]:g}'


def load(sweep_sha, c1_sha):
    """返回 recs[(w, seed, U, scheme)] = dict(row=..., segs=..., src=...)"""
    recs = {}
    # w=2
    M = json.loads((ROOT / "results/a_trial_seeds0-4_2ff2df1.meta.json").read_text())
    B = json.loads((ROOT / "results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.meta.json").read_text())
    BG = json.loads((ROOT / "results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.geom.json").read_text())
    for s in SEEDS:
        G = json.loads((ROOT / f"results/a_trial_seed{s}_2ff2df1.geom.json").read_text())
        for r in M["rows_full"]:
            if r["seed"] != s or r["heading"] != 0:
                continue
            if r["variant"] == "main" and r["offset"] == 0.0:
                sch = "S1"
            elif r["variant"] == "heuristic":
                sch = "S_h"
            else:
                continue
            recs[(2.0, s, r["U"], sch)] = dict(row=r, segs=G[gkey(f'{r["variant"]}_', r)]["segments"],
                                               src="results/a_trial_seeds0-4_2ff2df1.csv @2ff2df1")
    for r in B["rows_full"]:
        if r["variant"] == "b_boundary" and r["heading"] == 0:
            recs[(2.0, r["seed"], r["U"], "B")] = dict(row=r, segs=BG[gkey(f'b_boundary_s{r["seed"]}_', r)]["segments"],
                                                       src="results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv @0e0715a")
    # w=3 from 1c
    M = json.loads((ROOT / f"results/a_trial_seeds0-4_{c1_sha}_w3.meta.json").read_text())
    B = json.loads((ROOT / f"results/a_trial_extra_b_online_b_boundary_h0_90_{c1_sha}_w3.meta.json").read_text())
    BG = json.loads((ROOT / f"results/a_trial_extra_b_online_b_boundary_h0_90_{c1_sha}_w3.geom.json").read_text())
    assert float(M["swath"]) == 3.0 and float(B["swath"]) == 3.0
    for s in SEEDS:
        G = json.loads((ROOT / f"results/a_trial_seed{s}_{c1_sha}_w3.geom.json").read_text())
        for r in M["rows_full"]:
            if r["seed"] != s or r["heading"] != 0:
                continue
            if r["variant"] == "main" and r["offset"] == 0.0:
                sch = "S1"
            elif r["variant"] == "heuristic":
                sch = "S_h"
            else:
                continue
            recs[(3.0, s, r["U"], sch)] = dict(row=r, segs=G[gkey(f'{r["variant"]}_', r)]["segments"],
                                               src=f"results/a_trial_seeds0-4_{c1_sha}_w3.csv @{c1_sha}")
    for r in B["rows_full"]:
        if r["variant"] == "b_boundary" and r["heading"] == 0:
            recs[(3.0, r["seed"], r["U"], "B")] = dict(row=r, segs=BG[gkey(f'b_boundary_s{r["seed"]}_', r)]["segments"],
                                                       src=f"results/a_trial_extra_b_online_b_boundary_h0_90_{c1_sha}_w3.csv @{c1_sha}")
    # sweep widths
    for w in (2.5, 3.5, 4.0):
        p = sweep_path(w)
        if p is None:
            continue
        S = json.loads((ROOT / f"{p}.meta.json").read_text())
        SG = json.loads((ROOT / f"{p}.geom.json").read_text())
        assert float(S["swath"]) == w and not S["worktree_dirty_tracked"]
        for r in S["rows_full"]:
            sch = {"s1": "S1", "heuristic": "S_h", "b_boundary": "B"}[r["variant"]]
            g = SG.get(gkey(f'{r["variant"]}_s{r["seed"]}_', r))
            recs[(w, r["seed"], r["U"], sch)] = dict(row=r, segs=g and g["segments"], src=f"{p}.csv @{S['commit']}")
    return recs


PARTIAL = False  # --partial：缺失宽度跳过（仅用于中途预览，不用于提交）
CODE_SHA = None  # 1c-sweep 代码提交；各 w 的批次可能在其后的仅数据/文档提交上启动，须证明代码相同


def sweep_path(w):
    import glob
    c = sorted(glob.glob(str(ROOT / f"results/a_trial_extra_sweep0_h0_*_w{w:g}.meta.json")))
    if not c and PARTIAL:
        return None
    assert len(c) == 1, (w, c)
    p = str(Path(c[0]).relative_to(ROOT))[: -len(".meta.json")]
    sha = p.split("_h0_")[1].split("_w")[0]
    import subprocess
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", CODE_SHA, sha, "--", "planning", "scripts/a_trial_heading.py",
                           "scripts/a_trial_extra_runs.py", "scripts/a_trial_eval.py", "configs"]).returncode
    assert diff == 0, f"code differs between {CODE_SHA} and {sha}"
    return p


def reeval(args):
    w, seed, U, segs = args
    import a_trial_eval as ev
    import a_trial_heading as H
    from planning import configuration
    raw = {**H.JOB, "swath": w, "drift_mode": "sort", "wind_speed": float(U), "wind_direction": 0.0, "buffer_expand": 1.0}
    c = configuration(raw)
    # geom.json 不存 speed；时间不用（只取栅格面积），补上作业速度仅为让 evaluate 跑通
    segs = [dict(sg, speed=float(c["speed"])) for sg in segs]
    res = ev.evaluate(H.scene0(seed), segs, TIERS[U], 0.0, float(w), float(c["speed"]), dict(c),
                      resolutions=(0.05,), extra_cov=True)
    return res["by_resolution"]["0.05"]


def strip_stats(args):
    """B-boundary(0°) 被切掉的条带（描述性几何量，不是从计划里量出来的）：
    B 的航道边线在 x = −1 + k·w；含 F 边 x_F 的那条航道 [x_F − r, x_F − r + w] 与 F 重叠 r>0 → 整条在 F 的 y 范围内被切，
    F 外损失 x ∈ [x_F, x_F + w − r]。r=0 时无损失条带。返回 (树数, 冠层面积 m², 条带 x 范围)。冠层面积在 0.05 m 网格上数圆盘并集。"""
    w, seed, U = args
    import numpy as np
    import a_trial_eval as ev
    import a_trial_heading as H
    sc = H.scene0(seed)
    d = TIERS[U]
    F = ev.buffer_set(sc, d, 0.0)
    xs = [v[0] for f in F for v in f["vertices"]]
    ys = [v[1] for f in F for v in f["vertices"]]
    xF, y0, y1 = max(xs), min(ys), max(ys)
    r = d % w
    if r < 1e-9 or w - r < 1e-9:
        return 0, 0.0, None
    a, b = xF, xF + w - r
    g = [t["geometry"] for t in sc["targets"]]
    hit = [t for t in g if t["center"][0] + t["radius"] > a and t["center"][0] - t["radius"] < b
           and t["center"][1] + t["radius"] > y0 and t["center"][1] - t["radius"] < y1]
    res = 0.05
    X, Y = np.meshgrid(np.arange(a + res / 2, b, res), np.arange(y0 + res / 2, y1, res))
    m = np.zeros(X.shape, bool)
    for t in hit:
        m |= (X - t["center"][0]) ** 2 + (Y - t["center"][1]) ** 2 <= t["radius"] ** 2
    return len(hit), float(m.sum() * res * res), (round(a, 6), round(b, 6), round(y0, 6), round(y1, 6))


def fmt_strip(x):
    xs = sorted({sx for sx in x["strip_xs"]}, key=str)
    if all(v is None for v in xs):
        return "无（r=0）"
    return "；".join("无" if v is None else f"x∈[{v[0]:g}, {v[1]:g}], y∈[{v[2]:g}, {v[3]:g}]" for v in xs)


def mmm(vs, d=3):
    if not vs:
        return "-"
    nn = f"（n={len(vs)}）" if len(vs) < len(SEEDS) else ""
    return f"{st.mean(vs):+.{d}f} [{min(vs):+.{d}f}, {max(vs):+.{d}f}]{nn}"


def wtl(vals):
    w = t = l = sk = 0
    for v in vals:
        if abs(v) <= 1e-12:
            t += 1
        elif abs(v) < PHASE:
            sk += 1
        elif v < 0:
            w += 1
        else:
            l += 1
    return f"{w}/{t}/{l}/{sk}"


def main():
    global CODE_SHA, PARTIAL, WS
    PARTIAL = "--partial" in sys.argv
    sweep_sha, c1_sha = sys.argv[1], sys.argv[2]
    CODE_SHA = c1_sha
    recs = load(sweep_sha, c1_sha)
    # w=3 复用核对：sweep0 在 w=3 seed 0 的 6 行 vs 1c 主批/基线的对应 0° 行
    WS = tuple(w for w in WS if w in (2.0, 3.0) or sweep_path(w) is not None)
    p3 = sweep_path(3.0)
    S3 = json.loads((ROOT / f"{p3}.meta.json").read_text()) if p3 else dict(rows_full=[])
    reuse = []
    for r in S3["rows_full"]:
        sch = {"s1": "S1", "heuristic": "S_h", "b_boundary": "B"}[r["variant"]]
        R = recs[(3.0, r["seed"], r["U"], sch)]["row"]
        same = all(r.get(k) == R.get(k) for k in ("plan_hash", "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time",
                                                  "path_length", "cut_segments", "violations"))
        reuse.append((r["seed"], r["U"], sch, same))
    assert all(x[3] for x in reuse), reuse
    assert reuse or PARTIAL
    sw_src = {w: sweep_path(w) for w in (2.5, 3.5, 4.0) if w in WS}
    keys = sorted(recs)
    for w in WS:
        for s in SEEDS:
            for U in TIERS:
                for sch in ("S1", "S_h", "B"):
                    assert (w, s, U, sch) in recs, (w, s, U, sch)
    bad = [k for k in keys if recs[k]["row"].get("status") != "success" or recs[k]["segs"] is None]
    viol = [k for k in keys if k not in bad and recs[k]["row"].get("violations")]
    todo = [k for k in keys if k not in bad]
    with ProcessPoolExecutor(7) as ex:
        evs = dict(zip(todo, ex.map(reeval, [(k[0], k[1], k[2], recs[k]["segs"]) for k in todo])))
    mism = []
    for k in todo:
        e, r = evs[k], recs[k]["row"]
        for t in TAUS:
            if abs(e[f"A_extra_tau{t:g}"] - r[TK[t]]) > 1e-9:
                mism.append((k, t, e[f"A_extra_tau{t:g}"], r[TK[t]]))
        recs[k]["A_C"] = e["A_C"]
        recs[k]["cov"] = {t: e[f"A_cov_tau{t:g}"] / e["A_C"] for t in TAUS}
        recs[k]["CFP"] = {t: e[f"A_CFP_tau{t:g}"] for t in TAUS}

    # rows csv
    rp = ROOT / f"results/a_trial_1c_sweep_{sweep_sha}.rows.csv"
    with open(rp, "w", newline="", encoding="utf8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["w", "seed", "U", "d", "r", "scheme", "variant", "offset", "status", "violations", "n_lanes", "plan_hash",
                     "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "cov_all_tau0", "cov_all_tau0.5", "cov_all_tau1",
                     "A_C", "total_time", "path_length", "cut_segments", "source"])
        for k in keys:
            r, d = recs[k]["row"], TIERS[k[2]]
            cv = recs[k].get("cov", {})
            wr.writerow([k[0], k[1], k[2], d, round(d % k[0], 9), k[3], r["variant"], r["offset"], r.get("status"), r.get("violations"),
                         r.get("n_lanes"), r.get("plan_hash"), r.get(TK[0.0]), r.get(TK[0.5]), r.get(TK[1.0]),
                         cv.get(0.0), cv.get(0.5), cv.get(1.0), recs[k].get("A_C"), r.get("total_time"), r.get("path_length"),
                         r.get("cut_segments"), recs[k]["src"]])

    sk = [(w, s, U) for w in WS for s in SEEDS for U in TIERS]
    with ProcessPoolExecutor(7) as ex:
        STRIP = dict(zip(sk, ex.map(strip_stats, sk)))
    # table
    T = []
    for U, d in TIERS.items():
        for w in WS:
            rr = d % w
            for t in TAUS:
                def deltas(a, b, fld):
                    out = []
                    for s in SEEDS:
                        A, Bq = recs.get((w, s, U, a)), recs.get((w, s, U, b))
                        if (w, s, U, a) in bad or (w, s, U, b) in bad:
                            continue
                        out.append(fld(A, t) - fld(Bq, t))
                    return out
                ax = lambda R, t: R["row"][TK[t]]
                cv = lambda R, t: 100.0 * R["cov"][t]
                dB = deltas("S_h", "B", ax)
                T.append(dict(w=w, d=d, U=U, r=rr, rw=rr / w, tau=t, n=len(dB),
                              d_mean=st.mean(dB), d_min=min(dB), d_max=max(dB), wtl=wtl(dB), dB=dB,
                              cov=deltas("S_h", "B", cv), sh_s1=deltas("S_h", "S1", ax), b_s1=deltas("B", "S1", ax),
                              strip_n=[STRIP[(w, s, U)][0] for s in SEEDS], strip_a=[STRIP[(w, s, U)][1] for s in SEEDS],
                              strip_x=STRIP[(w, SEEDS[0], U)][2], strip_xs=[STRIP[(w, s, U)][2] for s in SEEDS],
                              lanes={sch: sorted({recs[(w, s, U, sch)]["row"].get("n_lanes") for s in SEEDS}) for sch in ("S1", "S_h", "B")}))
    tp = ROOT / f"results/a_trial_1c_sweep_{sweep_sha}.table.csv"
    with open(tp, "w", newline="", encoding="utf8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["w", "d", "U", "r", "r_over_w", "tau", "n", "dA_Sh_minus_B_mean", "min", "max", "win_tie_loss_skip",
                     "dCov_allcanopy_pp_mean", "min", "max", "Sh_minus_S1_mean", "min", "max", "B_minus_S1_mean", "min", "max",
                     "per_seed_dA", "lost_strip_xy", "lost_strip_trees_per_seed", "lost_strip_canopy_m2_per_seed"])
        for x in T:
            wr.writerow([x["w"], x["d"], x["U"], x["r"], round(x["rw"], 6), x["tau"], x["n"], x["d_mean"], x["d_min"], x["d_max"], x["wtl"],
                         st.mean(x["cov"]), min(x["cov"]), max(x["cov"]), st.mean(x["sh_s1"]), min(x["sh_s1"]), max(x["sh_s1"]),
                         st.mean(x["b_s1"]), min(x["b_s1"]), max(x["b_s1"]), ";".join(f"{v:.4f}" for v in x["dB"]),
                         x["strip_x"], ";".join(map(str, x["strip_n"])), ";".join(f"{v:.3f}" for v in x["strip_a"])])

    # figures
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figs = []
    for xkey, xlab, tagx in (("r", "余数 r = d mod w (m)", "r"), ("rw", "r / w", "rw")):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        cols = {0.0: "tab:blue", 0.5: "tab:orange", 1.0: "tab:red"}
        for t in TAUS:
            pts = sorted([x for x in T if x["tau"] == t], key=lambda x: (x[xkey], x["d"]))
            for dd, ls in ((10, "-"), (16, "--")):
                pd_ = sorted([x for x in pts if x["d"] == dd], key=lambda x: (x[xkey], x["w"]))
                # 同一 (d, x) 若有多个 w（如 d=16 时 r=0 的 w=2/4），按 x 取均值连线；不跨 d 平均
                ux = sorted({round(x[xkey], 9) for x in pd_})
                ax.plot(ux, [st.mean([x["d_mean"] for x in pd_ if round(x[xkey], 9) == u]) for u in ux], ls, color=cols[t],
                        alpha=0.6, label=f"τ={t:g} s, d={dd}（同 d 内按 x 连线）")
            for x in pts:
                mk = "o" if x["d"] == 10 else "s"
                ax.errorbar(x[xkey], x["d_mean"], yerr=[[x["d_mean"] - x["d_min"]], [x["d_max"] - x["d_mean"]]], fmt=mk,
                            color=cols[t], mfc="white" if x["d"] == 16 else cols[t], capsize=2, ms=6)
                ax.annotate(f"w{x['w']:g}", (x[xkey], x["d_mean"]), fontsize=6, xytext=(3, 3), textcoords="offset points")
        ax.axhspan(-PHASE, PHASE, color="grey", alpha=0.15, label="|Δ|<1 m² 低于相位误差，不解读")
        ax.axhline(0, color="k", lw=0.6)
        ax.plot([], [], "ko", label="d=10 (U=2)")
        ax.plot([], [], "ks", mfc="white", label="d=16 (U=4)")
        ax.set_xlabel(xlab)
        ax.set_ylabel("ΔA_extra = S_h − B-boundary (m², 0.05 m)")
        ax.set_title("1c-sweep 余数扫描（0°；均值，误差棒=5 seed min–max）", fontsize=10)
        ax.legend(fontsize=7, loc="best")
        fig.text(0.01, 0.005, "注：改变 w 同时改变航道条数（及条带位置），Δ 不是纯余数效应；w≠2 为假设值，未对应具体机型。",
                 fontsize=7)
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        pth = ROOT / f"results/a_trial_1c_sweep_{sweep_sha}_{tagx}.png"
        fig.savefig(pth, dpi=150)
        figs.append(pth.relative_to(ROOT))
        plt.close(fig)

    # 图 3：x = 损失条带冠层面积，y = ΔA_extra（每个 (w,d,seed,τ) 一点）
    import numpy as np
    pts3 = []
    for x in T:
        for k, s in enumerate(SEEDS):
            pts3.append((x["strip_a"][k], x["dB"][k], x["tau"], x["d"], x["w"], s))
    fits = {}
    # 敏感性：去掉 ≈57–63 m² 的大簇（条带冠层 < 10 m²），看拟合是否只被大簇撑起
    for t, small in [(t, sm) for sm in (False, True) for t in (None,) + TAUS]:
        sub = [p for p in pts3 if (t is None or p[2] == t) and (not small or p[0] < 10.0)]
        X = np.array([p[0] for p in sub]); Y = np.array([p[1] for p in sub])
        a1, a0 = np.polyfit(X, Y, 1)
        yhat = a1 * X + a0
        r2 = 1 - ((Y - yhat) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
        fits[("all" if t is None else f"tau{t:g}") + ("_canopy<10" if small else "")] = dict(n=len(sub), slope=float(a1), intercept=float(a0), r2=float(r2))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    cols = {0.0: "tab:blue", 0.5: "tab:orange", 1.0: "tab:red"}
    for p in pts3:
        ax.plot(p[0], p[1], "o" if p[3] == 10 else "s", color=cols[p[2]], mfc=cols[p[2]] if p[3] == 10 else "white", ms=5, alpha=0.8)
    xx = np.linspace(0, max(p[0] for p in pts3) or 1, 50)
    for t in TAUS:
        fz = fits[f"tau{t:g}"]
        ax.plot(xx, fz["slope"] * xx + fz["intercept"], "-", color=cols[t], lw=0.8,
                label=f"τ={t:g}: y={fz['slope']:.3f}x{fz['intercept']:+.2f}, R²={fz['r2']:.3f}")
    ax.axhspan(-PHASE, PHASE, color="grey", alpha=0.15, label="|Δ|<1 m² 低于相位误差，不解读")
    ax.plot([], [], "ko", label="d=10 (U=2)"); ax.plot([], [], "ks", mfc="white", label="d=16 (U=4)")
    ax.set_xlabel("B-boundary(0°) 损失条带内冠层面积 (m², 0.05 m)")
    ax.set_ylabel("ΔA_extra = S_h − B-boundary(0°) (m²)")
    ax.set_title("1c-sweep：损失条带冠层 vs ΔA_extra（每点 = w,d,seed,τ；描述性拟合，无检验）", fontsize=9)
    ax.legend(fontsize=7)
    fig.text(0.01, 0.005, "注：改变 w 同时改变航道条数；条带为几何推算（含 F 边航道被切），不是从计划量出；w≠2 为假设值。", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    pth = ROOT / f"results/a_trial_1c_sweep_{sweep_sha}_strip.png"
    fig.savefig(pth, dpi=150); plt.close(fig)
    figs.append(pth.relative_to(ROOT))
    (ROOT / f"results/a_trial_1c_sweep_{sweep_sha}.fit.json").write_text(json.dumps(dict(
        points=[dict(strip_canopy_m2=p[0], dA=p[1], tau=p[2], d=p[3], w=p[4], seed=p[5]) for p in pts3], fits=fits),
        ensure_ascii=False, indent=1))

    def ph(x):
        if all(abs(v) <= 1e-12 for v in x["dB"]):
            return "（5/5 精确平）"
        return " 「低于相位误差，不解读」" if abs(x["d_mean"]) < PHASE else ""

    hdr = ["| w (m) | d | r | r/w | τ | ΔA_extra S_h−B mean [min,max] | 胜/平/负/不解读 | Δ全冠层覆盖 S_h−B (百分点) mean [min,max] | S_h−S1 | B−S1 | B 损失条带 x 范围 | 条带内树数 mean（seed0/1/2/3/4） | 条带内冠层 m²（0.05 m）mean（seed0/1/2/3/4） | 航道数 S1/S_h/B |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tab = []
    for x in T:
        lab = "（假设值，未对应具体机型）" if x["w"] != 2.0 else ""
        tab.append(f"| {x['w']:g}{lab} | {x['d']:g} | {x['r']:g} | {x['rw']:.3f} | {x['tau']:g} | "
                   f"{mmm(x['dB'])}{ph(x)} | {x['wtl']} | {mmm(x['cov'], 4)} | {mmm(x['sh_s1'])} | {mmm(x['b_s1'])} | "
                   f"{fmt_strip(x)} | "
                   f"{st.mean(x['strip_n']):.1f}（{'/'.join(map(str, x['strip_n']))}） | {st.mean(x['strip_a']):.2f}（{'/'.join(f'{v:.2f}' for v in x['strip_a'])}） | "
                   f"{'/'.join(','.join(str(n) for n in x['lanes'][s]) for s in ('S1', 'S_h', 'B'))} |")
    src = ["- w=2：复用 `results/a_trial_seeds0-4_2ff2df1.csv`（@2ff2df1）与 `results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv`（@0e0715a）的 0° 行，未重跑。",
           f"- w=3：复用 1c 主批 `results/a_trial_seeds0-4_{c1_sha}_w3.csv` 与 `results/a_trial_extra_b_online_b_boundary_h0_90_{c1_sha}_w3.csv` 的 0° 行（@{c1_sha}；与 sweep0 抽检行比对见报告）。",
           f"- w=3 复用核对：`{p3}.csv`（sweep0，seed 0 × U=2/4 × 3 方案）与 1c 行逐项相同（plan_hash 与指标）{sum(x[3] for x in reuse)}/{len(reuse)}。",
           "- w∈{2.5,3.5,4}：`python scripts/a_trial_extra_runs.py --variants sweep0 --headings 0 --swath W` → "
           + "；".join(f"`{p}.csv`" for p in sw_src.values())
           + f"（代码与 {c1_sha} 相同，已用 git diff 校验 planning/、configs/ 与 a_trial_heading/extra_runs/eval）。",
           f"- 汇总：`python scripts/a_trial_1c_sweep_report.py {sweep_sha} {c1_sha}` → `results/a_trial_1c_sweep_{sweep_sha}.table.csv`、`.rows.csv`、`.report.md`；图 {', '.join(f'`{p}`' for p in figs)}。"]
    L = ["## 1c-sweep. 余数扫描", "",
         "> 除 w=2 外，所有 w 均为「假设值，未对应具体机型」。(w, U) 决定 d（U=2→d=10，U=4→d=16）。只跑 0°：S_h、B-boundary(0°)、S1(0°/0)。"
         "改变 w 同时改变航道条数与条带位置，Δ 不是纯余数效应。描述统计 n=5，无显著性检验。", ""] + src + [
         "", f"- 选中行 {len(keys)}；失败/无几何 {len(bad)}；violations>0：{len(viol)} {[k for k in viol]}",
         *[f"  - 失败行 {k}: stage={recs[k]['row'].get('stage')}, n_lanes={recs[k]['row'].get('n_lanes')}, reason={recs[k]['row'].get('reason')}" for k in bad],
         "  - 失败行不进入涉及该方案的配对差（表中 n<5 处已标 n）；失败为规划器 safety 阶段拒绝出计划（fail-closed），不是 violations。",
         f"- 重栅格化 A_extra 与 CSV 不一致：{len(mism)} 处{(' ' + str(mism[:5])) if mism else ''}",
         "- 全冠层覆盖 = |C∩P_τ|/|C|，分母固定为全部冠层格（含 F 内不可喷冠层）；Δ 为百分点。",
         "- 损失条带：B-boundary(0°) 航道边线在 x=−1+k·w，含 F 边 x_F 的航道与 F 重叠 r 被切，F 外损失 x∈[x_F, x_F+w−r]（y 取 F 的 y 范围）。"
         "这是几何推算的描述量，不是从计划量出。", ""] + hdr + tab + ["",
         "描述性线性拟合（图 3；ΔA_extra ~ 损失条带冠层面积；无显著性检验）：", ""] + [
         f"- {k}: n={v['n']}, slope={v['slope']:.4f}, intercept={v['intercept']:+.3f} m², R²={v['r2']:.4f}" for k, v in fits.items()] + [
         f"- τ=0 时 |ΔA_extra + 条带冠层| 最大 {max(abs(p[1] + p[0]) for p in pts3 if p[2] == 0.0):.2e} m²；"
         f"τ=0.5 / 1 时最大残差 {max(abs(p[1] + p[0]) for p in pts3 if p[2] == 0.5):.3f} / {max(abs(p[1] + p[0]) for p in pts3 if p[2] == 1.0):.3f} m²（相对 y=−x）。", ""]
    (ROOT / f"results/a_trial_1c_sweep_{sweep_sha}.overnight_section.md").write_text("\n".join(L), encoding="utf8")
    (ROOT / f"results/a_trial_1c_sweep_{sweep_sha}.report.md").write_text(
        "\n".join(L + ["### |C∩F∩P| 非零行（栅格上喷洒矩形擦入 F 的冠层格；不等于采样违规）", ""] +
                  [f"- {k}: {recs[k]['CFP']}" for k in todo if any(v > 0 for v in recs[k]["CFP"].values())]), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
