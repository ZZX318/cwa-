"""Validate materialized geometry without regenerating from source metadata."""

import math
from typing import Any, Dict, List, Optional
from .schema import VERSION, Scene, SceneError, require, number, vector, box, inside, contained
from .geometry import (
    terrain_height,
    polygon_bounds,
    in_polygon,
    disk_in_polygon,
    segments_intersect,
)
from .shapes import boxes_overlap


def validate_polygon(p: Dict[str, Any], field: str) -> None:
    require(
        isinstance(p, dict)
        and p.get("kind") == "polygon"
        and isinstance(p.get("vertices"), list),
        field,
        p,
        "需要 polygon 和 vertices",
    )
    vs = p["vertices"]
    require(3 <= len(vs) <= 1000, field, vs, "需要 3 至 1000 个顶点，不重复首点")
    for i, v in enumerate(vs):
        vector(v, f"{field}.vertices[{i}]", 2)
    require(len(set(tuple(v) for v in vs)) == len(vs), field, vs, "顶点不可重复")
    area = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(vs, vs[1:] + vs[:1]))
    require(abs(area) > 1e-9, field, vs, "多边形面积必须非零")
    edges = list(zip(vs, vs[1:] + vs[:1]))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            require(not segments_intersect(a, b, c, d), field, vs, "多边形边不可自交")


def _role(point: Dict[str, Any]) -> str:
    role = point.get("role", "both")
    require(
        role in ("both", "start", "return"),
        point["id"] + ".role",
        role,
        "必须是 both、start 或 return",
    )
    return role


def _validate_launch_assignments(s: Scene) -> None:
    assignments = s.get("launch_assignments")
    if assignments is None:
        return
    require(
        isinstance(assignments, list),
        "launch_assignments",
        assignments,
        "需要数组",
    )
    points = {p["id"]: p for p in s["launch_points"]}
    seen = set()
    for i, item in enumerate(assignments):
        field = f"launch_assignments[{i}]"
        require(isinstance(item, dict), field, item, "需要对象")
        uav = item.get("uav")
        require(
            type(uav) is int and 1 <= uav <= 32,
            field + ".uav",
            uav,
            "需要 1 至 32 的整数",
        )
        require(uav not in seen, field + ".uav", uav, "同一无人机的分配重复")
        seen.add(uav)
        for side, allowed in (("start", ("both", "start")), ("end", ("both", "return"))):
            ref = item.get(side)
            require(
                isinstance(ref, str) and ref in points,
                field + "." + side,
                ref,
                "引用的起降点不存在",
            )
            require(
                _role(points[ref]) in allowed,
                field + "." + side,
                ref,
                "该起降点的 role 不允许作为" + ("起点" if side == "start" else "终点"),
            )


def validate_scene(
    s: Scene, fast: bool = False, strict: Optional[bool] = None
) -> List[str]:
    """Validate actual metre geometry; return non-fatal reminders.

    Raises SceneError for malformed fields, invalid references or spatial rules.
    Neither assumes a grid nor compares geometry to generator provenance.

    ``fast=True`` skips only the O(n²) canopy-overlap reminder; blocking rules
    are identical to the default path.  ``strict`` overrides the automatic
    launch-point mode (explicit ``role``/``launch_assignments``).
    """
    require(isinstance(s, dict), "scene", s, "需要对象")
    for k in (
        "format_version",
        "coordinates",
        "source",
        "terrain",
        "plot",
        "extent",
        "trees",
        "targets",
        "launch_points",
        "obstacles",
        "no_fly_zones",
        "no_spray_zones",
    ):
        require(k in s, k, None, "缺少必填字段")
    require(
        s["format_version"] == VERSION,
        "format_version",
        s["format_version"],
        "不支持的版本",
    )
    require(
        s["coordinates"]
        == dict(
            unit="m",
            origin=[0, 0, 0],
            x="跨行方向",
            y="沿行方向",
            z="竖直向上",
            handedness="right",
        ),
        "coordinates",
        s["coordinates"],
        "不支持的坐标约定",
    )
    require(
        isinstance(s["source"], dict)
        and "kind" in s["source"]
        and isinstance(s["source"].get("parameters"), dict),
        "source",
        s["source"],
        "需要 kind 和 parameters",
    )
    require(
        isinstance(s["terrain"], dict)
        and s["terrain"].get("kind") == "flat"
        and "height" in s["terrain"],
        "terrain",
        s["terrain"],
        "需要 flat 地形和 height",
    )
    number(s["terrain"]["height"], "terrain.height")
    validate_polygon(s["plot"], "plot")
    box(s["extent"], "extent")
    require(
        contained(polygon_bounds(s["plot"]), s["extent"]),
        "plot",
        s["plot"],
        "必须位于场景 XY 范围内",
    )
    require(
        s["extent"]["min"][2] == terrain_height(s, 0, 0),
        "terrain.height",
        s["terrain"]["height"],
        "必须等于范围底面",
    )
    ids = set()
    tree_ids = set()

    def identity(o, f):
        require(isinstance(o, dict), f, o, "需要对象")
        v = o.get("id")
        require(
            isinstance(v, str) and bool(v) and v not in ids,
            f + ".id",
            v,
            "必须是全局唯一非空字符串",
        )
        ids.add(v)

    def cylinder(o, f):
        require(
            isinstance(o, dict)
            and all(k in o for k in ("kind", "center", "radius", "z_min", "z_max")),
            f,
            o,
            "圆柱字段不完整",
        )
        require(o["kind"] == "cylinder", f + ".kind", o["kind"], "仅支持 cylinder")
        vector(o["center"], f + ".center", 2)
        number(o["radius"], f + ".radius", True)
        number(o["z_min"], f + ".z_min")
        number(o["z_max"], f + ".z_max")
        require(o["z_min"] < o["z_max"], f, o, "底部必须低于顶部")
        x, y = o["center"]
        r = o["radius"]
        b = dict(min=[x - r, y - r, o["z_min"]], max=[x + r, y + r, o["z_max"]])
        require(contained(b, s["extent"]), f, b, "完整几何必须位于场景范围内")

    for k in (
        "trees",
        "targets",
        "launch_points",
        "obstacles",
        "no_fly_zones",
        "no_spray_zones",
    ):
        require(isinstance(s[k], list), k, s[k], "需要数组")
        for i, o in enumerate(s[k]):
            identity(o, f"{k}[{i}]")
    for t in s["trees"]:
        f = t["id"]
        tree_ids.add(f)
        vector(t.get("position"), f + ".position", 3)
        for k in ("trunk", "canopy"):
            cylinder(t.get(k), f + "." + k)
        require(
            t["position"][2] == terrain_height(s, *t["position"][:2])
            and t["trunk"]["z_min"] == terrain_height(s, *t["position"][:2]),
            f,
            t["position"],
            "树干须从地面开始",
        )
        require(
            t["trunk"]["center"] == t["position"][:2] == t["canopy"]["center"]
            and t["trunk"]["z_max"] == t["canopy"]["z_min"],
            f,
            t,
            "树干与树冠须同轴衔接",
        )
        x, y = t["position"][:2]
        r = t["canopy"]["radius"]
        require(
            disk_in_polygon([x, y], r, s["plot"]),
            f,
            t["position"],
            "完整树冠必须在作业地块内",
        )
    refs = []
    for t in s["targets"]:
        require(
            t.get("tree_id") in tree_ids,
            t["id"] + ".tree_id",
            t.get("tree_id"),
            "树木引用无效",
        )
        refs.append(t["tree_id"])
        cylinder(t.get("geometry"), t["id"] + ".geometry")
    require(
        set(refs) == tree_ids and len(refs) == len(tree_ids),
        "targets",
        refs,
        "每棵树须恰好关联一个目标体积",
    )
    for o in s["obstacles"]:
        require(
            o.get("kind") == "box", o["id"] + ".kind", o.get("kind"), "仅支持轴对齐 box"
        )
        box(o, o["id"])
        require(contained(o, s["extent"]), o["id"], o, "必须位于场景范围内")
        if "preset" in o:
            require(
                isinstance(o["preset"], str) and bool(o["preset"]),
                o["id"] + ".preset",
                o["preset"],
                "预设提示必须是非空字符串",
            )
    for k in ("no_fly_zones", "no_spray_zones"):
        for o in s[k]:
            require(
                o.get("kind") == "polygon_prism",
                o["id"] + ".kind",
                o.get("kind"),
                "需要 polygon_prism",
            )
            validate_polygon(o.get("footprint"), o["id"] + ".footprint")
            number(o.get("z_min"), o["id"] + ".z_min")
            number(o.get("z_max"), o["id"] + ".z_max")
            require(o["z_min"] < o["z_max"], o["id"], o, "底面必须低于顶面")
            b = polygon_bounds(o["footprint"])
            b["min"].append(o["z_min"])
            b["max"].append(o["z_max"])
            require(contained(b, s["extent"]), o["id"], o, "必须位于场景范围内")
    require(bool(s["launch_points"]), "launch_points", [], "至少一个起降点")
    for p in s["launch_points"]:
        v = p.get("position")
        vector(v, p["id"] + ".position", 3)
        _role(p)
        require(
            inside(v, s["extent"]) and v[2] == terrain_height(s, *v[:2]),
            p["id"],
            v,
            "须在场景范围内的地面",
        )
        require(not in_polygon(v, s["plot"]), p["id"], v, "起降点必须在作业地块外")
        for o in s["obstacles"] + s["no_fly_zones"]:
            collision = (
                inside(v, o)
                if o["kind"] == "box"
                else in_polygon(v, o["footprint"]) and o["z_min"] <= v[2] <= o["z_max"]
            )
            require(not collision, p["id"], v, f'落入 {o["id"]} 实体或禁飞体积')
        # 起降点与障碍的水平净空（默认 0.5 m）。禁飞区仍只禁止落入体积/足迹，
        # 以便场景编辑器测试能构造「紧挨禁飞」的提醒用例。
        clearance = 0.5
        for o in s["obstacles"]:
            dx = max(o["min"][0] - v[0], 0.0, v[0] - o["max"][0])
            dy = max(o["min"][1] - v[1], 0.0, v[1] - o["max"][1])
            require(
                math.hypot(dx, dy) + 1e-9 >= clearance,
                p["id"],
                v,
                f'距障碍 {o["id"]} 不足净空 {clearance} m',
            )

    _validate_launch_assignments(s)
    explicit_config = bool(s.get("launch_assignments")) or any(
        "role" in p for p in s["launch_points"]
    )
    # Explicit role/assignments always use strict rules; ``strict`` can only
    # force strict mode on legacy scenes, never downgrade an explicit config.
    explicit_launch = explicit_config or bool(strict)
    if explicit_launch:
        roles = [_role(p) for p in s["launch_points"]]
        require(
            any(role in ("both", "start") for role in roles),
            "launch_points",
            roles,
            "需要至少一个可作起点的起降点",
        )
        require(
            any(role in ("both", "return") for role in roles),
            "launch_points",
            roles,
            "需要至少一个可作终点的起降点",
        )

    warnings: List[str] = []
    ground = terrain_height(s, 0, 0)
    positions = [tuple(p["position"]) for p in s["launch_points"]]
    if len(set(positions)) != len(positions):
        warnings.append("多个起降点坐标相同：允许共用停机坪表达，请确认不是重复。")
    for p in s["launch_points"]:
        v = p["position"]
        for o in s["no_spray_zones"]:
            if in_polygon(v, o["footprint"]):
                if explicit_launch:
                    require(
                        False,
                        p["id"],
                        v,
                        f'严格起降配置下落入禁喷区 {o["id"]} 足迹',
                    )
                else:
                    warnings.append(
                        f'起降点 {p["id"]} 位于禁喷区 {o["id"]} 足迹内'
                        "（旧场景兼容：仅提醒，不阻断）。"
                    )
        if explicit_launch:
            for o in s["no_fly_zones"]:
                if in_polygon(v, o["footprint"]):
                    require(
                        False,
                        p["id"],
                        v,
                        f'严格起降配置下落入禁飞区 {o["id"]} 的 XY 足迹',
                    )
            for o in s["obstacles"]:
                if (
                    o["min"][2] <= ground + 1e-9
                    and o["min"][0] <= v[0] <= o["max"][0]
                    and o["min"][1] <= v[1] <= o["max"][1]
                ):
                    require(
                        False,
                        p["id"],
                        v,
                        f'严格起降配置下落入落地障碍 {o["id"]} 的 XY 足迹',
                    )

    strict_geometry = explicit_launch or any("preset" in o for o in s["obstacles"])
    target_boxes = []
    for t in s["targets"]:
        g = t["geometry"]
        x, y = g["center"]
        r = g["radius"]
        target_boxes.append(
            dict(
                id=t["id"],
                min=[x - r, y - r, g["z_min"]],
                max=[x + r, y + r, g["z_max"]],
            )
        )
    overlaps = []
    for o in s["obstacles"]:
        for tb in target_boxes:
            if boxes_overlap(o, tb):
                overlaps.append((o["id"], tb["id"]))
    if overlaps:
        if strict_geometry:
            oid, tid = overlaps[0]
            require(
                False,
                oid,
                s["obstacles"],
                f"障碍 {oid} 与目标 {tid} 体积重叠（显式配置严格模式）",
            )
        for oid, tid in overlaps[:20]:
            warnings.append(f"障碍 {oid} 与目标 {tid} 体积重叠，固定条带规划可能失败。")
        if len(overlaps) > 20:
            warnings.append(f"另有 {len(overlaps) - 20} 组障碍-目标重叠未逐条列出。")

    zone_boxes = []
    for key in ("no_fly_zones", "no_spray_zones"):
        for o in s[key]:
            bounds = polygon_bounds(o["footprint"])
            bounds["min"].append(o["z_min"])
            bounds["max"].append(o["z_max"])
            zone_boxes.append((o["id"], bounds))
    zone_overlaps = [
        (zone_id, tb["id"])
        for zone_id, zone_box in zone_boxes
        for tb in target_boxes
        if boxes_overlap(zone_box, tb)
    ]
    if zone_overlaps:
        for zone_id, target_id in zone_overlaps[:20]:
            warnings.append(
                f"区域 {zone_id} 与目标 {target_id} 体积重叠；"
                "禁喷会拒绝该处喷洒，禁飞可能阻断航段（仅提醒）。"
            )
        if len(zone_overlaps) > 20:
            warnings.append(
                f"另有 {len(zone_overlaps) - 20} 组区域-目标重叠未逐条列出。"
            )

    if not fast:
        ts = s["trees"]
        if any(
            math.dist(a["position"][:2], b["position"][:2])
            < a["canopy"]["radius"] + b["canopy"]["radius"]
            for i, a in enumerate(ts)
            for b in ts[i + 1 :]
        ):
            warnings.append(
                "树冠存在重叠：允许相邻冠层相接，不代表碰撞检查或喷洒评价结果。"
            )
    return warnings


def _error_code(error: SceneError) -> str:
    field = (error.field or "").lower()
    message = str(error)
    if error.code:
        return error.code
    if "自交" in message:
        return "polygon/self_intersection"
    if "面积" in message:
        return "polygon/zero_area"
    if "顶点不可重复" in message:
        return "polygon/duplicate_vertex"
    if "每个 min 必须小于 max" in message:
        return "box/min_ge_max"
    if "不支持的版本" in message:
        return "scene/format_version"
    if "role" in field:
        return "launch/role"
    if "launch_assignments" in field:
        return "launch/assignment"
    if "launch_points" in field:
        return "launch/invalid"
    if "树冠" in message or "目标" in message and "重叠" in message:
        return "geometry/overlap"
    if "唯一" in message:
        return "scene/id"
    if "范围" in message:
        return "scene/out_of_bounds"
    if "缺少必填" in message:
        return "scene/required"
    return "scene/invalid"


def report(
    s: Scene, mode: str = "full", strict: Optional[bool] = None
) -> Dict[str, Any]:
    """Structured validation result for ``POST /api/validate``.

    Content errors return ``ok:false`` without raising.  ``fast`` mode omits
    only the canopy-overlap reminder, so the blocking verdict is unchanged.
    """
    fast = mode == "fast"
    try:
        warnings = validate_scene(s, fast=fast, strict=strict)
    except SceneError as error:
        return dict(
            ok=False,
            mode=mode,
            warnings_complete=False,
            errors=[
                dict(
                    code=_error_code(error),
                    path=error.field,
                    message=str(error),
                )
            ],
            warnings=[],
            summary=None,
        )
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return dict(
            ok=False,
            mode=mode,
            warnings_complete=False,
            errors=[dict(code="scene/invalid", path="scene", message=str(error))],
            warnings=[],
            summary=None,
        )
    return dict(
        ok=True,
        mode=mode,
        warnings_complete=not fast,
        errors=[],
        warnings=warnings,
        summary=summary(s, validated=True, warnings=warnings),
    )


def summary(
    s: Scene,
    validated: bool = False,
    fast: bool = False,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return validated counts, XY bounding dimensions (m), and warnings."""
    if warnings is None:
        warnings = [] if validated else validate_scene(s, fast=fast)
    return dict(
        trees=len(s["trees"]),
        targets=len(s["targets"]),
        plot_size=[
            b - a
            for a, b in zip(
                polygon_bounds(s["plot"])["min"], polygon_bounds(s["plot"])["max"]
            )
        ],
        obstacles=len(s["obstacles"]),
        no_fly_zones=len(s["no_fly_zones"]),
        no_spray_zones=len(s["no_spray_zones"]),
        warnings=warnings,
    )
