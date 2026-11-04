"""Random-map regressions: reproducibility, styles, validation and compatibility."""

import tempfile
from pathlib import Path

from scene import decode, encode, generate, load, save
from scene.random_map import GENERATOR_VERSION, build
from scene.schema import SceneError
from scene.shapes import rectangle_overlaps_polygon
from scene.validation import report
from random_scene import generate_with_report


STYLES = (
    "regular",
    "jitter_rows",
    "clusters_gaps",
    "size_mix",
    "random_obstacles_zones",
)


def run() -> int:
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · 随机地图 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · 随机地图 · " + name + "：" + str(error))

    def reject(f, label):
        try:
            f()
        except (SceneError, ValueError):
            return
        raise AssertionError(label + "：未拒绝非法输入")

    def styles_valid():
        for style in STYLES:
            scene, result = build(style, 11)
            assert scene["trees"]
            assert len(scene["targets"]) == len(scene["trees"])
            assert result["style"] == style
            assert result["generator_version"] == GENERATOR_VERSION
            assert report(scene)["ok"] is True
            ids = [
                obj["id"]
                for key in (
                    "trees",
                    "targets",
                    "launch_points",
                    "obstacles",
                    "no_fly_zones",
                    "no_spray_zones",
                )
                for obj in scene[key]
            ]
            assert len(ids) == len(set(ids))

    check("五种样式均生成合法场景且目标一对一", styles_valid)

    def reproducible():
        for style in STYLES:
            first = encode(build(style, 12345)[0])
            second = encode(build(style, 12345)[0])
            assert first == second, style

    check("同 style/seed/params 编码逐字节一致", reproducible)

    def seed_effect():
        regular_a = build("regular", 1, {"rows": 3, "trees_per_row": 4})[0]
        regular_b = build("regular", 2, {"rows": 3, "trees_per_row": 4})[0]
        assert regular_a["trees"] == regular_b["trees"]
        for style in STYLES[1:]:
            assert encode(build(style, 1)[0]) != encode(build(style, 2)[0]), style

    check("规则样式 seed 不参与几何、其余样式不同 seed 不同", seed_effect)

    def metadata():
        scene, result = build("jitter_rows", 99)
        source = scene["source"]
        assert source["kind"] == "random_orchard"
        assert source["generator_version"] == GENERATOR_VERSION
        assert source["style"] == "jitter_rows"
        assert source["seed"] == 99
        assert source["parameters"] == result["parameters"]

    check("source 与 report 记录样式、seed、版本和参数", metadata)

    def invalid_params():
        cases = [
            ("unknown", {}),
            ("jitter_rows", {"jitter_xy": 5}),
            ("jitter_rows", {"rows": 2.5}),
            ("clusters_gaps", {"trees_per_cluster_range": [9, 2]}),
            ("clusters_gaps", {"missing_prob": 1.5}),
            ("size_mix", {"classes": [{"name": "a", "p": 1, "radius": [1, 2], "height": [1, 2]}]}),
            ("size_mix", {"classes": [
                {"name": "a", "p": 0.5, "radius": [1, 2], "height": [1, 2]},
                {"name": "b", "p": 0.2, "radius": [1, 2], "height": [1, 2]},
            ]}),
            ("random_obstacles_zones", {"allow_inside_plot": "yes"}),
            ("random_obstacles_zones", {"obstacle_count": -1}),
            ("random_obstacles_zones", {"base_style": "random_obstacles_zones"}),
            ("random_obstacles_zones", {"unknown": 1}),
        ]
        for style, params in cases:
            reject(lambda s=style, p=params: build(s, 0, p), f"{style} {params}")
        reject(lambda: build("regular", True), "bool seed")
        reject(lambda: build("regular", 1.5), "float seed")

    check("未知样式、非法参数与非整数 seed 被拒绝", invalid_params)

    def counts():
        scene, _ = build("clusters_gaps", 5, {"cluster_cols": 2, "cluster_rows": 1, "trees_per_cluster_range": [4, 4], "missing_prob": 0.0})
        assert len(scene["trees"]) == 8
        scene, result = build("size_mix", 5)
        assert sum(result["info"]["class_counts"].values()) == len(scene["trees"])
        scene, result = build("clusters_gaps", 5)
        assert result["info"]["actual_trees"] + result["info"]["missing_trees"] == result["info"]["requested_trees"]

    check("簇状缺株与尺寸混合的数量契约", counts)

    def decorations():
        for params in ({}, {"allow_inside_plot": True}):
            scene, result = build("random_obstacles_zones", 3, params)
            extent = scene["extent"]
            plot = scene["plot"]
            assert scene["obstacles"] and scene["no_fly_zones"] and scene["no_spray_zones"]
            for obstacle in scene["obstacles"]:
                assert all(
                    extent["min"][i] <= obstacle["min"][i] and obstacle["max"][i] <= extent["max"][i]
                    for i in range(3)
                )
                assert obstacle.get("preset")
            for key in ("no_fly_zones", "no_spray_zones"):
                for zone in scene[key]:
                    xs = [v[0] for v in zone["footprint"]["vertices"]]
                    ys = [v[1] for v in zone["footprint"]["vertices"]]
                    assert min(xs) >= extent["min"][0] and max(xs) <= extent["max"][0]
                    assert min(ys) >= extent["min"][1] and max(ys) <= extent["max"][1]
                    if not params.get("allow_inside_plot"):
                        assert not rectangle_overlaps_polygon(
                            [min(xs), min(ys)], [max(xs), max(ys)], plot
                        )
            for point in scene["launch_points"]:
                for zone in scene["no_fly_zones"] + scene["no_spray_zones"]:
                    xs = [v[0] for v in zone["footprint"]["vertices"]]
                    ys = [v[1] for v in zone["footprint"]["vertices"]]
                    assert not (
                        min(xs) <= point["position"][0] <= max(xs)
                        and min(ys) <= point["position"][1] <= max(ys)
                    )

    check("随机障碍/区域在范围内且不覆盖起降点", decorations)

    def reachability_failure():
        params = dict(
            no_spray_zones=[
                dict(
                    id="block",
                    kind="polygon_prism",
                    footprint=dict(
                        kind="polygon",
                        vertices=[[0, 0], [23, 0], [23, 25], [0, 25]],
                    ),
                    z_min=0,
                    z_max=11,
                )
            ]
        )
        try:
            generate_with_report(
                "regular", 1, params, require_reachable=True, max_attempts=2
            )
        except SceneError as error:
            assert "已尝试 2 次" in str(error)
            # 全地块禁喷时所有航带转为关喷头转场，任务结构以"没有喷洒航段"失败。
            assert "没有喷洒航段" in str(error)
            return
        raise AssertionError("阻塞配置未失败")

    check("require_reachable 阻塞配置明确失败并保留原因", reachability_failure)

    def save_load():
        scene, _ = build("random_obstacles_zones", 8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "random.scene.json"
            save(scene, path)
            loaded = load(path)
            assert encode(loaded) == encode(scene)
            assert loaded["source"] == scene["source"]

    check("随机场景保存加载逐字段一致且不重放生成器", save_load)

    def regular_golden():
        params = {"rows": 4, "trees_per_row": 6}
        random_regular = build("regular", 7, params)[0]
        generated = generate(params)
        assert random_regular["trees"] == generated["trees"]
        assert random_regular["targets"] == generated["targets"]
        assert random_regular["plot"] == generated["plot"]
        assert random_regular["extent"] == generated["extent"]

    check("regular 样式的树/目标/地块与 generate 一致", regular_golden)

    def fast_path():
        scene, _ = build("regular", 0, {"rows": 50, "trees_per_row": 50})
        fast = report(scene, mode="fast")
        full = report(scene, mode="full")
        assert fast["ok"] is True and full["ok"] is True
        assert fast["warnings_complete"] is False
        assert full["warnings_complete"] is True
        assert fast["summary"] == full["summary"]

    check("2500 棵树快速校验与完整校验结论一致", fast_path)

    def old_files():
        import json

        for path in sorted(Path("examples").glob("*.scene.json")):
            decode(path.read_text(encoding="utf8"))
        for name in ("default.json", "with_objects.json"):
            path = Path("configs") / name
            if path.exists():
                generate(json.loads(path.read_text(encoding="utf8")))

    check("旧场景与旧配置仍可加载/生成", old_files)

    print(f"\n随机地图检查完成：{passed} 通过 / {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
