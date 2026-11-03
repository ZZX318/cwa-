"""Stage 22 regressions: multi-UAV CAW plans, coordination, playback, failure."""

import copy
import json
from pathlib import Path

from coordination_plan import coordinate, verify as verify_coordination
from execution import build
from multi import run as multi_run
from multi_caw import plan_from_item, run as multi_caw_run, verify as verify_multi_caw
from playback import multi_playback
from scene import generate

SMALL_SCENE = json.loads(Path("configs/joint.small.json").read_text(encoding="utf8"))
SMALL_JOB = json.loads(Path("configs/job.joint.small.json").read_text(encoding="utf8"))
WALL_SCENE = json.loads(Path("configs/caw.wall.json").read_text(encoding="utf8"))
WALL_JOB = json.loads(Path("configs/job.caw.tiny.json").read_text(encoding="utf8"))


def _small():
    scene = generate(SMALL_SCENE)
    result = multi_caw_run(scene, SMALL_JOB, 2)
    assert result["status"] == "success", result.get("reason")
    assert result["algorithm"] == "caw" and len(result["uavs"]) == 2
    assert result["scene_hash"] and result["config_hash"]
    ids = set()
    for item in result["uavs"]:
        assert item["status"] == "success", item.get("reason")
        assert item["plan_version"] == "1.2"
        assert item["start_point_id"] and item["end_point_id"]
        assert item["start"] and item["end"]
        assert item["safety"] == "pass"
        ids.update(item["target_ids"])
        plan = plan_from_item(scene, item, SMALL_JOB)
        timeline = build(scene, plan)
        assert abs(timeline["duration"] - item["duration"]) < 1e-9
        assert item["coverage"] is not None and 0 <= item["coverage"] <= 1
    assert ids == {target["id"] for target in scene["targets"]}

    explicit = generate(SMALL_SCENE)
    explicit["launch_points"] = [
        {"id": "pad-west", "position": [-3, 12, 0], "role": "both"},
        {"id": "pad-east", "position": [14, 4.5, 0], "role": "both"},
    ]
    explicit["launch_assignments"] = [
        {"uav": 1, "start": "pad-west", "end": "pad-west"},
        {"uav": 2, "start": "pad-west", "end": "pad-east"},
    ]
    assigned = multi_caw_run(explicit, SMALL_JOB, 2)
    assert assigned["status"] == "success", assigned.get("reason")
    first, second = assigned["uavs"]
    assert first["start"] == first["end"] == [-3, 12, 0]
    assert second["start"] == [-3, 12, 0] and second["end"] == [14, 4.5, 0]
    assert second["start_point_id"] == "pad-west"
    assert second["end_point_id"] == "pad-east"
    timeline = build(explicit, plan_from_item(explicit, second, SMALL_JOB))
    assert timeline["segments"][0]["start"] == second["start"]
    assert timeline["segments"][-1]["end"] == second["end"]
    # Wall scene: fixed-Y fails, multi CAW flies over the wall at a higher layer.
    wall = generate(WALL_SCENE)
    assert multi_run(wall, WALL_JOB, 2)["status"] == "failed"
    climbed = multi_caw_run(wall, WALL_JOB, 2)
    assert climbed["status"] == "success", climbed.get("reason")
    for item in climbed["uavs"]:
        if not item.get("segments"):
            continue
        transit_z = [
            point[2]
            for segment in item["segments"]
            if segment["type"] == "transit"
            for point in (segment["start"], segment["end"])
        ]
        assert max(transit_z) > item["work_height"] + 1.0
        assert min(transit_z) >= 0.5 - 1e-9
    print("通过 · 多机 CAW：2 机成功、每机 v1.2 起降元数据、三维转场越墙、目标并集")


def _default_compatibility():
    scene = generate()
    first = multi_run(scene, {}, 2)
    second = multi_run(scene, {}, 2)
    assert first == second and first["status"] == "success"
    assert [item["duration"] for item in first["uavs"]] == [
        70.95061132783383,
        79.55741869544083,
    ]
    for item in first["uavs"]:
        assert "plan_version" not in item and "start_point_id" not in item
        assert item["segments"] and "coverage" in item
    print("通过 · 默认多机 fixed-y 兼容：时长 70.951/79.557 s、无新元数据、重复运行一致")


def _coordination():
    scene = generate(SMALL_SCENE)
    result = coordinate(
        scene, SMALL_JOB, 2, 1.0, 120.0, 200, include_playback=True, algorithm="caw"
    )
    assert result["status"] == "success", result.get("reason")
    assert result.get("algorithm") == "caw"
    assert result["conflicts_before"] > 0 and result["conflicts_after"] == 0
    assert result["playback"]["mode"] == "coordinated"
    assert verify_coordination(result, scene, SMALL_JOB)
    infeasible = coordinate(scene, SMALL_JOB, 2, 1000.0, 2.0, 20, algorithm="caw")
    assert infeasible["status"] == "failed"
    assert infeasible["stage"] == "coordination" and infeasible["reason"]
    assert infeasible["conflicts_after"] > 0
    assert verify_coordination(infeasible, scene, SMALL_JOB)
    # Default fixed-Y coordination output is unchanged (no algorithm field).
    legacy = coordinate(scene, SMALL_JOB, 2, 1.0, 120.0, 200)
    assert legacy["status"] == "success" and "algorithm" not in legacy
    assert [item["offset_seconds"] for item in legacy["uavs"]] == [0.0, 2.05]
    print("通过 · 多机 CAW 协调：conflicts_after=0、不可消解保留原因、默认 fixed-y 无新字段")


def _playback():
    scene = generate(SMALL_SCENE)
    payload = multi_playback(scene, SMALL_JOB, 2, algorithm="caw")
    assert payload["status"] == "success", payload.get("reason")
    assert payload["mode"] == "multi-caw" and len(payload["tracks"]) == 2
    multi = multi_caw_run(scene, SMALL_JOB, 2)
    for item, track in zip(multi["uavs"], payload["tracks"]):
        timeline = build(scene, plan_from_item(scene, item, SMALL_JOB))
        assert track["home"] == item["start"] == timeline["segments"][0]["start"]
        assert track["duration"] == timeline["duration"]
        assert len(track["segments"]) == len(timeline["segments"])
        for left, right in zip(track["segments"], timeline["segments"]):
            assert left["t_start"] == right["t_start"] and left["t_end"] == right["t_end"]
            assert left["start"] == right["start"] and left["end"] == right["end"]
            assert left["spray"] == right["spray"]
    script = Path("web/playback.js").read_text(encoding="utf8")
    assert "api(" not in script
    assert "requestAnimationFrame" in script and "function trackState" in script
    assert "localStateAt" in Path("web/execution.js").read_text(encoding="utf8")
    print("通过 · 多机 CAW 回放：每机 home/轨迹与执行器一致、播放期无逐帧请求")


def _failure_and_fingerprints():
    scene = generate(SMALL_SCENE)
    result = multi_caw_run(scene, SMALL_JOB, 2)
    assert verify_multi_caw(result, scene, SMALL_JOB)

    broken = multi_caw_run(scene, SMALL_JOB, 2, {"max_expansions": 1})
    assert broken["status"] == "failed"
    assert broken["stage"] == "search" and broken["reason"]
    assert all(item["status"] == "failed" for item in broken["uavs"])
    assert verify_multi_caw(broken, scene, SMALL_JOB)

    forged = copy.deepcopy(result)
    forged["uavs"][0]["duration"] += 1.0
    try:
        verify_multi_caw(forged, scene, SMALL_JOB)
    except ValueError:
        pass
    else:
        raise AssertionError("篡改多机 CAW 时长未被拒绝")

    tampered_options = copy.deepcopy(result)
    tampered_options["uavs"][0]["planner_options"]["step_xy"] = 2.0
    try:
        verify_multi_caw(tampered_options, scene, SMALL_JOB)
    except ValueError:
        pass
    else:
        raise AssertionError("篡改多机 CAW 规划器参数未被拒绝")

    tampered_hash = copy.deepcopy(result)
    tampered_hash["config_hash"] = "0" * 64
    try:
        verify_multi_caw(tampered_hash, scene, SMALL_JOB)
    except ValueError:
        pass
    else:
        raise AssertionError("篡改多机 CAW 配置指纹未被拒绝")

    tampered_top = copy.deepcopy(result)
    tampered_top["planner_options"]["step_xy"] = 2.0
    try:
        verify_multi_caw(tampered_top, scene, SMALL_JOB)
    except ValueError:
        pass
    else:
        raise AssertionError("篡改多机 CAW 顶层规划器参数未被拒绝")

    changed = generate({"rows": 3, "trees_per_row": 2})
    try:
        verify_multi_caw(result, changed, SMALL_JOB)
    except ValueError:
        pass
    else:
        raise AssertionError("场景变化后旧多机 CAW 结果未被拒绝")

    coordination_failure = coordinate(
        scene, SMALL_JOB, 2, 1.0, 120.0, 200, algorithm="caw", options={"max_expansions": 1}
    )
    assert coordination_failure["status"] == "failed"
    assert coordination_failure["stage"] == "multi" and coordination_failure["reason"]
    assert verify_coordination(coordination_failure, scene, SMALL_JOB)
    print("通过 · 失败传播与指纹：搜索失败 stage/reason、参数/时长/场景/配置篡改拒绝")


def run():
    _small()
    _default_compatibility()
    _coordination()
    _playback()
    _failure_and_fingerprints()
    return 0
