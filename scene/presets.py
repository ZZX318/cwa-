"""Obstacle preset library.  Pure data; every preset is an axis-aligned box.

``preset`` in a scene object is only an optional provenance hint.  Geometry is
always the explicit ``min``/``max`` pair validated by ``scene.validation``.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

from .shapes import quantize

PRESETS: Dict[str, Dict[str, Any]] = {
    "shed": dict(label="棚屋", size=[3.0, 4.0, 2.5]),
    "wall": dict(label="墙段", size=[0.4, 6.0, 2.0]),
    "container": dict(label="货柜", size=[2.4, 6.0, 2.6]),
    "post": dict(label="立柱", size=[0.3, 0.3, 3.0]),
}


def preset_names() -> List[str]:
    return sorted(PRESETS)


def preset_size(preset: str) -> List[float]:
    if preset not in PRESETS:
        raise ValueError(f"未知障碍预设 {preset!r}；可选：{', '.join(preset_names())}")
    return list(PRESETS[preset]["size"])


def make_box(
    preset: str,
    center: Sequence[float],
    ground_z: float,
    uid: str,
    size: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Build a ground-standing box from a preset or explicit X/Y/Z size."""
    if preset not in PRESETS:
        raise ValueError(f"未知障碍预设 {preset!r}；可选：{', '.join(preset_names())}")
    if not isinstance(uid, str) or not uid:
        raise ValueError("障碍 ID 必须是非空字符串")
    dimensions = list(size) if size is not None else preset_size(preset)
    if len(dimensions) != 3 or not all(
        type(v) in (int, float) and math.isfinite(v) and v > 0 for v in dimensions
    ):
        raise ValueError("障碍尺寸需要三个正的有限数值")
    if not (
        len(center) == 2
        and all(type(v) in (int, float) and math.isfinite(v) for v in center)
    ):
        raise ValueError("障碍中心需要两个有限数值")
    if type(ground_z) not in (int, float) or not math.isfinite(ground_z):
        raise ValueError("地面高度必须是有限数值")
    sx, sy, sz = (quantize(v) for v in dimensions)
    if sx <= 0 or sy <= 0 or sz <= 0:
        raise ValueError("毫米量化后障碍尺寸必须为正")
    cx, cy = (quantize(v) for v in center)
    z0 = quantize(ground_z)
    return dict(
        id=uid,
        kind="box",
        min=[quantize(cx - sx / 2.0), quantize(cy - sy / 2.0), z0],
        max=[quantize(cx + sx / 2.0), quantize(cy + sy / 2.0), quantize(z0 + sz)],
        preset=preset,
    )
