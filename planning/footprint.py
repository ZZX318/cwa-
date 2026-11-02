"""Geometric footprint contract: Y-directed rectangular strip, no end caps."""

import math


def rectangle(segment: dict, swath: float) -> tuple:
    """Return XY min/max in metres; cross-track width swath, zero end extension."""
    a, b = segment["start"], segment["end"]
    return (
        [min(a[0], b[0]) - swath / 2, min(a[1], b[1])],
        [max(a[0], b[0]) + swath / 2, max(a[1], b[1])],
    )


def overlaps_target(bounds: tuple, geometry: dict) -> bool:
    """Rectangle/disk positive-area overlap. Tangency within 1e-9 m is insufficient."""
    lo, hi = bounds
    x, y = geometry["center"]
    dx = max(lo[0] - x, 0, x - hi[0])
    dy = max(lo[1] - y, 0, y - hi[1])
    return math.hypot(dx, dy) < geometry["radius"] - 1e-9


def boxes_touch(a: tuple, b: tuple) -> bool:
    """Closed XY rectangles intersect, including contact within 1e-9 m."""
    return all(a[0][i] <= b[1][i] + 1e-9 and b[0][i] <= a[1][i] + 1e-9 for i in (0, 1))
