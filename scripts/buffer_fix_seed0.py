"""缓冲方向修复后的 seed 0 健全性检查（不是 A 小试）。

ha_orchard seed 0, plot 100x100, _inject_downwind_no_spray (ns-ablation: x∈[-8,-1], y∈[5,95]),
configs/job.ablation.crosswind.json, drift_mode=sort, wind_direction=0（来自 +x，下风 -x）。
对 wind_speed=2（d=10）与 4（d=16）各跑 buffer_expand=0/1，CAW planner（与消融相同 options）。
输出 results/buffer_fix_seed0_<sha7>.json 与 results/buffer_fix_seed0_d10.png / _d16.png。
用法：/home/box/.venvs/mpl/bin/python scripts/buffer_fix_seed0.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import json
import math
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import buffer_oracle as oracle
from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from experiment import _metrics
from planning import configuration, fingerprint
from planning.drift import expand_sensitive_inward, resolve_effective_buffer
from planning.planner import fixed_y_lanes, lane_parts
from planning.zones import classify
from planner_api import make_planner
from random_scene import generate_with_report

OPTIONS = dict(step_xy=2.0, max_grid_nodes=5_000_000, max_expansions=500_000)
JOB = json.loads((ROOT / "configs/job.ablation.crosswind.json").read_text())


def scene0():
    s, _ = generate_with_report("ha_orchard", 0, {"plot_width": 100.0, "plot_height": 100.0})
    return _inject_downwind_no_spray(s)


def run(args):
    wind, be = args
    scene = scene0()
    raw = {**JOB, "drift_mode": "sort", "wind_speed": float(wind), "buffer_expand": float(be)}
    c = configuration(raw)
    d = resolve_effective_buffer(c)
    geo = expand_sensitive_inward(scene, c)
    lay = fixed_y_lanes(geo, raw)
    parts_types = Counter()
    lanes_cut = 0
    lane_spray_len = 0.0
    lane_off_len = 0.0
    for L in lay["lanes"]:
        ps = lane_parts(geo, L, lay["config"])
        parts_types.update(p["type"] for p in ps)
        if any(p["type"] != "spray" for p in ps):
            lanes_cut += 1
        for p in ps:
            ln = math.dist(p["start"][:2], p["end"][:2])
            if p["type"] == "spray":
                lane_spray_len += ln
            else:
                lane_off_len += ln
    excl = classify(scene, c)
    t0 = time.perf_counter()
    plan = make_planner("caw").plan(scene, raw, options=OPTIONS)
    solve = time.perf_counter() - t0
    row = dict(
        wind_speed=wind, buffer_expand=be, d=d,
        zone_original=scene["no_spray_zones"][0]["footprint"]["vertices"],
        zone_expanded=geo["no_spray_zones"][0]["footprint"]["vertices"],
        n_lanes=len(lay["lanes"]), lane_part_types=dict(parts_types), lanes_with_cut=lanes_cut,
        lane_spray_len=round(lane_spray_len, 3), lane_nonspray_len=round(lane_off_len, 3),
        classify_excluded=len(excl), classify_reasons=dict(Counter(e["reason"] for e in excl.values())),
        excluded_ids=sorted(excl),
        status=plan.get("status"), stage=plan.get("stage"), reason=plan.get("reason"),
        solve_seconds=round(solve, 1),
    )
    if plan.get("status") == "success":
        segs = plan["segments"]
        row["plan_hash"] = fingerprint(plan)
        row["plan_segment_types"] = dict(Counter(s.get("type") for s in segs))
        row["plan_spray_len"] = round(sum(math.dist(s["start"][:2], s["end"][:2]) for s in segs if s.get("spray")), 3)
        row["plan_excluded"] = len(plan.get("excluded_targets") or [])
        m = _metrics(scene, plan)
        row.update({k: m.get(k) for k in ("target_coverage", "N_eligible", "coverage", "misspray_area", "total_time", "path_length", "spray_seconds")})
        d_probe = d if d > 0 else resolve_effective_buffer(configuration({**raw, "buffer_expand": 1.0}))
        n, bad = oracle.check_plan_drift_clear(scene, plan, d_probe, float(raw["wind_direction"]), float(lay["config"]["swath"]))
        row["oracle_b_d_probe"] = d_probe
        row["oracle_b_samples"] = n
        row["oracle_b_violations"] = len(bad)
        if d > 0:
            oracle.check_expanded_contains(row["zone_original"], row["zone_expanded"], d, float(raw["wind_direction"]), scene["extent"])
            row["oracle_a"] = "pass"
        row["_segments"] = [dict(start=s["start"], end=s["end"], spray=bool(s.get("spray")), type=s.get("type")) for s in segs]
    return row


def draw(scene, off, on, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon

    fig, ax = plt.subplots(figsize=(10, 10))
    pv = scene["plot"]["vertices"]
    ax.add_patch(Polygon(pv, closed=True, fill=False, ec="black", lw=1.5, label="plot"))
    ax.add_patch(Polygon(on["zone_expanded"], closed=True, fc="orange", alpha=0.25, ec="darkorange", lw=1.5, label="expanded no-spray (d=%g m)" % on["d"]))
    ax.add_patch(Polygon(on["zone_original"], closed=True, fc="none", ec="red", hatch="///", lw=1.5, label="original ns-ablation"))
    lost = set(on["excluded_ids"])
    for t in scene["targets"]:
        g = t["geometry"]
        ax.add_patch(Circle(g["center"], g["radius"], fc="red" if t["id"] in lost else "green", alpha=0.6, ec="none"))
    first = {True: True, False: True}
    for s in on.get("_segments", []):
        xs = [s["start"][0], s["end"][0]]
        ys = [s["start"][1], s["end"][1]]
        if s["spray"]:
            ax.plot(xs, ys, color="tab:blue", lw=1.2, label="spray" if first[True] else None)
            first[True] = False
        else:
            ax.plot(xs, ys, color="gray", lw=0.6, ls="--", label="non-spray (transit/off)" if first[False] else None)
            first[False] = False
    lp = scene["launch_points"][0]["position"]
    ax.plot(lp[0], lp[1], "k^", label="launch")
    e = scene["extent"]
    ax.set_xlim(e["min"][0], e["max"][0]); ax.set_ylim(e["min"][1], e["max"][1]); ax.set_aspect("equal")
    ax.set_title(
        "seed 0, wd=0 (wind from +x, downwind -x), U=%g m/s, d=%g m, buffer_expand=1\n"
        "trees lost %d (red), spray len %.1f m (off: %.1f m), lanes cut %d, status %s"
        % (on["wind_speed"], on["d"], on["classify_excluded"], on.get("plan_spray_len", float("nan")),
           off.get("plan_spray_len", float("nan")), on["lanes_with_cut"], on["status"]),
        fontsize=10,
    )
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"], text=True).strip()
    jobs = [(2, 0.0), (2, 1.0), (4, 0.0), (4, 1.0)]
    with ProcessPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(run, jobs))
    scene = scene0()
    by = {(r["wind_speed"], r["buffer_expand"]): r for r in rows}
    for U, tag in ((2, "d10"), (4, "d16")):
        draw(scene, by[(U, 0.0)], by[(U, 1.0)], ROOT / f"results/buffer_fix_seed0_{tag}.png")
    out = dict(sha=sha, job=JOB, options=OPTIONS, rows=[{k: v for k, v in r.items() if k != "_segments"} for r in rows])
    p = ROOT / f"results/buffer_fix_seed0_{sha}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for r in out["rows"]:
        print(json.dumps({k: v for k, v in r.items() if k not in ("excluded_ids", "zone_original")}, ensure_ascii=False))
    print("wrote", p)


if __name__ == "__main__":
    main()
