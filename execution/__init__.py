"""Deterministic segment-constant-speed time model. Units: m, s, m/s, radians."""

import bisect
import copy
import json
import math
from pathlib import Path
from planning import check, fingerprint
from planning.wind import segment_time


def build(scene: dict, plan: dict) -> dict:
    """Validate inputs and compile a compact timeline, never frame trajectories."""
    check(scene, plan)
    elapsed = 0.0
    heading = 0.0  # +X, retained during vertical motion
    segments = []
    for index, original in enumerate(plan["segments"]):
        segment = copy.deepcopy(original)
        a, b = segment["start"], segment["end"]
        length = math.dist(a, b)
        config = plan.get("config", {})
        version = plan.get("version", "1.0")
        duration = segment_time(a, b, segment["speed"], config, version=version)
        if version == "1.2":
            effective = length / duration if duration > 0 else 0.0
        else:
            wind_speed=config.get("wind_speed",0.0); wind_dir=config.get("wind_direction",0.0); cost=config.get("wind_cost",0.25)
            direction=math.atan2(b[1]-a[1],b[0]-a[0]) if length else 0.0
            aligned=math.cos(direction-wind_dir)
            effective=max(0.1, segment["speed"]*(1.0-cost*wind_speed/max(segment["speed"],0.1)*aligned))
        end = elapsed + duration
        if not math.isfinite(end) or end <= elapsed:
            raise ValueError(f"航段 {index} 时间无法有限且严格递增地表示")
        dx, dy = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dy) > 1e-10:
            heading = math.atan2(dy, dx)
        segment.update(
            index=index,
            length=length,
            duration=duration,
            t_start=elapsed,
            t_end=end,
            heading=heading,
            effective_speed=effective,
        )
        segments.append(segment)
        elapsed = end
    result = dict(
        version="1.0",
        model="piecewise-constant-speed",
        scene_hash=fingerprint(scene),
        plan_hash=fingerprint(plan),
        duration=elapsed,
        segments=segments,
    )
    result["execution_id"] = fingerprint(result)
    return result


def state_at(timeline: dict, time: float) -> dict:
    """Query a compiled timeline. Reject nonfinite/negative/out-of-range times.

    Segment intervals are [start,end); duration itself is landed/completed,
    spraying off, actual model speed zero. No epsilon snaps across boundaries.
    """
    if (
        type(time) not in (int, float)
        or not math.isfinite(time)
        or not 0 <= time <= timeline["duration"]
    ):
        raise ValueError(
            f'time={time!r}：必须在 [0, {timeline["duration"]}] 秒内且有限'
        )
    segments = timeline["segments"]
    complete = time == timeline["duration"]
    index = (
        len(segments) - 1
        if complete
        else bisect.bisect_right([s["t_end"] for s in segments], time)
    )
    segment = segments[index]
    fraction = 1.0 if complete else (time - segment["t_start"]) / segment["duration"]
    position = [
        a + (b - a) * fraction for a, b in zip(segment["start"], segment["end"])
    ]
    return dict(
        time=time,
        position=position,
        segment_index=index,
        segment_type=segment["type"],
        status="completed" if complete else segment["type"],
        spray=False if complete else segment["spray"],
        speed=0.0 if complete else segment["speed"],
        heading=segment["heading"],
        scene_hash=timeline["scene_hash"],
        plan_hash=timeline["plan_hash"],
        execution_id=timeline["execution_id"],
    )


def sample(timeline: dict, step: float) -> list:
    """Export grid samples PLUS every exact boundary and segment midpoint.

    Even a short spray segment between grid times is represented; future
    accumulation should integrate timeline intervals, not infer from frames.
    """
    if type(step) not in (int, float) or not math.isfinite(step) or step <= 0:
        raise ValueError("采样间隔必须是有限正秒数")
    count = math.ceil(timeline["duration"] / step)
    if count + 3 * len(timeline["segments"]) > 100000:
        raise ValueError("采样超过 100000 条限制")
    times = {0.0, timeline["duration"]}
    times.update(i * step for i in range(count))
    for segment in timeline["segments"]:
        times.update(
            (
                segment["t_start"],
                segment["t_end"],
                (segment["t_start"] + segment["t_end"]) / 2,
            )
        )
    return [state_at(timeline, t) for t in sorted(times)]


def save(timeline: dict, path) -> None:
    """Save compact compiled execution data; no frame list in plan files."""
    Path(path).write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )


def load(scene: dict, plan: dict, path) -> dict:
    """Rebuild from checked inputs and reject mismatched/tampered execution data."""
    supplied = json.loads(Path(path).read_text(encoding="utf8"))
    expected = build(scene, plan)
    if supplied != expected:
        raise ValueError("执行文件与当前场景/计划/时间定义不匹配")
    return expected
