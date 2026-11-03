"""Stage 17 regressions: continuous CPA detection and deterministic coordination."""

import copy
import json
import math
import tempfile
from pathlib import Path

from coordination import analyze
from coordination_plan import coordinate, save, verify
from execution import build
from multi import run as multi_run
from planning import config_fingerprint, configuration, fingerprint, generate_plan
from scene import generate

SMALL_SCENE = json.loads(Path("configs/joint.small.json").read_text(encoding="utf8"))
SMALL_JOB = json.loads(Path("configs/job.joint.small.json").read_text(encoding="utf8"))


def _timelines(scene, config, uavs):
    result = multi_run(scene, config, uavs)
    assert result["status"] == "success", result.get("reason")
    base = generate_plan(scene, config)
    assert base["status"] == "success", base.get("reason")
    out = []
    for item in result["uavs"]:
        plan = dict(base)
        plan["allow_partial"] = True
        plan["segments"] = item["segments"]
        out.append(build(scene, plan))
    return out


def _shift(timeline, offset):
    shifted = copy.deepcopy(timeline)
    for segment in shifted["segments"]:
        segment["t_start"] += offset
        segment["t_end"] += offset
    shifted["offset"] = offset
    return shifted


def _position(timeline, time):
    segments = timeline["segments"]
    for segment in segments:
        if segment["t_start"] - 1e-12 <= time <= segment["t_end"] + 1e-12:
            duration = segment["t_end"] - segment["t_start"]
            if duration <= 0:
                return list(segment["start"])
            fraction = (time - segment["t_start"]) / duration
            return [
                a + (b - a) * fraction
                for a, b in zip(segment["start"], segment["end"])
            ]
    return list(segments[-1]["end"])


def _dense_minimum(timelines, step=0.01):
    """Independent brute-force minimum distance, used to sanity-check the CPA."""
    best = None
    best_time = None
    for i in range(len(timelines)):
        for j in range(i + 1, len(timelines)):
            low = max(
                timelines[i]["segments"][0]["t_start"],
                timelines[j]["segments"][0]["t_start"],
            )
            high = min(
                timelines[i]["segments"][-1]["t_end"],
                timelines[j]["segments"][-1]["t_end"],
            )
            if high < low:
                continue
            count = max(1, math.ceil((high - low) / step))
            for k in range(count + 1):
                time = low + (high - low) * k / count
                distance = math.dist(
                    _position(timelines[i], time), _position(timelines[j], time)
                )
                if best is None or distance < best:
                    best, best_time = distance, time
    return best, best_time


def _line(x0, y0, z0, x1, y1, z1, start, end):
    return dict(
        duration=end - start,
        segments=[
            dict(
                t_start=start,
                t_end=end,
                start=[x0, y0, z0],
                end=[x1, y1, z1],
            )
        ],
    )


def _continuous_detection():
    crossing_a = _line(0, 0, 0, 10, 0, 0, 0, 10)
    crossing_b = _line(5, -5, 0, 5, 5, 0, 0, 10)
    at_start = math.dist([0, 0, 0], [5, -5, 0])
    assert at_start > 1.0
    result = analyze([crossing_a, crossing_b], 1.0)
    assert result["conflicts"] == 1
    assert abs(result["min_separation"]) < 1e-9
    pair = result["pairs"][0]
    assert abs(pair["time"] - 5.0) < 1e-9 and pair["conflict"] is True
    separated = _line(5, -5, 5, 5, 5, 5, 0, 10)
    assert analyze([crossing_a, separated], 1.0)["conflicts"] == 0
    assert abs(analyze([crossing_a, separated], 1.0)["min_separation"] - 5.0) < 1e-9
    scene = generate(SMALL_SCENE)
    raw = _timelines(scene, SMALL_JOB, 2)
    baseline = analyze(raw, 1.0)
    assert baseline["conflicts"] > 0
    dense, _ = _dense_minimum(raw)
    assert abs(dense - baseline["min_separation"]) < 0.02
    assert baseline["status"] == "success" and baseline["method"] == "continuous-cpa-analytic"
    print("通过 · 第十七阶段连续时间检测：线段对 CPA、交叉冲突与区间起点盲区")


def _coordination():
    scene = generate(SMALL_SCENE)
    result = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200)
    assert result["status"] == "success", result.get("reason")
    assert result["conflicts_before"] > 0 and result["conflicts_after"] == 0
    assert result["min_separation"] >= 1.0 - 1e-9
    offsets = [item["offset_seconds"] for item in result["uavs"]]
    durations = [item["plan_duration"] for item in result["uavs"]]
    assert all(value >= 0 for value in offsets) and any(value > 0 for value in offsets)
    expected = max(a + b for a, b in zip(offsets, durations))
    assert abs(result["makespan"] - expected) < 1e-9
    assert abs(result["waiting_seconds"] - sum(offsets)) < 1e-9
    assert all(item["conflicts"] == 0 for item in result["uavs"])
    assert all(
        abs(item["duration"] - item["plan_duration"]) < 1e-12
        for item in result["uavs"]
    )
    raw = _timelines(scene, SMALL_JOB, 2)
    shifted = [_shift(raw[i], offsets[i]) for i in range(2)]
    dense, _ = _dense_minimum(shifted)
    assert dense >= 1.0 - 1e-9
    assert abs(dense - result["min_separation"]) < 0.02
    assert result["separation_measured"] is True
    assert verify(result, scene, SMALL_JOB)
    serialized = coordinate(scene, SMALL_JOB, 2, 1000.0, 120.0, 200)
    assert serialized["status"] == "success"
    assert serialized["conflicts_after"] == 0
    assert serialized["separation_measured"] is False
    assert verify(serialized, scene, SMALL_JOB)
    print("通过 · 第十七阶段协调小场景：conflicts_after=0、offset/makespan 一致、独立密采样复核")


def _infeasible():
    scene = generate(SMALL_SCENE)
    result = coordinate(scene, SMALL_JOB, 2, 1000.0, 2.0, 20)
    assert result["status"] == "failed"
    assert result["reason"] and "最大地面等待" in result["reason"]
    assert result["conflicts_after"] > 0
    assert result["attempts"] > 0
    assert len(result["uavs"]) == 2
    assert verify(result, scene, SMALL_JOB)
    for field, value in (
        ("makespan", 999.0),
        ("waiting_seconds", 123.0),
        ("total_time", 999.0),
        ("min_separation", 999.0),
    ):
        bad = copy.deepcopy(result)
        bad[field] = value
        try:
            verify(bad, scene, SMALL_JOB)
            raise AssertionError(f"失败结果篡改 {field} 未被拒绝")
        except ValueError:
            pass
    limited = coordinate(scene, SMALL_JOB, 2, 1000.0, 0.0, 200)
    assert limited["status"] == "failed" and limited["conflicts_after"] > 0
    print("通过 · 第十七阶段不可消解：受限等待返回 failed 并保留冲突与原因")


def _determinism():
    scene = generate(SMALL_SCENE)
    first = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200)
    second = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["status"] == "success"
    print("通过 · 第十七阶段确定性：同输入重复运行一致")


def _fingerprints():
    scene = generate(SMALL_SCENE)
    result = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200)
    assert result["scene_hash"] == fingerprint(scene)
    assert result["config_hash"] == config_fingerprint(configuration(SMALL_JOB))
    assert verify(result, scene, SMALL_JOB)
    changed = generate({"rows": 3, "trees_per_row": 2})
    try:
        verify(result, changed, SMALL_JOB)
        raise AssertionError("篡改场景后旧结果未被拒绝")
    except ValueError:
        pass
    tampered = dict(result)
    tampered["config_hash"] = "0" * 64
    try:
        verify(tampered, scene, SMALL_JOB)
        raise AssertionError("篡改配置指纹未被拒绝")
    except ValueError:
        pass
    weak = copy.deepcopy(result)
    weak["min_separation"] = 0.2
    try:
        verify(weak, scene, SMALL_JOB)
        raise AssertionError("伪造成功的最小间距未被拒绝")
    except ValueError:
        pass
    failed = coordinate(scene, SMALL_JOB, 2, 1000.0, 2.0, 20)
    forged = copy.deepcopy(failed)
    forged.update(
        status="success",
        reason="",
        stage="done",
        conflicts_after=0,
        min_separation=0.2,
        separation_measured=True,
    )
    try:
        verify(forged, scene, SMALL_JOB)
        raise AssertionError("伪造成功状态未被拒绝")
    except ValueError:
        pass
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "coordination.json"
        save(result, path)
        assert json.loads(path.read_text(encoding="utf8")) == result
    print("通过 · 第十七阶段指纹：场景/配置一致、篡改场景拒绝与保存加载")


def _failure_propagation():
    scene = generate(SMALL_SCENE)
    result = coordinate(scene, {"swath": 0}, 2, 1.0, 120.0, 200)
    assert result["status"] == "failed"
    assert result["stage"] in ("multi", "plan") and result["reason"]
    assert result["conflicts_after"] is None and result["uavs"] == []
    assert verify(result, scene, {"swath": 0})
    try:
        verify(result, scene, SMALL_JOB)
        raise AssertionError("失败结果被错误地用于当前有效配置")
    except ValueError:
        pass
    try:
        coordinate(scene, SMALL_JOB, 0)
        raise AssertionError("非法无人机数量未被拒绝")
    except ValueError:
        pass
    print("通过 · 第十七阶段计划失败传播：多机基线失败原因保留")


def _compatibility():
    scene = generate(SMALL_SCENE)
    timelines = _timelines(scene, SMALL_JOB, 2)
    result = analyze(timelines)
    for key in (
        "status",
        "conflicts",
        "min_separation",
        "waiting_seconds",
        "makespan",
        "total_time",
        "pairs",
    ):
        assert key in result, key
    assert result["waiting_seconds"] == 0.0
    assert abs(result["makespan"] - max(t["duration"] for t in timelines)) < 1e-9
    assert abs(result["total_time"] - sum(t["duration"] for t in timelines)) < 1e-9
    assert analyze(timelines[:1], 1.0)["min_separation"] is None
    for call in (
        lambda: analyze([], 1.0),
        lambda: analyze([{"segments": []}], 1.0),
        lambda: analyze([{"segments": [dict(t_start=2, t_end=1, start=[0, 0, 0], end=[1, 0, 0])]}], 1.0),
        lambda: analyze([{"segments": [dict(t_start=1, t_end=1, start=[0, 0, 0], end=[1, 0, 0])]}], 1.0),
        lambda: analyze(
            [
                {
                    "segments": [
                        dict(t_start=0, t_end=1, start=[0, 0, 0], end=[1, 0, 0]),
                        dict(t_start=1, t_end=2, start=[2, 0, 0], end=[3, 0, 0]),
                    ]
                }
            ],
            1.0,
        ),
        lambda: analyze(
            [
                {
                    "offset": 5,
                    "segments": [
                        dict(t_start=0, t_end=1, start=[0, 0, 0], end=[1, 0, 0])
                    ],
                }
            ],
            1.0,
        ),
        lambda: analyze(
            [
                {
                    "offset": 5,
                    "segments": [
                        dict(t_start=100, t_end=101, start=[0, 0, 0], end=[1, 0, 0])
                    ],
                }
            ],
            1.0,
        ),
        lambda: analyze(timelines, 0),
        lambda: analyze(timelines, float("nan")),
        lambda: analyze(timelines, -1.0),
    ):
        try:
            call()
            raise AssertionError("非法输入未被拒绝")
        except ValueError:
            pass
    print("通过 · 第十七阶段输入防御与旧 analyze 字段兼容")


def run():
    _continuous_detection()
    _coordination()
    _infeasible()
    _determinism()
    _fingerprints()
    _failure_propagation()
    _compatibility()
    return 0
