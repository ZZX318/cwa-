"""Behavioral acceptance checks for the geometric plan, not deposition coverage."""

import copy
import tempfile
from pathlib import Path
from scene import generate
from planning import generate_plan, check, save_plan, load_plan


def run() -> int:
    try:
        scene = generate()
        import json
        from planning import fingerprint

        integer_roundtrip = json.loads(
            json.dumps(scene),
            parse_float=lambda v: int(float(v)) if float(v).is_integer() else float(v),
        )
        assert fingerprint(scene) == fingerprint(integer_roundtrip)
        p = generate_plan(scene)
        assert p["status"] == "success", p["reason"]
        check(scene, p)
        assert all(s["spray"] == (s["type"] == "spray") for s in p["segments"])
        assert generate_plan(scene, {"swath": 1})["strip_count"] > p["strip_count"]
        reordered = copy.deepcopy(scene)
        reordered["trees"].reverse()
        reordered["targets"].reverse()
        assert generate_plan(reordered)["segments"] == p["segments"]
        changed = copy.deepcopy(scene)
        changed["trees"][0]["canopy"]["z_max"] += 1
        assert generate_plan(changed)["work_height"] == p["work_height"] + 1
        moved = copy.deepcopy(scene)
        moved["targets"][0]["geometry"]["center"][0] += 0.6
        assert generate_plan(moved)["segments"] != p["segments"]
        blocked = copy.deepcopy(scene)
        blocked["obstacles"] = [
            dict(id="block", kind="box", min=[-4, 11, 2], max=[-2, 14, 3])
        ]
        assert generate_plan(blocked)["status"] == "failed"
        forbidden = copy.deepcopy(scene)
        forbidden["no_spray_zones"] = [
            dict(
                id="zone",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon", vertices=[[1.1, 2], [1.3, 2], [1.3, 3], [1.1, 3]]
                ),
                z_min=0,
                z_max=1,
            )
        ]
        forbidden_plan = generate_plan(forbidden)
        assert forbidden_plan["status"] == "success", forbidden_plan.get("reason")
        check(forbidden, forbidden_plan)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.json"
            save_plan(scene, p, path)
            assert load_plan(scene, path) == p
            try:
                load_plan(moved, path)
            except ValueError:
                pass
            else:
                raise AssertionError("未拒绝场景不匹配")
        tampered = copy.deepcopy(p)
        tampered["segments"][1]["start"][0] += 1
        try:
            check(scene, tampered)
        except ValueError:
            pass
        else:
            raise AssertionError("未拒绝不连续计划")

        def rejected(candidate, expected):
            try:
                check(scene, candidate)
            except ValueError as error:
                assert expected in str(error), str(error)
            else:
                raise AssertionError("错误计划被接受：" + expected)

        empty_job = copy.deepcopy(p)
        for segment in empty_job["segments"]:
            if segment["spray"]:
                segment.update(type="transit", spray=False, target_ids=[])
        rejected(empty_job, "没有喷洒航段")

        missing_job = copy.deepcopy(p)
        removed_id = scene["targets"][0]["id"]
        for segment in missing_job["segments"]:
            segment["target_ids"] = [
                v for v in segment["target_ids"] if v != removed_id
            ]
            if segment["spray"] and not segment["target_ids"]:
                segment.update(type="transit", spray=False)
        rejected(missing_job, "缺少有效喷洒关联")

        false_association = copy.deepcopy(p)
        first_spray = next(s for s in false_association["segments"] if s["spray"])
        first_spray["target_ids"].append(scene["targets"][-1]["id"])
        rejected(false_association, "正面积相交")

        from planning.footprint import rectangle, overlaps_target, boxes_touch

        footprint = rectangle(dict(start=[0, 0, 5], end=[0, 10, 5]), 2)
        assert footprint == ([-1.0, 0], [1.0, 10])
        assert overlaps_target(footprint, dict(center=[1.5, 5], radius=1))
        assert not overlaps_target(footprint, dict(center=[2, 5], radius=1))
        assert not boxes_touch(footprint, ([-0.5, 10.1], [0.5, 10.2]))
        assert boxes_touch(footprint, ([0.9, 5], [1.2, 6]))
        print("通过 · 任务结构回归：全关喷、漏目标、伪关联、矩形足迹端部/切触")
        print(
            "通过 · 第二阶段：连续往返、喷幅、高度、独立目标、重排、阻挡、禁喷、文件匹配与篡改检查"
        )

        orchard = generate({"rows": 4, "trees_per_row": 5})
        orchard["no_fly_zones"] = [
            dict(
                id="no-fly-01",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[[0.5, 12.5], [10.5, 12.5], [10.5, 20.5], [0.5, 20.5]],
                ),
                z_min=0.0,
                z_max=8.0,
            )
        ]
        from scene import validate_scene

        validate_scene(orchard)
        from planner_api import make_planner
        assert generate_plan(orchard)["status"] == "failed"
        detour = make_planner("caw-a*-fixed-order").plan(orchard)
        assert detour["status"] == "success", detour.get("reason")
        check(orchard, detour)
        inside, outside = [], []
        for target in orchard["targets"]:
            cx, cy = target["geometry"]["center"]
            if 0.5 <= cx <= 10.5 and 12.5 <= cy <= 20.5:
                inside.append(target["id"])
            else:
                outside.append(target["id"])
        associated = {tid for seg in detour["segments"] for tid in seg["target_ids"]}
        assert inside, "test setup: expected trees inside no-fly"
        assert not (set(inside) & associated), (inside, associated)
        assert set(outside) <= associated, set(outside) - associated
        from planner_api import make_planner

        caw = make_planner("caw").plan(orchard)
        assert caw["status"] == "success", caw.get("reason")
        print("通过 · 果园内禁飞：切断喷洒带并绕行，区内目标不喷")

        # Aircraft clearance alone is insufficient: both neighbouring spray
        # strips used to enter this narrow region while their centrelines cleared it.
        fringe = copy.deepcopy(scene)
        fringe["no_fly_zones"] = [
            dict(
                id="no-fly-fringe", kind="polygon_prism",
                footprint=dict(kind="polygon", vertices=[[2.9, 6], [3.1, 6], [3.1, 7], [2.9, 7]]),
                z_min=0.0, z_max=8.0,
            )
        ]
        fringe_plan = make_planner("caw-a*-fixed-order").plan(fringe)
        assert fringe_plan["status"] == "success", fringe_plan.get("reason")
        check(fringe, fringe_plan)
        for segment in fringe_plan["segments"]:
            if segment["spray"]:
                assert not boxes_touch(rectangle(segment, 2), ([2.9, 6], [3.1, 7]))
        unsafe = copy.deepcopy(p)
        unsafe["scene_hash"] = fingerprint(fringe)
        try:
            check(fringe, unsafe)
        except ValueError as error:
            assert "喷洒足迹" in str(error), str(error)
        else:
            raise AssertionError("检查器未检出喷幅边缘侵入禁飞区")

        # A zone above the aircraft still prohibits spraying its XY footprint.
        overhead = copy.deepcopy(fringe)
        overhead["no_fly_zones"][0].update(z_min=8.0, z_max=10.0)
        overhead_plan = make_planner("caw-a*-fixed-order").plan(overhead)
        assert overhead_plan["status"] == "success", overhead_plan.get("reason")
        check(overhead, overhead_plan)
        from execution import build
        from evaluation import build as evaluate, at
        timeline = build(overhead, overhead_plan)
        metrics = at(evaluate(overhead, overhead_plan, timeline, .25), timeline, timeline["duration"])
        assert 0 < metrics["coverage"] < 1
        assert all(not s["spray"] for s in timeline["segments"] if s["type"] != "spray")

        sealed = copy.deepcopy(scene)
        sealed["no_fly_zones"] = [
            dict(
                id="no-fly-all", kind="polygon_prism",
                footprint=copy.deepcopy(scene["plot"]), z_min=8.0, z_max=10.0,
            )
        ]
        sealed_plan = make_planner("caw-a*-fixed-order").plan(sealed)
        assert sealed_plan["status"] == "failed"
        assert "没有喷洒航段" in sealed_plan["reason"]
        assert sealed_plan["segments"] == []
        print("通过 · 禁飞喷幅边缘、上方区域、独立拒绝侵入、执行评价与全部受限提示")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("失败 · 第二阶段：", e)
        return 1
