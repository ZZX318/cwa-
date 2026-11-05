"""T8: five tiers, fixed-y generate_plan (no CAW search).

Reuse the original four tiers verbatim; run only no_wind_awareness seeds 0–29.

Run: python3 scripts/wind_baseline_T8.py --workers 4
min_buffer_1m is a geometric assumption (几何假设), not Kong 2026.
Areas use a_trial_eval's original-scene F construction and 0.05 m raster.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from a_trial_eval import evaluate
from planning import configuration, fingerprint, generate_plan
from planning.drift import resolve_effective_buffer
from planning.model import _digest
from planning.zones import summary
from random_scene import generate_with_report

JOB = json.loads((ROOT / "configs/job.ablation.crosswind.json").read_text())
CONDITIONS = {
    "none": dict(buffer_expand=0, min_buffer=0, wind_speed=0, drift_buffer=0),
    "min_buffer_1m": dict(buffer_expand=1, min_buffer=1.0, wind_speed=0.0, drift_buffer=0),
    "d10": dict(buffer_expand=1, min_buffer=0, wind_speed=2.0, drift_buffer=0),
    "d16": dict(buffer_expand=1, min_buffer=0, wind_speed=4.0, drift_buffer=0),
}
NEW_CONDITION = "no_wind_awareness"
CONDITIONS[NEW_CONDITION] = dict(buffer_expand=0, min_buffer=0, wind_speed=2.0, drift_buffer=0)
EXPECTED = dict(none=0, min_buffer_1m=1, d10=10, d16=16, no_wind_awareness=0)
PRIOR_CSV = ROOT / "results/wind_baseline_T8_463badb.csv"
METRICS = ("A_C", "A_excluded", "A_extra", "full_canopy_coverage", "N_exempt",
           "N_eligible", "exemption_rate", "violations", "path_length", "total_time")


def run(task):
    seed, condition = task
    row = dict(seed=seed, condition=condition,
               note=("no_wind_awareness_downwind_baseline" if condition == NEW_CONDITION else
                     "geometric_assumption_not_Kong2026" if condition == "min_buffer_1m" else ""),
               **CONDITIONS[condition], eval_resolution=0.05, tau=0.0)
    start = time.perf_counter()
    try:
        scene, _ = generate_with_report("ha_orchard", seed,
                                        dict(plot_width=100.0, plot_height=100.0))
        scene = _inject_downwind_no_spray(scene)
        raw = {**JOB, **CONDITIONS[condition], "drift_mode": "sort"}
        c = configuration(raw)
        d = resolve_effective_buffer(c)
        assert d == EXPECTED[condition], (condition, d)
        row["d_effective"] = d
        eval_d = 10.0 if condition == NEW_CONDITION else d
        row["eval_d"] = eval_d
        z = summary(scene, c)
        row.update({k: z[k] for k in ("N_total", "N_eligible", "exemption_rate")})
        row["N_exempt"] = z["N_total"] - z["N_eligible"]
        plan = generate_plan(scene, raw)
        row.update(status=plan.get("status"), reason=plan.get("reason", ""),
                   plan_hash=fingerprint(plan), config_hash=plan.get("config_hash"),
                   segment_digest=_digest(plan.get("segments", [])))
        if row["status"] == "success":
            ev = evaluate(scene, plan["segments"], eval_d, c["wind_direction"], c["swath"],
                          c["speed"], c, taus=(0.0,), resolutions=(0.05,), extra_cov=True)
            row.update({k: ev[k] for k in ("A_C", "A_excluded", "violations", "path_length", "total_time")})
            row["A_extra"] = ev["A_extra_tau0"]
            row["full_canopy_coverage"] = (ev["A_C"] - ev["A_excluded"] - ev["A_extra_tau0"]) / ev["A_C"]
            row["A_CFP"] = ev["A_CFP_tau0"]
            row["full_canopy_coverage_direct"] = ev["A_cov_tau0"] / ev["A_C"]
            # Direct coverage also includes spraying inside the evaluation buffer F.
            assert abs(row["full_canopy_coverage"] + row["A_CFP"] / row["A_C"]
                       - row["full_canopy_coverage_direct"]) < 1e-10
    except Exception:
        row.update(status="error", reason=traceback.format_exc())
    row["wall_seconds"] = time.perf_counter() - start
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    prefix = ROOT / "results" / f"wind_baseline_T8_{sha[:7]}"
    sources = ["scripts/wind_baseline_T8.py", "planning/model.py", "planning/drift.py",
               "scripts/a_trial_eval.py", "scripts/ablation_sort_vs_sort_drift.py",
               "configs/job.ablation.crosswind.json"]
    meta = dict(base_commit=sha, planner="planning.generate_plan / fixed-y", job=JOB,
                conditions=CONDITIONS, workers=args.workers, seeds=list(range(30)),
                eval_resolution=0.05, tau=0.0,
                source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources})
    with PRIOR_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    expected_keys = {(str(s), c) for s in range(30) for c in CONDITIONS if c != NEW_CONDITION}
    assert len(rows) == 120 and {(r["seed"], r["condition"]) for r in rows} == expected_keys
    meta.update(reused_csv=str(PRIOR_CSV.relative_to(ROOT)),
                reused_csv_sha256=hashlib.sha256(PRIOR_CSV.read_bytes()).hexdigest(),
                reused_rows=len(rows), executed_conditions=[NEW_CONDITION],
                eval_d_by_condition={**EXPECTED, NEW_CONDITION: 10.0})
    with prefix.with_suffix(".log").open("w") as log:
        def emit(value):
            line = json.dumps(value, ensure_ascii=False)
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
        emit(meta)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run, (s, c)) for s in range(30) for c in [NEW_CONDITION]]
            for future in as_completed(futures):
                row = future.result()
                row["base_commit"] = sha
                rows.append(row)
                emit(row)
        rows.sort(key=lambda r: (int(r["seed"]), list(CONDITIONS).index(r["condition"])))
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with prefix.with_suffix(".csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        groups = {}
        for condition in CONDITIONS:
            group = [r for r in rows if r["condition"] == condition]
            ok = [r for r in group if r["status"] == "success"]
            stats = dict(n=len(group), success=len(ok), failures=len(group)-len(ok))
            for metric in METRICS:
                values = [float(r[metric]) for r in ok]
                stats[metric] = (dict(mean=statistics.mean(values), sd=statistics.stdev(values) if len(values)>1 else 0,
                                      min=min(values), max=max(values)) if values else None)
            groups[condition] = stats
        meta["summary"] = groups
        prefix.with_suffix(".summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2)+"\n")
        emit(dict(completed=len(rows), failures=sum(r["status"] != "success" for r in rows)))
    return int(any(r["status"] != "success" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
