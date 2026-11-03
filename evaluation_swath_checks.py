"""M0 evaluator regression: the footprint width is the job swath, not resolution."""

from evaluation import at
from evaluation import build as eval_build
from execution import build
from planning import generate_plan
from scene import generate


def _timeline():
    return dict(
        duration=1.0,
        segments=[
            dict(
                start=[0.0, 0.0, 5.0],
                end=[0.0, 1.0, 5.0],
                type="spray",
                spray=True,
                speed=2.0,
                target_ids=["t"],
                t_start=0.0,
                t_end=1.0,
                length=1.0,
                duration=1.0,
            )
        ],
    )


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

    def default_full():
        scene = generate()
        plan = generate_plan(scene)
        timeline = build(scene, plan)
        for resolution in (0.25, 0.5, 1.0):
            evaluation = eval_build(scene, plan, timeline, resolution)
            metrics = at(evaluation, timeline, timeline["duration"])
            assert metrics["coverage"] == 1.0, (resolution, metrics["coverage"])
            assert metrics["covered_cells"] == metrics["total_cells"]
            assert metrics["missed_cells"] == 0
            assert evaluation["config"]["swath"] == 2.0
        assert abs(metrics["coverage"] - 0.546875) > 1e-9
        print("通过 · 默认 fixed-Y 在 swath=2.0 下覆盖全部网格（0.25/0.5/1.0 m 分辨率）")

    def resolution_independent():
        scene = generate()
        plan = generate_plan(scene)
        timeline = build(scene, plan)
        values = []
        for resolution in (0.25, 0.5, 1.0):
            evaluation = eval_build(scene, plan, timeline, resolution)
            values.append(at(evaluation, timeline, timeline["duration"])["coverage"])
        assert values == [1.0, 1.0, 1.0], values
        print("通过 · 覆盖率不随评价分辨率变化（旧缺陷会把 resolution 当喷幅）")

    def config_swath_drives():
        cells = [("t", 0, 0)]
        timeline = _timeline()
        wide = at(
            dict(duration=1.0, resolution=1.0, config=dict(swath=2.0, flow_rate=1.0), cells=cells),
            timeline,
            1.0,
        )
        narrow = at(
            dict(duration=1.0, resolution=1.0, config=dict(swath=0.5, flow_rate=1.0), cells=cells),
            timeline,
            1.0,
        )
        assert wide["coverage"] == 1.0, wide["coverage"]
        assert narrow["coverage"] == 0.0, narrow["coverage"]
        print("通过 · 评价器足迹宽度取 config['swath']（2.0 覆盖 / 0.5 不覆盖同一单元）")

    def changed_spray_changes_coverage():
        scene = generate()
        plan = generate_plan(scene)
        timeline = build(scene, plan)
        trimmed = dict(timeline)
        trimmed["segments"] = [
            segment for index, segment in enumerate(timeline["segments"]) if index < len(timeline["segments"]) - 8
        ]
        partial = at(
            eval_build(scene, plan, timeline, 0.5), trimmed, timeline["duration"]
        )
        assert partial["coverage"] < 1.0
        print("通过 · 减少喷洒航段后覆盖率下降（评价仍响应实际喷雾）")

    def partial_spray():
        scene = generate()
        plan = generate_plan(scene)
        timeline = build(scene, plan)
        evaluation = eval_build(scene, plan, timeline, 0.5)
        spray = next(segment for segment in timeline["segments"] if segment["spray"])
        early = at(evaluation, timeline, spray["t_start"] + 1e-6)
        middle = at(evaluation, timeline, spray["t_start"] + spray["duration"] / 2)
        assert early["coverage"] == 0.0
        assert 0.0 < middle["coverage"] < 1.0
        assert middle["spray_seconds"] < spray["duration"]
        print("通过 · 部分喷洒时刻只评价已飞行足迹（不提前计入整段）")

    check("default", default_full)
    check("partial", partial_spray)
    check("resolution", resolution_independent)
    check("swath", config_swath_drives)
    check("spray", changed_spray_changes_coverage)
    return 1 if failed else 0
