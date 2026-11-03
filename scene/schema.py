"""Scene format constants and lightweight JSON data aliases.

Physical values use local metres. See README for the version 1.0 field contract.
Display options never belong to a Scene.
"""

import math
from typing import Any, Dict

Scene = Dict[str, Any]
Config = Dict[str, Any]

VERSION = "1.0"
DEFAULT = dict(
    rows=4,
    trees_per_row=6,
    row_spacing=6.0,
    plant_spacing=4.0,
    canopy_radius=1.5,
    canopy_height=2.4,
    trunk_radius=0.15,
    trunk_height=1.8,
    plot_margin=2.5,
    reserve=6.0,
    ground_z=0.0,
    obstacles=[],
    no_fly_zones=[],
    no_spray_zones=[],
)


class SceneError(ValueError):
    """Invalid scene content. ``field`` locates the first blocking problem."""

    def __init__(self, message, field=None, code=None):
        super().__init__(message)
        self.field = field
        self.code = code


def require(ok, field, value, reason, code=None):
    if not ok:
        raise SceneError(f"{field} = {value!r}：{reason}", field=field, code=code)


def number(v, field, positive=False):
    require(type(v) in (int, float) and math.isfinite(v), field, v, "必须是有限数值")
    if positive:
        require(v > 0, field, v, "必须大于 0 米")


def vector(v, field, n):
    require(isinstance(v, list) and len(v) == n, field, v, f"需要 {n} 个数值")
    for i, x in enumerate(v):
        number(x, f"{field}[{i}]")


def box(b, field, n=3):
    require(
        isinstance(b, dict) and "min" in b and "max" in b, field, b, "需要 min 和 max"
    )
    vector(b["min"], field + ".min", n)
    vector(b["max"], field + ".max", n)
    require(
        all(a < z for a, z in zip(b["min"], b["max"])),
        field,
        b,
        "每个 min 必须小于 max",
    )


def inside(p, b):
    return all(a <= x <= z for x, a, z in zip(p, b["min"], b["max"]))


def contained(a, b):
    return inside(a["min"], b) and inside(a["max"], b)
