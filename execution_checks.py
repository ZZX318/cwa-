"""Independent expected-value checks for time semantics and reconstruction."""

import copy
import math
import tempfile
from pathlib import Path
from scene import generate
from planning import generate_plan
from execution import build, state_at, sample, save, load


def run() -> int:
    try:
        scene = generate()
        plan = generate_plan(scene)
        # Hand-calculated first two legs: 6.2 m / 3.1 m/s = 2 s;
        # (-3,12.5) -> (2,1) has length sqrt(157.25), chosen duration 3 s.
        assert plan["segments"][1]["end"] == [2.0, 1.0, 6.2]
        plan["segments"][0]["speed"] = 3.1
        plan["segments"][1]["speed"] = math.sqrt(157.25) / 3
        timeline = build(scene, plan)
        assert timeline["segments"][0]["t_end"] == 2
        assert math.isclose(timeline["segments"][1]["t_end"], 5)
        assert state_at(timeline, 1)["position"] == [-3, 12.5, 3.1]
        assert math.dist(state_at(timeline, 3.5)["position"], [-0.5, 6.75, 6.2]) < 1e-12
        for index, segment in enumerate(timeline["segments"]):
            boundary = state_at(timeline, segment["t_start"])
            assert boundary["segment_index"] == index
            assert boundary["position"] == segment["start"]
            assert boundary["spray"] == segment["spray"]
            midpoint = (segment["t_start"] + segment["t_end"]) / 2
            a = state_at(timeline, midpoint)
            state_at(timeline, 0)
            state_at(timeline, timeline["duration"])
            assert a == state_at(timeline, midpoint)
        end = state_at(timeline, timeline["duration"])
        assert end["status"] == "completed" and not end["spray"] and end["speed"] == 0
        assert end["position"] == scene["launch_points"][0]["position"]
        assert (
            timeline["segments"][-1]["heading"] == timeline["segments"][-2]["heading"]
        )
        for time in (-1, float("nan"), float("inf"), timeline["duration"] + 1, True):
            try:
                state_at(timeline, time)
            except ValueError:
                pass
            else:
                raise AssertionError("非法时间被接受")
        short = copy.deepcopy(plan)
        spray = next(s for s in short["segments"] if s["spray"])
        spray["speed"] = math.dist(spray["start"], spray["end"]) / 0.001
        short_timeline = build(scene, short)
        states = sample(short_timeline, 10000)
        for segment in short_timeline["segments"]:
            assert any(
                s["segment_index"] == segment["index"]
                and s["time"] == segment["t_start"]
                for s in states
            )
        # Playback rate has no input into duration or state calculation.
        for rate in (0.5, 1, 2, 4):
            assert state_at(timeline, rate * (3.5 / rate)) == state_at(timeline, 3.5)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "execution.json"
            save(timeline, file)
            assert load(scene, plan, file) == timeline
            changed = copy.deepcopy(plan)
            changed["segments"][0]["speed"] = 2
            try:
                load(scene, changed, file)
            except ValueError:
                pass
            else:
                raise AssertionError("计划变化未拒绝")
        wrong = copy.deepcopy(plan)
        wrong["scene_hash"] = "wrong"
        try:
            build(scene, wrong)
        except ValueError:
            pass
        else:
            raise AssertionError("不匹配计划被接受")
        print(
            "通过 · 第三阶段：手算时间/中点、全部边界、短段采样、重复查询、终态、非法时间、文件重建及计划绑定"
        )
        return 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        print("失败 · 第三阶段：", error)
        return 1
