"""Regression for NN + 2-opt ordering, lower bounds and exact comparison."""

import json
import math
from unittest.mock import patch

from execution import build
from joint import candidate_plan, optimize
from planning.order import solve_order
from planning.planner import fixed_y_lanes
from scene import generate


def _tiny():
    return generate(dict(rows=1, trees_per_row=3))


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

    scene = _tiny()
    job = {"swath": 5.0}
    lanes = fixed_y_lanes(scene, job)["lanes"]

    def exact_vs_heuristic():
        assert len(lanes) == 3
        heuristic = solve_order(scene, job, lanes, strategy="nn+2opt")
        assert heuristic["status"] == "success" and sorted(heuristic["order"]) == [0, 1, 2]
        assert heuristic["matrix_mode"] == "exact3d"
        assert heuristic["routes_computed"] == 12
        exact = optimize(scene, job, 8, {"transition": "caw"})
        assert exact["status"] == "success", exact.get("reason")
        assert exact["optimality_gap"] == 0.0
        assert exact["expanded"] == exact["orders_total"]
        caw_plan = candidate_plan(scene, job, heuristic["order"], {"transition": "caw"})
        heuristic_time = build(scene, caw_plan)["duration"]
        assert exact["total_time"] <= heuristic_time + 1e-9
        gap = heuristic_time - exact["total_time"]
        assert gap >= -1e-9
        height = caw_plan["work_height"]
        speed = caw_plan["config"]["speed"]
        exact_order_cost = exact["total_time"] - 2 * height / speed
        assert heuristic["lower_bound"] <= heuristic["order_cost"] + 1e-9
        assert heuristic["lower_bound"] <= exact_order_cost + 1e-9

    def deterministic():
        first = solve_order(scene, job, lanes, strategy="nn+2opt")
        second = solve_order(scene, job, lanes, strategy="nn+2opt")
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def nn_bound():
        nn = solve_order(scene, job, lanes, strategy="nn")
        two = solve_order(scene, job, lanes, strategy="nn+2opt")
        assert two["order_cost"] <= nn["order_cost"] + 1e-9
        fixed = solve_order(scene, job, lanes, strategy="fixed")
        assert fixed["order"] == [0, 1, 2] and fixed["evaluated"] == 1

    def infeasible():
        blocked = generate(
            dict(
                rows=1,
                trees_per_row=3,
                obstacles=[dict(id="w", kind="box", min=[-1, -5.5, 0], max=[0, 18.5, 11.2])],
            )
        )
        result = solve_order(blocked, job, fixed_y_lanes(blocked, job)["lanes"], strategy="nn+2opt")
        assert result["status"] == "failed" and result["route_failures_total"] > 0
        assert result["route_failures"] and result["route_failures"][0]["stage"] == "search"

    def large_proxy():
        large = generate()
        lanes_large = fixed_y_lanes(large, {})["lanes"]
        assert len(lanes_large) == 48
        result = solve_order(large, {}, lanes_large, strategy="nn+2opt")
        assert result["status"] == "success"
        assert result["matrix_mode"] == "euclidean_lb"
        assert result["routes_computed"] == 0
        assert sorted(result["order"]) == list(range(48))
        assert result["lower_bound"] is not None
        assert result["order_cost"] >= result["lower_bound"] - 1e-9

    def nn_astar():
        first = solve_order(scene, job, lanes, strategy="nn_astar")
        second = solve_order(scene, job, lanes, strategy="nn_astar")
        nn = solve_order(scene, job, lanes, strategy="nn", matrix_mode="exact3d")
        assert first["status"] == "success"
        assert first["matrix_mode"] == "exact3d"
        assert sorted(first["order"]) == list(range(3))
        assert first["order"] == nn["order"]
        assert abs(first["order_cost"] - nn["order_cost"]) < 1e-9
        assert first["evaluated"] == 3  # no 2-opt
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        forced = solve_order(scene, job, lanes, strategy="nn_astar", matrix_mode="euclidean_lb")
        assert forced == first
        assert solve_order(scene, job, lanes) == solve_order(scene, job, lanes, strategy="nn+2opt")
        try:
            solve_order(scene, job, lanes, strategy="bogus")
        except ValueError:
            pass
        else:
            raise AssertionError("未知策略未拒绝")

    def large_astar_guard():
        # Exercise the real matrix/NN path with cheap route responses; tiny test
        # above covers real A*. Avoid hundreds of searches in the unit suite.
        many = lanes * 8
        with patch("planning.order.route3d", return_value={"status": "success", "cost": 1.0}) as route:
            result = solve_order(scene, job, many, strategy="nn_astar", step_xy=2.0)
            assert result["status"] == "success" and result["matrix_mode"] == "exact3d"
            assert route.call_count == 24 * 25
            assert sorted(result["order"]) == list(range(24))
            try:
                solve_order(scene, job, many, strategy="nn", matrix_mode="exact3d")
            except ValueError as error:
                assert "超过 20 条" in str(error)
            else:
                raise AssertionError("旧策略的 exact3d 上限改变")

    def unsupported():
        small = generate(dict(rows=2, trees_per_row=2))
        result = optimize(small, {}, 6, {"transition": "caw"})
        assert result["status"] == "unsupported"
        assert result["order"] is None and result["total_time"] is None
        assert "上限" in result["reason"]

    check("exact-vs-heuristic", exact_vs_heuristic)
    check("determinism", deterministic)
    check("nn", nn_bound)
    check("infeasible", infeasible)
    check("large-proxy", large_proxy)
    check("nn-astar", nn_astar)
    check("large-astar-guard", large_astar_guard)
    check("unsupported", unsupported)
    return 1 if failed else 0
