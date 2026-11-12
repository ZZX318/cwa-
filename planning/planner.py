import copy
import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from scene.launch import resolve
from .model import configuration, config_fingerprint, fingerprint, options_fingerprint
from .safety import check, intersects, nofly_expanded_boxes, obstacle_expanded_boxes


def fixed_y_lanes(scene: dict, raw=None, *, clip_flight=True) -> dict:
    """Shared fixed-Y spray-lane set; the only source for every lane planner.

    Returns ``lanes``, ``strip_count`` and ``work_height``. Unrestricted scenes
    retain the original geometry. No-fly regions restrict aircraft clearance;
    both no-fly and no-spray regions restrict the full horizontal spray footprint.
    """
    validate_scene(scene)
    c = configuration(raw or {})
    from wind_buffer import check_buffer_wind
    check_buffer_wind(scene, c)
    if not scene["targets"] or not scene["trees"]:
        raise ValueError("不支持空目标场景")
    targets = scene["targets"]
    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in targets)
    xmax = max(t["geometry"]["center"][0] + t["geometry"]["radius"] for t in targets)
    phase = c["lane_phase"]
    n = math.ceil((xmax - xmin - phase) / c["swath"])
    if n > 10000:
        raise ValueError("作业带超过 10000，喷幅过小")
    height = max(t["canopy"]["z_max"] for t in scene["trees"]) + c["height_offset"]
    if any(t["geometry"]["z_max"] >= height for t in targets):
        raise ValueError("目标体积高于作业面，不支持")
    lanes = []
    active = 0
    from .safety import TOUCH, remaining_y_intervals
    from .footprint import rectangle, overlaps_target
    flight_boxes = (nofly_expanded_boxes(scene, c["clearance"]) + obstacle_expanded_boxes(scene, c["clearance"])) if clip_flight else []
    spray_boxes = []
    for zone in (scene["no_fly_zones"] if clip_flight else []) + scene["no_spray_zones"]:
        bounds = polygon_bounds(zone["footprint"])
        spray_boxes.append(
            (
                [bounds["min"][0] - c["swath"] / 2 - TOUCH, bounds["min"][1], height],
                [bounds["max"][0] + c["swath"] / 2 + TOUCH, bounds["max"][1], height],
            )
        )
    restricted_boxes = flight_boxes + spray_boxes
    target_geoms = {t["id"]: t["geometry"] for t in targets}
    for k in range(-1 if phase else 0, n):
        low = xmin + phase + k * c["swath"]
        high = low + c["swath"] if phase else min(xmax, low + c["swath"])
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
        pieces = []
        for lo, hi, tids in merged:
            for plo, phi in remaining_y_intervals(x, height, lo, hi, restricted_boxes):
                probe = dict(start=[x, plo, height], end=[x, phi, height])
                keep = [
                    tid
                    for tid in tids
                    if overlaps_target(rectangle(probe, c["swath"]), target_geoms[tid])
                ]
                if keep:
                    pieces.append([plo, phi, keep])
        if not pieces:
            continue
        reverse = active % 2 == 1
        active += 1
        for lo, hi, ids in (reversed(pieces) if reverse else pieces):
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


def generate_plan(scene: dict, raw=None, uav=1) -> dict:
    """Straight baseline; physical conflicts fail. Explicit legacy search is a separate method."""
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
        layout = fixed_y_lanes(scene, raw or {}, clip_flight=False)
        c = layout["config"]
        lanes = layout["lanes"]
        height = layout["work_height"]
        plan["config"] = c
        plan["config_hash"] = config_fingerprint(c)
        if not lanes:
            raise ValueError(
                "没有可执行喷洒段：障碍净空、禁飞/禁喷区域或喷幅限制已覆盖全部候选航带。"
                "请检查区域范围和喷幅；当前条件下无法执行喷洒作业"
            )
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

        add([start[0], start[1], height], "takeoff")
        for lane in lanes:
            add(lane["start"], "transit")
            add(lane["end"], "spray", lane["target_ids"])
        add([end_point[0], end_point[1], height], "transit")
        add(end_point, "landing")
        plan.update(status="success", strip_count=layout["strip_count"], work_height=height)
        if c["transition_mode"] == "search":
            from routing import route

            phase = "search"
            rebuilt = []
            nodes = 0
            routes = 0
            for seg in plan["segments"]:
                if seg["type"] != "transit":
                    rebuilt.append(seg)
                    continue
                result = route(scene, seg["start"], seg["end"], 1.0, c["clearance"])
                if result["status"] != "success":
                    raise ValueError(
                        f"转场搜索失败: {result.get('reason', '未知原因')}"
                    )
                nodes += result.get("expanded", 0)
                routes += 1
                for a, b in zip(result["path"], result["path"][1:]):
                    rebuilt.append(
                        dict(
                            start=a,
                            end=b,
                            type="transit",
                            spray=False,
                            speed=c["speed"],
                            target_ids=[],
                        )
                    )
            plan["segments"] = rebuilt
            plan["method"] = "fixed-y-boustrophedon+clearance-search"
            if plan["version"] == "1.2":
                plan["planner"] = plan["method"]
            plan["search"] = dict(
                model="clearance-grid-a-star",
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
