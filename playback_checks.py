"""Stage 17 playback regressions: executor-sourced timelines and local rendering."""

import json
import math
from pathlib import Path

from coordination_plan import coordinate
from execution import build
from joint import candidate_plan, optimize
from multi import run as multi_run
from playback import joint_playback, multi_playback
from planning import generate_plan
from scene import generate

SMALL_SCENE = json.loads(Path("configs/joint.small.json").read_text(encoding="utf8"))
SMALL_JOB = json.loads(Path("configs/job.joint.small.json").read_text(encoding="utf8"))


def _timelines(scene, config, uavs):
    result = multi_run(scene, config, uavs)
    assert result["status"] == "success", result.get("reason")
    base = generate_plan(scene, config)
    assert base["status"] == "success", base.get("reason")
    timelines = []
    for item in result["uavs"]:
        plan = dict(base)
        plan["allow_partial"] = True
        plan["segments"] = item["segments"]
        timelines.append(build(scene, plan))
    return timelines, base


def _assert_track(track, timeline, offset=0.0):
    assert track["duration"] == timeline["duration"] + offset
    assert len(track["segments"]) == len(timeline["segments"])
    for payload, segment in zip(track["segments"], timeline["segments"]):
        assert abs(payload["t_start"] - (segment["t_start"] + offset)) < 1e-9
        assert abs(payload["t_end"] - (segment["t_end"] + offset)) < 1e-9
        assert payload["start"] == segment["start"] and payload["end"] == segment["end"]
        assert payload["type"] == segment["type"] and payload["spray"] == segment["spray"]
        for value in payload["start"] + payload["end"]:
            assert math.isfinite(value)


def _multi():
    scene = generate(SMALL_SCENE)
    payload = multi_playback(scene, SMALL_JOB, 2)
    assert payload["status"] == "success" and len(payload["tracks"]) == 2
    timelines, base = _timelines(scene, SMALL_JOB, 2)
    home = base["segments"][0]["start"]
    assert payload["home"] == home
    for index, track in enumerate(payload["tracks"]):
        _assert_track(track, timelines[index])
        assert track["home"] == home
        assert track["segments"][0]["start"] == home
    assert abs(payload["duration"] - max(t["duration"] for t in timelines)) < 1e-9
    idle = multi_playback(scene, SMALL_JOB, 6)
    assert idle["status"] == "success" and len(idle["tracks"]) == 4
    assert len(idle["idle"]) == 2 and all(t["segments"] for t in idle["tracks"])
    print("通过 · 第十七阶段G 多机基线回放：时间线与执行器一致、t=0 在起降点、空闲机不伪造轨迹")


def _coordinated():
    scene = generate(SMALL_SCENE)
    result = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200, include_playback=True)
    assert result["status"] == "success"
    payload = result["playback"]
    assert payload["mode"] == "coordinated" and len(payload["tracks"]) == 2
    timelines, base = _timelines(scene, SMALL_JOB, 2)
    home = base["segments"][0]["start"]
    assert payload["home"] == home
    offsets = [item["offset_seconds"] for item in result["uavs"]]
    assert offsets == [0.0, 2.05]
    for index, track in enumerate(payload["tracks"]):
        _assert_track(track, timelines[index], offsets[index])
        assert track["offset"] == offsets[index]
        assert abs(track["segments"][0]["t_start"] - offsets[index]) < 1e-9
        assert track["segments"][0]["start"] == home
    assert abs(payload["duration"] - result["makespan"]) < 1e-9
    print("通过 · 第十七阶段G 协调回放：等待偏移生效、首段时刻=偏移、时长=makespan")


def _joint():
    scene = generate(SMALL_SCENE)
    result = optimize(scene, SMALL_JOB, 8)
    assert result["status"] == "success"
    payload = joint_playback(scene, SMALL_JOB, result["order"])
    assert payload["status"] == "success"
    assert [track["label"] for track in payload["tracks"]] == ["最优", "基准"]
    optimal = build(scene, candidate_plan(scene, SMALL_JOB, result["order"]))
    baseline = build(scene, generate_plan(scene, SMALL_JOB))
    _assert_track(payload["tracks"][0], optimal)
    _assert_track(payload["tracks"][1], baseline)
    assert abs(payload["tracks"][0]["duration"] - result["total_time"]) < 1e-9
    assert abs(payload["tracks"][1]["duration"] - result["baseline"]["total_time"]) < 1e-9
    assert payload["duration"] == max(optimal["duration"], baseline["duration"])
    print("通过 · 第十七阶段G 联合回放：最优/基准轨迹与执行器一致")


def _frontend():
    playback = Path("web/playback.js").read_text(encoding="utf8")
    execution = Path("web/execution.js").read_text(encoding="utf8")
    server = Path("server.py").read_text(encoding="utf8")
    for token in (
        "requestAnimationFrame",
        "performance.now",
        "function trackState",
        "const MultiPlayback",
        "function drawDynamic",
        "function drawPlaybackPaths",
    ):
        assert token in playback, token
    assert "/api/state" not in execution
    assert "function localStateAt" in execution
    assert "queryTime(desiredTime())" in execution
    assert "if (t < segments[i].t_end)" in execution
    assert "if (t === segments[0].t_start)" in execution
    assert "if (t < segments[i].t_end)" in playback
    assert "if (t === first.t_start)" in playback
    assert "visibilitychange" in execution and "document.hidden && playing" in execution
    assert "visibilitychange" in playback and "document.hidden && MultiPlayback" in playback
    assert "api(" not in playback
    animate_start = execution.index("async function animate()")
    animate_end = execution.index("document.addEventListener('visibilitychange'", animate_start)
    assert "api(" not in execution[animate_start:animate_end]
    assert "/api/multi-playback" in server and "/api/joint-playback" in server
    assert "include_playback=True" in server
    print("通过 · 第十七阶段G 前端回放：边界插值、rAF 墙钟、后台暂停、无逐帧请求")


def run():
    _multi()
    _coordinated()
    _joint()
    _frontend()
    return 0
