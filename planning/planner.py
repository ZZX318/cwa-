import copy
import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from scene.launch import resolve
from .footprint import overlaps_target
from .zones import rect_poly_positive_overlap
from .model import configuration, config_fingerprint, fingerprint, options_fingerprint
from .drift import expand_sensitive_inward
from .safety import check

# 切割边界与禁喷区 AABB 之间的留隙；须大于 safety.boxes_touch 的 1e-9 接触容差。
_ZONE_GAP = 1e-6


def fixed_y_lanes(scene: dict, raw=None) -> dict:
    """Shared fixed-Y spray-lane set; the only source for every lane planner.

    Returns ``lanes`` (unchanged endpoint/association geometry), ``strip_count``
    and ``work_height``.  The arithmetic is the original ``generate_plan``
    order, so fixed-Y output stays byte-for-byte reproducible.
    """
    validate_scene(scene)
    c = configuration(raw or {})
    if not scene["targets"] or not scene["trees"]:
        raise ValueError("不支持空目标场景")
    targets = scene["targets"]
    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in targets)
    xmax = max(t["geometry"]["center"][0] + t["geometry"]["radius"] for t in targets)
    n = math.ceil((xmax - xmin) / c["swath"])
    if n > 10000:
        raise ValueError("作业带超过 10000，喷幅过小")
    height = max(t["canopy"]["z_max"] for t in scene["trees"]) + c["height_offset"]
    if any(t["geometry"]["z_max"] >= height for t in targets):
        raise ValueError("目标体积高于作业面，不支持")
    lanes = []
    active = 0
    for k in range(n):
        low = xmin + k * c["swath"]
        high = min(xmax, low + c["swath"])
        x = (low + high) / 2
        intervals = []
        for t in targets:
            g = t["geometry"]
            cx, cy = g["center"]
            r = g["radius"]
            dx = max(low - cx, 0, cx - high)
            if dx < r:
                dy = math.sqrt(max(0, r * r - dx * dx))
                intervals.append((cy - dy, cy + dy, t["id"]))
        merged = []
        for lo, hi, tid in sorted(intervals):
            if merged and lo <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], hi)
                merged[-1][2].append(tid)
            else:
                merged.append([lo, hi, [tid]])
        if not merged:
            continue
        reverse = active % 2 == 1
        active += 1
        for lo, hi, ids in (reversed(merged) if reverse else merged):
            start, end = (hi, lo) if reverse else (lo, hi)
            lanes.append(
                dict(
                    start=[x, start, height],
                    end=[x, end, height],
                    type="spray",
                    spray=True,
                    speed=c["speed"],
                    target_ids=sorted(ids),
                )
            )
    return dict(lanes=lanes, strip_count=active, work_height=height, config=c)


def lane_parts(scene: dict, lane: dict, c: dict) -> list:
    """_split_lane without leading/trailing no-fly gaps.

    An end of the lane that falls inside a no-fly buffer is simply not flown:
    the planner enters at the first kept piece's start and leaves from the
    last kept piece's end.  A lane fully inside no-fly returns ``[]``.
    """
    parts = _split_lane(scene, lane, c)
    while parts and parts[0]["type"] == "detour":
        parts.pop(0)
    while parts and parts[-1]["type"] == "detour":
        parts.pop()
    return parts


def _split_lane(scene: dict, lane: dict, c: dict) -> list:
    """Cut one fixed-Y spray lane at no-spray / no-fly conflicts.

    Returns ordered full segments covering the lane exactly: spray sub-lanes
    on clear footprint intervals, same-height transit (sprayer off) across
    no-spray overlaps, and detour gaps across no-fly corridor blocks.
    No-spray cuts where the swath rectangle has positive-area overlap with
    the zone polygon (AABB is only a reject filter). No-fly cuts where the
    centerline ± clearance corridor positively overlaps the zone polygon;
    inactive when zone Z does not block work height. Overflying a no-spray
    zone is allowed (禁喷 != 禁飞). With no intersecting zone the output is
    the single original spray segment.
    """
    swath, speed = c["swath"], c["speed"]
    height = lane["start"][2]
    x = lane["start"][0]
    lane_lo = min(lane["start"][1], lane["end"][1])
    lane_hi = max(lane["start"][1], lane["end"][1])
    forward = lane["start"][1] < lane["end"][1]
    x_lo, x_hi = x - swath / 2, x + swath / 2

    blocked = []

    def overlap_y_intervals(zone, xa, xb, search_lo, search_hi):
        """Scan Y slices in [search_lo, search_hi] with positive-area rect∩polygon."""
        if search_hi - search_lo <= 1e-9 or xb - xa <= 1e-9:
            return []
        step = 0.05
        intervals = []
        y = search_lo
        while y < search_hi - 1e-12:
            y1 = min(search_hi, y + step)
            if rect_poly_positive_overlap(([xa, y], [xb, y1]), zone["footprint"]):
                if intervals and y <= intervals[-1][1] + 1e-9:
                    intervals[-1] = (intervals[-1][0], y1)
                else:
                    intervals.append((y, y1))
            y = y1
        return intervals

    # 禁喷：足迹矩形与禁喷多边形必须有正面积交集；AABB 只作快筛。
    for zone in scene.get("no_spray_zones", []):
        bounds = polygon_bounds(zone["footprint"])
        zx_lo, zy_lo = bounds["min"]
        zx_hi, zy_hi = bounds["max"]
        if x_lo < zx_hi - 1e-9 and zx_lo < x_hi - 1e-9:
            lo = max(lane_lo, zy_lo)
            hi = min(lane_hi, zy_hi)
            for gap_lo, gap_hi in overlap_y_intervals(zone, x_lo, x_hi, lo, hi):
                gap_lo = max(lane_lo, gap_lo - _ZONE_GAP)
                gap_hi = min(lane_hi, gap_hi + _ZONE_GAP)
                if gap_hi - gap_lo > 1e-9:
                    blocked.append((gap_lo, gap_hi, "transit"))

    # 禁飞：按中心线 x ± clearance 走廊与禁飞多边形正面积相交切断；不用喷幅。
    # 先在多边形 Y 范围求相交，再外扩 clearance，最后裁到本条带——避免邻接条带
    # 因未与多边形 Y 重叠而漏掉净空外扩（否则端点会落在 route3d 禁飞盒边界上）。
    margin = c["clearance"] + _ZONE_GAP
    for zone in scene.get("no_fly_zones", []):
        if zone["z_max"] + c["clearance"] + 1e-9 < height:
            continue
        if zone["z_min"] - c["clearance"] > height + 1e-9:
            continue
        bounds = polygon_bounds(zone["footprint"])
        zx_lo, zy_lo = bounds["min"]
        zx_hi, zy_hi = bounds["max"]
        if x + c["clearance"] <= zx_lo + 1e-9 or x - c["clearance"] >= zx_hi - 1e-9:
            continue
        for gap_lo, gap_hi in overlap_y_intervals(
            zone, x - c["clearance"], x + c["clearance"], zy_lo, zy_hi
        ):
            gap_lo = max(lane_lo, gap_lo - margin)
            gap_hi = min(lane_hi, gap_hi + margin)
            if gap_hi - gap_lo > 1e-9:
                blocked.append((gap_lo, gap_hi, "detour"))

    blocked.sort()
    merged = []
    for a, b, kind in blocked:
        if merged and a <= merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], b), "detour" if "detour" in (prev[2], kind) else "transit")
        else:
            merged.append((a, b, kind))

    pieces = []
    cursor = lane_lo
    for a, b, kind in merged:
        if a - cursor > 1e-9:
            pieces.append((cursor, a, True))
        pieces.append((a, b, kind))
        cursor = b
    if lane_hi - cursor > 1e-9:
        pieces.append((cursor, lane_hi, True))

    target_geometry = {t["id"]: t["geometry"] for t in scene["targets"]}

    def make_segment(y0, y1, kind, ids):
        if forward:
            start, end = [x, y0, height], [x, y1, height]
        else:
            start, end = [x, y1, height], [x, y0, height]
        return dict(
            start=start,
            end=end,
            type=kind,
            spray=kind == "spray",
            speed=speed,
            target_ids=sorted(ids),
        )

    segments = []
    for lo, hi, sprayable in pieces:
        if sprayable == "detour":
            segments.append(make_segment(lo, hi, "detour", []))
            continue
        ids = []
        if sprayable is True:
            ids = [
                tid
                for tid in lane["target_ids"]
                if overlaps_target(([x_lo, lo], [x_hi, hi]), target_geometry[tid])
            ]
        segments.append(
            make_segment(lo, hi, "spray" if ids else "transit", ids)
        )
    if not forward:
        # pieces 按 Y 升序生成；反向条带必须倒序飞，否则会来回折返并把喷洒段排进禁喷区。
        segments.reverse()
    return segments


def zone_exclusions(scene: dict, segments: list, c=None) -> list:
    """计划未喷到、且 classify 认定为豁免/不可达的目标。"""
    from .zones import classify

    c = configuration(c or {}) if not isinstance(c, dict) or "swath" not in c else c
    associated = {tid for seg in segments if seg.get("spray") for tid in seg["target_ids"]}
    return [e for tid, e in sorted(classify(scene, c).items()) if tid not in associated]



def generate_plan(scene: dict, raw=None, uav=1) -> dict:
    """Fixed Y strips: each strip covers target slices across its full swath width."""
    original_scene = scene
    plan = dict(
        version="1.1",
        scene_hash=fingerprint(original_scene),
        method="fixed-y-boustrophedon",
        status="failed",
        reason="",
        segments=[],
    )
    phase = "plan"
    try:
        c0 = configuration(raw or {})
        # 几何切割用外扩副本；scene_hash 指纹原场景。
        # classify / zone_exclusions / safety 误喷对入参原场景调用，内部按 buffer_expand 外扩几何。
        scene = expand_sensitive_inward(original_scene, c0)
        layout = fixed_y_lanes(scene, raw or {})
        c = layout["config"]
        lanes = layout["lanes"]
        height = layout["work_height"]
        plan["config"] = c
        plan["config_hash"] = config_fingerprint(c)
        resolved = resolve(scene, uav)
        start = list(resolved["start"]["position"])
        end_point = list(resolved["end"]["position"])
        if resolved["explicit"] or math.dist(start, end_point) > 1e-8:
            plan.update(
                version="1.2",
                planner="fixed-y-boustrophedon",
                objective="time",
                planner_options={},
                planner_options_hash=options_fingerprint({}),
                uav=uav,
                start_point_id=resolved["start_id"],
                end_point_id=resolved["end_id"],
            )
        current = start[:]

        def add(end, kind, ids=None):
            nonlocal current
            if math.dist(current, end) > 1e-8:
                plan["segments"].append(
                    dict(
                        start=current[:],
                        end=end[:],
                        type=kind,
                        spray=kind == "spray",
                        speed=c["speed"],
                        target_ids=sorted(ids or []),
                    )
                )
            current = end[:]

        detours = 0

        def detour(goal):
            nonlocal detours
            from .routing3d import route3d

            result = route3d(scene, list(current), list(goal), c)
            if result["status"] != "success":
                raise ValueError(
                    f"禁飞区绕行失败 {current} → {goal}：{result.get('reason', '未知原因')}"
                )
            detours += 1
            for point in result["path"][1:]:
                add(list(point), "transit")
            if list(current) != list(goal):
                add(list(goal), "transit")

        has_no_fly = bool(scene.get("no_fly_zones"))
        add([start[0], start[1], height], "takeoff")
        for lane in lanes:
            parts = lane_parts(scene, lane, c)
            if not parts:
                continue
            entry = parts[0]["start"]
            if has_no_fly and list(current) != list(entry):
                detour(entry)
            else:
                add(entry, "transit")
            for part in parts:
                if part["type"] == "detour":
                    detour(part["end"])
                else:
                    add(part["end"], part["type"], part["target_ids"])
        home_air = [end_point[0], end_point[1], height]
        if has_no_fly and list(current) != home_air:
            detour(home_air)
        if detours and plan["version"] != "1.2":
            plan.update(
                version="1.2",
                planner="fixed-y-boustrophedon",
                objective="time",
                planner_options={},
                planner_options_hash=options_fingerprint({}),
            )
        if detours:
            plan["no_fly_detours"] = detours
        if list(current) != home_air:
            add(home_air, "transit")
        add(end_point, "landing")
        plan.update(status="success", strip_count=layout["strip_count"], work_height=height)
        excluded = zone_exclusions(original_scene, plan["segments"], c)
        if excluded:
            plan["excluded_targets"] = excluded
        if c["transition_mode"] == "search":
            # 有禁飞区时必须走 3D 净空搜索；2D 网格会无视禁飞/树高，把已绕行的路径冲掉。
            use_3d = bool(scene.get("no_fly_zones"))
            if use_3d:
                from .routing3d import route3d as _search_route

                def _run(start, end):
                    return _search_route(scene, list(start), list(end), c)
            else:
                from routing import route as _grid_route

                def _run(start, end):
                    return _grid_route(scene, start, end, 1.0, c["clearance"])

            phase = "search"
            rebuilt = []
            nodes = 0
            routes = 0
            for seg in plan["segments"]:
                if seg["type"] != "transit":
                    rebuilt.append(seg)
                    continue
                result = _run(seg["start"], seg["end"])
                if result["status"] != "success":
                    raise ValueError(
                        f"转场搜索失败: {result.get('reason', '未知原因')}"
                    )
                nodes += result.get("expanded", 0)
                routes += 1
                for a, b in zip(result["path"], result["path"][1:]):
                    rebuilt.append(
                        dict(
                            start=list(a),
                            end=list(b),
                            type="transit",
                            spray=False,
                            speed=c["speed"],
                            target_ids=[],
                        )
                    )
            plan["segments"] = rebuilt
            plan["method"] = "fixed-y-boustrophedon+clearance-search"
            if use_3d and plan["version"] != "1.2":
                plan.update(
                    version="1.2",
                    planner=plan["method"],
                    objective="time",
                    planner_options={},
                    planner_options_hash=options_fingerprint({}),
                )
            elif plan["version"] == "1.2":
                plan["planner"] = plan["method"]
            plan["search"] = dict(
                model="layered-3d-clearance-a-star" if use_3d else "clearance-grid-a-star",
                step=1.0,
                clearance=c["clearance"],
                routes=routes,
                nodes=nodes,
            )
        phase = "safety"
        check(original_scene, plan)
    except (ValueError, KeyError, TypeError) as e:
        plan.update(status="failed", reason=str(e), segments=[], stage=phase)
    return plan
