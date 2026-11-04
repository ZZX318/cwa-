import copy
import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from scene.launch import resolve
from .footprint import overlaps_target
from .model import configuration, config_fingerprint, fingerprint, options_fingerprint
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
    """Cut one fixed-Y spray lane where its footprint meets no-spray zones.

    Returns ordered full segments covering the lane exactly: spray sub-lanes
    on clear footprint intervals and same-height transit segments (sprayer
    off) across the blocked intervals. Geometry uses the same conservative
    XY AABB contract as ``planning.safety.check``; zone Z is ignored and the
    aircraft may overfly a no-spray zone (禁喷 != 禁飞). With no intersecting
    zone the output is the single original spray segment, byte-identical.
    """
    swath, speed = c["swath"], c["speed"]
    height = lane["start"][2]
    x = lane["start"][0]
    lane_lo = min(lane["start"][1], lane["end"][1])
    lane_hi = max(lane["start"][1], lane["end"][1])
    forward = lane["start"][1] < lane["end"][1]
    x_lo, x_hi = x - swath / 2, x + swath / 2

    blocked = []
    # 禁喷：只关喷头，飞机照常沿条带飞越（gap 类型 transit）。
    # 禁飞：既不能喷也不能进入，条带在区外留出净空后断开，断口由规划器绕行（gap 类型 detour）。
    for zone in scene.get("no_spray_zones", []):
        bounds = polygon_bounds(zone["footprint"])
        zx_lo, zy_lo = bounds["min"]
        zx_hi, zy_hi = bounds["max"]
        # 禁喷按正面积：条带足迹与多边形 AABB 有重叠才切；真正误喷判定在 safety/zones。
        if x_lo < zx_hi - 1e-9 and zx_lo < x_hi - 1e-9:
            gap_lo = max(lane_lo, zy_lo - _ZONE_GAP)
            gap_hi = min(lane_hi, zy_hi + _ZONE_GAP)
            if gap_hi - gap_lo > 1e-9:
                blocked.append((gap_lo, gap_hi, "transit"))
    # 禁飞：只切断作业高度上真正挡住飞行的区（z 有效）
    margin = c["clearance"] + _ZONE_GAP
    for zone in scene.get("no_fly_zones", []):
        if zone["z_max"] + c["clearance"] + 1e-9 < height:
            continue
        if zone["z_min"] - c["clearance"] > height + 1e-9:
            continue
        bounds = polygon_bounds(zone["footprint"])
        zx_lo, zy_lo = bounds["min"]
        zx_hi, zy_hi = bounds["max"]
        if x_lo <= zx_hi + 1e-9 and zx_lo <= x_hi + 1e-9:
            gap_lo = max(lane_lo, zy_lo - margin)
            gap_hi = min(lane_hi, zy_hi + margin)
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
    plan = dict(
        version="1.1",
        scene_hash=fingerprint(scene),
        method="fixed-y-boustrophedon",
        status="failed",
        reason="",
        segments=[],
    )
    phase = "plan"
    try:
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
        excluded = zone_exclusions(scene, plan["segments"], c)
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
        check(scene, plan)
    except (ValueError, KeyError, TypeError) as e:
        plan.update(status="failed", reason=str(e), segments=[], stage=phase)
    return plan
