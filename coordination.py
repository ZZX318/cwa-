"""Continuous-time pairwise separation checks for multi-UAV timelines.

Method: every segment is a linear-motion interval.  For each overlapping time
window of a segment pair the relative position is a quadratic in time, so the
closest point of approach (CPA) is solved analytically (no start-of-interval
sampling and no frame grid).  Distances are Euclidean 3-D metres.
"""

import math

METHOD = "continuous-cpa-analytic"
VECTOR = (list, tuple)


def _vector(value, label):
    if not isinstance(value, VECTOR) or len(value) != 3:
        raise ValueError(f"{label} 必须是三维坐标")
    out = []
    for item in value:
        if type(item) not in (int, float) or not math.isfinite(item):
            raise ValueError(f"{label} 坐标必须是有限数值")
        out.append(float(item))
    return out


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} 必须是有限数值")
    return float(value)


def _validate(timelines):
    """Parse timelines and reject malformed or internally overlapping data."""
    if not isinstance(timelines, (list, tuple)) or not timelines:
        raise ValueError("timelines 必须是非空列表")
    parsed = []
    for index, timeline in enumerate(timelines):
        if not isinstance(timeline, dict):
            raise ValueError(f"timeline {index} 必须是对象")
        segments = timeline.get("segments")
        if not isinstance(segments, (list, tuple)) or not segments:
            raise ValueError(f"timeline {index} 缺少非空 segments")
        has_offset = "offset" in timeline
        offset = timeline.get("offset", 0.0)
        if offset is not None:
            offset = _number(offset, f"timeline {index} offset")
            if offset < 0:
                raise ValueError(f"timeline {index} offset 不得为负")
        rows = []
        previous_end = None
        previous_position = None
        for position, segment in enumerate(segments):
            label = f"timeline {index} 航段 {position}"
            if not isinstance(segment, dict):
                raise ValueError(f"{label} 必须是对象")
            start_t = _number(segment.get("t_start"), f"{label} t_start")
            end_t = _number(segment.get("t_end"), f"{label} t_end")
            if start_t < 0:
                raise ValueError(f"{label} t_start 不得为负")
            if end_t <= start_t:
                raise ValueError(f"{label} t_end 必须晚于 t_start")
            if previous_end is not None and start_t < previous_end - 1e-9:
                raise ValueError(f"{label} 与前一段重叠或乱序")
            start = _vector(segment.get("start"), f"{label} start")
            end = _vector(segment.get("end"), f"{label} end")
            if previous_position is not None and math.dist(previous_position, start) > 1e-8:
                raise ValueError(f"{label} 起点与上一段终点不连续")
            if position == 0 and has_offset and abs(start_t - (offset or 0.0)) > 1e-9:
                raise ValueError(f"timeline {index} 起始时间与地面等待偏移不一致")
            rows.append((start_t, end_t, start, end))
            previous_end = end_t
            previous_position = end
        parsed.append(dict(segments=rows, offset=offset or 0.0))
    return parsed


def _closest_approach(a, b):
    """Return (distance, time, relative_speed) for one overlapping segment pair."""
    a_start, a_end, a_begin, a_finish = a
    b_start, b_end, b_begin, b_finish = b
    low = max(a_start, b_start)
    high = min(a_end, b_end)
    if high < low - 1e-12:
        return None
    high = max(low, high)
    a_duration = a_end - a_start
    b_duration = b_end - b_start
    a_velocity = (
        [(a_finish[k] - a_begin[k]) / a_duration for k in range(3)]
        if a_duration > 0
        else [0.0, 0.0, 0.0]
    )
    b_velocity = (
        [(b_finish[k] - b_begin[k]) / b_duration for k in range(3)]
        if b_duration > 0
        else [0.0, 0.0, 0.0]
    )
    a_low = [a_begin[k] + a_velocity[k] * (low - a_start) for k in range(3)]
    b_low = [b_begin[k] + b_velocity[k] * (low - b_start) for k in range(3)]
    relative = [a_low[k] - b_low[k] for k in range(3)]
    relative_velocity = [a_velocity[k] - b_velocity[k] for k in range(3)]
    speed_squared = sum(v * v for v in relative_velocity)
    if speed_squared <= 1e-18:
        time = low
    else:
        time = low - sum(relative[k] * relative_velocity[k] for k in range(3)) / speed_squared
        time = min(high, max(low, time))
    a_position = [a_begin[k] + a_velocity[k] * (time - a_start) for k in range(3)]
    b_position = [b_begin[k] + b_velocity[k] * (time - b_start) for k in range(3)]
    distance = math.dist(a_position, b_position)
    if not math.isfinite(distance):
        raise ValueError("最近接近距离计算结果非有限")
    return distance, time, math.sqrt(speed_squared)


def analyze(timelines, min_distance=1.0):
    """Detect pairwise separation conflicts over the full overlapping airtime.

    ``conflicts`` counts conflicting UAV pairs.  Each entry in ``pairs`` carries
    the minimum separation, its time and the segment pair where it occurs.
    """
    if type(min_distance) not in (int, float) or not math.isfinite(min_distance):
        raise ValueError("min_distance 必须是有限数值")
    if min_distance <= 0:
        raise ValueError("最小机间距必须为正")
    parsed = _validate(timelines)
    min_distance = float(min_distance)
    pairs = []
    conflicts = 0
    closest = None
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            pair = None
            events = []
            for a_index, a in enumerate(parsed[i]["segments"]):
                for b_index, b in enumerate(parsed[j]["segments"]):
                    result = _closest_approach(a, b)
                    if result is None:
                        continue
                    distance, time, relative_speed = result
                    if pair is None or distance < pair["min_distance"]:
                        pair = dict(
                            uav_a=i + 1,
                            uav_b=j + 1,
                            min_distance=distance,
                            time=time,
                            segment_a=a_index,
                            segment_b=b_index,
                            relative_speed=relative_speed,
                            conflict=distance < min_distance,
                        )
                    if distance < min_distance:
                        events.append(
                            dict(
                                min_distance=distance,
                                time=time,
                                segment_a=a_index,
                                segment_b=b_index,
                                relative_speed=relative_speed,
                            )
                        )
            if pair is None:
                continue
            pair["conflicts"] = len(events)
            pair["events"] = events[:20]
            if events:
                conflicts += 1
            pairs.append(pair)
            if closest is None or pair["min_distance"] < closest:
                closest = pair["min_distance"]
    makespan = max(row["segments"][-1][1] for row in parsed)
    total_time = sum(
        row["segments"][-1][1] - row["segments"][0][0] for row in parsed
    )
    waiting = sum(row["offset"] for row in parsed)
    return dict(
        status="success",
        method=METHOD,
        min_distance=min_distance,
        conflicts=conflicts,
        pairs=pairs,
        min_separation=closest,
        waiting_seconds=waiting,
        makespan=makespan,
        total_time=total_time,
    )
