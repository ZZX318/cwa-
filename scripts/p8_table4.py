"""表4（选择建议，d=11 几何档）——只读，从表3 的 d=11 行派生；原表为手工派生，此处补脚本。

用法：python scripts/p8_table4.py [--out-dir results/repro_main]
每个数字给出其来源（表3 哪一行哪一列，或差值/百分比公式）。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p8_common import OUT_DIR  # noqa: E402
import p8_main_tables  # noqa: E402


def derive(T=None) -> dict:
    T = T or p8_main_tables.compute()
    t3 = T["table3"]
    sh, b0, b90 = t3[("11", "0°", "S_h")], t3[("11", "0°", "B")], t3[("11", "90°", "B")]
    m = lambda s, c: s[c][0]  # noqa: E731  (mean)
    tm = T["time"]
    # Applicability conditions, from data: d=11 → r = d mod w = 1 ≠ 0 and C∩L≠∅ (B τ=0 > 0);
    # d=15 reference: C∩L=∅ (B τ=0 mean = 0); d=10/16 integer tiers: r = 0.
    t1 = T["table1"]
    cond = dict(r_d11=11 % 2, CL_d11_nonempty=m(b0, "A_extra_tau0") > 0,
                CL_d15_empty=t1[(15, "B")]["A_extra_tau0"][0] == 0.0, r_d10=10 % 2, r_d16=16 % 2)
    rows = {
        # row 2: τ=0, 90° allowed
        "r2_extra_90_tau0": (m(b90, "A_extra_tau0"), "表3 d=11 90° τ=0 mean"),
        "r2_time_90": (m(b90, "total_time"), "表3 d=11 90° time mean"),
        # row 3: τ=0, 0° only
        "r3_dt_sh_b0": (tm["d_sh_b0"], "mean(t S_h 0°) − mean(t B 0°)"),
        "r3_pct_sh_b0": (tm["pct_sh_b0"], "Δt / mean(t B 0°) ×100"),
        "r3_extra_sh_tau0": (m(sh, "A_extra_tau0"), "表3 d=11 0° S_h τ=0 mean"),
        "r3_extra_b0_tau0": (m(b0, "A_extra_tau0"), "表3 d=11 0° B τ=0 mean"),
        "r3_time_sh": (m(sh, "total_time"), "表3 d=11 0° S_h time mean"),
        "r3_time_b0": (m(b0, "total_time"), "表3 d=11 0° B time mean"),
        # row 4: τ=0.5/1.0
        "r4_dt_sh_90": (tm["d_sh_90"], "mean(t S_h 0°) − mean(t B 90°)"),
        "r4_pct_sh_90": (tm["pct_sh_90"], "Δt / mean(t B 90°) ×100"),
        "r4_dt_sh_b0": (tm["d_sh_b0"], "mean(t S_h 0°) − mean(t B 0°)"),
        "r4_pct_sh_b0": (tm["pct_sh_b0"], "Δt / mean(t B 0°) ×100"),
        "r4_sh_tau05": (m(sh, "A_extra_tau0.5"), "表3 d=11 0° S_h τ=0.5"),
        "r4_sh_tau1": (m(sh, "A_extra_tau1"), "表3 d=11 0° S_h τ=1.0"),
        "r4_b0_tau05": (m(b0, "A_extra_tau0.5"), "表3 d=11 0° B τ=0.5"),
        "r4_b0_tau1": (m(b0, "A_extra_tau1"), "表3 d=11 0° B τ=1.0"),
        "r4_b90_tau05": (m(b90, "A_extra_tau0.5"), "表3 d=11 90° τ=0.5"),
        "r4_b90_tau1": (m(b90, "A_extra_tau1"), "表3 d=11 90° τ=1.0"),
        "r4_time_sh": (m(sh, "total_time"), "表3 d=11 0° S_h time"),
        "r4_time_b0": (m(b0, "total_time"), "表3 d=11 0° B time"),
        "r4_time_90": (m(b90, "total_time"), "表3 d=11 90° time"),
    }
    return dict(values=rows, conditions=cond)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args(argv)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    D = derive()
    with (out / "table4_values.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["key", "value", "source"])
        for k, (v, src) in D["values"].items():
            w.writerow([k, repr(v), src])
        for k, v in D["conditions"].items():
            w.writerow([k, v, "condition check"])
    for k, (v, src) in D["values"].items():
        print(f"{k:20s} {v:12.4f}  {src}")
    print(D["conditions"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
