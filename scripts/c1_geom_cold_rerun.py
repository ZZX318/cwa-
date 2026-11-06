"""Cold rerun 16 stratified F3 geom cells; compare A_extra/time/violations (tol 0 / 1e-9)."""
from __future__ import annotations

import csv
import json
import shutil
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clear_caches():
    for p in (
        ROOT / "results" / ".cache",
        ROOT / ".cache",
        Path("/tmp") / "cwa_route_cache",
        Path("/tmp") / "cwa_grid_cache",
    ):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def worker(cell):
    clear_caches()
    import a_trial_heading as H
    import a_trial_extra_runs as E
    from f2_noninteger_dw import strip_stats

    d = float(cell["requested_d"])
    seed = int(cell["seed"])
    heading = int(cell["heading"])
    variant = cell["variant"]
    H.apply_swath_override(2.0)
    H.JOB = {**H.JOB, "drift_buffer": float(d)}
    H.TIERS = {2.0: float(d)}
    try:
        scene = H.scene0(seed)
        cut = strip_stats(scene, d) if heading == 0 else E.oh_rot(scene, 90, d, 2.0)[1]
        offset, info = 0.0, {}
        if variant == "oh_rot":
            offset, info = E.oh_rot(scene, heading, d, 2.0)
            run_variant = "main"
        elif variant == "b_boundary":
            offset, info = E._boundary_offset(scene, heading, d, 2.0, {})
            run_variant = "main"
        else:
            run_variant = "heuristic"
        row, geom = H.run(
            dict(seed=seed, U=2.0, heading=heading, offset=offset, variant=run_variant)
        )
        row.update(variant=variant, requested_d=d, cut_geometry=cut, extra_info=info, family="geom_cold")
        return row
    except Exception as exc:
        return dict(
            cell,
            status="exception",
            reason=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )


def eq(a, b, tol=1e-9):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def main():
    sample = json.loads((ROOT / "results/c1_geom_cold_sample.json").read_text())
    cells = sample["cells"]
    assert len(cells) == 16
    t0 = time.perf_counter()
    try:
        pool = ProcessPoolExecutor(max_workers=4, max_tasks_per_child=1)
    except TypeError:
        pool = ProcessPoolExecutor(max_workers=4)
    results = []
    with pool as ex:
        futs = {ex.submit(worker, c): c for c in cells}
        for fut in as_completed(futs):
            cell = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = dict(cell, status="worker_exception", reason=repr(exc))
            cmp = dict(
                seed=cell["seed"],
                requested_d=cell["requested_d"],
                heading=cell["heading"],
                variant=cell["variant"],
                variant_label=cell["variant_label"],
                role=cell["role"],
                stratum=cell["stratum"],
                status=row.get("status"),
                new_A_extra_tau0=row.get("A_extra_tau0"),
                old_A_extra_tau0=cell["old_A_extra_tau0"],
                A_extra_equal=eq(row.get("A_extra_tau0"), cell["old_A_extra_tau0"]),
                new_total_time=row.get("total_time"),
                old_total_time=cell["old_total_time"],
                time_equal=eq(row.get("total_time"), cell["old_total_time"]),
                new_violations=row.get("violations"),
                old_violations=cell["old_violations"],
                violations_equal=eq(row.get("violations"), cell["old_violations"]),
                new_plan_hash=row.get("plan_hash"),
                old_plan_hash=cell["old_plan_hash"],
                # record hash, do not judge
                reason=row.get("reason", ""),
            )
            cmp["metrics_equal"] = (
                cmp["A_extra_equal"] and cmp["time_equal"] and cmp["violations_equal"]
            )
            results.append(cmp)
            print(
                f"[{len(results)}/16] {cell['stratum']} seed{cell['seed']}: "
                f"status={cmp['status']} metrics_eq={cmp['metrics_equal']} "
                f"A={cmp['A_extra_equal']} t={cmp['time_equal']} v={cmp['violations_equal']}",
                flush=True,
            )
    results.sort(key=lambda r: (r["requested_d"], r["heading"], r["variant_label"], r["seed"]))
    elapsed = time.perf_counter() - t0
    out = dict(
        sampling_seed=sample["sampling_seed"],
        elapsed_seconds=elapsed,
        n=len(results),
        n_metrics_equal=sum(1 for r in results if r["metrics_equal"]),
        n_success=sum(1 for r in results if r["status"] == "success"),
        results=results,
    )
    (ROOT / "results/c1_geom_cold_rerun.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    )
    with (ROOT / "results/c1_geom_cold_rerun.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(results[0]))
        wr.writeheader()
        wr.writerows(results)
    print(
        json.dumps(
            {
                k: out[k]
                for k in ("n", "n_success", "n_metrics_equal", "elapsed_seconds")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
