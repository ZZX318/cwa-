"""Regression for the real planner registry, dispatch and failure contract."""

import json

from evaluation import at
from evaluation import build as eval_build
from execution import build
from planning import check, generate_plan, options_fingerprint
from planner_api import PLANNERS, make_planner
from scene import generate


def _wall():
    return generate(
        dict(
            rows=1,
            trees_per_row=3,
            obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
        )
    )


def run() -> int:
    passed = 0
    failed = 0

    def check_(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · " + name + "：" + str(error))

    tiny = generate(dict(rows=1, trees_per_row=3))

    def registry():
        assert set(PLANNERS) == {
            "fixed-y-boustrophedon",
            "naive-target-order",
            "caw-a*-3d-wind",
            "caw-a*-fixed-order",
            "caw-a*-nn",
        }
        assert make_planner("fixed-y").name == "fixed-y-boustrophedon"
        assert make_planner("naive").name == "naive-target-order"
        assert make_planner("caw").name == "caw-a*-3d-wind"
        for bad in ("multi-contiguous-uav", "nope", ""):
            try:
                make_planner(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"未拒绝 {bad!r}")

    def fixed_identity():
        scene = generate()
        assert make_planner("fixed-y").plan(scene, {}) == generate_plan(scene, {})
        plan = make_planner("fixed-y").plan(scene, {})
        assert plan["version"] == "1.1" and plan["status"] == "success"
        check(scene, plan)

    def naive_distinct():
        scene = generate()
        fixed = make_planner("fixed-y").plan(scene, {})
        naive = make_planner("naive").plan(scene, {})
        assert naive["status"] == "success", naive.get("reason")
        assert naive["segments"] != fixed["segments"]
        assert naive["version"] == "1.1" and naive["method"] == "naive-target-order"
        check(scene, naive)
        fixed_timeline = build(scene, fixed)
        naive_timeline = build(scene, naive)
        assert abs(fixed_timeline["duration"] - naive_timeline["duration"]) > 1e-6

    def caw_success():
        plan = make_planner("caw").plan(tiny, {})
        assert plan["status"] == "success", plan.get("reason")
        assert plan["version"] == "1.2"
        assert plan["planner"] == plan["method"] == "caw-a*-3d-wind"
        assert plan["objective"] == "time"
        assert plan["planner_options_hash"] == options_fingerprint(plan["planner_options"])
        check(tiny, plan)
        timeline = build(tiny, plan)
        assert abs(plan["objective_value"] - timeline["duration"]) < 1e-12
        evaluation = eval_build(tiny, plan, timeline)
        metrics = at(evaluation, timeline, timeline["duration"])
        assert metrics["coverage"] == 1.0
        json.dumps(plan, allow_nan=False)
        for key in ("order", "search", "order_search", "work_height", "config_hash"):
            assert key in plan

    def option_rejection():
        cases = [
            ({"step_xy": 1.5}, "step_xy"),
            ({"bogus": 1}, "未知"),
            ({"order_strategy": "random"}, "order_strategy"),
        ]
        for options, text in cases:
            plan = make_planner("caw").plan(tiny, {}, options)
            assert plan["status"] == "failed" and text in plan["reason"], plan
        energy_plan = make_planner("caw").plan(tiny, {}, {"objective": "energy"})
        assert energy_plan["status"] == "success"
        assert energy_plan["objective"] == "energy"
        assert energy_plan["objective_value"] > 0
        plan = make_planner("fixed-y").plan(tiny, {}, {"x": 1})
        assert plan["status"] == "failed" and "不支持" in plan["reason"]
        plan = make_planner("naive").plan(tiny, {}, {"transition": "bogus"})
        assert plan["status"] == "failed" and plan["stage"] == "plan"

    def failure_contract():
        wall = _wall()
        fixed = make_planner("fixed-y").plan(wall, {})
        assert fixed["status"] == "failed" and fixed["stage"] and fixed["reason"]
        naive = make_planner("naive").plan(wall, {})
        assert naive["status"] == "failed" and naive["stage"] and naive["reason"]
        caw = make_planner("caw").plan(wall, {})
        assert caw["status"] == "success", caw.get("reason")
        assert max(
            p[2] for s in caw["segments"] for p in (s["start"], s["end"])
        ) > 7.0
        capped = make_planner("caw").plan(tiny, {}, {"max_grid_nodes": 5})
        assert capped["status"] == "failed" and capped["stage"] == "search"
        assert "上限" in capped["reason"]
        for name in ("naive", "caw"):
            bad = make_planner(name).plan(tiny, {"swath": -1})
            assert bad["status"] == "failed" and bad["stage"] == "plan", (name, bad)

    def caw_variants():
        for name, strategy in (
            ("caw-a*-fixed-order", "fixed"),
            ("caw-a*-nn", "nn"),
            ("caw-a*-3d-wind", "nn+2opt"),
        ):
            plan = make_planner(name).plan(tiny, {})
            assert plan["status"] == "success", (name, plan.get("reason"))
            assert plan["planner_options"]["order_strategy"] == strategy
            check(tiny, plan)

    def subset_sequence():
        planner = make_planner("caw")
        plan = planner.plan_sequence(tiny, {}, [0, 1])
        assert plan["status"] == "success", plan.get("reason")
        assert plan["allow_partial"] is True
        assert plan["assigned_lane_indices"] == [0, 1]
        check(tiny, plan)
        build(tiny, plan)

    def v12_safety():
        plan = make_planner("caw").plan(tiny, {})
        tampered = json.loads(json.dumps(plan))
        tampered["planner"] = "unknown"
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "未知规划器" in str(error)
        else:
            raise AssertionError("未拒绝未知规划器")
        tampered = json.loads(json.dumps(plan))
        tampered["planner_options"]["step_xy"] = 2.0
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "参数指纹" in str(error)
        else:
            raise AssertionError("未拒绝参数指纹篡改")
        tampered = json.loads(json.dumps(plan))
        tampered["objective"] = "fuel"
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "目标口径" in str(error)
        else:
            raise AssertionError("未拒绝非法目标口径")

    check_("registry", registry)
    check_("fixed-y", fixed_identity)
    check_("naive", naive_distinct)
    check_("caw", caw_success)
    check_("options", option_rejection)
    check_("failure", failure_contract)
    check_("variants", caw_variants)
    check_("subset", subset_sequence)
    check_("safety", v12_safety)
    return 1 if failed else 0
