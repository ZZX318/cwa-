import copy
import json
from pathlib import Path

from coordination_plan import coordinate
from execution import build
from joint import optimize as joint_optimize
from multi import run as multi_run
from playback import multi_playback
from planning import check, generate_plan
from scene import generate
from scene.launch import resolve, resolve_all

ROOT = Path(__file__).resolve().parent
SMALL = json.loads((ROOT / "configs" / "joint.small.json").read_text(encoding="utf8"))
JOB = json.loads((ROOT / "configs" / "job.joint.small.json").read_text(encoding="utf8"))


def _explicit_scene():
    scene = generate(SMALL)
    scene["launch_points"] = [
        {"id": "pad-west", "position": [-3, 12, 0], "role": "start"},
        {"id": "pad-east", "position": [14, 4.5, 0], "role": "return"},
    ]
    scene["launch_assignments"] = [
        {"uav": 1, "start": "pad-west", "end": "pad-east"},
        {"uav": 2, "start": "pad-west", "end": "pad-east"},
    ]
    return scene


def run_checks():
    default = generate()
    resolved = resolve(default, 1)
    assert not resolved["explicit"]
    assert resolved["start_id"] == resolved["end_id"] == "launch-1"
    baseline = generate_plan(default, {})
    assert baseline["version"] == "1.1"
    assert "start_point_id" not in baseline
    timeline = build(default, baseline)
    assert abs(timeline["duration"] - 127.3963848374023) < 1e-9
    fleet = multi_run(default, {}, 2)
    assert fleet["status"] == "success"
    assert all("start_point_id" not in uav for uav in fleet["uavs"])
    assert fleet["uavs"][0]["duration"] > 0

    role_scene = generate(SMALL)
    role_scene["launch_points"] = [
        {"id": "pad-west", "position": [-3, 12, 0], "role": "start"},
        {"id": "pad-east", "position": [14, 4.5, 0], "role": "return"},
    ]
    role = resolve(role_scene, 1)
    assert role["explicit"] and role["start_id"] == "pad-west" and role["end_id"] == "pad-east"
    role_plan = generate_plan(role_scene, JOB)
    assert role_plan["status"] == "success"
    assert role_plan["version"] == "1.2"
    assert role_plan["start_point_id"] == "pad-west"
    assert role_plan["end_point_id"] == "pad-east"
    assert role_plan["segments"][0]["start"][:2] == [-3, 12]
    assert role_plan["segments"][-1]["end"][:2] == [14, 4.5]
    build(role_scene, role_plan)

    explicit = _explicit_scene()
    units = resolve_all(explicit, 2)
    assert units[0]["start_id"] == "pad-west" and units[0]["end_id"] == "pad-east"
    assert units[1]["start_id"] == "pad-west" and units[1]["end_id"] == "pad-east"
    fleet = multi_run(explicit, JOB, 2)
    assert fleet["status"] == "success"
    for unit in fleet["uavs"]:
        assert unit["status"] == "success"
        assert unit["start_point_id"] == "pad-west"
        assert unit["end_point_id"] == "pad-east"
        assert unit["start"][:2] == [-3, 12]
        assert unit["end"][:2] == [14, 4.5]
    first = copy.deepcopy(fleet["uavs"][0]["segments"])
    plan = dict(generate_plan(explicit, JOB, uav=1))
    plan["segments"] = first
    plan["allow_partial"] = True
    check(explicit, plan)

    shared = copy.deepcopy(explicit)
    for point in shared["launch_points"]:
        point["role"] = "both"
    shared["launch_assignments"] = [
        {"uav": 1, "start": "pad-west", "end": "pad-west"},
        {"uav": 2, "start": "pad-east", "end": "pad-east"},
    ]
    assert resolve(shared, 1)["start_id"] == resolve(shared, 1)["end_id"] == "pad-west"
    assert resolve(shared, 2)["start_id"] == resolve(shared, 2)["end_id"] == "pad-east"
    shared_fleet = multi_run(shared, JOB, 2)
    assert shared_fleet["status"] == "success"
    assert shared_fleet["uavs"][0]["start_point_id"] == "pad-west"
    assert shared_fleet["uavs"][1]["start_point_id"] == "pad-east"

    missing = copy.deepcopy(explicit)
    missing["launch_assignments"] = [{"uav": 1, "start": "pad-west", "end": "pad-east"}]
    try:
        resolve(missing, 2)
    except ValueError as error:
        assert "缺少 UAV 2" in str(error)
    else:
        raise AssertionError("缺少分配的 UAV 未被拒绝")
    missing_fleet = multi_run(missing, JOB, 2)
    assert missing_fleet["status"] == "failed" and missing_fleet["stage"] == "launch"

    tampered = copy.deepcopy(plan)
    tampered["start_point_id"] = "pad-east"
    try:
        check(explicit, tampered)
    except ValueError as error:
        assert "起降点元数据" in str(error)
    else:
        raise AssertionError("起降点元数据篡改未被拒绝")
    missing_meta = copy.deepcopy(plan)
    for key in ("start_point_id", "end_point_id", "uav"):
        missing_meta.pop(key, None)
    try:
        check(explicit, missing_meta)
    except ValueError as error:
        assert "缺少起降点元数据" in str(error)
    else:
        raise AssertionError("显式场景缺少元数据的计划未被拒绝")

    from planner_api import make_planner
    from execution import build as build_timeline

    caw_plan = make_planner("caw").plan(
        explicit, JOB, {"step_xy": 1.0, "order_strategy": "nn+2opt", "objective": "time"}
    )
    assert caw_plan["status"] == "success"
    assert caw_plan["version"] == "1.2"
    assert caw_plan["start_point_id"] == "pad-west"
    assert caw_plan["end_point_id"] == "pad-east"
    assert caw_plan["segments"][0]["start"][:2] == [-3, 12]
    assert caw_plan["segments"][-1]["end"][:2] == [14, 4.5]
    build_timeline(explicit, caw_plan)
    caw_energy = make_planner("caw").plan(
        explicit, JOB, {"step_xy": 1.0, "order_strategy": "nn+2opt", "objective": "energy"}
    )
    assert caw_energy["status"] == "success"
    assert caw_energy["objective"] == "energy"
    assert caw_energy["objective_value"] > 0
    build_timeline(explicit, caw_energy)

    joint = joint_optimize(explicit, JOB, 8, {"transition": "caw", "step_xy": 1.0, "objective": "time"})
    assert joint["status"] == "success"
    assert joint["order"]

    coordinated = coordinate(explicit, JOB, 2, 1.0, 120.0, 200, include_playback=True)
    assert coordinated["status"] == "success"
    assert coordinated["playback"]["homes"][0][:2] == [-3, 12]
    assert coordinated["playback"]["homes"][1][:2] == [-3, 12]
    playback = multi_playback(explicit, JOB, 2)
    assert playback["status"] == "success"
    assert playback["homes"][0][:2] == [-3, 12]
    assert playback["homes"][1][:2] == [-3, 12]
    assert all(track["home"] is not None for track in playback["tracks"])

    print("通过 · 起降点 L2：默认回退、role/assignment、start≠end、缺失与篡改拒绝、多机/协同/回放")
    return 0
