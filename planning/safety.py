import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from .model import configuration, config_fingerprint, fingerprint
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
    if plan.get("version") not in ("1.0", "1.1") or plan.get("scene_hash") != fingerprint(scene):
        raise ValueError("计划版本或场景指纹不匹配")
    if plan.get("status") != "success":
        raise ValueError("计划不是成功状态")
    c = configuration(plan["config"])
    if plan["version"] == "1.1" and plan.get("config_hash") != config_fingerprint(c):
        raise ValueError("配置指纹不匹配")
    method = plan.get("method")
    expected = (
        "fixed-y-boustrophedon+clearance-search"
        if c["transition_mode"] == "search"
        else "fixed-y-boustrophedon"
    )
    if method in ("fixed-y-boustrophedon", "fixed-y-boustrophedon+clearance-search") and method != expected:
        raise ValueError("计划方法与转场模式不一致")
    segs = plan["segments"]
    launch = sorted(scene["launch_points"], key=lambda p: tuple(p["position"]))[0][
        "position"
    ]
    if not segs or segs[0]["type"] != "takeoff" or segs[-1]["type"] != "landing":
        raise ValueError("缺少起降航段")
    previous = launch
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
        if kind in ("takeoff", "landing"):
            if a[:2] != launch[:2] or b[:2] != launch[:2]:
                raise ValueError("起降须垂直")
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
            for zone in scene["no_spray_zones"]:
                bounds = polygon_bounds(zone["footprint"])
                if boxes_touch(footprint, (bounds["min"], bounds["max"])):
                    raise ValueError("喷洒足迹触及禁喷区；不支持禁喷切割")
        previous = b
    if math.dist(previous, launch) > 1e-8:
        raise ValueError("未返回起降点")
    if spray_count == 0:
        raise ValueError("任务结构不完整：没有喷洒航段")
    missing = ids - associated
    if missing and not plan.get("allow_partial", False):
        raise ValueError(f"任务结构不完整：目标缺少有效喷洒关联 {sorted(missing)}")
