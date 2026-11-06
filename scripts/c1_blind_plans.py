"""C1 盲预测后的 12 个规划：seed=10 × 6 (w,d) × {S_h=heuristic, B=b_boundary}，heading=0。

硬约束：必须在预测 commit 之后运行；总新增规划计入 12。
不改 planning/；只改配置与本新驱动。
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 10
COMBOS = [
    (4.5, 10.0),
    (7.0, 10.0),
    (2.23, 10.0),
    (7.0, 16.0),
    (3.5, 10.0),
    (4.5, 16.0),
]
VARIANTS = ("heuristic", "b_boundary")  # H / B


def strip_stats_w(scene, d, w):
    import numpy as np
    import a_trial_eval as ev

    polygons = ev.buffer_set(scene, d, 0.0)
    xs = [v[0] for f in polygons for v in f["vertices"]]
    ys = [v[1] for f in polygons for v in f["vertices"]]
    xF, y0, y1 = max(xs), min(ys), max(ys)
    r = d - math.floor(d / w) * w
    a, b = xF, xF + (w - r)
    hit = [
        t["geometry"]
        for t in scene["targets"]
        if t["geometry"]["center"][0] + t["geometry"]["radius"] > a
        and t["geometry"]["center"][0] - t["geometry"]["radius"] < b
        and t["geometry"]["center"][1] + t["geometry"]["radius"] > y0
        and t["geometry"]["center"][1] - t["geometry"]["radius"] < y1
    ]
    if b <= a:
        return dict(x_F=xF, lost_strip=[a, b, y0, y1], n_trees=0, canopy_m2=0.0, on_tree_row=False, r=r, w=w)
    X, Y = np.meshgrid(np.arange(a + 0.025, b, 0.05), np.arange(y0 + 0.025, y1, 0.05))
    mask = np.zeros(X.shape, bool)
    for t in hit:
        mask |= (X - t["center"][0]) ** 2 + (Y - t["center"][1]) ** 2 <= t["radius"] ** 2
    return dict(
        x_F=xF,
        lost_strip=[a, b, y0, y1],
        n_trees=len(hit),
        canopy_m2=float(mask.sum() * 0.05 * 0.05),
        on_tree_row=bool(hit),
        r=r,
        w=w,
        hyp_a_width=w - r,
        hyp_b_width=r,
    )


def clear_runtime_caches():
    """Best-effort: drop common cache dirs under results/ and /tmp for this process tree."""
    import shutil

    for p in (
        ROOT / "results" / ".cache",
        ROOT / ".cache",
        Path("/tmp") / "cwa_route_cache",
        Path("/tmp") / "cwa_grid_cache",
    ):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def worker(job):
    clear_runtime_caches()
    import a_trial_heading as H
    import a_trial_extra_runs as E

    w, d, seed, variant = job["w"], job["d"], job["seed"], job["variant"]
    H.apply_swath_override(w)
    H.JOB = {**H.JOB, "drift_buffer": float(d)}
    H.TIERS = {2.0: float(d)}
    info, cut = {}, None
    try:
        scene = H.scene0(seed)
        cut = strip_stats_w(scene, d, w)
        if variant == "b_boundary":
            offset, info = E._boundary_offset(scene, 0, d, w, {})
            run_variant = "main"
        else:
            offset, info = 0.0, {}
            run_variant = "heuristic"
        row, geom = H.run(
            dict(seed=seed, U=2.0, heading=0, offset=offset, variant=run_variant)
        )
        assert abs(float(row["d"]) - d) < 1e-12, (row.get("d"), d)
        row.update(
            variant=variant,
            label="H" if variant == "heuristic" else "B",
            extra_info=info,
            requested_d=d,
            w=w,
            cut_geometry=cut,
            family="c1_blind",
        )
        return row, geom
    except Exception as exc:
        return (
            dict(
                job,
                U=2.0,
                status="exception",
                reason=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
                cut_geometry=cut,
                extra_info=info,
                label="H" if variant == "heuristic" else "B",
                family="c1_blind",
            ),
            None,
        )


def main():
    # Guard: prediction commit must exist and no prior plan outputs for this stem
    pred = subprocess.check_output(
        ["git", "log", "--all", "--format=%H %cI %s", "--grep=blind dual-hypothesis"],
        cwd=ROOT,
        text=True,
    ).strip().splitlines()
    assert pred, "missing prediction commit"
    pred_hash, pred_date, *_ = pred[0].split(" ", 2)
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    stem = f"c1_blind_plans_{sha}"
    out = ROOT / "results"
    csv_path = out / f"{stem}.csv"
    assert not csv_path.exists(), csv_path

    jobs = [
        dict(w=w, d=d, seed=SEED, variant=v) for w, d in COMBOS for v in VARIANTS
    ]
    assert len(jobs) == 12
    rows, geoms = [], {}
    t0 = time.perf_counter()
    print(f"C1 blind plans: {len(jobs)} jobs, pred={pred_hash[:8]} @ {pred_date}", flush=True)
    try:
        pool = ProcessPoolExecutor(max_workers=4, max_tasks_per_child=1)
    except TypeError:
        pool = ProcessPoolExecutor(max_workers=4)
    with pool as ex:
        futs = {ex.submit(worker, j): j for j in jobs}
        for fut in as_completed(futs):
            job = futs[fut]
            try:
                row, geom = fut.result()
            except Exception as exc:
                row, geom = dict(job, status="worker_exception", reason=repr(exc)), None
            rows.append(row)
            ident = f"w{job['w']:g}_d{job['d']:g}_s{job['seed']}_{job['variant']}"
            if geom is not None:
                geoms[ident] = geom
            print(
                f"[{len(rows)}/12] {ident}: {row.get('status')}; "
                f"A0={row.get('A_extra_tau0')}; lane_found={row.get('heuristic_lane_found')}; "
                f"reason={row.get('reason','')}",
                flush=True,
            )
    rows.sort(key=lambda r: (r.get("w", 0), r.get("requested_d", 0), r.get("variant", "")))
    elapsed = time.perf_counter() - t0
    fields = sorted({k for r in rows for k in r})
    with csv_path.open("x", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        for r in rows:
            wr.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                    for k, v in r.items()
                }
            )
    meta = dict(
        commit=sha,
        prediction_commit=pred_hash,
        prediction_date=pred_date,
        seed=SEED,
        n_plans=len(rows),
        elapsed_seconds=elapsed,
        rows_full=rows,
        note="12 blind plans after dual-hypothesis prediction commit",
    )
    (out / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    (out / f"{stem}.geom.json").write_text(json.dumps(geoms, ensure_ascii=False) + "\n")
    # mtime evidence
    mtimes = {
        str(csv_path.relative_to(ROOT)): csv_path.stat().st_mtime,
        str((out / f"{stem}.meta.json").relative_to(ROOT)): (out / f"{stem}.meta.json").stat().st_mtime,
    }
    (out / "c1_blind_mtime_evidence.json").write_text(
        json.dumps(
            dict(prediction_commit=pred_hash, prediction_date=pred_date, plan_mtimes=mtimes),
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(dict(n=len(rows), elapsed=elapsed, csv=str(csv_path)), ensure_ascii=False))
    assert len(rows) == 12


if __name__ == "__main__":
    main()
