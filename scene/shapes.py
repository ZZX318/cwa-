"""Footprint and prism construction shared by random maps and the editor.

Pure geometry in local metres.  These helpers describe *candidate* geometry;
they do not mutate a scene and they never silently drop an invalid shape.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

from .geometry import in_polygon, polygon_bounds, segments_intersect

PRISM_KIND = "polygon_prism"


def quantize(value: float) -> float:
    """Stable millimetre quantization used by generated geometry."""
    rounded = round(value * 1000.0) / 1000.0
    return 0.0 if rounded == 0 else rounded


def rectangle_footprint(
    center: Sequence[float], size_x: float, size_y: float
) -> Dict[str, Any]:
    """Counter-clockwise axis-aligned rectangle footprint."""
    if not (math.isfinite(size_x) and size_x > 0 and math.isfinite(size_y) and size_y > 0):
        raise ValueError("矩形足迹的边长必须为正的有限数值")
    if not (
        len(center) == 2
        and all(type(v) in (int, float) and math.isfinite(v) for v in center)
    ):
        raise ValueError("矩形足迹中心需要两个有限坐标")
    cx, cy = center
    hx, hy = size_x / 2.0, size_y / 2.0
    return dict(
        kind="polygon",
        vertices=[
            [quantize(cx - hx), quantize(cy - hy)],
            [quantize(cx + hx), quantize(cy - hy)],
            [quantize(cx + hx), quantize(cy + hy)],
            [quantize(cx - hx), quantize(cy + hy)],
        ],
    )


def convex_footprint(
    center: Sequence[float], radius: float, sides: int
) -> Dict[str, Any]:
    """Regular convex polygon footprint; kept for later shape templates."""
    if type(sides) is not int or not 3 <= sides <= 1000:
        raise ValueError("正多边形边数必须是 3 至 1000 的整数")
    if not (math.isfinite(radius) and radius > 0):
        raise ValueError("正多边形半径必须为正的有限数值")
    if not (
        len(center) == 2
        and all(type(v) in (int, float) and math.isfinite(v) for v in center)
    ):
        raise ValueError("正多边形中心需要两个有限坐标")
    cx, cy = center
    vertices = []
    for k in range(sides):
        angle = 2.0 * math.pi * k / sides
        vertices.append(
            [
                quantize(cx + radius * math.cos(angle)),
                quantize(cy + radius * math.sin(angle)),
            ]
        )
    return dict(kind="polygon", vertices=vertices)


def prism(
    footprint: Dict[str, Any], z_min: float, z_max: float, uid: Optional[str] = None
) -> Dict[str, Any]:
    """Build a ``polygon_prism`` object from a footprint and vertical range."""
    if not (math.isfinite(z_min) and math.isfinite(z_max) and z_min < z_max):
        raise ValueError("棱柱底面必须低于顶面")
    obj = dict(kind=PRISM_KIND, footprint=footprint, z_min=z_min, z_max=z_max)
    if uid is not None:
        obj = dict(id=uid, **obj)
    return obj


def point_in_footprint(point: Sequence[float], footprint: Dict[str, Any]) -> bool:
    """Boundary-inclusive XY containment; ignores point z."""
    return in_polygon(point, footprint)


def footprint_problems(
    footprint: Dict[str, Any], extent: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Return structured problems for a candidate footprint; empty means valid.

    This mirrors ``scene.validation.validate_polygon`` for interactive previews.
    It is intentionally non-raising so the UI can highlight every problem.
    """
    problems: List[Dict[str, Any]] = []

    def add(code: str, path: str, message: str) -> None:
        problems.append(dict(code=code, path=path, message=message))

    if not isinstance(footprint, dict) or footprint.get("kind") != "polygon":
        add("polygon/kind", "footprint.kind", "需要 polygon 足迹")
        return problems
    vertices = footprint.get("vertices")
    if not isinstance(vertices, list):
        add("polygon/vertices", "footprint.vertices", "需要顶点数组")
        return problems
    if not 3 <= len(vertices) <= 1000:
        add("polygon/vertex_count", "footprint.vertices", "需要 3 至 1000 个顶点")
        return problems
    for index, vertex in enumerate(vertices):
        if not (
            isinstance(vertex, list)
            and len(vertex) == 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in vertex)
        ):
            add(
                "polygon/vertex",
                f"footprint.vertices[{index}]",
                "顶点需要两个有限数值",
            )
    if problems:
        return problems
    if len({tuple(v) for v in vertices}) != len(vertices):
        add("polygon/duplicate_vertex", "footprint.vertices", "顶点不可重复")
    area = sum(
        a[0] * b[1] - a[1] * b[0]
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )
    if abs(area) <= 1e-9:
        add("polygon/zero_area", "footprint.vertices", "多边形面积必须非零")
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if segments_intersect(a, b, c, d):
                add(
                    "polygon/self_intersection",
                    "footprint.vertices",
                    f"边 {i} 与边 {j} 自交",
                )
                return problems
    if extent is not None:
        bounds = polygon_bounds(footprint)
        if not (
            bounds["min"][0] >= extent["min"][0]
            and bounds["min"][1] >= extent["min"][1]
            and bounds["max"][0] <= extent["max"][0]
            and bounds["max"][1] <= extent["max"][1]
        ):
            add("polygon/out_of_bounds", "footprint.vertices", "足迹超出场景范围")
    return problems


def rectangle_overlaps_polygon(
    low: Sequence[float], high: Sequence[float], polygon: Dict[str, Any]
) -> bool:
    """Closed overlap test between an axis-aligned rectangle and a simple polygon."""
    corners = [
        [low[0], low[1]],
        [high[0], low[1]],
        [high[0], high[1]],
        [low[0], high[1]],
    ]
    if any(in_polygon(corner, polygon) for corner in corners):
        return True
    rectangle = dict(kind="polygon", vertices=corners)
    if any(in_polygon(vertex, rectangle) for vertex in polygon["vertices"]):
        return True
    rectangle_edges = list(zip(corners, corners[1:] + corners[:1]))
    polygon_edges = list(
        zip(polygon["vertices"], polygon["vertices"][1:] + polygon["vertices"][:1])
    )
    return any(
        segments_intersect(a, b, c, d)
        for a, b in rectangle_edges
        for c, d in polygon_edges
    )


def boxes_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Strict 3D AABB overlap; touching faces are not treated as overlap."""
    return all(a["min"][i] < b["max"][i] and b["min"][i] < a["max"][i] for i in range(3))


def point_in_box(point: Sequence[float], box: Dict[str, Any]) -> bool:
    """Boundary-inclusive 3D box containment."""
    return all(
        box["min"][i] <= point[i] <= box["max"][i] for i in range(3)
    )
