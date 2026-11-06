"""表1、表3（含整数档两行与表注数字）——只读重算，不规划、不写入库文件。

数据：F3_main_postcache_46360be_geom.csv（几何档 d=11/13/15）、F3_main_postcache_46360be_main.csv（整数档）。
p 值：精确 Wilcoxon 符号秩双侧（去零差、平均秩、全符号枚举），与 F2/F3 报告同口径。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p8_common import exact_wilcoxon_two_sided, mean_sd, read_csv, select  # noqa: E402
import p8_table1_d15  # noqa: E402

GEOM = "results/F3_main_postcache_46360be_geom.csv"
MAIN = "results/F3_main_postcache_46360be_main.csv"
COLD = "results/c1_geom_cold_rerun.csv"
TAUS = ["A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1"]
COLS = TAUS + ["total_time"]


def summarize(rs) -> dict:
    assert len(rs) == 10, len(rs)
    assert all(r["status"] == "success" for r in rs)
    assert all(float(r["violations"]) == 0 for r in rs)
    out = {"n": len(rs), "seeds": [int(r["seed"]) for r in rs]}
    for c in COLS:
        out[c] = mean_sd(r[c] for r in rs)
    return out


def same_per_seed(a, b, cols=COLS, tol=1e-9) -> dict:
    """Per-seed equality (|Δ|<=tol) of the given metrics, used for the ≡ claims.

    Also reports max |Δ| and how many seeds share the identical plan_hash (informational).
    """
    assert [r["seed"] for r in a] == [r["seed"] for r in b]
    dmax = max(abs(float(x[c]) - float(y[c])) for x, y in zip(a, b) for c in cols)
    return dict(equal=dmax <= tol, max_abs_diff=dmax,
                plan_hash_equal=sum(x["plan_hash"] == y["plan_hash"] for x, y in zip(a, b)), n=len(a))


def compute() -> dict:
    geom, main = read_csv(GEOM), read_csv(MAIN)
    T = {"table1": {}, "table3": {}, "checks": {}, "notes": {}}
    sel = {}
    for d in (11.0, 13.0, 15.0):
        sel[(d, 0, "S_h")] = select(geom, d=d, heading="0", variant="heuristic")
        sel[(d, 0, "B")] = select(geom, d=d, heading="0", variant="b_boundary")
        sel[(d, 90, "B")] = select(geom, d=d, heading="90", variant="b_boundary")
        sel[(d, 90, "oh_rot")] = select(geom, d=d, heading="90", variant="oh_rot")
    sel[(10.0, 0, "S_h")] = select(main, d=10.0, U=2.0, heading="0", variant="heuristic")
    sel[(10.0, 0, "B")] = select(main, d=10.0, U=2.0, heading="0", variant="b_boundary")
    sel[(10.0, 90, "B")] = select(main, d=10.0, U=2.0, heading="90", variant="b_boundary")
    sel[(10.0, 90, "oh_rot")] = select(main, d=10.0, U=2.0, heading="90", variant="oh_rot")
    S = {k: summarize(v) for k, v in sel.items()}

    # 表1: d=11/13 paired rows + d=15 reference rows (separate read-only script).
    for d in (11.0, 13.0):
        T["table1"][(int(d), "S_h")] = S[(d, 0, "S_h")]
        T["table1"][(int(d), "B")] = S[(d, 0, "B")]
    d15 = p8_table1_d15.d15_rows(geom)
    for rec, key in zip(d15, ["S_h", "B"]):
        T["table1"][(15, key)] = {c: (rec[c + "_mean"], rec[c + "_sd"]) for c in COLS}
    T["notes"]["d15_heuristic_lane_found_true"] = d15[0]["heuristic_lane_found_true"]
    T["notes"]["d15_paired_n"] = d15[0]["paired_n"]
    # Paired exact Wilcoxon for d=11/13 at each τ (S_h − B).
    pv = {}
    for d in (11.0, 13.0):
        h, b = sel[(d, 0, "S_h")], sel[(d, 0, "B")]
        assert [r["seed"] for r in h] == [r["seed"] for r in b]
        assert all(r["heuristic_lane_found"] == "True" for r in h)
        for c in TAUS:
            diffs = [float(x[c]) - float(y[c]) for x, y in zip(h, b)]
            n, p = exact_wilcoxon_two_sided(diffs)
            pv[(int(d), c)] = dict(n=n, p=p, all_negative=all(x < 0 for x in diffs))
    T["notes"]["wilcoxon"] = pv
    # Cold rerun 16/16 (表1 注).
    cold = read_csv(COLD)
    T["notes"]["cold_rerun"] = (sum(r["metrics_equal"] == "True" for r in cold), len(cold))
    # d=15 loss strip L=[x_F, x_F+(w−r)] from frozen cut_geometry (表1 注 “L=[14,15]”).
    import json
    cg = {json.dumps(json.loads(r["cut_geometry"])["lost_strip"][:2]) for r in sel[(15.0, 0, "B")]}
    assert len(cg) == 1, cg
    T["notes"]["d15_lost_strip"] = json.loads(cg.pop())

    # 表3 rows.
    order = [
        ("11", "0°", "S_h", (11.0, 0, "S_h")), ("11", "0°", "B", (11.0, 0, "B")),
        ("11", "90°", "B", (11.0, 90, "B")),
        ("13", "0°", "S_h", (13.0, 0, "S_h")), ("13", "0°", "B", (13.0, 0, "B")),
        ("13", "90°", "B", (13.0, 90, "B")),
        ("10", "0°", "S_h≡B", (10.0, 0, "S_h")), ("10", "90°", "B", (10.0, 90, "B")),
    ]
    for d, hd, rule, key in order:
        T["table3"][(d, hd, rule)] = S[key]
    T["table3_d15_90"] = S[(15.0, 90, "B")]
    # ≡ claims checked per seed on the frozen rows.
    for d in (11.0, 13.0, 15.0, 10.0):
        T["checks"][f"d{int(d)}_90_B_equiv_oh_rot"] = same_per_seed(sel[(d, 90, "B")], sel[(d, 90, "oh_rot")])
    T["checks"]["d10_0_S_h_equiv_B"] = same_per_seed(sel[(10.0, 0, "S_h")], sel[(10.0, 0, "B")])
    # 时间代价（表3 后文）：差值与百分比由均值计算。
    t_sh = S[(11.0, 0, "S_h")]["total_time"][0]
    t_b0 = S[(11.0, 0, "B")]["total_time"][0]
    t_90 = S[(11.0, 90, "B")]["total_time"][0]
    T["time"] = dict(t_sh=t_sh, t_b0=t_b0, t_90=t_90, d_sh_90=t_sh - t_90, pct_sh_90=100 * (t_sh - t_90) / t_90,
                     d_sh_b0=t_sh - t_b0, pct_sh_b0=100 * (t_sh - t_b0) / t_b0)
    return T


if __name__ == "__main__":
    import pprint
    pprint.pprint(compute(), width=140)
