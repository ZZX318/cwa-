import copy
import math
from scene import validate_scene
from scene.launch import resolve
from .model import configuration, config_fingerprint, fingerprint, options_fingerprint
from .safety import check


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
