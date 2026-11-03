"""Shared anisotropic wind time/energy model.

The horizontal formula is copied verbatim from the legacy executor so plans
using version 1.0/1.1 keep bit-identical durations.  Version 1.2 splits a
segment into horizontal and vertical components; wind never affects the
vertical part.

Sign convention (unchanged from the executor): ``cos(theta - wind_direction)``
equal to +1 means the smallest effective speed, i.e. ``wind_direction`` is the
direction the wind comes from.
"""

import math

MIN_SPEED = 0.1
_EPS = 1e-12

# Explicit proxy coefficients, not measured power figures.
ENERGY_C_MOVE = 1.0
ENERGY_C_CLIMB = 0.2
ENERGY_C_DESCENT = 0.1


def _wind(config):
    return (
        float(config.get("wind_speed", 0.0)),
        float(config.get("wind_direction", 0.0)),
        float(config.get("wind_cost", 0.25)),
    )


def _horizontal_heading(start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    return math.atan2(dy, dx), math.hypot(dx, dy)


def _effective(speed, heading, config):
    wind_speed, wind_direction, cost = _wind(config)
    aligned = math.cos(heading - wind_direction)
    return max(
        MIN_SPEED,
        speed * (1.0 - cost * wind_speed / max(speed, MIN_SPEED) * aligned),
    )


def effective_speed(start, end, speed, config) -> float:
    """Legacy effective speed over the full segment (same as execution 1.0/1.1)."""
    heading, _ = _horizontal_heading(start, end)
    return _effective(speed, heading, config)


def max_effective_speed(speed, config) -> float:
    """Best-case effective speed at ``aligned == -1`` (downwind)."""
    return _effective(speed, _wind(config)[1] + math.pi, config)


def segment_time(start, end, speed, config, version="1.2", vertical_speed=None) -> float:
    """Segment duration; 1.0/1.1 keep the legacy full-3D formula."""
    distance = math.dist(start, end)
    if distance <= 0:
        return 0.0
    if version in ("1.0", "1.1"):
        return distance / effective_speed(start, end, speed, config)
    heading, horizontal = _horizontal_heading(start, end)
    vertical = abs(end[2] - start[2])
    v_vertical = speed if vertical_speed is None else vertical_speed
    result = 0.0
    if horizontal > _EPS:
        result += horizontal / _effective(speed, heading, config)
    if vertical > _EPS:
        result += vertical / v_vertical
    return result


def segment_energy(
    start,
    end,
    speed,
    config,
    c_move=ENERGY_C_MOVE,
    c_climb=ENERGY_C_CLIMB,
    c_descent=ENERGY_C_DESCENT,
) -> float:
    """Relative energy proxy (M2 interface); coefficients are explicit proxies."""
    heading, horizontal = _horizontal_heading(start, end)
    ratio = speed / _effective(speed, heading, config)
    dz = end[2] - start[2]
    return (
        c_move * horizontal * ratio * ratio
        + c_climb * max(0.0, dz)
        + c_descent * max(0.0, -dz)
    )


def horizon_heuristic(start, end, speed, config, objective="time", vertical_speed=None):
    """Admissible, consistent lower bound for the layered 3D grid."""
    _, horizontal = _horizontal_heading(start, end)
    vertical = abs(end[2] - start[2])
    v_max = max_effective_speed(speed, config)
    v_vertical = speed if vertical_speed is None else vertical_speed
    if objective == "time":
        return horizontal / v_max + vertical / v_vertical
    if objective == "energy":
        return (
            ENERGY_C_MOVE * horizontal * (speed / v_max) ** 2
            + min(ENERGY_C_CLIMB, ENERGY_C_DESCENT) * vertical
        )
    raise ValueError("objective 必须为 time 或 energy")


def lane_duration(start, end, speed, config, version="1.2") -> float:
    return segment_time(start, end, speed, config, version)
