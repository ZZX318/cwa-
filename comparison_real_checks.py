"""Regression for real planner dispatch in comparison tables."""

import json
import math

from comparison import FIVE_METHODS, run
from planning import config_fingerprint, configuration, fingerprint
from scene import generate


def run_checks() -> int:
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

    def three_methods():
        scene = generate()
        result = run(scene, {}, "all")
        assert [row["method"] for row in result["results"]] == [
            "fixed-y-boustrophedon",
            "naive-target-order",
            "caw-a*-3d-wind",
        ]
        fixed, naive, caw = result["results"]
        assert fixed["status"] == naive["status"] == caw["status"] == "success"
        assert fixed["path_length"] != naive["path_length"]
        assert fixed["duration"] != naive["duration"]
        assert caw["plan_version"] == "1.2"
        assert fixed["plan_version"] == naive["plan_version"] == "1.1"
        assert caw["safety"] == fixed["safety"] == "pass"
        assert "violation" not in fixed
        assert caw["search_nodes"] and caw["order"] and caw["matrix_mode"]
        assert result["config_hash"] == config_fingerprint(configuration({}))
        assert all(row["scene_hash"] == fingerprint(scene) for row in result["results"])
        json.dumps(result, allow_nan=False)

    def both_semantics():
        scene = generate()
        result = run(scene, {}, "both")
        assert len(result["results"]) == 2
        fixed, naive = result["results"]
        assert fixed["method"] != naive["method"]
        assert fixed["path_length"] != naive["path_length"]

    def failures_retained():
        wall = generate(
            dict(
                rows=1,
                trees_per_row=3,
                obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
            )
        )
        result = run(wall, {}, "all")
        rows = {row["method"]: row for row in result["results"]}
        assert rows["fixed-y-boustrophedon"]["status"] == "failed"
        assert rows["fixed-y-boustrophedon"]["stage"] == "safety"
        assert rows["fixed-y-boustrophedon"]["reason"]
        assert rows["naive-target-order"]["status"] == "failed"
        assert rows["caw-a*-3d-wind"]["status"] == "success"
        assert rows["caw-a*-3d-wind"]["safety"] == "pass"

    def unknown_method():
        result = run(generate(), {}, "not-a-planner")
        assert len(result["results"]) == 1
        row = result["results"][0]
        assert row["status"] == "failed" and "未知规划器" in row["reason"]

    def caw_metrics():
        result = run(generate(dict(rows=1, trees_per_row=3)), {}, "caw")
        row = result["results"][0]
        assert row["status"] == "success"
        assert row["coverage"] == 1.0
        assert row["transition_length"] > 0
        assert row["spray_seconds"] > 0
        assert row["amount"] == row["spray_seconds"] * 1.0

    def five_methods():
        scene = generate(dict(rows=1, trees_per_row=3))
        result = run(scene, {"transition_mode": "auto"}, "five", .25)
        assert result["methods"] == list(FIVE_METHODS)
        assert len(result["results"]) == 5
        assert all(row["status"] == "success" for row in result["results"])
        assert all(row["planning_seconds"] >= 0 for row in result["results"])
        assert all(row["evaluated_plan_version"] == "1.2" for row in result["results"])
        fixed, naive, fixed_order, nn, main = result["results"]
        assert len({row["spray_geometry_hash"] for row in (fixed, fixed_order, nn, main)}) == 1
        assert not naive["relative_to_fixed_y"]["available"]
        assert naive["relative_to_fixed_y"]["time_saving_pct"] is None
        assert [row["order_strategy"] for row in (fixed_order, nn, main)] == ["fixed", "nn", "nn+2opt"]
        assert all(pair["available"] for pair in result["contributions"])
        for pair in result["contributions"]:
            rows = {row["method"]: row for row in result["results"]}
            baseline, candidate = rows[pair["baseline"]], rows[pair["candidate"]]
            assert math.isclose(pair["time_saving_s"], baseline["duration"] - candidate["duration"], abs_tol=1e-9)
        json.dumps(result, allow_nan=False)

    def shared_wind_clock():
        scene = generate(dict(rows=1, trees_per_row=3))
        config = dict(wind_speed=2, wind_direction=0, transition_mode="auto")
        result = run(scene, config, "fixed-y,caw-fixed-order", .25)
        fixed, caw = result["results"]
        assert fixed["plan_version"] == "1.1" and caw["plan_version"] == "1.2"
        assert fixed["evaluated_plan_version"] == caw["evaluated_plan_version"] == "1.2"
        assert math.isclose(fixed["duration"], caw["duration"], abs_tol=1e-9)
        assert abs(result["contributions"][0]["time_saving_pct"]) < 1e-8
        assert fixed["source_plan_hash"] != fixed["plan_hash"]

    def automatic_obstacles():
        scene = generate(dict(rows=1, trees_per_row=3, obstacles=[
            dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7]),
        ]))
        result = run(scene, {"transition_mode": "auto"}, "five", .25)
        rows = {row["method"]: row for row in result["results"]}
        assert rows["fixed-y-boustrophedon"]["status"] == "failed"
        assert rows["caw-a*-3d-wind"]["status"] == "success"
        assert rows["naive-target-order"]["status"] == "failed"
        assert not result["contributions"][0]["available"]
        legacy = run(scene, {}, "five", .25)
        assert legacy["results"][0]["status"] == "failed"
        assert not legacy["contributions"][0]["available"]
        assert legacy["contributions"][0]["time_saving_pct"] is None

    def selection_and_validation():
        scene = generate(dict(rows=1, trees_per_row=2))
        assert run(scene, {}, "ablation")["methods"] == [FIVE_METHODS[0], *FIVE_METHODS[2:]]
        for resolution in (0, float("nan"), True):
            try:
                run(scene, {}, "five", resolution)
            except ValueError:
                pass
            else:
                raise AssertionError("非法评价分辨率被接受")

    check("three", three_methods)
    check("both", both_semantics)
    check("failures", failures_retained)
    check("unknown", unknown_method)
    check("metrics", caw_metrics)
    check("five-methods-and-pairwise-contributions", five_methods)
    check("shared-wind-clock", shared_wind_clock)
    check("automatic-obstacle-comparison", automatic_obstacles)
    check("comparison-selection-and-validation", selection_and_validation)
    return 1 if failed else 0
