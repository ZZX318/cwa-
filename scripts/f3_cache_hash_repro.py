"""Read-only F3 cache cross-talk repro (step ①). Does not modify planning/.

Reproduces seed2 U=2 B-boundary 0° plan_hash mismatch after a same-process
predecessor (seed2 U=2 heuristic 0°), vs a fresh-process B-only run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FROZEN_B = "4a81e0ea87be1bbc291cf334a1ad82a4c8162711ad60ddc445d3d91bca98443c"
POOL_B = "dc9c98d65faa6dd350207837387a4b8aba106bd50086c9653ae42d0260432f12"
FROZEN_METRICS = {
    "A_extra_tau0": 0.0,
    "A_extra_tau0.5": 0.5875000000000001,
    "A_extra_tau1": 1.3725000000000003,
    "total_time": 1442.2321342517662,
    "violations": 0,
}
PRED = dict(seed=2, U=2.0, heading=0, variant="heuristic", family="main")
TARGET = dict(seed=2, U=2.0, heading=0, variant="b_boundary", family="main")


def _install_cache_probe():
    import planning.routing3d as R

    stats = {
        "hits": 0,
        "misses": 0,
        "false_endpoint": 0,
        "examples": [],
        "route_calls": 0,
    }
    real_get = R._ROUTE_CACHE.get

    def counting_get(k, default=None):
        v = real_get(k, default)
        if v is not None:
            stats["hits"] += 1
        else:
            stats["misses"] += 1
        return v

    R._ROUTE_CACHE.get = counting_get  # type: ignore
    orig = R.route3d

    def wrapped(scene, start, goal, config, objective="time", grid=None):
        stats["route_calls"] += 1
        result = orig(scene, start, goal, config, objective=objective, grid=grid)
        if result.get("status") == "success" and result.get("path"):
            p0, p1 = result["path"][0], result["path"][-1]
            rs = tuple(round(float(v), 9) for v in start)
            rg = tuple(round(float(v), 9) for v in goal)
            ps = tuple(round(float(v), 9) for v in p0)
            pg = tuple(round(float(v), 9) for v in p1)
            bit_ok = list(p0) == [float(v) for v in start] and list(p1) == [float(v) for v in goal]
            if ps == rs and pg == rg and not bit_ok:
                stats["false_endpoint"] += 1
                if len(stats["examples"]) < 8:
                    stats["examples"].append(
                        dict(
                            req_start=[float(v) for v in start],
                            path_start=list(p0),
                            req_goal=[float(v) for v in goal],
                            path_goal=list(p1),
                            start_ulp_diffs=[float(a) - float(b) for a, b in zip(p0, start)],
                            goal_ulp_diffs=[float(a) - float(b) for a, b in zip(p1, goal)],
                        )
                    )
        return result

    R.route3d = wrapped
    return stats


def run_job(job):
    from f3_seed_expand import worker_main

    t0 = time.perf_counter()
    row, geom = worker_main(job)
    row = dict(row)
    row["_wall"] = round(time.perf_counter() - t0, 3)
    return row, geom


def summarize(row):
    keys = (
        "seed",
        "variant",
        "U",
        "heading",
        "offset",
        "lane_offset_used",
        "plan_hash",
        "solve_seconds",
        "A_extra_tau0",
        "A_extra_tau0.5",
        "A_extra_tau1",
        "total_time",
        "violations",
        "path_length",
        "path_spray",
        "n_lanes",
        "status",
        "_wall",
    )
    return {k: row.get(k) for k in keys}


def metrics_equal_frozen(row):
    return {k: (row.get(k) == v) for k, v in FROZEN_METRICS.items()}


def lane_endpoint_compare():
    """Show whether heuristic vs b_boundary lane endpoints are bit-identical."""
    import a_trial_heading as H
    import a_trial_extra_runs as E
    import planning.planner as pp
    from planning import configuration
    from planning.drift import resolve_effective_buffer

    H.apply_swath_override(2.0)
    H.TIERS = {2.0: 10.0, 4.0: 16.0}
    H.JOB = {k: v for k, v in H.JOB.items() if k != "drift_buffer"}
    scene = H.scene0(2)
    d = 10.0
    raw0 = {**H.JOB, "drift_mode": "sort", "wind_speed": 2.0, "wind_direction": 0.0, "buffer_expand": 1.0}
    o_h, x_F, xmin = H.heuristic_offset(scene, d, 0.0, 2.0)
    o_b, info = E._boundary_offset(scene, 0, d, 2.0, {})
    out = {
        "offset_heuristic": o_h,
        "offset_b_boundary": o_b,
        "offset_diff": o_h - o_b,
        "offset_round9_equal": round(o_h, 9) == round(o_b, 9),
        "boundary_info": info,
    }
    lanes = {}
    for name, off in (("heuristic", o_h), ("b_boundary", o_b)):
        H.install_lane_offset(off)
        layout = pp.fixed_y_lanes(scene, raw0)
        lanes[name] = [(lane["start"], lane["end"]) for lane in layout["lanes"]]
        out[f"n_lanes_{name}"] = len(layout["lanes"])
    n = min(len(lanes["heuristic"]), len(lanes["b_boundary"]))
    bit_diff = 0
    round9_diff = 0
    examples = []
    for i in range(n):
        sh, eh = lanes["heuristic"][i]
        sb, eb = lanes["b_boundary"][i]
        for label, a, b in (("start", sh, sb), ("end", eh, eb)):
            if list(a) != list(b):
                bit_diff += 1
                if tuple(round(float(v), 9) for v in a) != tuple(round(float(v), 9) for v in b):
                    round9_diff += 1
                if len(examples) < 6:
                    examples.append(
                        dict(
                            i=i,
                            end=label,
                            heuristic=list(a),
                            b_boundary=list(b),
                            diff=[float(x) - float(y) for x, y in zip(a, b)],
                            round9_equal=tuple(round(float(v), 9) for v in a)
                            == tuple(round(float(v), 9) for v in b),
                        )
                    )
    out.update(
        lane_pairs_compared=n,
        endpoint_bit_diffs=bit_diff,
        endpoint_round9_diffs=round9_diff,
        endpoint_examples=examples,
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=("chained", "fresh_target", "lane_compare", "all"),
        required=True,
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    import planning.routing3d as R

    base = {
        "pred_job": PRED,
        "target_job": TARGET,
        "frozen_b_hash": FROZEN_B,
        "pool_b_hash": POOL_B,
        "frozen_metrics": FROZEN_METRICS,
        "evidence_pred_from_checkpoint": (
            "F3_main_checkpoint.jsonl completion order: "
            "[14] seed2 heuristic U=2 h=0 solve=77.7s hash=d742d538…; "
            "[15] seed2 b_boundary U=2 h=0 solve=13.9s hash=dc9c98d6… "
            "(anomalously short; pool mismatch). "
            "Worker PID not logged; same-process chain is the controlled repro."
        ),
        "cache_key_route": [
            "fingerprint(scene)",
            "config_fingerprint(effective)",
            "objective",
            "round(start,9)",
            "round(goal,9)",
            "step_xy",
            "step_z",
            "max_expansions",
            "max_grid_nodes",
            "smoothing",
        ],
        "cache_key_grid": [
            "fingerprint(scene)",
            "config_fingerprint(config)",
            "step_xy",
            "step_z",
            "round(start_z,9)",
            "round(goal_z,9)",
            "(XY omitted)",
        ],
        "key_omits": (
            "No explicit lane_offset / variant / heading fields — those enter only "
            "via scene fingerprint, config (wind_speed/direction, drift_buffer), and "
            "start/goal coordinates. start/goal are rounded to 9 decimals in the key, "
            "while the cached path retains the first caller's full-precision endpoints."
        ),
    }

    if a.mode in ("lane_compare", "all"):
        base["lane_compare"] = lane_endpoint_compare()

    if a.mode in ("fresh_target", "all"):
        R.clear_cache()
        stats = _install_cache_probe()
        # re-bind after clear; counting_get already on cache object
        row, _ = run_job(TARGET)
        base["fresh_target"] = {
            "row": summarize(row),
            "hash_vs_frozen": row.get("plan_hash") == FROZEN_B,
            "hash_vs_pool": row.get("plan_hash") == POOL_B,
            "metrics_eq_frozen": metrics_equal_frozen(row),
            "route_cache_stats": dict(stats),
            "cache_sizes": dict(route=len(R._ROUTE_CACHE), grid=len(R._GRID_CACHE)),
        }

    if a.mode in ("chained", "all"):
        # Fresh interpreter state preferred; if all-mode, caches already warm from fresh.
        # For chained we need empty cache then pred then target — if all, restart probe.
        R.clear_cache()
        stats = _install_cache_probe()
        stats["hits"] = stats["misses"] = stats["false_endpoint"] = stats["route_calls"] = 0
        stats["examples"] = []
        pred_row, _ = run_job(PRED)
        after_pred = dict(route=len(R._ROUTE_CACHE), grid=len(R._GRID_CACHE), stats=dict(stats))
        stats["hits"] = stats["misses"] = stats["false_endpoint"] = stats["route_calls"] = 0
        stats["examples"] = []
        tgt_row, _ = run_job(TARGET)
        base["chained"] = {
            "predecessor": summarize(pred_row),
            "after_pred": after_pred,
            "target": summarize(tgt_row),
            "route_cache_stats_during_target": dict(stats),
            "cache_after_target": dict(route=len(R._ROUTE_CACHE), grid=len(R._GRID_CACHE)),
            "hash_vs_frozen": tgt_row.get("plan_hash") == FROZEN_B,
            "hash_vs_pool": tgt_row.get("plan_hash") == POOL_B,
            "metrics_eq_frozen": metrics_equal_frozen(tgt_row),
        }

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # compact stdout
    brief = {k: base[k] for k in base if k not in ("cache_key_route", "cache_key_grid")}
    print(json.dumps(brief, indent=2, ensure_ascii=False)[:6000])


if __name__ == "__main__":
    main()
