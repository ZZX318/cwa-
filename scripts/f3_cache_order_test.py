"""Plan-level cache order stability: seed2 U=2 heuristic↔B vs fresh solos.

Asserts plan_hash of each variant matches its fresh-process solo, and that
route3d path endpoints stay bitwise-equal to each call's start/goal under load.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FROZEN_B = "4a81e0ea87be1bbc291cf334a1ad82a4c8162711ad60ddc445d3d91bca98443c"
FROZEN_H = "d742d538e13bfd1a70b42f2b5e25e7d5b31dd80e3c9bd546bab9169a311c2f86"
JOB_H = dict(seed=2, U=2.0, heading=0, variant="heuristic", family="main")
JOB_B = dict(seed=2, U=2.0, heading=0, variant="b_boundary", family="main")


def _run(job):
    from f3_seed_expand import worker_main
    import planning.routing3d as R

    # Patch route3d to assert endpoint bitwise equality on every call.
    orig = R.route3d

    def wrapped(scene, start, goal, config, objective="time", grid=None):
        result = orig(scene, start, goal, config, objective=objective, grid=grid)
        if result.get("status") == "success" and result.get("path"):
            assert list(result["path"][0]) == [float(v) for v in start], (
                result["path"][0],
                start,
            )
            assert list(result["path"][-1]) == [float(v) for v in goal], (
                result["path"][-1],
                goal,
            )
        return result

    R.route3d = wrapped
    try:
        t0 = time.perf_counter()
        row, _ = worker_main(job)
        row = dict(row)
        row["_wall"] = round(time.perf_counter() - t0, 3)
        return row
    finally:
        R.route3d = orig


def main():
    import planning.routing3d as R
    from planning.routing3d import clear_cache

    out = {"frozen_b": FROZEN_B, "frozen_h": FROZEN_H}

    # Fresh solos in this process, clearing cache between (simulates fresh process
    # for cache state; full interpreter isolation is the chained/fresh repro).
    clear_cache()
    fresh_b = _run(JOB_B)
    out["fresh_b"] = dict(plan_hash=fresh_b["plan_hash"], solve=fresh_b["solve_seconds"])

    clear_cache()
    fresh_h = _run(JOB_H)
    out["fresh_h"] = dict(plan_hash=fresh_h["plan_hash"], solve=fresh_h["solve_seconds"])

    # heuristic → B
    clear_cache()
    pred_h = _run(JOB_H)
    tgt_b = _run(JOB_B)
    out["chain_h_then_b"] = dict(
        pred_hash=pred_h["plan_hash"],
        target_hash=tgt_b["plan_hash"],
        target_solve=tgt_b["solve_seconds"],
    )

    # B → heuristic
    clear_cache()
    pred_b = _run(JOB_B)
    tgt_h = _run(JOB_H)
    out["chain_b_then_h"] = dict(
        pred_hash=pred_b["plan_hash"],
        target_hash=tgt_h["plan_hash"],
        target_solve=tgt_h["solve_seconds"],
    )

    errors = []
    if fresh_b["plan_hash"] != FROZEN_B:
        errors.append(f"fresh B hash {fresh_b['plan_hash']} != frozen {FROZEN_B}")
    if fresh_h["plan_hash"] != FROZEN_H:
        errors.append(f"fresh H hash {fresh_h['plan_hash']} != frozen {FROZEN_H}")
    if tgt_b["plan_hash"] != fresh_b["plan_hash"]:
        errors.append(
            f"H→B target {tgt_b['plan_hash']} != fresh B {fresh_b['plan_hash']}"
        )
    if tgt_h["plan_hash"] != fresh_h["plan_hash"]:
        errors.append(
            f"B→H target {tgt_h['plan_hash']} != fresh H {fresh_h['plan_hash']}"
        )
    if pred_h["plan_hash"] != fresh_h["plan_hash"]:
        errors.append("pred H in H→B chain drifted from fresh H")
    if pred_b["plan_hash"] != fresh_b["plan_hash"]:
        errors.append("pred B in B→H chain drifted from fresh B")

    out["ok"] = not errors
    out["errors"] = errors
    path = ROOT / "results/F3_cache_order_test.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
