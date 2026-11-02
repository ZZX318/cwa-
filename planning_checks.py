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
        assert generate_plan(forbidden)["status"] == "failed"
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
        return 0
    except Exception as e:
        print("失败 · 第二阶段：", e)
        return 1
