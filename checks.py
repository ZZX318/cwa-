"""Small behavioral checks; UI uses exactly these generation and storage functions."""

import json
import tempfile
from pathlib import Path
from scene import generate, validate_scene, summary, save, load, decode, SceneError


def run() -> int:
    """Run independent numeric and file-integrity checks; return nonzero on failure."""
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · " + name)
        except Exception as e:
            failed += 1
            print("失败 · " + name + "：" + str(e))

    def expect_invalid(f):
        try:
            f()
        except (SceneError, ValueError):
            return
        raise AssertionError("未拒绝非法输入")

    def default():
        s = generate()
        assert len(s["trees"]) == 24 and len(s["targets"]) == 24
        assert s["trees"][0]["position"] == [2.5, 2.5, 0]
        assert s["trees"][-1]["position"] == [20.5, 22.5, 0]
        assert s["plot"]["vertices"][2] == [23, 25] and s["launch_points"][0][
            "position"
        ] == [-3, 12.5, 0]

    check("默认 4×6、坐标与地块几何", default)

    def changed():
        c = dict(
            rows=3,
            trees_per_row=8,
            row_spacing=8,
            plant_spacing=5,
            canopy_radius=2,
            canopy_height=3,
        )
        s = generate(c)
        assert len(s["trees"]) == 24 and s["trees"][-1]["position"] == [18.5, 37.5, 0]
        assert s["trees"][0]["canopy"]["z_max"] == 4.8
        assert s == generate(c)

    check("改行数、间距、冠层尺寸及确定性", changed)

    def roundtrip():
        s = generate(
            dict(
                obstacles=[
                    dict(id="shed", kind="box", min=[-5, -5, 0], max=[-4, -3, 2])
                ],
                no_spray_zones=[
                    dict(
                        id="water",
                        kind="polygon_prism",
                        footprint=dict(
                            kind="polygon", vertices=[[0, 0], [2, 0], [2, 3], [0, 3]]
                        ),
                        z_min=0,
                        z_max=5,
                    )
                ],
                no_fly_zones=[
                    dict(
                        id="restricted",
                        kind="polygon_prism",
                        footprint=dict(
                            kind="polygon",
                            vertices=[[25, 0], [27, 0], [27, 3], [25, 3]],
                        ),
                        z_min=0,
                        z_max=8,
                    )
                ],
            )
        )
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scene.json"
            save(s, p)
            assert load(p) == s
        assert summary(s)["obstacles"] == 1

    check("障碍、禁飞、禁喷保存加载逐字段一致", roundtrip)

    def invalid():
        for c in [
            dict(rows=0),
            dict(rows=True),
            dict(row_spacing=float("nan")),
            dict(plant_spacing=-1),
            dict(canopy_radius=0),
            dict(canopy_radius=3),
            dict(canopy_height=float("inf")),
        ]:
            expect_invalid(lambda: generate(c))
        expect_invalid(
            lambda: generate(
                dict(
                    obstacles=[
                        dict(id="blocked", kind="box", min=[-4, 11, 0], max=[-2, 14, 3])
                    ]
                )
            )
        )

    check("非法尺寸、数量、非有限值及起降点碰撞", invalid)

    def corrupt():
        for modify in [
            lambda s: s.update(format_version="999"),
            lambda s: s.pop("plot"),
            lambda s: s["trees"][1].update(id=s["trees"][0]["id"]),
            lambda s: s["targets"][0].update(tree_id="missing"),
            lambda s: s["trees"][0]["position"].__setitem__(0, 10),
            lambda s: s["trees"][0]["canopy"].update(radius=999),
        ]:
            s = generate()
            modify(s)
            expect_invalid(lambda: decode(json.dumps(s)))

    check("文件版本、必填、唯一 ID、引用与越界检查", corrupt)

    def overlap():
        s = generate(dict(row_spacing=2))
        assert validate_scene(s)

    check("树冠重叠允许并提供提醒", overlap)

    def size():
        for c in [
            dict(rows=1, trees_per_row=1),
            dict(rows=10, trees_per_row=20, plot_margin=4, canopy_radius=3, ground_z=7),
        ]:
            validate_scene(generate(c))

    check("小规模、大规模与非零地面高度", size)

    def independent():
        from scene.geometry import terrain_height, in_polygon

        s = generate()
        t = s["trees"][0]
        t["position"][0] += 0.3
        for k in ("trunk", "canopy"):
            t[k]["center"][0] += 0.3
        t["canopy"]["radius"] = 1.3
        s["targets"][0]["geometry"]["center"][0] += 0.3
        validate_scene(s)
        assert terrain_height(s, 5, 8) == 0
        s["trees"].reverse()
        validate_scene(s)
        assert decode(json.dumps(s)) == s
        assert in_polygon(
            [1, 1], dict(vertices=[[0, 0], [3, 0], [3, 2], [1, 3], [0, 2]])
        )
        s["plot"] = dict(
            kind="polygon", vertices=[[0, 0], [23, 0], [24, 12], [23, 25], [0, 25]]
        )
        validate_scene(s)
        s["no_fly_zones"] = [
            dict(
                id="blocked",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon", vertices=[[-4, 11], [-2, 11], [-2, 14], [-4, 14]]
                ),
                z_min=0,
                z_max=5,
            )
        ]
        expect_invalid(lambda: validate_scene(s))
        s = generate()
        s["plot"]["vertices"] = [[0, 0], [23, 25], [23, 0], [0, 25]]
        expect_invalid(lambda: validate_scene(s))

    check("独立树木、不规则多边形、平地查询与禁飞约束", independent)
    print(f"\n检查完成：{passed} 通过 / {failed} 失败")
    return 1 if failed else 0
