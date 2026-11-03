"""Scene-editor backend regressions: shapes, presets, validation and launch L1."""

import copy
from pathlib import Path

from scene import decode, encode, generate, load, summary, validate_scene
from scene.launch import resolve
from scene.presets import PRESETS, make_box, preset_names
from scene.schema import SceneError
from scene.shapes import (
    footprint_problems,
    point_in_footprint,
    rectangle_footprint,
)
from scene.validation import report
from server import random_response, validate_response


def run() -> int:
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · 场景编辑器 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · 场景编辑器 · " + name + "：" + str(error))

    def reject(f, label):
        try:
            f()
        except (SceneError, ValueError):
            return
        raise AssertionError(label + "：未拒绝非法输入")

    def shapes():
        footprint = rectangle_footprint([10, 20], 4, 6)
        assert footprint["vertices"] == [
            [8.0, 17.0],
            [12.0, 17.0],
            [12.0, 23.0],
            [8.0, 23.0],
        ]
        assert point_in_footprint([10, 20], footprint)
        assert point_in_footprint([8, 17], footprint)
        assert not point_in_footprint([7.9, 20], footprint)
        assert footprint_problems(footprint) == []
        bowtie = dict(
            kind="polygon", vertices=[[0, 0], [2, 2], [2, 0], [0, 2]]
        )
        codes = {item["code"] for item in footprint_problems(bowtie)}
        assert "polygon/self_intersection" in codes
        extent = dict(min=[0, 0, 0], max=[30, 30, 10])
        outside = rectangle_footprint([25, 25], 20, 20)
        codes = {item["code"] for item in footprint_problems(outside, extent)}
        assert "polygon/out_of_bounds" in codes

    check("矩形足迹、点包含、自交与越界检查", shapes)

    def presets():
        assert preset_names() == ["container", "post", "shed", "wall"]
        for preset in preset_names():
            box = make_box(preset, [0, 0], 0, "obstacle-" + preset)
            assert box["kind"] == "box"
            assert box["preset"] == preset
            assert all(a < b for a, b in zip(box["min"], box["max"]))
            size = PRESETS[preset]["size"]
            assert abs((box["max"][0] - box["min"][0]) - size[0]) < 1e-9
        custom = make_box("shed", [4, 5], 2, "custom", size=[2, 3, 4])
        assert custom["min"][2] == 2 and custom["max"][2] == 6
        reject(lambda: make_box("missing", [0, 0], 0, "x"), "unknown preset")

    check("障碍预设库生成合法轴对齐 box", presets)

    def structured_report():
        scene = generate()
        good = report(scene)
        assert good["ok"] is True and good["summary"]["trees"] == 24
        bad = copy.deepcopy(scene)
        bad["obstacles"] = [
            dict(id="bad", kind="box", min=[1, 1, 0], max=[0, 2, 2])
        ]
        result = report(bad)
        assert result["ok"] is False
        assert result["errors"][0]["path"] == "bad"
        assert result["errors"][0]["code"] == "box/min_ge_max"
        fast = report(bad, mode="fast")
        assert fast["ok"] is False and fast["errors"][0]["code"] == "box/min_ge_max"
        assert result["summary"] is None

    check("结构化校验定位对象/字段且快速模式阻断一致", structured_report)

    def summary_reuse():
        scene = generate()
        assert summary(scene, validated=True, warnings=[]) == summary(scene)

    check("summary(validated=True) 与完整校验一致", summary_reuse)

    def launch_defaults():
        scene = generate()
        assert scene["launch_points"] == [
            dict(id="launch-1", position=[-3.0, 12.5, 0.0])
        ]
        assert "launch_assignments" not in scene
        resolved = resolve(scene)
        assert resolved["start_id"] == "launch-1"
        assert resolved["end_id"] == "launch-1"
        assert resolved["explicit"] is False
        multi = copy.deepcopy(scene)
        multi["launch_points"].append(dict(id="pad-b", position=[28, 12.5, 0]))
        resolved = resolve(multi)
        assert resolved["start_id"] == "launch-1"
        assert resolved["end_id"] == "launch-1"
        assert resolved["explicit"] is False
        assert validate_scene(multi) == []

    check("默认与多点无 role 均回退排序首个点、start=end", launch_defaults)

    def launch_roles():
        scene = generate()
        scene["launch_points"][0]["role"] = "start"
        scene["launch_points"].append(
            dict(id="pad-r", position=[28, 12.5, 0], role="return")
        )
        assert validate_scene(scene) == []
        resolved = resolve(scene)
        assert resolved["start_id"] == "launch-1"
        assert resolved["end_id"] == "pad-r"
        assert resolved["explicit"] is True
        missing_end = copy.deepcopy(scene)
        missing_end["launch_points"][1]["role"] = "start"
        reject(lambda: validate_scene(missing_end), "explicit roles missing end")

    check("显式 role 解析与缺一侧失败", launch_roles)

    def launch_assignments():
        scene = generate()
        scene["launch_points"][0]["role"] = "start"
        scene["launch_points"].append(
            dict(id="pad-r", position=[28, 12.5, 0], role="return")
        )
        scene["launch_assignments"] = [
            dict(uav=1, start="launch-1", end="pad-r")
        ]
        assert validate_scene(scene) == []
        assert resolve(scene, 1)["end_id"] == "pad-r"
        reject(lambda: resolve(scene, 2), "missing uav assignment")
        duplicate = copy.deepcopy(scene)
        duplicate["launch_assignments"].append(
            dict(uav=1, start="launch-1", end="pad-r")
        )
        reject(lambda: validate_scene(duplicate), "duplicate uav")
        missing = copy.deepcopy(scene)
        missing["launch_assignments"][0]["end"] = "missing"
        reject(lambda: validate_scene(missing), "missing point reference")
        wrong_role = copy.deepcopy(scene)
        wrong_role["launch_assignments"][0]["start"] = "pad-r"
        reject(lambda: validate_scene(wrong_role), "wrong start role")

    check("起降分配引用、唯一性与角色校验", launch_assignments)

    def launch_strict_modes():
        scene = generate()
        scene["no_spray_zones"] = [
            dict(
                id="sp",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[[-5, 11], [-1, 11], [-1, 14], [-5, 14]],
                ),
                z_min=0,
                z_max=5,
            )
        ]
        warnings = validate_scene(scene)
        assert any("禁喷区 sp" in item for item in warnings)
        strict = copy.deepcopy(scene)
        strict["launch_points"][0]["role"] = "both"
        reject(lambda: validate_scene(strict), "strict no-spray")
        no_fly = copy.deepcopy(scene)
        no_fly["no_spray_zones"] = []
        no_fly["no_fly_zones"] = [
            dict(
                id="nf",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[[-5, 11], [-1, 11], [-1, 14], [-5, 14]],
                ),
                z_min=5,
                z_max=10,
            )
        ]
        assert validate_scene(no_fly) == []
        consistent = copy.deepcopy(no_fly)
        consistent["launch_points"][0]["role"] = "both"
        reject(lambda: validate_scene(consistent), "strict no-fly XY")

    check("禁喷旧场景仅提醒、显式配置严格阻断（含禁飞 XY）", launch_strict_modes)

    def target_obstacle():
        scene = generate()
        scene["obstacles"] = [
            dict(id="tower", kind="box", min=[1, 1, 1.8], max=[4, 4, 4.2])
        ]
        result = report(scene)
        assert result["ok"] is True
        assert any("与目标" in item for item in result["warnings"])
        strict = copy.deepcopy(scene)
        strict["obstacles"][0]["preset"] = "shed"
        result = report(strict)
        assert result["ok"] is False
        assert result["errors"][0]["path"] == "tower"
        assert "目标" in result["errors"][0]["message"]
        # The editor sends {"strict": true}; /api/validate must treat it as strict.
        strict_response = validate_response(dict(scene=scene, mode="fast", strict=True))
        assert strict_response["ok"] is False
        assert strict_response["errors"][0]["path"] == "tower"

    check("障碍-目标重叠旧场景警告、显式配置阻断", target_obstacle)

    def api_responses():
        response = random_response(dict(style="jitter_rows", seed=3))
        assert response["scene"]["source"]["kind"] == "random_orchard"
        assert decode(response["serialized"]) == response["scene"]
        assert response["summary"]["trees"] >= 1
        assert response["config"] is None
        regular = random_response(dict(style="regular", seed=1))
        assert regular["config"]["rows"] == 4
        reject(lambda: random_response(dict(style="missing", seed=1)), "unknown style")
        reject(lambda: random_response(dict(style="regular", seed="1")), "string seed")
        valid = validate_response(dict(scene=generate()))
        assert valid["ok"] is True
        invalid = copy.deepcopy(generate())
        invalid["launch_points"] = []
        result = validate_response(dict(scene=invalid))
        assert result["ok"] is False
        assert result["errors"][0]["path"] == "launch_points"
        reject(lambda: validate_response(dict(mode="fast")), "missing scene")
        reject(
            lambda: validate_response(dict(scene=generate(), mode="slow")),
            "bad mode",
        )

    check("/api/random 与 /api/validate 纯响应结构", api_responses)

    def golden():
        text = Path("examples/default.scene.json").read_text(encoding="utf8")
        assert encode(generate()) == text
        assert decode(text) == generate()
        for path in sorted(Path("examples").glob("*.scene.json")):
            load(path)
        assert summary(generate()) == summary(decode(text))

    check("generate() 黄金输出与旧示例兼容", golden)

    def large_fast():
        scene = generate(dict(rows=50, trees_per_row=50))
        fast = report(scene, mode="fast")
        assert fast["ok"] is True
        assert fast["warnings_complete"] is False
        assert fast["summary"]["trees"] == 2500

    check("2500 棵树快速路径可用且不改变阻断结论", large_fast)

    print(f"\n场景编辑器检查完成：{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
