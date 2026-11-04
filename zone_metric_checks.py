"""禁喷/禁飞口径验收：豁免、部分重叠仍喷、禁飞边缘部分覆盖、禁飞不可达、截图场景三规划器同 N。"""
import copy

from execution import build
from evaluation import at, build as eval_build
from planner_api import make_planner
from planning import check, generate_plan
from scene import generate

PLANNERS = ("fixed-y-boustrophedon", "caw-a*-3d-wind", "caw-a*-nn")


def _zone(zone_id, x0, y0, x1, y1, z_max=10.0):
    return dict(
        id=zone_id,
        kind="polygon_prism",
        footprint=dict(kind="polygon", vertices=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]),
        z_min=0.0,
        z_max=z_max,
    )


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
        tid = "target-tree-01-05"  # 中心 (2.5, 18.5)，半径 1.5，树冠框 [1,4]×[17,20]

        # 1. 整株落在禁喷区：豁免，不进 N，误喷 0。
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-full", 0.5, 16.5, 4.5, 20.5)]
        for name in PLANNERS:
            _, m = metrics(s, name)
            _assert(m["exempt_no_spray"] == [tid], f"{name} 豁免错误 {m['exempt_no_spray']}")
            _assert(m["N_eligible"] == 23 and m["misspray"]["area"] == 0, f"{name} N/误喷错误")

        # 2. 部分重叠禁喷区：照常作业（有正面积覆盖），误喷 0。
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-part", 0.5, 17.6, 4.5, 19.4)]
        for name in PLANNERS:
            _, m = metrics(s, name)
            _assert(m["exempt_no_spray"] == [] and m["N_eligible"] == 24, f"{name} 部分重叠被误豁免")
            _assert(tid not in m["uncovered_targets"], f"{name} 部分重叠目标未被覆盖")
            _assert(m["misspray"] == dict(area=0.0, segments=0), f"{name} 误喷非 0：{m['misspray']}")

        # 3. 禁飞区边缘：树冠一侧被禁飞区吃掉，仍有正面积覆盖，列入 partial_targets。
        s = copy.deepcopy(base)
        s["no_fly_zones"] = [_zone("nf-edge", 3.6, 16.5, 6.0, 20.5, 12.0)]
        for name in PLANNERS:
            _, m = metrics(s, name)
            _assert(m["unreachable_no_fly"] == [], f"{name} 边缘树被误判不可达")
            partial = {p["target_id"]: p["covered_fraction"] for p in m["partial_targets"]}
            _assert(tid in partial and 0 < partial[tid] < 1, f"{name} 边缘树未列入 partial_targets：{partial}")

        # 4. 禁飞区完全罩住：几何证明不可达，记 unreachable_no_fly，不算漏喷。
        s = copy.deepcopy(base)
        s["no_fly_zones"] = [_zone("nf-full", 0.5, 16.5, 4.5, 20.5, 12.0)]
        for name in PLANNERS:
            plan, m = metrics(s, name)
            _assert(m["unreachable_no_fly"] == [tid], f"{name} 不可达错误 {m['unreachable_no_fly']}")
            _assert(tid not in m["uncovered_targets"] and m["target_coverage"] == 1.0, f"{name} 不可达树计入漏喷")
            # 伪造：把不可达改成禁喷豁免、或凭空多排除一棵树，都必须被拒。
            for forged_list in (
                [dict(e, reason="no_spray") for e in plan["excluded_targets"]],
                plan["excluded_targets"] + [dict(target_id="target-tree-03-03", reason="no_fly", zone_ids=["nf-full"])],
            ):
                forged = copy.deepcopy(plan)
                forged["excluded_targets"] = forged_list
                try:
                    check(s, forged)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"{name} 伪造排除未被拒绝")

        # 5. 截图场景：禁喷区罩住 01-05/01-06/02-05/02-06，三种规划器同一个 N。
        s = copy.deepcopy(base)
        s["no_spray_zones"] = [_zone("ns-1", 0.5, 16.5, 10.5, 24.5)]
        ns = set()
        for name in PLANNERS:
            _, m = metrics(s, name)
            ns.add(m["N_eligible"])
            _assert(
                m["exempt_no_spray"]
                == ["target-tree-01-05", "target-tree-01-06", "target-tree-02-05", "target-tree-02-06"],
                f"{name} 截图场景豁免错误",
            )
        _assert(ns == {20}, f"三规划器 N 不一致：{ns}")
        print("通过 · 禁区口径：整株豁免/部分重叠仍喷且误喷 0/禁飞边缘部分覆盖/禁飞不可达/伪造拒绝/截图场景同 N")
        return 0
    except Exception as e:
        print("失败 · 禁区口径：", repr(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
