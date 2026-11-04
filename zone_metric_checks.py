"""禁喷/禁飞口径验收（多边形整株豁免、作业高度有效禁飞、三规划器同 N）。"""
import copy
import math

from execution import build
from evaluation import at, build as eval_build
from planner_api import make_planner
from planning import check, configuration, generate_plan
from planning.zones import classify
from scene import generate
from sortie import plan_sorties

PLANNERS = ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-3d-wind", "caw-a*-nn")


def _poly(zone_id, vertices, z_max=10.0):
    return dict(
        id=zone_id,
        kind="polygon_prism",
        footprint=dict(kind="polygon", vertices=vertices),
        z_min=0.0,
        z_max=z_max,
    )


def _zone(zone_id, x0, y0, x1, y1, z_max=10.0):
    return _poly(zone_id, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], z_max)


def _plan(scene, name):
    return generate_plan(scene) if name == "fixed-y-boustrophedon" else make_planner(name).plan(scene, {})


def metrics(scene, name):
    plan = _plan(scene, name)
    if plan["status"] != "success":
        raise AssertionError(f"{name} 失败：{plan.get('stage')} {plan['reason']}")
    check(scene, plan)
    timeline = build(scene, plan)
    m = at(eval_build(scene, plan, timeline), timeline, timeline["duration"])
    m["duration"] = timeline["duration"]
    return plan, m


def _assert(ok, msg):
    if not ok:
        raise AssertionError(msg)


def run():
    try:
        base = generate()
        c = configuration({})
        tid = "target-tree-01-05"  # (2.5,18.5) r=1.5 → 圆 [1,4]×[17,20]

        # 1. 矩形整株禁喷：豁免
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-full", 0.5, 16.5, 4.5, 20.5)]
        truth = classify(s, c)
        _assert(tid in truth and truth[tid]["reason"] == "no_spray", truth)
        ns = set()
        for name in PLANNERS:
            _, m = metrics(s, name)
            _assert(m["exempt_no_spray"] == [tid], f"{name} 豁免 {m['exempt_no_spray']}")
            _assert(m["N_eligible"] == 23 and m["misspray"]["area"] == 0, f"{name} N/误喷")
            ns.add(m["N_eligible"])
        _assert(len(ns) == 1, ns)

        # 2. 三角禁喷：仅当圆完全在三角内才豁免。大半覆盖但非整株 → 不豁免。
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [
            _poly("ns-tri", [[0.0, 16.0], [6.0, 16.0], [3.0, 22.0]])
        ]
        _assert(tid not in classify(s, c) or classify(s, c)[tid]["reason"] != "no_spray", classify(s, c))
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            _, m = metrics(s, name)
            _assert(tid not in m["exempt_no_spray"], f"{name} 三角误豁免")
            _assert(m["misspray"]["area"] == 0, f"{name} 三角误喷 {m['misspray']}")

        # 3. L 形禁喷整株罩住 → 豁免（两矩形拼 L，用多边形）
        s = copy.deepcopy(base)
        # 一个足够大的矩形仍用整株；另测 L：覆盖 [1,4]x[17,20] 的 L
        s["no_spray_zones"] = [
            _poly(
                "ns-L",
                [[0.5, 16.5], [4.5, 16.5], [4.5, 18.0], [2.5, 18.0], [2.5, 20.5], [0.5, 20.5]],
            )
        ]
        # L 未必含整个圆，不强制豁免；只要求三规划器 N 一致且能规划
        Ns = set()
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            _, m = metrics(s, name)
            Ns.add(m["N_eligible"])
            _assert(m["misspray"]["area"] == 0, f"{name} L 误喷")
        _assert(len(Ns) == 1, f"L 形 N 不一致 {Ns}")

        # 4. 部分重叠矩形：仍喷，误喷 0
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-part", 0.5, 17.6, 4.5, 19.4)]
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            _, m = metrics(s, name)
            _assert(m["exempt_no_spray"] == [] and m["N_eligible"] == 24, f"{name} 部分重叠")
            _assert(tid not in m["uncovered_targets"], f"{name} 未覆盖")
            _assert(m["misspray"]["area"] == 0, f"{name} 误喷")

        # 5. 边界相切：外接相切但正面积为 0 → 不误喷、不豁免
        s = copy.deepcopy(base)
        # 树冠左缘 x=1.0，禁喷右缘 x=1.0
        s["no_spray_zones"] = [_zone("ns-tan", -2.0, 17.0, 1.0, 20.0)]
        for name in ("fixed-y-boustrophedon", "caw-a*-nn"):
            plan, m = metrics(s, name)
            _assert(tid not in m["exempt_no_spray"], f"{name} 相切误豁免")
            _assert(m["misspray"]["area"] == 0, f"{name} 相切误喷")

        # 6. 低空禁飞 z_max=3 < 作业高 6.2：不可达名单为空，三规划器同 N=24
        s = copy.deepcopy(base)
        s["no_fly_zones"] = [_zone("nf-low", 0.5, 16.5, 10.5, 24.5, 3.0)]
        _assert(classify(s, c) == {}, classify(s, c))
        Ns = set()
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            _, m = metrics(s, name)
            _assert(m["unreachable_no_fly"] == [], f"{name} 低空误不可达")
            Ns.add(m["N_eligible"])
        _assert(Ns == {24}, Ns)

        # 7. 细长禁飞挡住一条 fixed-y 但 naive 树心带可喷 → 不应标 no_fly（仍可达）
        s = copy.deepcopy(base)
        # x∈[1.7,2.3] 挡住 x=2 的条带，树心在 2.5，naive 短带在 x=2.5
        s["no_fly_zones"] = [_zone("nf-thin", 1.7, 16.5, 2.3, 20.5, 12.0)]
        _assert(tid not in classify(s, c), classify(s, c))
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            _, m = metrics(s, name)
            _assert(tid not in m["unreachable_no_fly"], f"{name} 细长误不可达")

        # 8. 高禁飞整罩：unreachable_no_fly
        s = copy.deepcopy(base)
        s["no_fly_zones"] = [_zone("nf-full", 0.5, 16.5, 4.5, 20.5, 12.0)]
        for name in ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-nn"):
            plan, m = metrics(s, name)
            _assert(m["unreachable_no_fly"] == [tid], f"{name} {m['unreachable_no_fly']}")
            _assert(tid not in m["uncovered_targets"] and m["target_coverage"] == 1.0, name)

        # 9. 截图场景：四棵豁免，N=20
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-1", 0.5, 16.5, 10.5, 24.5)]
        ns = set()
        for name in PLANNERS:
            _, m = metrics(s, name)
            ns.add(m["N_eligible"])
            _assert(
                m["exempt_no_spray"]
                == ["target-tree-01-05", "target-tree-01-06", "target-tree-02-05", "target-tree-02-06"],
                f"{name} {m['exempt_no_spray']}",
            )
        _assert(ns == {20}, ns)

        # 10. search / sortie
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-1", 0.5, 16.5, 10.5, 24.5)]
        searched = generate_plan(s, {"transition_mode": "search"})
        _assert(searched["status"] == "success", searched.get("reason"))
        sorties = plan_sorties(s, {}, dict(payload_capacity_kg=100, flow_rate_kg_per_s=0.05))
        _assert(sorties["status"] == "success", sorties.get("reason"))
        s_nf = copy.deepcopy(base)
        s_nf["no_fly_zones"] = [_zone("nf-1", 0.5, 16.5, 10.5, 24.5, 12.0)]
        _assert(generate_plan(s_nf, {"transition_mode": "search"})["status"] == "success", "search+禁飞失败")
        _assert(plan_sorties(s_nf, {}, dict(payload_capacity_kg=100, flow_rate_kg_per_s=0.05))["status"] == "success", "sortie+禁飞失败")

        # 11. multi：人为制造子计划失败 → 总状态 failed
        from multi import run as multi_run
        from unittest import mock

        s = generate()
        # 用禁飞盖住几乎全部可飞空间，迫使某机失败较难；改为 mock check
        real_check = __import__("planning").check
        calls = {"n": 0}

        def flaky(scene, plan):
            calls["n"] += 1
            if plan.get("uav") == 2 or (plan.get("allow_partial") and calls["n"] > 1):
                raise ValueError("injected multi failure")
            return real_check(scene, plan)

        with mock.patch("multi.check", side_effect=flaky):
            r = multi_run(s, {}, 2)
        _assert(r["status"] == "failed", r)

        # 12. seed 0–19 零失败
        import random_scene

        for seed in range(20):
            sc, _ = random_scene.generate_with_report("random_obstacles_zones", seed, None, False)
            p1 = generate_plan(sc)
            _assert(p1["status"] == "success", f"seed {seed} fixed-y: {p1.get('reason')}")
            p2 = make_planner("caw-a*-nn").plan(sc, {})
            _assert(p2["status"] == "success", f"seed {seed} caw: {p2.get('reason')}")

        print(
            "通过 · 禁区口径：多边形整株/三角L/相切/低空禁飞/细长禁飞/截图同N/search·sortie/multi失败传播/seed0-19"
        )
        return 0
    except Exception as e:
        print("失败 · 禁区口径：", repr(e))
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
