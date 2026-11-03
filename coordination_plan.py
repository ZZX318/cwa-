"""Deterministic multi-UAV coordination on top of the shared executor.

Waiting semantics: every adjustment is a ground hold before takeoff.  The UAV
stays parked at the launch point and its mission clock starts later; the plan
itself (segments, speeds, spray order) is never modified.  No airborne hover is
implemented because the execution model has no hover segment.

Resolution policy (deterministic, reproducible):
  * detect continuous-time conflicts (``coordination.analyze``);
  * for each conflicting UAV pair, delay the higher-numbered UAV by a step
    derived from the measured CPA distance and relative speed;
  * recompute all timelines and repeat, subject to ``max_delay`` and
    ``max_attempts``.  Only ``conflicts_after == 0`` yields ``success``.
"""

import copy
import json
import math
from pathlib import Path

from coordination import analyze
from execution import build
from planning import config_fingerprint, configuration, fingerprint, generate_plan
from multi import run as multi_run
import multi_caw

METHOD = "sequential-ground-hold+continuous-cpa"
SEMANTICS = "ground-hold-before-takeoff; no airborne hover; plan unchanged"


def normalize_algorithm(value):
    """Coordination algorithm selector; default stays the fixed-Y baseline."""
    if value in (None, "", "fixed-y", "fixed", "default"):
        return "fixed-y"
    if value in ("caw", "multi-caw") or (
        isinstance(value, str) and value.startswith("caw-")
    ):
        return "caw"
    raise ValueError("协调算法必须为 fixed-y 或 caw")


def _finite_number(value, label, minimum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} 必须是有限数值")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} 不得小于 {minimum}")
    return float(value)


def _offset_timeline(timeline, offset):
    """Shift a compiled timeline in time without touching the plan or segments."""
    shifted = copy.deepcopy(timeline)
    for segment in shifted["segments"]:
        segment["t_start"] = segment["t_start"] + offset
        segment["t_end"] = segment["t_end"] + offset
    shifted["offset"] = offset
    shifted["duration"] = timeline["duration"] + offset
    shifted["source_execution_id"] = timeline["execution_id"]
    shifted["execution_id"] = fingerprint(shifted)
    return shifted


def _delay_step(pair, min_distance):
    """Deterministic delay estimate for the higher-numbered UAV of a pair."""
    deficit = max(0.0, min_distance - pair["min_distance"])
    speed = max(pair.get("relative_speed", 0.0), 0.5)
    return min(10.0, max(0.1, deficit / speed + 0.05))


def _diagnostics(timelines, min_distance):
    return analyze(timelines, min_distance)


def _failure(result, reason, stage):
    result.update(status="failed", reason=reason, stage=stage)
    return result


def coordinate(
    scene,
    config=None,
    uavs=2,
    min_distance=1.0,
    max_delay=120.0,
    max_attempts=200,
    include_playback=False,
    algorithm=None,
    options=None,
    multi_result=None,
):
    """Build multi-UAV plans and resolve separation conflicts with ground holds."""
    if type(uavs) is not int or not 1 <= uavs <= 32:
        raise ValueError("无人机数量需为 1..32")
    min_distance = _finite_number(min_distance, "最小机间距")
    if min_distance <= 0:
        raise ValueError("最小机间距必须为正")
    max_delay = _finite_number(max_delay, "最大地面等待", 0.0)
    if type(max_attempts) is not int or max_attempts < 0:
        raise ValueError("最大尝试次数必须为非负整数")
    if config is not None and not isinstance(config, dict):
        raise ValueError("作业配置必须是对象")
    if multi_result is not None and algorithm in (None, ""):
        if isinstance(multi_result, dict) and multi_result.get("algorithm") == "caw":
            algorithm = "caw"
    algorithm = normalize_algorithm(algorithm)
    if algorithm == "caw" and options is None and isinstance(multi_result, dict):
        options = multi_result.get("planner_options")
    if options is not None and not isinstance(options, dict):
        raise ValueError("规划器参数必须是对象")

    result = dict(
        version="1.0",
        method=METHOD,
        status="failed",
        reason="",
        stage="init",
        min_distance=min_distance,
        max_delay=max_delay,
        max_attempts=max_attempts,
        waiting_semantics=SEMANTICS,
        scene_hash=None,
        config_hash=None,
        uavs=[],
        conflicts_before=None,
        conflicts_after=None,
        min_separation=None,
        separation_measured=False,
        makespan=None,
        waiting_seconds=None,
        total_time=None,
        attempts=0,
        diagnostics_before=None,
        diagnostics_after=None,
    )
    try:
        result["scene_hash"] = fingerprint(scene)
    except (TypeError, ValueError):
        return _failure(result, "场景无法计算指纹", "scene")

    base = None
    if algorithm == "caw":
        from planning.model import options_fingerprint

        result["algorithm"] = "caw"
        result["planner_options"] = dict(options or {})
        result["planner_options_hash"] = options_fingerprint(options or {})
        multi = (
            multi_result
            if multi_result is not None
            else multi_caw.run(scene, config or {}, uavs, options)
        )
        if multi.get("status") != "success":
            return _failure(
                result, f"多机 CAW 失败：{multi.get('reason', '未知原因')}", "multi"
            )
        result["config_hash"] = multi.get("config_hash")
        result["work_height"] = multi.get("work_height")
        result["uav_count"] = uavs
        timelines = []
        for item in multi.get("uavs", []):
            if item.get("status") != "success":
                return _failure(
                    result,
                    f"无人机 {item.get('uav')} 计划失败：{item.get('reason', '未知原因')}",
                    "uav",
                )
            if item.get("idle"):
                return _failure(
                    result,
                    f"无人机 {item.get('uav')} 没有分配喷洒航段，无法协调",
                    "uav",
                )
            plan = multi_caw.plan_from_item(scene, item, config or {})
            try:
                timelines.append(build(scene, plan))
            except (ValueError, KeyError, TypeError) as error:
                return _failure(
                    result,
                    f"无人机 {item.get('uav')} 执行时间构建失败：{error}",
                    "execution",
                )
    else:
        multi = multi_run(scene, config or {}, uavs)
        if multi.get("status") != "success":
            return _failure(
                result, f"多机基线失败：{multi.get('reason', '未知原因')}", "multi"
            )
        base = generate_plan(scene, config or {})
        if base.get("status") != "success":
            return _failure(
                result, f"基准计划失败：{base.get('reason', '未知原因')}", "plan"
            )
        result["config_hash"] = base.get("config_hash")
        result["work_height"] = base.get("work_height")
        result["uav_count"] = uavs
        timelines = []
        for item in multi.get("uavs", []):
            if item.get("status") != "success":
                return _failure(
                    result,
                    f"无人机 {item.get('uav')} 计划失败：{item.get('reason', '未知原因')}",
                    "uav",
                )
            from playback import plan_from_item

            plan = plan_from_item(base, item)
            try:
                timelines.append(build(scene, plan))
            except (ValueError, KeyError, TypeError) as error:
                return _failure(
                    result,
                    f"无人机 {item.get('uav')} 执行时间构建失败：{error}",
                    "execution",
                )
    if len(timelines) != uavs:
        return _failure(result, "多机基线返回的无人机数量不一致", "multi")

    offsets = [0.0] * uavs
    plan_durations = [timeline["duration"] for timeline in timelines]
    shifted = [_offset_timeline(timeline, 0.0) for timeline in timelines]
    diagnostics = _diagnostics(shifted, min_distance)
    before = diagnostics
    result["conflicts_before"] = diagnostics["conflicts"]
    result["diagnostics_before"] = _summary(before)
    attempts = 0
    stalled = False

    while diagnostics["conflicts"] > 0 and attempts < max_attempts and not stalled:
        attempts += 1
        proposed = list(offsets)
        adjusted = False
        for pair in diagnostics["pairs"]:
            if not pair["conflict"]:
                continue
            index = pair["uav_b"] - 1
            delta = _delay_step(pair, min_distance)
            proposed[index] = min(max_delay, proposed[index] + delta)
            if proposed[index] > offsets[index] + 1e-12:
                adjusted = True
        if not adjusted:
            stalled = True
            break
        offsets = proposed
        shifted = [
            _offset_timeline(timelines[index], offsets[index])
            for index in range(uavs)
        ]
        diagnostics = _diagnostics(shifted, min_distance)
        if all(offsets[index] >= max_delay - 1e-12 for index in range(uavs)) and diagnostics["conflicts"] > 0:
            stalled = True

    after = diagnostics
    result["attempts"] = attempts
    result["conflicts_after"] = after["conflicts"]
    result["diagnostics_after"] = _summary(after)
    result["min_separation"] = after["min_separation"]
    result["separation_measured"] = after["min_separation"] is not None
    result["waiting_seconds"] = sum(offsets)
    result["makespan"] = max(
        offsets[index] + plan_durations[index] for index in range(uavs)
    )
    result["total_time"] = sum(plan_durations)
    result["uavs"] = [
        dict(
            uav=index + 1,
            offset_seconds=offsets[index],
            plan_duration=plan_durations[index],
            duration=plan_durations[index],
            makespan=offsets[index] + plan_durations[index],
            conflicts=0 if after["conflicts"] == 0 else _uav_conflicts(after, index + 1),
        )
        for index in range(uavs)
    ]
    if include_playback:
        from playback import coordinate_tracks

        homes = [list(timeline["segments"][0]["start"]) for timeline in shifted]
        result["playback"] = dict(
            mode="coordinated",
            home=homes[0],
            homes=homes,
            tracks=coordinate_tracks(shifted, homes=homes),
            duration=max(timeline["duration"] for timeline in shifted),
        )

    if after["conflicts"] == 0:
        result.update(status="success", reason="", stage="done")
        return result

    if stalled and max(offsets) >= max_delay - 1e-12:
        reason = (
            f"达到最大地面等待 {max_delay:.2f} s 仍存在 {after['conflicts']} 个冲突对"
        )
    elif attempts >= max_attempts:
        reason = (
            f"达到最大尝试次数 {max_attempts} 仍存在 {after['conflicts']} 个冲突对"
        )
    else:
        reason = f"协调未收敛，仍存在 {after['conflicts']} 个冲突对"
    return _failure(result, reason, "coordination")


def _uav_conflicts(diagnostics, number):
    return sum(
        1
        for pair in diagnostics["pairs"]
        if pair["conflict"] and number in (pair["uav_a"], pair["uav_b"])
    )


def _summary(diagnostics):
    return dict(
        conflicts=diagnostics["conflicts"],
        min_separation=diagnostics["min_separation"],
        pairs=[
            dict(
                uav_a=pair["uav_a"],
                uav_b=pair["uav_b"],
                min_distance=pair["min_distance"],
                time=pair["time"],
                conflict=pair["conflict"],
            )
            for pair in diagnostics["pairs"]
        ],
    )


def _rebuild(scene, config, uavs, algorithm="fixed-y", options=None):
    """Rebuild plans and timelines so verification does not trust result fields."""
    if algorithm == "caw":
        multi = multi_caw.run(scene, config or {}, uavs, options)
        if multi.get("status") != "success":
            return None, multi, None
        timelines = []
        for item in multi.get("uavs", []):
            if item.get("status") != "success" or item.get("idle"):
                return None, multi, None
            plan = multi_caw.plan_from_item(scene, item, config or {})
            timelines.append(build(scene, plan))
        if len(timelines) != uavs:
            return None, multi, None
        return timelines, multi, None
    multi = multi_run(scene, config or {}, uavs)
    base = generate_plan(scene, config or {})
    if multi.get("status") != "success" or base.get("status") != "success":
        return None, multi, base
    timelines = []
    for item in multi.get("uavs", []):
        if item.get("status") != "success":
            return None, multi, base
        plan = dict(base)
        plan["allow_partial"] = True
        plan["segments"] = item["segments"]
        timelines.append(build(scene, plan))
    if len(timelines) != uavs:
        return None, multi, base
    return timelines, multi, base


def _same(left, right, tolerance=1e-6):
    if left is None or right is None:
        return left is right
    return abs(left - right) <= tolerance


def verify(result, scene, config=None):
    """Reject stale, tampered or forged results by replaying the pipeline."""
    if not isinstance(result, dict):
        raise ValueError("协调结果必须是对象")
    if result.get("scene_hash") != fingerprint(scene):
        raise ValueError("协调结果与场景指纹不匹配")
    status = result.get("status")
    if status not in ("success", "failed"):
        raise ValueError("协调结果状态非法")
    algorithm = normalize_algorithm(result.get("algorithm", "fixed-y"))
    options = result.get("planner_options") if algorithm == "caw" else None
    if algorithm == "caw" and result.get("planner_options_hash") is not None:
        from planning.model import options_fingerprint

        if result["planner_options_hash"] != options_fingerprint(options or {}):
            raise ValueError("协调结果的规划器参数指纹不匹配")
    if result.get("config_hash") is not None:
        expected = config_fingerprint(configuration(config or {}))
        if result["config_hash"] != expected:
            raise ValueError("协调结果与配置指纹不匹配")
    units = result.get("uavs", [])
    if status == "failed":
        if not result.get("reason"):
            raise ValueError("失败结果缺少原因")
        if result.get("conflicts_after") == 0:
            raise ValueError("失败结果不得声称零冲突")
        stage = result.get("stage")
        if stage == "coordination":
            timelines, _, _ = _rebuild(
                scene, config, len(units), algorithm, options
            )
            if timelines is None:
                raise ValueError("失败结果无法在当前输入上复核")
            raw = analyze(timelines, result["min_distance"])
            if result.get("conflicts_before") != raw["conflicts"]:
                raise ValueError("失败结果的 conflicts_before 与复核不一致")
            offsets = [float(item["offset_seconds"]) for item in units]
            shifted = [
                _offset_timeline(timelines[index], offsets[index])
                for index in range(len(units))
            ]
            diagnostics = analyze(shifted, result["min_distance"])
            if diagnostics["conflicts"] == 0:
                raise ValueError("失败结果与复核不一致：当前偏移下已无冲突")
            if result.get("conflicts_after") != diagnostics["conflicts"]:
                raise ValueError("失败结果的 conflicts_after 与复核不一致")
            if any(value < 0 for value in offsets):
                raise ValueError("每机地面等待偏移必须非负")
            if not _same(
                result.get("min_separation"), diagnostics["min_separation"]
            ):
                raise ValueError("失败结果的最小间距与复核不一致")
            if result.get("separation_measured") != (
                diagnostics["min_separation"] is not None
            ):
                raise ValueError("失败结果的 separation_measured 与复核不一致")
            if not _same(
                result.get("makespan"),
                max(
                    offsets[index] + timelines[index]["duration"]
                    for index in range(len(units))
                ),
            ):
                raise ValueError("失败结果的 makespan 与复核不一致")
            if not _same(result.get("waiting_seconds"), sum(offsets)):
                raise ValueError("失败结果的等待时间汇总与复核不一致")
            if not _same(
                result.get("total_time"),
                sum(timeline["duration"] for timeline in timelines),
            ):
                raise ValueError("失败结果的 total_time 与复核不一致")
            if len(units) != result.get("uav_count"):
                raise ValueError("失败结果的无人机数量不一致")
            return True
        if algorithm == "caw":
            # A CAW fleet may plan successfully yet coordination can fail for an
            # idle UAV or an execution-build error.  Rebuild instead of assuming
            # any successful fleet result refutes the failure claim.
            timelines, _, _ = _rebuild(
                scene, config, result.get("uav_count") or 2, algorithm, options
            )
            if timelines is not None:
                raise ValueError("失败结果与当前输入不一致：当前可构建多机 CAW 时间线")
            return True
        multi = multi_run(scene, config or {}, result.get("uav_count") or 2)
        if multi.get("status") == "success" and all(
            item.get("status") == "success" for item in multi.get("uavs", [])
        ):
            raise ValueError("失败结果与当前输入不一致：当前多机基线成功")
        return True
    if result.get("config_hash") is None:
        raise ValueError("成功结果缺少配置指纹")
    if result.get("method") != METHOD:
        raise ValueError("协调方法标识不一致")
    if result.get("conflicts_after") != 0:
        raise ValueError("成功结果必须满足 conflicts_after == 0")
    if len(units) != result.get("uav_count") or result.get("uav_count") is None:
        raise ValueError("协调结果无人机数量不一致")
    if result.get("separation_measured") != (result.get("min_separation") is not None):
        raise ValueError("最小间距与 separation_measured 不一致")
    if not units:
        raise ValueError("成功结果缺少无人机明细")
    offsets = [float(item["offset_seconds"]) for item in units]
    if any(value < 0 for value in offsets):
        raise ValueError("每机地面等待偏移必须非负")
    timelines, _, base = _rebuild(scene, config, len(units), algorithm, options)
    if timelines is None:
        raise ValueError("成功结果无法在当前输入上重建")
    if algorithm != "caw" and result.get("config_hash") != base.get("config_hash"):
        raise ValueError("协调结果与重新生成的配置指纹不匹配")
    makespan = max(
        offsets[index] + timelines[index]["duration"] for index in range(len(units))
    )
    if not _same(result.get("makespan"), makespan):
        raise ValueError("makespan 与各机偏移/时长不一致")
    if not _same(result.get("waiting_seconds"), sum(offsets)):
        raise ValueError("等待时间汇总与各机偏移不一致")
    if not _same(
        result.get("total_time"), sum(timeline["duration"] for timeline in timelines)
    ):
        raise ValueError("total_time 与重新生成的计划时长不一致")
    raw = analyze(timelines, result["min_distance"])
    if result.get("conflicts_before") != raw["conflicts"]:
        raise ValueError("成功结果的 conflicts_before 与复核不一致")
    shifted = [
        _offset_timeline(timelines[index], offsets[index])
        for index in range(len(units))
    ]
    diagnostics = analyze(shifted, result["min_distance"])
    if diagnostics["conflicts"] != 0:
        raise ValueError("成功结果复核后仍存在冲突")
    if result.get("separation_measured") != (
        diagnostics["min_separation"] is not None
    ):
        raise ValueError("最小间距复核结果与 separation_measured 不一致")
    if not _same(result.get("min_separation"), diagnostics["min_separation"]):
        raise ValueError("最小间距与复核结果不一致")
    if not _same(
        result.get("conflicts_after"), diagnostics["conflicts"]
    ):
        raise ValueError("conflicts_after 与复核结果不一致")
    return True


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )
