import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from scene.launch import resolve
from .model import (
    LEGACY_METHODS,
    OBJECTIVES,
    PLAN_VERSIONS,
    V12_PLANNERS,
    configuration,
    config_fingerprint,
    fingerprint,
    options_fingerprint,
)
from .footprint import rectangle, overlaps_target, boxes_touch


def intersects(a, b, lo, hi):
    """Closed segment/AABB slab test, inclusive contact; no waypoint sampling."""
    left, right = 0.0, 1.0
    for x, y, l, h in zip(a, b, lo, hi):
        d = y - x
        if abs(d) < 1e-12:
            if x < l or x > h:
                return False
        else:
            u, v = sorted(((l - x) / d, (h - x) / d))
            left = max(left, u)
            right = min(right, v)
            if left > right:
                return False
    return True


def check(scene: dict, plan: dict) -> None:
    """Independent safety and minimum task-structure checks; not coverage certification."""
    validate_scene(scene)
    version = plan.get("version")
    if version not in PLAN_VERSIONS or plan.get("scene_hash") != fingerprint(scene):
        raise ValueError("计划版本或场景指纹不匹配")
    if plan.get("status") != "success":
        raise ValueError("计划不是成功状态")
    c = configuration(plan["config"])
    if version in ("1.1", "1.2") and plan.get("config_hash") != config_fingerprint(c):
        raise ValueError("配置指纹不匹配")
    method = plan.get("method")
    if version == "1.2":
        planner = plan.get("planner")
        if planner not in V12_PLANNERS:
            raise ValueError("未知规划器")
        if method != planner:
            raise ValueError("规划器与方法不一致")
        if plan.get("objective") not in OBJECTIVES:
            raise ValueError("目标口径必须为 time 或 energy")
        options = plan.get("planner_options")
        if not isinstance(options, dict):
            raise ValueError("planner_options 必须为对象")
        if plan.get("planner_options_hash") != options_fingerprint(options):
            raise ValueError("规划器参数指纹不匹配")
    else:
        if method not in LEGACY_METHODS:
            raise ValueError("未知计划方法")
        expected = (
            "fixed-y-boustrophedon+clearance-search"
            if c["transition_mode"] == "search"
            else "fixed-y-boustrophedon"
        )
        if method in ("fixed-y-boustrophedon", "fixed-y-boustrophedon+clearance-search") and method != expected:
            raise ValueError("计划方法与转场模式不一致")
    segs = plan["segments"]
    explicit_scene = bool(scene.get("launch_assignments")) or any(
        "role" in point for point in scene["launch_points"]
    )
    if version == "1.2" and (
        "start_point_id" in plan or "end_point_id" in plan
    ):
        uav = plan.get("uav", 1)
        if type(uav) is not int or uav < 1:
            raise ValueError("计划 uav 必须是正整数")
        resolved = resolve(scene, uav)
        if (
            plan.get("start_point_id") != resolved["start_id"]
            or plan.get("end_point_id") != resolved["end_id"]
        ):
            raise ValueError("计划起降点元数据与场景分配不一致")
        start = list(resolved["start"]["position"])
        end = list(resolved["end"]["position"])
    elif version == "1.2" and explicit_scene:
        raise ValueError("计划缺少起降点元数据")
    else:
        legacy = sorted(scene["launch_points"], key=lambda p: tuple(p["position"]))[0][
            "position"
        ]
        start = list(legacy)
        end = list(legacy)
    if not segs or segs[0]["type"] != "takeoff" or segs[-1]["type"] != "landing":
        raise ValueError("缺少起降航段")
    previous = start
    boxes = []
    for t in scene["trees"]:
        for kind in ("trunk", "canopy"):
            g = t[kind]
            x, y = g["center"]
            r = g["radius"]
            boxes.append(([x - r, y - r, g["z_min"]], [x + r, y + r, g["z_max"]]))
    boxes += [(o["min"], o["max"]) for o in scene["obstacles"]]
    for o in scene["no_fly_zones"]:
        b = polygon_bounds(o["footprint"])
        boxes.append((b["min"] + [o["z_min"]], b["max"] + [o["z_max"]]))
    targets = {t["id"]: t["geometry"] for t in scene["targets"]}
    ids = set(targets)
    associated = set()
    spray_count = 0
    height = max(t["canopy"]["z_max"] for t in scene["trees"]) + c["height_offset"]
    # 误喷判定与 classify/切带共用外扩禁喷几何；scene_hash 仍对入参原场景。
    from .drift import expand_sensitive_inward

    spray_geo = expand_sensitive_inward(scene, c)
    if version == "1.2":
        if (
            type(plan.get("work_height")) not in (int, float)
            or not math.isfinite(plan["work_height"])
            or abs(plan["work_height"] - height) > 1e-8
        ):
            raise ValueError("计划作业高度与场景配置不符")
        transit_floor = scene["extent"]["min"][2] + c["clearance"]
        transit_ceiling = scene["extent"]["max"][2] - c["clearance"]
    for i, s in enumerate(segs):
        a, b = s["start"], s["end"]
        kind = s["type"]
        if any(
            len(p) != 3
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in p)
            for p in (a, b)
        ):
            raise ValueError(f"航段 {i} 坐标非法")
        if math.dist(a, previous) > 1e-8 or math.dist(a, b) <= 1e-8:
            raise ValueError(f"航段 {i} 不连续或零长度")
        if (
            kind not in ("takeoff", "transit", "spray", "landing")
            or type(s["spray"]) is not bool
            or s["spray"] != (kind == "spray")
        ):
            raise ValueError("航段类型/喷洒状态非法")
        if (
            type(s["speed"]) not in (int, float)
            or not math.isfinite(s["speed"])
            or s["speed"] <= 0
        ):
            raise ValueError("速度非法")
        references = s["target_ids"]
        if not isinstance(references, list) or any(
            not isinstance(v, str) for v in references
        ):
            raise ValueError(f"航段 {i} 目标关联必须是字符串列表")
        if len(set(references)) != len(references):
            raise ValueError(f"航段 {i} 目标关联重复")
        if not s["spray"] and references:
            raise ValueError(f"航段 {i} 非喷洒段不得声明目标关联")
        if not set(s["target_ids"]) <= ids:
            raise ValueError("目标引用无效")
        if kind == "takeoff":
            if a[:2] != start[:2] or b[:2] != start[:2]:
                raise ValueError("起飞须在起点垂直")
        elif kind == "landing":
            if a[:2] != end[:2] or b[:2] != end[:2]:
                raise ValueError("降落须在终点垂直")
        elif version == "1.2" and kind == "transit":
            for p in (a, b):
                if p[2] < transit_floor - 1e-8 or p[2] > transit_ceiling + 1e-8:
                    raise ValueError("转场高度超出净空范围")
        elif abs(a[2] - height) > 1e-8 or abs(b[2] - height) > 1e-8:
            raise ValueError("作业/转场高度不符")
        for p in (a, b):
            if any(
                v < l or v > h
                for v, l, h in zip(p, scene["extent"]["min"], scene["extent"]["max"])
            ):
                raise ValueError("航段超出场景范围")
        for lo, hi in boxes:
            if intersects(
                a, b, [v - c["clearance"] for v in lo], [v + c["clearance"] for v in hi]
            ):
                raise ValueError(f"航段 {i} 与实体净空或禁飞包围盒冲突")
        if s["spray"]:
            if not s["target_ids"] or abs(a[0] - b[0]) > 1e-8:
                raise ValueError("喷洒段必须沿 Y 且关联目标")
            spray_count += 1
            footprint = rectangle(s, c["swath"])
            for target_id in references:
                if not overlaps_target(footprint, targets[target_id]):
                    raise ValueError(
                        f"航段 {i} 足迹未与关联目标 {target_id} 正面积相交"
                    )
                associated.add(target_id)
            # Exact strip rectangle against conservative polygon AABB, ignoring zone Z.
            from .zones import rect_poly_positive_overlap

            for zone in spray_geo["no_spray_zones"]:
                if rect_poly_positive_overlap(footprint, zone["footprint"]):
                    raise ValueError(f"误喷：航段 {i} 喷洒足迹正面积进入禁喷区 {zone['id']}")
        previous = b
    if math.dist(previous, end) > 1e-8:
        raise ValueError("未返回终点")
    if spray_count == 0:
        raise ValueError("任务结构不完整：没有喷洒航段")
    missing = ids - associated
    excluded = plan.get("excluded_targets") or []
    if not isinstance(excluded, list) or any(
        not isinstance(e, dict) or not isinstance(e.get("target_id"), str) for e in excluded
    ):
        raise ValueError("excluded_targets 结构非法")
    excluded_ids = {e["target_id"] for e in excluded}
    if excluded_ids & associated:
        raise ValueError(f"被排除的目标不得再有喷洒关联 {sorted(excluded_ids & associated)}")
    if excluded_ids - ids:
        raise ValueError("excluded_targets 引用了不存在的目标")
    # 排除必须与 planning.zones 的几何分类逐条一致（id、理由），不能多报也不能改理由。
    from .zones import classify

    if excluded:
        truth = classify(scene, c)
        for e in excluded:
            t = truth.get(e["target_id"])
            if t is None or t["reason"] != e.get("reason"):
                raise ValueError(f"目标 {e['target_id']} 的排除理由与区域几何不符")
    missing -= excluded_ids
    if missing and not plan.get("allow_partial", False):
        raise ValueError(f"任务结构不完整：目标缺少有效喷洒关联 {sorted(missing)}（不在任何禁喷/禁飞区排除范围内）")
