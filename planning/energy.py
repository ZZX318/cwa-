"""Relative energy proxy shared by depot optimization and reports.

Units are ``eu`` (energy-equivalent metres); this is not Wh, mAh or a battery
model.  ``wh_per_eu`` plus ``calibration_id`` are required before a Wh figure
may be shown.
"""

import math

from .model import config_fingerprint
from .wind import _horizontal_heading, effective_speed

MODEL = "relative-energy-proxy"

PROFILES = {
    "motion-only": dict(k_hover=0.0, k_ground_idle=0.0, k_pump=0.0, k_payload=0.0,
                        k_takeoff=0.0, k_landing=0.0),
    "mission-proxy": dict(k_hover=0.5, k_ground_idle=0.02, k_pump=0.3, k_payload=0.0,
                          k_takeoff=0.0, k_landing=0.0),
}

DEFAULT_ENERGY = dict(
    version="1.0",
    model=MODEL,
    profile="motion-only",
    k_move=1.0,
    k_climb=0.2,
    k_desc=0.1,
    k_hover=0.0,
    k_ground_idle=0.0,
    k_pump=0.0,
    k_takeoff=0.0,
    k_landing=0.0,
    k_payload=0.0,
    payload_capacity_kg=0.0,
    flow_rate_kg_per_s=0.0,
    endurance_eu=None,
    reserve_ratio=0.0,
    wh_per_eu=None,
    calibration_id=None,
)

_COEFFICIENTS = (
    "k_move", "k_climb", "k_desc", "k_hover", "k_ground_idle", "k_pump",
    "k_takeoff", "k_landing", "k_payload", "payload_capacity_kg",
    "flow_rate_kg_per_s",
)


def energy_config(raw=None):
    """Validate a partial energy configuration and apply profile defaults."""
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ValueError("能耗配置必须是对象")
    if set(raw) - set(DEFAULT_ENERGY):
        raise ValueError("未知能耗配置字段")
    profile = raw.get("profile", DEFAULT_ENERGY["profile"])
    if profile not in PROFILES:
        raise ValueError("能耗 profile 必须为 motion-only 或 mission-proxy")
    config = dict(DEFAULT_ENERGY)
    config.update(PROFILES[profile])
    config.update(raw)
    config["version"] = "1.0"
    config["model"] = MODEL
    config["profile"] = profile
    for key in _COEFFICIENTS:
        value = config[key]
        if isinstance(value, bool) or type(value) not in (int, float):
            raise ValueError(f"{key} 必须是有限非负数")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} 必须是有限非负数")
    reserve = config["reserve_ratio"]
    if isinstance(reserve, bool) or type(reserve) not in (int, float) or not (
        0 <= reserve <= 0.9
    ):
        raise ValueError("reserve_ratio 必须在 0..0.9 之间")
    endurance = config["endurance_eu"]
    if endurance is not None and (
        isinstance(endurance, bool)
        or type(endurance) not in (int, float)
        or not math.isfinite(endurance)
        or endurance < 0
    ):
        raise ValueError("endurance_eu 必须为 null 或有限非负数")
    wh = config["wh_per_eu"]
    calibration = config["calibration_id"]
    if wh is None and calibration is None:
        config["calibrated"] = False
    elif wh is None or calibration is None:
        raise ValueError("wh_per_eu 与 calibration_id 必须同时提供")
    else:
        if type(wh) not in (int, float) or not math.isfinite(wh) or wh <= 0:
            raise ValueError("wh_per_eu 必须是有限正数")
        if not isinstance(calibration, str) or not calibration:
            raise ValueError("calibration_id 必须是非空字符串")
        config["calibrated"] = True
    return config


def energy_fingerprint(config):
    return config_fingerprint(config)


def timeline_energy(timeline, job_config, energy=None):
    """Sum the proxy over a compiled execution timeline."""
    if isinstance(energy, dict) and energy.get("model") == MODEL and "calibrated" in energy:
        config = dict(energy)
    else:
        config = energy_config(energy)
    move = climb = descent = pump = payload = fixed = 0.0
    remaining = config["payload_capacity_kg"]
    flow = config["flow_rate_kg_per_s"]
    use_payload = config["k_payload"] > 0 and remaining > 0 and flow > 0
    for segment in timeline["segments"]:
        start, end = segment["start"], segment["end"]
        speed = segment["speed"]
        heading, horizontal = _horizontal_heading(start, end)
        v_eff = effective_speed(start, end, speed, job_config)
        ratio = speed / v_eff
        dz = end[2] - start[2]
        move += config["k_move"] * horizontal * ratio * ratio
        climb += config["k_climb"] * max(0.0, dz)
        descent += config["k_desc"] * max(0.0, -dz)
        duration = segment.get("duration", 0.0)
        if segment.get("spray"):
            pump += config["k_pump"] * duration
        if use_payload:
            before = remaining
            if segment.get("spray"):
                remaining = max(0.0, remaining - flow * duration)
            payload += config["k_payload"] * (before + remaining) / 2 * horizontal
        if segment.get("type") == "takeoff":
            fixed += config["k_takeoff"]
        elif segment.get("type") == "landing":
            fixed += config["k_landing"]
    total = move + climb + descent + pump + payload + fixed
    if not math.isfinite(total) or total < 0:
        raise ValueError("能耗代理计算结果非法")
    limit = None
    feasible = True
    reason = ""
    if config["endurance_eu"] is not None:
        limit = config["endurance_eu"] * (1.0 - config["reserve_ratio"])
        if total > limit + 1e-9:
            feasible = False
            reason = f"能耗代理 {total:.3f} eu 超过可用上限 {limit:.3f} eu"
    result = dict(
        version="1.0",
        model=MODEL,
        profile=config["profile"],
        calibrated=config["calibrated"],
        total_eu=total,
        components=dict(
            move=move, climb=climb, descent=descent, pump=pump,
            payload=payload, fixed=fixed, ground_idle=0.0,
        ),
        coefficients=config,
        config_hash=energy_fingerprint(config),
        endurance_limit_eu=limit,
        feasible=feasible,
        reason=reason,
    )
    if config["calibrated"]:
        result["energy_wh"] = total * config["wh_per_eu"]
    return result
