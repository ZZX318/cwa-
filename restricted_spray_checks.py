"""No-spray planning, timed switching and spatial coverage regressions."""

import copy
import json
import math
import tempfile
from pathlib import Path

from evaluation import at, build as evaluate
from execution import build, state_at
from planning import check, generate_plan, load_plan, save_plan
from planning.footprint import boxes_touch, rectangle
from planning.safety import intersects
from planner_api import make_planner
from scene import generate


def _zone(vertices):
    return dict(
        id="restricted", kind="polygon_prism",
        footprint=dict(kind="polygon", vertices=vertices), z_min=0.0, z_max=8.0,
    )


def run():
    scene = generate({"rows": 2, "trees_per_row": 3})
    scene["no_spray_zones"] = [
        _zone([[1.8, 6.2], [3.2, 6.2], [3.2, 6.8], [1.8, 6.8]])
    ]
    plan = generate_plan(scene)
    assert plan["status"] == "success", plan.get("reason")
    check(scene, plan)
    timeline = build(scene, plan)
    for segment in plan["segments"]:
        if segment["spray"]:
            assert not boxes_touch(rectangle(segment, 2), ([1.8, 6.2], [3.2, 6.8]))
    crossing = [
        s for s in timeline["segments"]
        if not s["spray"] and intersects(s["start"], s["end"], [1.8, 6.2, 0], [3.2, 6.8, 8])
    ]
    assert crossing, "no-spray area should permit a closed-nozzle transit"
    for segment in crossing:
        assert not state_at(timeline, (segment["t_start"] + segment["t_end"]) / 2)["spray"]
    kinds = [s["spray"] for s in timeline["segments"]]
    assert any(kinds[i:i + 3] == [True, False, True] for i in range(len(kinds) - 2))
    metrics_by_resolution = []
    for resolution in (.25, .125):
        evaluation = evaluate(scene, plan, timeline, resolution)
        metrics = at(evaluation, timeline, timeline["duration"])
        assert 0 < metrics["coverage"] < 1
        assert metrics["restricted_canopy_area_m2"] > 0
        assert metrics["extra_miss_area_m2"] > 0
        assert not metrics["illegal"]
        assert math.isclose(
            metrics["canopy_union_area_m2"],
            metrics["restricted_canopy_area_m2"] + metrics["sprayable_canopy_area_m2"],
        )
        assert math.isclose(
            metrics["sprayable_canopy_area_m2"],
            metrics["covered_sprayable_area_m2"] + metrics["extra_miss_area_m2"],
        )
        initial = at(evaluation, timeline, 0)
        assert initial["covered_sprayable_area_m2"] == 0
        assert initial["extra_miss_area_m2"] == metrics["sprayable_canopy_area_m2"]
        metrics_by_resolution.append(metrics)
    assert abs(metrics_by_resolution[0]["extra_miss_area_m2"] - metrics_by_resolution[1]["extra_miss_area_m2"]) < .5
    print("通过 · 禁喷切段、关喷飞越、恢复喷洒、面积守恒与栅格复算")

    # Repeated projections must not double count the new spatial area metrics.
    repeated = copy.deepcopy(scene)
    extra_tree = copy.deepcopy(repeated["trees"][0])
    extra_tree["id"] = "duplicate-tree"
    repeated["trees"].append(extra_tree)
    extra = copy.deepcopy(repeated["targets"][0])
    extra["id"] = "duplicate-projection"
    extra["tree_id"] = extra_tree["id"]
    repeated["targets"].append(extra)
    repeated_plan = generate_plan(repeated)
    assert repeated_plan["status"] == "success", repeated_plan.get("reason")
    repeated_timeline = build(repeated, repeated_plan)
    repeated_metrics = at(evaluate(repeated, repeated_plan, repeated_timeline, .25), repeated_timeline, repeated_timeline["duration"])
    assert repeated_metrics["canopy_union_area_m2"] == metrics_by_resolution[0]["canopy_union_area_m2"]
    print("通过 · 重叠目标的空间面积去重")

    # A changed execution footprint is detected independently of the valid plan.
    evaluation = evaluate(scene, plan, timeline)
    tampered = copy.deepcopy(timeline)
    segment = next(s for s in tampered["segments"] if not s["spray"] and s["type"] == "transit"
        and intersects(s["start"], s["end"], [1.8, 6.2, 0], [3.2, 6.8, 8]))
    segment["spray"] = True
    assert at(evaluation, tampered, tampered["duration"])["illegal"]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "restricted.plan.json"
        save_plan(scene, plan, path)
        assert load_plan(scene, path) == plan
    print("通过 · 独立执行侵入检查与计划保存加载")

    # Fully excluded targets may be omitted, but other targets remain mandatory.
    excluded = copy.deepcopy(scene)
    excluded["no_spray_zones"] = [_zone([[.5, .5], [4.5, .5], [4.5, 12.5], [.5, 12.5]])]
    excluded_plan = generate_plan(excluded)
    assert excluded_plan["status"] == "success", excluded_plan.get("reason")
    associated = {tid for s in excluded_plan["segments"] for tid in s["target_ids"]}
    assert all(t["id"] not in associated for t in excluded["targets"][:3])
    missing = copy.deepcopy(plan)
    victim = scene["targets"][-1]["id"]
    for segment in missing["segments"]:
        segment["target_ids"] = [tid for tid in segment["target_ids"] if tid != victim]
        if segment["spray"] and not segment["target_ids"]:
            segment.update(type="transit", spray=False)
    try:
        check(scene, missing)
    except ValueError as error:
        assert "缺少有效喷洒关联" in str(error), str(error)
    else:
        raise AssertionError("missing unrestricted target was accepted")
    sealed = copy.deepcopy(scene)
    sealed["no_spray_zones"] = [_zone(copy.deepcopy(scene["plot"]["vertices"]))]
    rejected = generate_plan(sealed)
    assert rejected["status"] == "failed" and not rejected["segments"]
    assert "没有可执行喷洒段" in rejected["reason"]
    print("通过 · 完全受限目标、漏任务拒绝与全部禁喷提示")

    for name in ("caw-a*-fixed-order", "caw-a*-nn", "caw-a*-3d-wind"):
        candidate = make_planner(name).plan(scene, {})
        assert candidate["status"] == "success", (name, candidate.get("reason"))
        check(scene, candidate)
    json.dumps(metrics_by_resolution, allow_nan=False)
    print("通过 · 三个 CAW 变体共用禁喷裁切")
    return 0
