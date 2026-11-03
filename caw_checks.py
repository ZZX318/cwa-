"""End-to-end CAW-A* chain: plan, safety, execution, evaluation, joint, replay."""

import copy
import json
import math
import tempfile
from pathlib import Path

from evaluation import at
from evaluation import build as eval_build
from execution import build
import joint
from joint import optimize
from planning import check, load_plan, save_plan
from planner_api import make_planner
from playback import joint_playback
from scene import generate

WALL = dict(
    rows=1,
    trees_per_row=3,
    obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
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

    def end_to_end():
        plan = make_planner("caw").plan(tiny, {})
        assert plan["status"] == "success", plan.get("reason")
        assert plan["version"] == "1.2"
        check(tiny, plan)
        timeline = build(tiny, plan)
        evaluation = eval_build(tiny, plan, timeline)
        metrics = at(evaluation, timeline, timeline["duration"])
        assert metrics["coverage"] == 1.0
        assert metrics["missed_cells"] == 0
        assert abs(plan["objective_value"] - timeline["duration"]) < 1e-12
        json.dumps(plan, allow_nan=False)

    def joint_exact():
        result = optimize(tiny, {}, 6, {"transition": "caw"})
        assert result["status"] == "success", result.get("reason")
        assert result["optimality_gap"] == 0.0
        assert result["expanded"] == result["orders_total"] == 720
        assert result["feasible_orders"] == 720
        assert result["transition"] == "caw"
        assert result["method"] == "exact-permutation+transition-caw"

    def wind_changes():
        calm = make_planner("caw").plan(tiny, {"swath": 5.0, "wind_speed": 0.0})
        windy = make_planner("caw").plan(
            tiny, {"swath": 5.0, "wind_speed": 2.0, "wind_direction": math.pi / 2}
        )
        assert calm["status"] == windy["status"] == "success"
        calm_timeline = build(tiny, calm)
        windy_timeline = build(tiny, windy)
        changed = (
            calm["config_hash"] != windy["config_hash"]
            and (
                abs(calm_timeline["duration"] - windy_timeline["duration"]) > 1e-6
                or calm["order"] != windy["order"]
            )
        )
        assert changed
        tampered = copy.deepcopy(calm)
        tampered["config"]["wind_speed"] = 2.0
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "配置指纹" in str(error)
        else:
            raise AssertionError("风场改变后旧计划未被拒绝")

    def v12_height_rule():
        plan = make_planner("caw").plan(tiny, {})
        home = plan["segments"][0]["start"]
        height = plan["work_height"]
        low = 0.1
        inserted = [
            dict(
                start=[home[0], home[1], height],
                end=[home[0], home[1], low],
                type="transit",
                spray=False,
                speed=plan["config"]["speed"],
                target_ids=[],
            ),
            dict(
                start=[home[0], home[1], low],
                end=[home[0], home[1], height],
                type="transit",
                spray=False,
                speed=plan["config"]["speed"],
                target_ids=[],
            ),
        ]
        tampered = copy.deepcopy(plan)
        tampered["segments"] = tampered["segments"][:1] + inserted + tampered["segments"][1:]
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "转场高度" in str(error), str(error)
        else:
            raise AssertionError("未拒绝低于净空的转场")

    def tamper_options():
        plan = make_planner("caw").plan(tiny, {})
        tampered = copy.deepcopy(plan)
        tampered["planner_options"]["step_xy"] = 2.0
        try:
            check(tiny, tampered)
        except ValueError as error:
            assert "参数指纹" in str(error)
        else:
            raise AssertionError("未拒绝规划器参数篡改")

    def persistence():
        plan = make_planner("caw").plan(tiny, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caw.plan.json"
            save_plan(tiny, plan, path)
            assert load_plan(tiny, path) == plan
            try:
                load_plan(generate(dict(rows=1, trees_per_row=2)), path)
            except ValueError:
                pass
            else:
                raise AssertionError("未拒绝场景不匹配")
        legacy = Path("examples/default.plan.json")
        if legacy.exists():
            old = load_plan(generate(), legacy)
            assert old["version"] == "1.0"
            build(generate(), old)

    def wall_joint_playback():
        wall = generate(WALL)
        result = optimize(wall, {"swath": 5.0}, 8, {"transition": "caw"})
        assert result["status"] == "success", result.get("reason")
        assert result["baseline"]["status"] == "failed"
        payload = joint_playback(
            wall,
            {"swath": 5.0},
            result["order"],
            {"transition": "caw", "step_xy": 1.0, "objective": "time"},
        )
        assert payload["status"] == "success", payload.get("reason")
        assert [track["label"] for track in payload["tracks"]] == ["最优"]
        assert payload["tracks"][0]["duration"] > 0

    def caw_verify():
        wall = generate(WALL)
        result = optimize(wall, {"swath": 5.0}, 8, {"transition": "caw"})
        assert joint.verify(result, wall, {"swath": 5.0})
        tampered = json.loads(json.dumps(result))
        tampered["total_time"] += 1.0
        try:
            joint.verify(tampered, wall, {"swath": 5.0})
        except ValueError as error:
            assert "复核不一致" in str(error), str(error)
        else:
            raise AssertionError("未拒绝被篡改的 caw 总时间")
        tampered = json.loads(json.dumps(result))
        tampered["planner_options"]["step_xy"] = 2.0
        try:
            joint.verify(tampered, wall, {"swath": 5.0})
        except ValueError as error:
            assert "参数指纹" in str(error), str(error)
        else:
            raise AssertionError("未拒绝被篡改的 caw 规划器参数")

    def wall_plan_heights():
        wall = generate(WALL)
        fixed = make_planner("fixed-y").plan(wall, {})
        caw = make_planner("caw").plan(wall, {})
        assert fixed["status"] == "failed" and fixed["stage"] == "safety"
        assert caw["status"] == "success"
        transit = [s for s in caw["segments"] if s["type"] == "transit"]
        assert max(max(s["start"][2], s["end"][2]) for s in transit) > caw["work_height"] + 1.0
        assert all(
            s["start"][2] >= 0.5 and s["end"][2] >= 0.5
            for s in transit
        )

    check_("end-to-end", end_to_end)
    check_("joint-exact", joint_exact)
    check_("wind", wind_changes)
    check_("height", v12_height_rule)
    check_("options", tamper_options)
    check_("persistence", persistence)
    check_("wall-joint", wall_joint_playback)
    check_("caw-verify", caw_verify)
    check_("wall-plan", wall_plan_heights)
    return 1 if failed else 0
