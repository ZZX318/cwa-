"""表1 d=15 两行（仅作参照，非配对）——只读重算。

f3_seed_expand.py --report-only 只出配对表（d=15 可配对 n=0），不出这两行；它还会覆盖
F3_tables.md / F3.report.md，所以这里另写只读实现，只读冻结 CSV。
用法：python scripts/p8_table1_d15.py [--out-dir results/repro_main]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p8_common import OUT_DIR, mean_sd, read_csv, select  # noqa: E402

GEOM = "results/F3_main_postcache_46360be_geom.csv"
COLS = ["A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time"]
RULES = [("S_h", "heuristic"), ("B-boundary", "b_boundary")]


def d15_rows(rows=None) -> list[dict]:
    rows = rows if rows is not None else read_csv(GEOM)
    out = []
    for label, var in RULES:
        rs = select(rows, d=15.0, heading="0", variant=var)
        assert len(rs) == 10 and all(r["status"] == "success" for r in rs), (label, len(rs))
        rec = dict(d=15, rule=label, n=len(rs), seeds=",".join(r["seed"] for r in rs),
                   heuristic_lane_found_true=sum(r["heuristic_lane_found"] == "True" for r in rs),
                   violations_sum=sum(float(r["violations"]) for r in rs))
        for c in COLS:
            m, s = mean_sd(r[c] for r in rs)
            rec[c + "_mean"], rec[c + "_sd"] = m, s
        out.append(rec)
    # Paired n: seeds where S_h premise A0 holds (heuristic_lane_found=True) and both succeed.
    h = {r["seed"]: r for r in select(rows, d=15.0, heading="0", variant="heuristic")}
    b = {r["seed"]: r for r in select(rows, d=15.0, heading="0", variant="b_boundary")}
    paired = [s for s in h if s in b and h[s]["heuristic_lane_found"] == "True"
              and h[s]["status"] == b[s]["status"] == "success"]
    for rec in out:
        rec["paired_n"] = len(paired)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args(argv)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    recs = d15_rows()
    with (out / "table1_d15.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0])); w.writeheader(); w.writerows(recs)
    for r in recs:
        print(r["rule"], " | ".join(f"{r[c+'_mean']:.2f}±{r[c+'_sd']:.2f}" for c in COLS),
              f"lane_found={r['heuristic_lane_found_true']}/10 paired_n={r['paired_n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
