"""Deterministic grid evaluator using the shared rectangular spray footprint."""

import math
from execution import state_at
from planning import fingerprint, check, configuration
from planning.footprint import rectangle, boxes_touch
from scene.geometry import polygon_bounds
from planning.zones import summary, misspray_area as zone_misspray_area, classify, rect_poly_positive_overlap
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
    classified = classify(scene, config)
    excluded = sorted(classified)
    # 分母只含应喷目标；与计划无关
    for target in scene["targets"]:
        if target["id"] in classified:
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
        zone_summary=summary(scene, config),
        no_spray_zones=list(scene.get("no_spray_zones", [])),
        classified=classified,
        duration=timeline["duration"],
        config=config,
    )


def at(evaluation, timeline, time):
    """t 时刻的评价指标。

    覆盖率口径（coverage，单元覆盖率；总览项 2 核实，不是 bug，见 RESULTS_overnight.md「2. 覆盖率口径」）：
      coverage = covered_cells / total_cells
      total_cells  = build() 中按 resolution（默认 0.5 m）cell 中心采样、且只取"应喷目标"树冠圆盘内的单元数；
                     应喷目标 = 不在 planning.zones.classify(scene, config) 结果里的目标。classify 会按
                     buffer_expand 外扩后的禁喷几何判定，树冠圆盘完全落在外扩禁喷区内的树记为 no_spray 豁免，
                     不可达的记为 no_fly / no_spray_cut，这些树整棵移出分母。
      covered_cells = 上述单元中，中心落在至少一个喷洒段矩形 rectangle(seg, swath)（闭区间）内的单元数。
    因此：
      * 整棵落入缓冲区的树不计入损失（只体现在 N_eligible / exemption_rate 中）；
      * 与缓冲边界相邻、仍应喷的树，若其所在航道因喷幅与外扩禁喷区正面积相交而被整段切掉，损失计入 coverage；
      * coverage 随缓冲距离 d 不单调：取决于缓冲边界落在树冠上还是落在行间空隙里
        （seed 0：d=10 m 边界 x=9 切在第 2 列树冠 [8.852, 13.086] 上 -> 0.9546；
         d=16 m 边界 x=15 落在第 2/3 列间空隙 (13.086, 16.939) 中 -> 1.0）。
    要衡量缓冲造成的总面积损失，应同时报 N_eligible 或用独立评价器 scripts/a_trial_eval.py 的
    A_excluded = |C∩F|、A_extra = |(C\\F)\\P|。
    """
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
                hit_area = zone_misspray_area(foot, evaluation.get("no_spray_zones", []))
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
        grid_note='网格近似；目标级统计按目标投影采样单元汇总；N_eligible 由 classify 决定；豁免/不可达不计入覆盖率分母',
    )


def _zone_metrics(evaluation, target_stats):
    """论文口径：目标覆盖率 = 有正面积覆盖的应喷目标数 / N_eligible；N 来自 classify。"""
    zs = dict(evaluation.get("zone_summary") or {})
    classified = evaluation.get("classified") or {}
    n = zs.get("N_eligible", len(target_stats))
    eligible_ids = {c[0] for c in evaluation["cells"]}
    covered = [x for x in target_stats if x["covered_cells"] > 0]
    # partial：应喷且 0<coverage<1，且树冠与禁喷/有效禁飞正面积相交（因禁区损失覆盖）
    partial = []
    zones = list(evaluation.get("no_spray_zones") or [])
    for x in target_stats:
        if not (0 < x["coverage"] < 1):
            continue
        # 取该目标采样包围盒
        pts = [
            ((ix + 0.5) * evaluation["resolution"], (iy + 0.5) * evaluation["resolution"])
            for tid, ix, iy in evaluation["cells"]
            if tid == x["target_id"]
        ]
        if not pts:
            continue
        box = (
            [min(p[0] for p in pts), min(p[1] for p in pts)],
            [max(p[0] for p in pts), max(p[1] for p in pts)],
        )
        caused = False
        for z in zones:
            if rect_poly_positive_overlap(box, z["footprint"]):
                caused = True
                break
        entry = classified.get(x["target_id"])
        if entry and entry.get("reason") in ("no_fly", "no_spray_cut"):
            caused = True
        if caused:
            partial.append(dict(target_id=x["target_id"], covered_fraction=x["coverage"]))
    return dict(
        **zs,
        target_coverage=len(covered) / n if n else 0.0,
        uncovered_targets=[x["target_id"] for x in target_stats if x["covered_cells"] == 0],
        partial_targets=partial,
    )
