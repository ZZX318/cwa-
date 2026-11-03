"""Regression for the shared wind time model and its executor agreement."""

import math

from execution import build
from planner_api import make_planner
from planning import configuration, generate_plan
from planning.wind import (
    effective_speed,
    horizon_heuristic,
    max_effective_speed,
    segment_energy,
    segment_time,
)
from scene import generate


def run() -> int:
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · " + name + "：" + str(error))

    def zero_wind_legacy():
        scene = generate()
        plan = generate_plan(scene)
        timeline = build(scene, plan)
        config = plan["config"]
        for segment in timeline["segments"]:
            expected = math.dist(segment["start"], segment["end"]) / segment["speed"]
            assert abs(segment["duration"] - expected) < 1e-12
            assert abs(
                segment["duration"]
                - segment_time(
                    segment["start"], segment["end"], segment["speed"], config, version="1.1"
                )
            ) < 1e-12

    def anisotropic():
        config = dict(wind_speed=2.0, wind_direction=0.0, wind_cost=0.25)
        a, b = [0.0, 0.0, 5.0], [10.0, 0.0, 5.0]
        head = effective_speed(a, b, 2.0, config)
        tail = effective_speed(b, a, 2.0, config)
        assert head < 2.0 < tail
        assert abs(head - 1.5) < 1e-12 and abs(tail - 2.5) < 1e-12
        assert abs(max_effective_speed(2.0, config) - tail) < 1e-12
        assert segment_time(a, b, 2.0, config) > segment_time(b, a, 2.0, config)

    def v12_decomposition():
        scene = generate(dict(rows=1, trees_per_row=3))
        plan = make_planner("caw-a*-3d-wind").plan(
            scene, dict(wind_speed=2.0, wind_direction=math.pi / 2)
        )
        assert plan["status"] == "success", plan["reason"]
        timeline = build(scene, plan)
        for segment in timeline["segments"]:
            expected = segment_time(
                segment["start"],
                segment["end"],
                segment["speed"],
                plan["config"],
                version="1.2",
            )
            assert abs(segment["duration"] - expected) < 1e-12

    def vertical_no_wind():
        calm = dict(wind_speed=0.0, wind_direction=0.0, wind_cost=0.25)
        windy = dict(wind_speed=5.0, wind_direction=1.1, wind_cost=0.25)
        a, b = [2.0, 3.0, 5.0], [2.0, 3.0, 8.0]
        assert abs(segment_time(a, b, 2.0, calm) - segment_time(a, b, 2.0, windy)) < 1e-15
        assert abs(segment_time(a, b, 2.0, calm) - 1.5) < 1e-12

    def heuristic_bound():
        config = configuration(dict(wind_speed=2.0, wind_direction=0.3))
        points = [
            ([0, 0, 6.2], [5, 4, 6.2]),
            ([-3, 2, 6.2], [2, 9, 7.5]),
            ([1, 1, 6.2], [1, 1, 9.0]),
        ]
        for a, b in points:
            assert horizon_heuristic(a, b, 2.0, config) <= segment_time(a, b, 2.0, config) + 1e-12

    def invalid_config():
        for raw in ({"wind_speed": -1}, {"wind_direction": float("nan")}, {"wind_cost": -0.5}):
            try:
                configuration(raw)
            except ValueError:
                pass
            else:
                raise AssertionError(f"未拒绝非法风场配置 {raw}")

    def energy_interface():
        config = configuration(dict(wind_speed=1.0, wind_direction=0.0))
        climb = segment_energy([0, 0, 5], [1, 0, 6], 2.0, config)
        descent = segment_energy([0, 0, 5], [1, 0, 4], 2.0, config)
        assert math.isfinite(climb) and climb > 0
        assert math.isfinite(descent) and descent > 0
        assert horizon_heuristic([0, 0, 5], [1, 0, 6], 2.0, config, objective="energy") <= climb

    def legacy_wind_time():
        scene = generate()
        plan = generate_plan(scene, {"wind_speed": 1.0, "wind_direction": 0.0})
        timeline = build(scene, plan)
        for segment in timeline["segments"]:
            expected = segment_time(
                segment["start"], segment["end"], segment["speed"], plan["config"], version="1.1"
            )
            assert abs(segment["duration"] - expected) < 1e-12

    check("zero-wind", zero_wind_legacy)
    check("anisotropic", anisotropic)
    check("v1.2", v12_decomposition)
    check("vertical", vertical_no_wind)
    check("heuristic", heuristic_bound)
    check("invalid", invalid_config)
    check("energy", energy_interface)
    check("legacy-wind", legacy_wind_time)
    return 1 if failed else 0
