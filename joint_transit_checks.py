"""Independent regression for exact lane-order + transition joint optimization."""

import copy
import itertools
import json
import math
import tempfile
from pathlib import Path

from execution import build as build_execution
from joint import (
    MAX_EXACT_ORDERS,
    METHOD_FIXED,
    METHOD_SEARCH,
    candidate_plan,
    load,
    optimize,
    save,
    verify,
)
from planning import (
    check,
    config_fingerprint,
    configuration,
    fingerprint,
    generate_plan,
)
from routing import route
from scene import generate

SWATH = {"swath": 4.0}


def _lanes(scene, config):
    plan = generate_plan(scene, config)
    assert plan["status"] == "success", plan.get("reason")
    return [segment for segment in plan["segments"] if segment["type"] == "spray"]


def _air_home(scene, config):
    height = max(tree["canopy"]["z_max"] for tree in scene["trees"]) + config["height_offset"]
    launch = sorted(scene["launch_points"], key=lambda point: tuple(point["position"]))[0]
    return [launch["position"][0], launch["position"][1], height], height


def _order_transition(order, lanes, air_home):
    """All transit-type length: ingress + lane-to-lane + egress (no takeoff/landing)."""
    return (
        math.dist(air_home, lanes[order[0]]["start"])
        + sum(
            math.dist(lanes[order[i]]["end"], lanes[order[i + 1]]["start"])
            for i in range(len(order) - 1)
        )
        + math.dist(lanes[order[-1]]["end"], air_home)
    )


def _expect_reject(action):
    try:
        action()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("未拒绝非法输入")


def _search_order(order, lanes, air_home, scene, clearance):
    """Independent search-mode enumeration: routing.route only, no joint builder."""
    cache = {}
    legs = [(air_home, lanes[order[0]]["start"])]
    legs += [
        (lanes[order[i]]["end"], lanes[order[i + 1]]["start"])
        for i in range(len(order) - 1)
    ]
    legs.append((lanes[order[-1]]["end"], air_home))
    total = 0.0
    nodes = 0
    for start, goal in legs:
        if math.dist(start, goal) <= 1e-8:
            continue
        key = (tuple(start), tuple(goal))
        if key not in cache:
            cache[key] = route(scene, list(start), list(goal), 1.0, clearance)
        result = cache[key]
        assert result["status"] == "success", result.get("reason")
        total += result["length"]
        nodes += result.get("expanded", 0)
    return total, nodes


def _assert_spray_lanes_preserved(scene, config, result):
    """Reordering may change transitions only; spray lanes keep start/end/direction."""
    lanes = _lanes(scene, config)
    plan = candidate_plan(scene, config, result["order"])
    actual = [segment for segment in plan["segments"] if segment["type"] == "spray"]
    expected = [lanes[index] for index in result["order"]]
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert got["start"] == want["start"] and got["end"] == want["end"]
        assert got["target_ids"] == want["target_ids"]
    return plan


def _blocked_scene():
    return generate(
        {
            "rows": 1,
            "trees_per_row": 3,
            "obstacles": [
                dict(id="wall", kind="box", min=[1.0, -5.0, 0.0], max=[4.0, 18.0, 7.0])
            ],
        }
    )


def _partial_scene():
    # Blocks the long lane-1 -> lane-0 jump but not the baseline order.
    return generate(
        {
            "rows": 2,
            "trees_per_row": 1,
            "obstacles": [
                dict(id="thin", kind="box", min=[4.0, 0.8, 0.0], max=[6.0, 1.2, 7.0])
            ],
        }
    )


def run():
    passed = 0
    failed = 0

    def check_case(name, action):
        nonlocal passed, failed
        try:
            action()
            passed += 1
            print("通过 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · " + name + "：" + str(error))

    def exact_optimality():
        scene = generate({"rows": 1, "trees_per_row": 3})
        lanes = _lanes(scene, SWATH)
        assert len(lanes) == 3
        air_home, height = _air_home(scene, configuration(SWATH))
        brute = min(
            _order_transition(order, lanes, air_home)
            for order in itertools.permutations(range(3))
        )
        result = optimize(scene, SWATH, 8)
        assert result["status"] == "success", result.get("reason")
        assert result["expanded"] == result["orders_total"] == 6
        assert abs(result["transition_length"] - brute) < 1e-9
        assert abs(_order_transition(result["order"], lanes, air_home) - brute) < 1e-9
        spray_length = sum(math.dist(lane["start"], lane["end"]) for lane in lanes)
        expected_path = 2.0 * height + spray_length + brute
        assert abs(result["total_path_length"] - expected_path) < 1e-9
        assert abs(result["total_time"] - expected_path / 2.0) < 1e-9
        plan = _assert_spray_lanes_preserved(scene, SWATH, result)
        check(scene, plan)
        timeline = build_execution(scene, plan)
        assert abs(timeline["duration"] - result["total_time"]) < 1e-9
        assert result["optimality_gap"] == 0.0

    def unsupported():
        scene = generate({"rows": 1, "trees_per_row": 3})
        result = optimize(scene, SWATH, 2)
        assert result["status"] == "unsupported"
        assert "3" in result["reason"] and "2" in result["reason"]
        assert result["order"] is None and result["total_time"] is None
        assert result["orders_total"] == 6
        assert result["scene_hash"] == fingerprint(scene)
        assert result["config_hash"] == config_fingerprint(configuration(SWATH))
        scene9 = generate({"rows": 1, "trees_per_row": 9})
        result9 = optimize(scene9, SWATH, 9)
        assert result9["status"] == "unsupported"
        assert str(MAX_EXACT_ORDERS) in result9["reason"]
        assert result9["orders_total"] == math.factorial(9)
        assert result9["order"] is None and result9["total_time"] is None

    def failure_retention():
        blocked = optimize(_blocked_scene(), SWATH, 8)
        assert blocked["status"] == "failed"
        assert blocked["baseline"]["status"] == "failed"
        assert blocked["rejected"] and blocked["rejected"][0]["reason"]
        assert blocked["rejected"][0]["stage"] == "baseline"
        assert blocked["order"] is None and blocked["total_time"] is None
        partial = optimize(_partial_scene(), SWATH, 8)
        assert partial["status"] == "success", partial.get("reason")
        assert partial["feasible_orders"] == 1
        assert partial["rejected_total"] == 5
        assert len(partial["rejected"]) == 5
        assert all(item["reason"] for item in partial["rejected"])
        assert partial["rejected_truncated"] is False
        assert partial["rejected_note"] == ""
        truncating = generate(
            {
                "rows": 2,
                "trees_per_row": 2,
                "obstacles": [
                    dict(
                        id="pin",
                        kind="box",
                        min=[3.8, 2.3, 6.05],
                        max=[4.2, 2.7, 6.35],
                    )
                ],
            }
        )
        truncated = optimize(truncating, {"swath": 3.5}, 8)
        assert truncated["status"] == "success", truncated.get("reason")
        assert truncated["feasible_orders"] > 0
        assert truncated["rejected_total"] > 20
        assert truncated["rejected_truncated"] is True
        assert len(truncated["rejected"]) == 20
        assert f"共 {truncated['rejected_total']} 条失败候选" in truncated["rejected_note"]
        for item in truncated["rejected"]:
            assert item["reason"]

    def fingerprints_and_tamper():
        scene = generate({"rows": 1, "trees_per_row": 3})
        result = optimize(scene, SWATH, 8)
        assert result["scene_hash"] == fingerprint(scene)
        assert result["config_hash"] == config_fingerprint(configuration(SWATH))
        assert verify(result, scene, SWATH) is True
        tampered_scene = copy.deepcopy(scene)
        tampered_scene["trees"][0]["position"][0] += 0.1
        _expect_reject(lambda: verify(result, tampered_scene, SWATH))
        _expect_reject(lambda: verify(result, scene, {"swath": 4.5}))
        tampered_result = copy.deepcopy(result)
        tampered_result["order"] = [0, 0, 1]
        _expect_reject(lambda: verify(tampered_result, scene, SWATH))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "joint.json"
            save(result, path)
            assert load(path) == result

    def determinism():
        scene = generate({"rows": 1, "trees_per_row": 4})
        for config in (SWATH, dict(SWATH, transition_mode="search")):
            first = optimize(scene, config, 8)
            second = optimize(scene, config, 8)
            assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
                second, ensure_ascii=False, sort_keys=True
            )

    def input_defense():
        from main import job_config

        scene = generate({"rows": 1, "trees_per_row": 3})
        result = optimize(scene, SWATH, 8)
        for bad in ([], [("swath", 4.0)], "swath", 3):
            rejected = optimize(scene, bad, 8)
            assert rejected["status"] == "failed"
            assert "config 必须是对象" in rejected["reason"]
            assert rejected["order"] is None and rejected["total_time"] is None
            _expect_reject(lambda: verify(result, scene, bad))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            for text in ("[]", "null", "3"):
                path.write_text(text, encoding="utf8")
                _expect_reject(lambda: job_config(path, None))

    def fixed_and_search():
        scene = generate({"rows": 1, "trees_per_row": 3})
        fixed = optimize(scene, dict(SWATH, transition_mode="fixed"), 8)
        search = optimize(scene, dict(SWATH, transition_mode="search"), 8)
        assert fixed["status"] == "success", fixed.get("reason")
        assert search["status"] == "success", search.get("reason")
        assert fixed["method"] == METHOD_FIXED
        assert search["method"] == METHOD_SEARCH
        assert fixed["search_nodes"] == 0
        assert search["search_nodes"] > 0 and search["search_routes"] > 0
        assert search["scene_hash"] == fixed["scene_hash"]
        assert search["config_hash"] != fixed["config_hash"]
        for config, result in (
            (dict(SWATH, transition_mode="fixed"), fixed),
            (dict(SWATH, transition_mode="search"), search),
        ):
            plan = _assert_spray_lanes_preserved(scene, config, result)
            check(scene, plan)
            timeline = build_execution(scene, plan)
            transit = sum(
                segment["length"]
                for segment in timeline["segments"]
                if segment["type"] == "transit"
            )
            assert abs(transit - result["transition_length"]) < 1e-9
            assert plan["config"]["transition_mode"] == config["transition_mode"]
            assert verify(result, scene, config) is True
        # Independent search-mode enumeration using routing.route directly.
        lanes = _lanes(scene, SWATH)
        search_config = dict(SWATH, transition_mode="search")
        air_home, height = _air_home(scene, configuration(search_config))
        clearance = configuration(search_config)["clearance"]
        brute = min(
            (
                _search_order(order, lanes, air_home, scene, clearance)
                for order in itertools.permutations(range(len(lanes)))
            ),
            key=lambda item: (item[0], item[1]),
        )
        assert abs(search["transition_length"] - brute[0]) < 1e-9
        chosen_length, chosen_nodes = _search_order(
            search["order"], lanes, air_home, scene, clearance
        )
        assert abs(chosen_length - search["transition_length"]) < 1e-9
        assert chosen_nodes == search["search_nodes"]
        spray_length = sum(math.dist(lane["start"], lane["end"]) for lane in lanes)
        expected_path = 2.0 * height + spray_length + brute[0]
        assert abs(search["total_path_length"] - expected_path) < 1e-9
        assert abs(search["total_time"] - expected_path / 2.0) < 1e-9

    check_case("第十六阶段精确最优：3 航段穷举与独立暴力计算、执行器一致", exact_optimality)
    check_case("第十六阶段规模上限：超航段数与超排列数均 unsupported 且无伪结果", unsupported)
    check_case("第十六阶段失败保留：阻塞基准失败、部分候选拒绝与截断说明", failure_retention)
    check_case("第十六阶段指纹：场景/配置一致、篡改拒绝与保存加载", fingerprints_and_tamper)
    check_case("第十六阶段确定性：fixed/search 同一输入重复运行一致", determinism)
    check_case("第十六阶段输入防御：非对象 config/job 被拒绝而非崩溃", input_defense)
    check_case("第十六阶段转场语义：fixed/search 独立暴力核验与喷洒方向不变", fixed_and_search)
    return 1 if failed else 0
