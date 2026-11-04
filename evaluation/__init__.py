"""Deterministic grid evaluator using the shared rectangular spray footprint."""

import math
from execution import state_at
from planning import fingerprint, check, configuration
from planning.footprint import rectangle, boxes_touch
from scene.geometry import polygon_bounds
from planning.zones import summary, zone_box, overlap_area, boxes_touch as _touch


def build(scene, plan, timeline, resolution=0.5):
    if (
        not isinstance(resolution, (int, float))
        or not math.isfinite(resolution)
        or resolution <= 0
    ):
        raise ValueError("评价分辨率必须为有限正数")
    check(scene, plan)
    config = configuration(plan["config"])
    if timeline["scene_hash"] != fingerprint(scene) or timeline[
        "plan_hash"
    ] != fingerprint(plan):
        raise ValueError("执行与场景/计划指纹不匹配")
    cells = []
    excluded = sorted({e["target_id"] for e in plan.get("excluded_targets") or []})
    for target in scene["targets"]:
        if target["id"] in excluded:
            continue
        g = target["geometry"]
        x, y = g["center"]
        r = g["radius"]
        row = []
        for ix in range(
            math.floor((x - r) / resolution), math.ceil((x + r) / resolution)
        ):
            for iy in range(
                math.floor((y - r) / resolution), math.ceil((y + r) / resolution)
            ):
                cx = (ix + 0.5) * resolution
                cy = (iy + 0.5) * resolution
                if math.hypot(cx - x, cy - y) <= r:
                    row.append((target["id"], ix, iy))
        cells.extend(row)
    return dict(
        version="1.0",
        resolution=resolution,
        scene_hash=fingerprint(scene),
        plan_hash=fingerprint(plan),
        timeline_id=timeline["execution_id"],
        cells=cells,
        excluded_targets=excluded,
        zone_summary=summary(scene, plan.get("excluded_targets") or []),
        no_spray_boxes=[[z["id"], *zone_box(z)] for z in scene.get("no_spray_zones", [])],
        zone_boxes=[zone_box(z) for z in scene.get("no_spray_zones", []) + scene.get("no_fly_zones", [])],
        duration=timeline["duration"],
        config=config,
    )


def at(evaluation, timeline, time):
    if time < 0 or time > evaluation["duration"] or not math.isfinite(time):
        raise ValueError("评价时间越界")
    covered = {}
    spray_seconds = 0.0
    misspray_area = 0.0
    misspray_segments = 0
    illegal = []
    for seg in timeline["segments"]:
        if seg["spray"]:
            end = min(time, seg["t_end"])
            start = seg["t_start"]
            if end > start:
                spray_seconds += end - start
                flown = seg
                if end < seg["t_end"]:
                    fraction = (end - start) / (seg["t_end"] - seg["t_start"])
                    flown = dict(seg)
                    flown["end"] = [
                        a + (b - a) * fraction
                        for a, b in zip(seg["start"], seg["end"])
                    ]
                foot = rectangle(flown, evaluation["config"]["swath"])
                hit_area = sum(overlap_area(foot, (lo, hi)) for _, lo, hi in evaluation.get("no_spray_boxes", []))
                if hit_area > 0:
                    misspray_area += hit_area
                    misspray_segments += 1
                for target in evaluation["cells"]:
                    tid, ix, iy = target
                    cx = (ix + 0.5) * evaluation["resolution"]
                    cy = (iy + 0.5) * evaluation["resolution"]
                    if (
                        foot[0][0] <= cx <= foot[1][0]
                        and foot[0][1] <= cy <= foot[1][1]
                    ):
                        covered[(tid, ix, iy)] = covered.get((tid, ix, iy), 0) + 1
    total = len(evaluation["cells"])
    hit = sum(1 for v in covered.values() if v)
    repeat = sum(max(0, v - 1) for v in covered.values())
    target_stats=[]
    for tid in sorted({c[0] for c in evaluation["cells"]}):
        allc=[c for c in evaluation["cells"] if c[0]==tid]; hitc=sum(1 for c in allc if c in covered)
        target_stats.append({'target_id':tid,'total_cells':len(allc),'covered_cells':hitc,'coverage':hitc/len(allc) if allc else 0,'missed':len(allc)-hitc,'repeated':sum(max(0,covered.get(c,0)-1) for c in allc)})
    return dict(
        time=time,
        total_cells=total,
        covered_cells=hit,
        coverage=hit / total if total else 0,
        repeated_cells=repeat,
        missed_cells=total - hit,
        spray_seconds=spray_seconds,
        illegal=illegal,
        coverage_cells=list(covered),
        target_stats=target_stats,
        missed_targets=[x['target_id'] for x in target_stats if x['coverage'] < 1.0],
        repeated_targets=[x['target_id'] for x in target_stats if x['repeated'] > 0],
        total_spray_amount=spray_seconds * evaluation['config']['flow_rate'],
        excluded_targets=evaluation.get('excluded_targets', []),
        **_zone_metrics(evaluation, target_stats),
        misspray=dict(area=misspray_area, segments=misspray_segments),
        grid_note='网格近似；目标级统计按目标投影采样单元汇总；excluded_targets（禁喷/禁飞区内）不计入覆盖率分母',
    )


def _zone_metrics(evaluation, target_stats):
    """论文口径：目标覆盖率 = 至少一个采样单元被有效足迹覆盖的应喷目标数 / N_eligible。"""
    zs = dict(evaluation.get("zone_summary") or {})
    n = zs.get("N_eligible", len(target_stats))
    covered = [x for x in target_stats if x["covered_cells"] > 0]
    boxes = evaluation.get("zone_boxes", [])
    centers = {}
    for tid, ix, iy in evaluation["cells"]:
        centers.setdefault(tid, []).append(((ix + 0.5) * evaluation["resolution"], (iy + 0.5) * evaluation["resolution"]))
    partial = []
    for x in target_stats:
        if 0 < x["coverage"] < 1:
            pts = centers[x["target_id"]]
            box = ([min(p[0] for p in pts), min(p[1] for p in pts)], [max(p[0] for p in pts), max(p[1] for p in pts)])
            if any(_touch(([box[0][0] - 1, box[0][1] - 1], [box[1][0] + 1, box[1][1] + 1]), b) for b in boxes):
                partial.append(dict(target_id=x["target_id"], covered_fraction=x["coverage"]))
    return dict(
        **zs,
        target_coverage=len(covered) / n if n else 0.0,
        uncovered_targets=[x["target_id"] for x in target_stats if x["covered_cells"] == 0],
        partial_targets=partial,
    )
