"""Physical geometry helpers. No drawing or planner dependencies; metres throughout."""

import math
from typing import Any, Dict, Sequence


def terrain_height(scene: Dict[str, Any], x: float, y: float) -> float:
    """Ground elevation in metres at local (x, y). Version 1 supports flat terrain."""
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (x, y)):
        raise ValueError(f"terrain query ({x!r}, {y!r})：需要有限米制坐标")
    return scene["terrain"]["height"]


def polygon_bounds(p: Dict[str, Any]) -> Dict[str, list]:
    return dict(
        min=[min(v[i] for v in p["vertices"]) for i in (0, 1)],
        max=[max(v[i] for v in p["vertices"]) for i in (0, 1)],
    )


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(p, a, b):
    return abs(cross(a, b, p)) < 1e-9 and all(
        min(a[i], b[i]) - 1e-9 <= p[i] <= max(a[i], b[i]) + 1e-9 for i in (0, 1)
    )


def in_polygon(point: Sequence[float], polygon: Dict[str, Any]) -> bool:
    """Boundary-inclusive point test for a simple polygon; ignores point z."""
    x, y = point[:2]
    vs = polygon["vertices"]
    result = False
    for a, b in zip(vs, vs[1:] + vs[:1]):
        if on_segment([x, y], a, b):
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            result = not result
    return result


def segments_intersect(a, b, c, d):
    if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
        return True
    return any(
        on_segment(p, u, v) for p, u, v in [(a, c, d), (b, c, d), (c, a, b), (d, a, b)]
    )


def disk_in_polygon(
    center: Sequence[float], radius: float, polygon: Dict[str, Any]
) -> bool:
    if not in_polygon(center, polygon):
        return False
    for a, b in zip(
        polygon["vertices"], polygon["vertices"][1:] + polygon["vertices"][:1]
    ):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        t = max(
            0,
            min(
                1,
                ((center[0] - a[0]) * dx + (center[1] - a[1]) * dy)
                / (dx * dx + dy * dy),
            ),
        )
        if (
            math.hypot(center[0] - a[0] - t * dx, center[1] - a[1] - t * dy)
            < radius - 1e-9
        ):
            return False
    return True


def rectangle(w, h):
    return dict(kind="polygon", vertices=[[0, 0], [w, 0], [w, h], [0, h]])
