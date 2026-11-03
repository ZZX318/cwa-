import json
import math
from pathlib import Path

from depot import optimize
from execution import build
from planning import config_fingerprint, configuration, fingerprint, generate_plan
from planning.energy import (
    DEFAULT_ENERGY,
    energy_config,
    energy_fingerprint,
    timeline_energy,
)
from planning.wind import segment_energy
from scene import generate

ROOT = Path(__file__).resolve().parent
SMALL = json.loads((ROOT / "configs" / "caw.tiny.json").read_text(encoding="utf8"))


def run_checks():
    default_scene = generate()
    baseline = generate_plan(default_scene, {})
    baseline_timeline = build(default_scene, baseline)
    assert abs(baseline_timeline["duration"] - 127.3963848374023) < 1e-9
    assert len(baseline["segments"]) == 99

    motion = energy_config()
    assert motion["profile"] == "motion-only"
    assert motion["k_move"] == 1.0 and motion["k_pump"] == 0.0
    mission = energy_config({"profile": "mission-proxy"})
    assert mission["k_pump"] > 0 and mission["k_hover"] > 0
    assert energy_fingerprint(motion) == energy_fingerprint(energy_config())
    for bad in (
        {"unknown": 1},
        {"k_move": -1},
        {"k_move": True},
        {"wh_per_eu": 1.0},
        {"calibration_id": "x"},
        {"reserve_ratio": 1.0},
    ):
        try:
            energy_config(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法能耗配置未被拒绝: {bad}")

    motion_report = timeline_energy(baseline_timeline, baseline["config"], motion)
    expected = sum(
        segment_energy(s["start"], s["end"], s["speed"], baseline["config"])
        for s in baseline_timeline["segments"]
    )
    assert math.isclose(motion_report["total_eu"], expected, rel_tol=1e-9, abs_tol=1e-9)
    assert motion_report["total_eu"] > 0 and motion_report["feasible"]
    assert "energy_wh" not in motion_report
    mission_report = timeline_energy(baseline_timeline, baseline["config"], mission)
    assert mission_report["components"]["pump"] > 0
    assert mission_report["total_eu"] > motion_report["total_eu"]
    calibrated = energy_config({"wh_per_eu": 0.5, "calibration_id": "test-01"})
    calibrated_report = timeline_energy(baseline_timeline, baseline["config"], calibrated)
    assert calibrated_report["calibrated"] and math.isclose(
        calibrated_report["energy_wh"], calibrated_report["total_eu"] * 0.5
    )
    limited = energy_config({"endurance_eu": 1.0, "reserve_ratio": 0.1})
    limited_report = timeline_energy(baseline_timeline, baseline["config"], limited)
    assert not limited_report["feasible"] and "超过可用上限" in limited_report["reason"]

    launch = optimize(default_scene, {}, dict(candidates="launch", uavs=1, objective="time"))
    assert launch["status"] == "success" and launch["exact"]
    assert launch["selected"]["depot"] == [-3.0, 12.5, 0.0]
    assert math.isclose(launch["selected"]["makespan"], 127.3963848374023)
    assert launch["selected"]["coverage"] == 1.0
    assert launch["scene_hash"] == fingerprint(default_scene)
    assert launch["config_hash"] == config_fingerprint(configuration({}))
    assert launch["energy_config_hash"] == energy_fingerprint(motion)
    assert launch["lower_bound"] <= launch["selected"]["makespan"] + 1e-9
    assert launch["gap"] >= 0

    scene = generate(SMALL)
    grid = optimize(scene, {}, dict(candidates="grid", grid=3, uavs=1, objective="time"))
    assert grid["status"] == "success" and grid["exact"]
    assert grid["candidates_total"] > 1 and grid["evaluated"] == grid["candidates_total"]
    assert all(row["status"] == "success" for row in grid["rows"])
    assert grid["selected"]["coverage"] == 1.0
    assert grid["selected"]["makespan"] > 0 and grid["selected"]["energy_eu"] > 0
    assert grid["gap"] >= 0
    again = optimize(scene, {}, dict(candidates="grid", grid=3, uavs=1, objective="time"))
    assert again["selected"] == grid["selected"]
    assert [r["depot"] for r in again["rows"]] == [r["depot"] for r in grid["rows"]]

    by_energy = optimize(scene, {}, dict(candidates="grid", grid=3, uavs=1, objective="energy"))
    assert by_energy["status"] == "success" and by_energy["objective"] == "energy"
    feasible = [r for r in by_energy["rows"] if r["status"] == "success"]
    best = min(r["energy_eu"] for r in feasible)
    assert math.isclose(by_energy["selected"]["energy_eu"], best)
    assert by_energy["lower_bound"] is None and by_energy["gap"] is None

    fleet = optimize(scene, {}, dict(candidates="grid", grid=3, uavs=2, objective="time"))
    assert fleet["status"] == "success"
    assert fleet["selected"]["makespan"] > 0 and fleet["selected"]["total_time"] > 0
    assert fleet["selected"]["coverage_note"]

    coordinated = optimize(
        scene,
        {},
        dict(
            candidates="grid",
            grid=3,
            uavs=2,
            objective="time",
            coordinate=True,
            min_distance=1.0,
        ),
    )
    assert coordinated["status"] == "success"
    assert coordinated["selected"]["coordinated"]
    assert coordinated["selected"]["conflicts_after"] == 0
    assert coordinated["selected"]["waiting_seconds"] >= 0

    calibrated = optimize(
        scene,
        {},
        dict(
            candidates="launch",
            uavs=1,
            objective="energy",
            energy={"wh_per_eu": 0.5, "calibration_id": "test-01"},
        ),
    )
    assert calibrated["status"] == "success"
    assert calibrated["selected"]["calibrated"]
    assert math.isclose(
        calibrated["selected"]["energy_wh"],
        calibrated["selected"]["energy_eu"] * 0.5,
    )

    blocked = dict(generate())
    extent = blocked["extent"]
    blocked["obstacles"] = [
        {"id": "wall", "kind": "box", "min": [-3.5, 12.0, 0], "max": [-2.5, 13.0, 3]}
    ]
    failed = optimize(blocked, {}, dict(candidates="launch", uavs=1, objective="time"))
    assert failed["status"] == "failed" and failed["reason"]
    assert "基准计划失败" in failed["reason"]

    try:
        optimize(scene, {}, dict(candidates="bad"))
    except ValueError:
        pass
    else:
        raise AssertionError("非法候选来源未被拒绝")

    print("通过 · 起降点优化与能耗代理：候选枚举、能量守恒、指纹、失败与确定性")
    return 0
