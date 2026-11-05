"""Single-aircraft geometric baseline; all coordinates in metres."""

import hashlib
import json
import math
from scene import validate_scene
from scene.geometry import polygon_bounds

# 「新增，不改已冻结主表」：repair_lanes is opt-in.
DEFAULT = dict(repair_lanes=0, swath=2.0, height_offset=2.0, clearance=0.5, speed=2.0, target_type="canopy_horizontal_projection", flow_rate=1.0, wind_speed=0.0, wind_direction=0.0, wind_cost=0.25, transition_mode="fixed", drift_buffer=0.0, min_buffer=0.0, buffer_expand=0.0, drift_mode="sort")

PLAN_VERSIONS = ("1.0", "1.1", "1.2")
OBJECTIVES = ("time", "energy")

# Registered plan v1.2 methods.  Unknown names are rejected by safety.check.
V12_PLANNERS = {
    "fixed-y-boustrophedon",
    "fixed-y-boustrophedon+clearance-search",
    "multi-contiguous-uav",
    "multi-sortie-uav",
    "naive-target-order",
    "caw-a*-fixed-order",
    "caw-a*-nn",
    "caw-a*-3d-wind",
    "exact-permutation+transition-fixed",
    "exact-permutation+transition-search",
    "exact-permutation+transition-caw",
}

# Methods that may appear in a legacy v1.0/v1.1 plan.  Kept explicit so an
# arbitrary string cannot pass the version check by accident.
LEGACY_METHODS = {
    "fixed-y-boustrophedon",
    "fixed-y-boustrophedon+clearance-search",
    "naive-target-order",
    "exact-permutation+transition-fixed",
    "exact-permutation+transition-search",
    "multi-contiguous-uav",
    "multi-sortie-uav",
}


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(_canonical(value), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def fingerprint(scene: dict) -> str:
    """Exact scene content fingerprint; list reordering changes association, not routes."""
    return _digest(scene)


# 463badb 之后新增的可选开关：取默认 0 时不序列化，保证默认 plan_hash 与 463badb 一致。
_OPTIONAL_DEFAULT_OFF = ("repair_lanes", "min_buffer")


def public_config(config: dict) -> dict:
    """Drop newly added optional switches that sit at their default 0 value."""
    c = dict(config)
    for k in _OPTIONAL_DEFAULT_OFF:
        if k in c and not isinstance(c[k], bool) and c[k] == 0:
            del c[k]
    return c


def config_fingerprint(config: dict) -> str:
    """Fingerprint of the effective job configuration, including transition mode."""
    return _digest(public_config(config))


def options_fingerprint(options: dict) -> str:
    """Fingerprint for planner-specific options kept outside the job config."""
    return _digest(options)


def with_transition_mode(raw: dict, mode) -> dict:
    """CLI transition mode takes precedence over the job JSON value when given."""
    out = dict(raw)
    if mode is not None:
        out["transition_mode"] = mode
    return out


def configuration(raw: dict) -> dict:
    """合并 DEFAULT。开关默认集中在 DEFAULT：buffer_expand / drift_mode 改一处即可。"""
    c = dict(DEFAULT)
    if set(raw) - set(c):
        raise ValueError("未知作业配置字段")
    c.update(raw)
    if not isinstance(c["target_type"], str) or not c["target_type"]:
        raise ValueError("target_type 必须为非空字符串")
    if c["transition_mode"] not in ("fixed", "search"):
        raise ValueError("transition_mode 必须为 fixed 或 search")
    if not isinstance(c["drift_mode"], str) or c["drift_mode"] not in ("off", "sort", "sort_drift"):
        raise ValueError('drift_mode 必须为 "off" / "sort" / "sort_drift"')
    # buffer_expand：仅允许 0/1（浮点亦可）
    be = c["buffer_expand"]
    if type(be) not in (int, float) or not math.isfinite(be) or be not in (0, 0.0, 1, 1.0):
        raise ValueError("buffer_expand 必须为 0 或 1")
    c["buffer_expand"] = float(be)
    if type(c["repair_lanes"]) not in (int, float) or c["repair_lanes"] not in (0, 1):
        raise ValueError("repair_lanes 必须为 0 或 1")
    allow_zero = ("wind_speed", "wind_direction", "drift_buffer", "buffer_expand", "min_buffer", "repair_lanes")
    for k, v in c.items():
        if k in ("target_type", "transition_mode", "drift_mode"):
            continue
        if type(v) not in (int, float) or not math.isfinite(v) or (
            v < 0 if k in allow_zero else v <= 0
        ):
            raise ValueError(f"{k}={v!r}：需要有限正数" if k not in allow_zero else f"{k}={v!r}：需要非负有限数")
    if c["height_offset"] <= c["clearance"]:
        raise ValueError("作业高度差必须大于安全净空")
    return c
