"""Deterministic grid evaluator using the shared rectangular spray footprint."""

import math
from execution import state_at
from planning import fingerprint, check, configuration
from planning.footprint import rectangle, boxes_touch
from scene.geometry import polygon_bounds


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
    for target in scene["targets"]:
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
    restrictions = [
        dict(id=zone["id"], bounds=polygon_bounds(zone["footprint"]))
        for zone in scene["no_fly_zones"] + scene["no_spray_zones"]
    ]
    excluded_xy = []
    for ix, iy in sorted({(ix, iy) for _, ix, iy in cells}):
        cx, cy = (ix + 0.5) * resolution, (iy + 0.5) * resolution
        if any(
            region["bounds"]["min"][0] <= cx <= region["bounds"]["max"][0]
            and region["bounds"]["min"][1] <= cy <= region["bounds"]["max"][1]
            for region in restrictions
        ):
            excluded_xy.append((ix, iy))
    return dict(
        version="1.0",
        resolution=resolution,
        scene_hash=fingerprint(scene),
        plan_hash=fingerprint(plan),
        timeline_id=timeline["execution_id"],
        cells=cells,
        restrictions=restrictions,
        excluded_xy=excluded_xy,
        duration=timeline["duration"],
        config=config,
    )


def at(evaluation, timeline, time):
    if time < 0 or time > evaluation["duration"] or not math.isfinite(time):
        raise ValueError("评价时间越界")
    covered = {}
    spray_seconds = 0.0
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
                for region in evaluation.get("restrictions", []):
                    bounds = region["bounds"]
                    if boxes_touch(foot, (bounds["min"], bounds["max"])):
                        illegal.append(dict(
                            zone_id=region["id"], segment_index=seg["index"],
                            t_start=start, t_end=end,
                            overlap_area_m2=math.prod(
                                max(0.0, min(foot[1][i], bounds["max"][i])
                                    - max(foot[0][i], bounds["min"][i]))
                                for i in (0, 1)
                            ),
                        ))
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
    target_xy = {(ix, iy) for _, ix, iy in evaluation["cells"]}
    excluded_xy = set(map(tuple, evaluation.get("excluded_xy", []))) & target_xy
    sprayable_xy = target_xy - excluded_xy
    covered_xy = {(ix, iy) for _, ix, iy in covered}
    covered_sprayable_xy = sprayable_xy & covered_xy
    union_passes = {}
    for (_, ix, iy), passes in covered.items():
        union_passes[(ix, iy)] = max(union_passes.get((ix, iy), 0), passes)
    cell_area = evaluation["resolution"] ** 2
    target_stats=[]
    for tid in sorted({c[0] for c in evaluation["cells"]}):
        allc=[c for c in evaluation["cells"] if c[0]==tid]; hitc=sum(1 for c in allc if c in covered)
        target_stats.append({'target_id':tid,'total_cells':len(allc),'covered_cells':hitc,'coverage':hitc/len(allc) if allc else 0,'missed':len(allc)-hitc,'repeated':sum(max(0,covered.get(c,0)-1) for c in allc)})
    return dict(
        time=time,
        total_cells=total,
        covered_cells=hit,
        coverage=hit / total if total else 0,
        canopy_union_area_m2=len(target_xy) * cell_area,
        restricted_canopy_area_m2=len(excluded_xy) * cell_area,
        sprayable_canopy_area_m2=len(sprayable_xy) * cell_area,
        covered_sprayable_area_m2=len(covered_sprayable_xy) * cell_area,
        extra_miss_area_m2=len(sprayable_xy - covered_xy) * cell_area,
        repeated_sprayable_area_m2=sum(max(0, n-1) for xy,n in union_passes.items()
                                       if xy in sprayable_xy) * cell_area,
        sprayable_coverage=(
            len(covered_sprayable_xy) / len(sprayable_xy) if sprayable_xy else None
        ),
        repeated_cells=repeat,
        missed_cells=total - hit,
        spray_seconds=spray_seconds,
        illegal=illegal,
        coverage_cells=list(covered),
        target_stats=target_stats,
        missed_targets=[x['target_id'] for x in target_stats if x['coverage'] < 1.0],
        repeated_targets=[x['target_id'] for x in target_stats if x['repeated'] > 0],
        total_spray_amount=spray_seconds * evaluation['config']['flow_rate'],
        grid_note=(
            '网格中心采样近似；总覆盖率按目标分别统计；面积指标按空间网格去重；'
            '可喷面积扣除禁飞/禁喷多边形的保守包围矩形，忽略区域高度'
        ),
    )
