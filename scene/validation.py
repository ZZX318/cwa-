"""Validate materialized geometry without regenerating from source metadata."""

import math
from typing import Any, Dict, List
from .schema import VERSION, Scene, require, number, vector, box, inside, contained
from .geometry import (
    terrain_height,
    polygon_bounds,
    in_polygon,
    disk_in_polygon,
    segments_intersect,
)


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


def validate_scene(s: Scene) -> List[str]:
    """Validate actual metre geometry; return non-fatal canopy-overlap reminders.

    Raises SceneError for malformed fields, invalid references or spatial rules.
    Neither assumes a grid nor compares geometry to generator provenance.
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
    warnings = []
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


def summary(s: Scene) -> Dict[str, Any]:
    """Return validated counts, XY bounding dimensions (m), and warnings."""
    warnings = validate_scene(s)
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
