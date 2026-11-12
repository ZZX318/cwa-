"""Straight baseline versus the CAW 3D main method."""
import copy
from scene import generate
from planning import generate_plan, check
from planner_api import make_planner
from execution import build
from evaluation import build as evaluate, at
from planning.safety import intersects, obstacle_expanded_boxes


def run():
    scene = generate(dict(rows=4, trees_per_row=5))
    plain = generate_plan(scene)
    assert plain["status"] == "success"
    blocked = copy.deepcopy(scene)
    blocked["obstacles"] = [dict(id="floating-box",kind="box",min=[1.8,5.8,5.7],max=[2.2,7.2,6.7])]
    for mode in ("fixed", "auto"):
        baseline = generate_plan(blocked,dict(transition_mode=mode))
        assert baseline["status"] == "failed" and not baseline["segments"]
        assert "冲突" in baseline["reason"]
    for method in ("caw-a*-fixed-order","caw-a*-nn","caw-a*-3d-wind"):
        plan = make_planner(method).plan(blocked)
        assert plan["status"] == "success", plan
        check(blocked,plan)
        boxes = obstacle_expanded_boxes(blocked,.5)
        assert all(not intersects(s["start"],s["end"],lo,hi) for s in plan["segments"] for lo,hi in boxes)
        timeline = build(blocked,plan)
        metrics = at(evaluate(blocked,plan,timeline,.25),timeline,timeline["duration"])
        assert not metrics["illegal"] and metrics["extra_miss_area_m2"] > 0
    overhead = copy.deepcopy(blocked)
    overhead["obstacles"][0].update(min=[1.8,5.8,8],max=[2.2,7.2,10])
    high = generate_plan(overhead)
    assert high["status"] == "success" and high["segments"] == plain["segments"]
    # An object merely existing on the map must not reject a clear flight.
    away = copy.deepcopy(blocked)
    away["obstacles"][0].update(min=[25,1,0],max=[26,2,7])
    assert generate_plan(away)["status"] == "success"
    nofly = copy.deepcopy(scene)
    nofly["no_fly_zones"] = [dict(id="nf",kind="polygon_prism",footprint=dict(kind="polygon",vertices=[[.5,12.5],[10.5,12.5],[10.5,20.5],[.5,20.5]]),z_min=0,z_max=8)]
    assert generate_plan(nofly)["status"] == "failed"
    assert make_planner("caw-a*-3d-wind").plan(nofly)["status"] == "success"
    print("通过 · 固定 Y 实际冲突报错、CAW 三维绕障、上方/远处实体不误报与禁飞分工")
    return 0
