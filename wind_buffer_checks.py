"""Wind direction, recomputation, phase benefit and protection regressions."""
import copy
import math
from scene import generate, encode, decode
from wind_buffer import apply_buffer
from planning import generate_plan, check
from execution import build
from evaluation import build as evaluate, at


def example():
    scene = generate(dict(rows=4, trees_per_row=5))
    source = dict(id="sensitive-east", kind="polygon_prism", footprint=dict(kind="polygon",
        vertices=[[23,0],[24,0],[24,22],[23,22]]), z_min=0, z_max=8)
    return scene, source


def run():
    base, source = example()
    west = apply_buffer(base, [source], 3.5, 2, math.pi)["scene"]
    assert base["no_spray_zones"] == []
    assert west["no_spray_zones"][0]["footprint"]["vertices"][0] == [19.5, 0]
    assert apply_buffer(west, [source], 3.5, 2, math.pi)["scene"] == west
    east = apply_buffer(west, [source], 3.5, 2, 0)["scene"]
    assert east["no_spray_zones"][0]["footprint"]["vertices"][1] == [27.5, 0]
    still = apply_buffer(west, [source], 3.5, 0, 0)["scene"]
    assert still["no_spray_zones"][0]["footprint"] == source["footprint"]
    diagonal = apply_buffer(base, [source], 1, 2, math.pi/4)["scene"]
    assert diagonal["no_spray_zones"][0]["footprint"]["vertices"][2][1] > 22
    assert decode(encode(west)) == west
    manual = copy.deepcopy(base)
    zone = copy.deepcopy(source); zone["id"] = "manual"
    manual["no_spray_zones"] = [zone]
    assert apply_buffer(manual, [source], 3.5, 2, math.pi)["scene"]["no_spray_zones"][0] == zone
    edited = copy.deepcopy(west); edited["no_spray_zones"][0]["z_max"] = 9
    for scene, distance in ((edited,3.5),(base,-1),(base,float("nan")),(base,100)):
        try: apply_buffer(scene,[source],distance,2,math.pi)
        except ValueError: pass
        else: raise AssertionError("invalid or overwritten input accepted")
    metrics = []
    for phase in (0,.49):
        plan = generate_plan(west,dict(wind_speed=2,wind_direction=math.pi,lane_phase=phase,transition_mode="auto"))
        assert plan["status"] == "success", plan
        check(west,plan)
        timeline = build(west,plan)
        values = []
        for resolution in (.25,.1,.05):
            m = at(evaluate(west,plan,timeline,resolution),timeline,timeline["duration"])
            assert not m["illegal"]
            assert m["restricted_canopy_area_m2"] > 0
            values.append(m)
        metrics.append(values)
    for before, after in zip(*metrics):
        assert before["restricted_canopy_area_m2"] == after["restricted_canopy_area_m2"]
        assert before["extra_miss_area_m2"] > after["extra_miss_area_m2"]
    assert abs(metrics[0][-1]["extra_miss_area_m2"] - metrics[0][-2]["extra_miss_area_m2"]) < .2
    stale = generate_plan(west,dict(wind_speed=1,wind_direction=math.pi))
    assert stale["status"] == "failed" and "风参数" in stale["reason"]
    from coverage_recovery import recover
    result = recover(west,dict(wind_speed=2,wind_direction=math.pi),.1)
    assert result["improved"] and abs(result["recommended"]["phase"]-.49)<1e-6
    assert result["recommended"]["extra_miss"] < result["baseline"]["extra_miss"]
    assert result["recommended"]["restricted_area"] == result["baseline"]["restricted_area"]
    assert result["recommended"]["illegal_count"] == 0
    full=copy.deepcopy(base)
    zone=copy.deepcopy(source);zone["footprint"]=copy.deepcopy(base["plot"])
    full["no_spray_zones"]=[zone]
    denied=recover(full,{},.25)
    assert not denied["improved"] and "没有合法喷洒面积" in denied["message"]
    print("通过 · 敏感区上风扩展、静风/反向/斜风、重复应用、手工区域保护、保存重载、相位覆盖与网格对照")
    return 0
