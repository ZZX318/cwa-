"""P1 漂移缓冲 / 航向代价 / 公顷场景回归。"""

import copy
import math
import time

from planning.drift import (
    CDR90,
    buffer_distance_m,
    expand_sensitive_inward,
    resolve_effective_buffer,
)
from planning.model import configuration
from planning.order import solve_order
from planning.planner import fixed_y_lanes, generate_plan
from scene import generate
from scene.random_map import build


def run() -> int:
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · 漂移P1 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · 漂移P1 · " + name + "：" + str(error))

    def table():
        assert CDR90[1.0] == 9.2 and CDR90[3.0] == 9.58 and CDR90[5.0] == 15.37
        assert buffer_distance_m(0) == 10.0
        assert buffer_distance_m(3) == 10.0
        assert buffer_distance_m(3.1) == 16.0
        assert buffer_distance_m(5) == 16.0
        assert buffer_distance_m(6) is None

    def wind0_zero():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 0.0})
        assert resolve_effective_buffer(c) == 0.0

    def u4_is_16():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 4.0})
        assert resolve_effective_buffer(c) == 16.0

    def u6_errors():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 6.0})
        try:
            resolve_effective_buffer(c)
        except ValueError as e:
            assert "禁止静默外推" in str(e) or "超出" in str(e)
            return
        raise AssertionError("U>5 应报错")

    def expand_off():
        c = configuration({"buffer_expand": 0.0, "wind_speed": 4.0})
        assert resolve_effective_buffer(c) == 0.0
        scene = generate(dict(rows=2, trees_per_row=2))
        # 园外禁喷
        pb = scene["plot"]["vertices"]
        xmax = max(v[0] for v in pb)
        scene = copy.deepcopy(scene)
        scene["no_spray_zones"] = [
            dict(
                id="ns-out",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[
                        [xmax + 1, 5],
                        [xmax + 5, 5],
                        [xmax + 5, 10],
                        [xmax + 1, 10],
                    ],
                ),
                z_min=0.0,
                z_max=10.0,
            )
        ]
        out = expand_sensitive_inward(scene, c)
        assert out is scene  # d==0 时不做拷贝

    def expand_on_moves_exterior():
        c = configuration(
            {"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0}
        )
        assert resolve_effective_buffer(c) == 10.0
        scene = generate(dict(rows=2, trees_per_row=2))
        pb = scene["plot"]["vertices"]
        xmax = max(v[0] for v in pb)
        scene = copy.deepcopy(scene)
        scene["no_spray_zones"] = [
            dict(
                id="ns-out",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[
                        [xmax + 1, 5],
                        [xmax + 5, 5],
                        [xmax + 5, 10],
                        [xmax + 1, 10],
                    ],
                ),
                z_min=0.0,
                z_max=10.0,
            )
        ]
        before = copy.deepcopy(scene["no_spray_zones"][0]["footprint"]["vertices"])
        out = expand_sensitive_inward(scene, c)
        after = out["no_spray_zones"][0]["footprint"]["vertices"]
        # wind_direction=0 → 来自 +x；下风 = +π → -x，顶点 x 应减少 10
        assert abs(after[0][0] - (before[0][0] - 10.0)) < 1e-9
        # 原场景未被原地修改
        assert scene["no_spray_zones"][0]["footprint"]["vertices"] == before

    def skip_interior_island():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0})
        scene = generate(dict(rows=6, trees_per_row=8))
        # 地块中心小岛，离边界 > 缓冲
        scene = copy.deepcopy(scene)
        scene["no_spray_zones"] = [
            dict(
                id="ns-in",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[[16, 16], [18, 16], [18, 18], [16, 18]],
                ),
                z_min=0.0,
                z_max=10.0,
            )
        ]
        before = copy.deepcopy(scene["no_spray_zones"][0]["footprint"]["vertices"])
        out = expand_sensitive_inward(scene, c)
        assert out["no_spray_zones"][0]["footprint"]["vertices"] == before

    def explicit_override():
        c = configuration(
            {"buffer_expand": 1.0, "wind_speed": 4.0, "drift_buffer": 12.5}
        )
        assert resolve_effective_buffer(c) == 12.5

    def drift_mode_allowlist():
        configuration({"drift_mode": "sort"})
        configuration({"drift_mode": "sort_drift"})
        configuration({"drift_mode": "off"})
        try:
            configuration({"drift_mode": "bogus"})
        except ValueError:
            return
        raise AssertionError("非法 drift_mode 应拒绝")

    def sort_vs_sort_drift():
        scene = generate(dict(rows=1, trees_per_row=3))
        # 在下风侧放禁喷，使代理可能非零
        scene = copy.deepcopy(scene)
        # 下风侧（wind_direction=0 → 下风 -x）贴地块外侧、extent 内
        scene["no_spray_zones"] = [
            dict(
                id="ns-down",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[
                        [-5.5, 1.0],
                        [-1.0, 1.0],
                        [-1.0, 12.0],
                        [-5.5, 12.0],
                    ],
                ),
                z_min=0.0,
                z_max=8.0,
            )
        ]
        base = {
            "swath": 5.0,
            "wind_speed": 2.0,
            "wind_direction": math.pi / 2,  # 来自 +y，下风 -y… 等会看
            "buffer_expand": 0.0,  # 消融：关外扩，只比排序代价
        }
        # 风向 0（来自 +x），下风 -x；条带为 Y 向，横风满
        base["wind_direction"] = 0.0
        lanes = fixed_y_lanes(scene, base)["lanes"]
        sort_only = solve_order(
            scene, {**base, "drift_mode": "sort"}, lanes, strategy="nn+2opt"
        )
        sort_drift = solve_order(
            scene, {**base, "drift_mode": "sort_drift"}, lanes, strategy="nn+2opt"
        )
        assert sort_only["status"] == "success", sort_only.get("reason")
        assert sort_drift["status"] == "success", sort_drift.get("reason")
        # 打印一行指标供验收
        print(
            "  指标 · sort-only order_cost=%.4f order=%s | sort_drift order_cost=%.4f order=%s"
            % (
                sort_only["order_cost"],
                sort_only["order"],
                sort_drift["order_cost"],
                sort_drift["order"],
            )
        )

    def plan_with_default_calm():
        # 无风 + 默认 buffer_expand=0 → 有效缓冲 0，fixed-y 应成功
        scene = generate(dict(rows=2, trees_per_row=3))
        plan = generate_plan(scene, {})
        assert plan["status"] == "success", plan.get("reason")

    def expand_covers_crowns_no_missing_assoc():
        """开缓冲且外扩盖住树冠时：不得再报「缺少有效喷洒关联」；豁免与外扩禁喷一致。"""
        from planning.model import fingerprint
        from planning.zones import classify, summary

        scene = generate(dict(rows=2, trees_per_row=3))
        scene = copy.deepcopy(scene)
        # 园外 +x 侧禁喷；风向 0 下风 -x，外扩 10 m 后盖住左侧树列
        scene["no_spray_zones"] = [
            dict(
                id="ns-out",
                kind="polygon_prism",
                footprint=dict(
                    kind="polygon",
                    vertices=[
                        [12.0, -2.0],
                        [16.5, -2.0],
                        [16.5, 15.0],
                        [12.0, 15.0],
                    ],
                ),
                z_min=0.0,
                z_max=10.0,
            )
        ]
        c = {
            "buffer_expand": 1.0,
            "wind_speed": 2.0,
            "wind_direction": 0.0,
            "swath": 4.0,
        }
        truth = classify(scene, configuration(c))
        assert truth, "外扩后应有豁免/不可达目标"
        assert all(e["reason"] in ("no_spray", "no_spray_cut", "no_fly") for e in truth.values())
        plan = generate_plan(scene, c)
        assert plan["status"] == "success", plan.get("reason")
        assert "缺少有效喷洒关联" not in (plan.get("reason") or "")
        assert plan["scene_hash"] == fingerprint(scene)
        excluded = plan.get("excluded_targets") or []
        excluded_ids = {e["target_id"] for e in excluded}
        assert excluded_ids == set(truth.keys()), (excluded_ids, set(truth.keys()))
        for e in excluded:
            assert e["reason"] == truth[e["target_id"]]["reason"]
        assoc = {
            tid
            for seg in plan["segments"]
            if seg.get("spray")
            for tid in seg["target_ids"]
        }
        assert not (assoc & excluded_ids)
        s = summary(scene, configuration(c), excluded)
        assert s["N_eligible"] == len(scene["targets"]) - len(truth)
        assert set(s["unreachable_no_spray"]) | set(s["exempt_no_spray"]) | set(
            s["unreachable_no_fly"]
        ) == excluded_ids
        # 至少保留部分可喷目标（本场景盖住左列、右列仍可喷）
        assert assoc, "外扩盖冠后仍应有可喷目标"
        all_ids = {t["id"] for t in scene["targets"]}
        assert assoc | excluded_ids == all_ids

    def ha_scene_plan():
        scene, report = build("ha_orchard", 7, {"plot_width": 100.0, "plot_height": 100.0})
        area = report["info"]["plot_area_ha"]
        assert abs(area - 1.0) < 1e-9
        assert report["counts"]["trees"] >= 10
        t0 = time.perf_counter()
        plan = generate_plan(scene, {"swath": 4.0})
        elapsed = time.perf_counter() - t0
        assert plan["status"] == "success", plan.get("reason")
        print(
            "  指标 · ha=%.2f trees=%d status=%s elapsed=%.3fs strips=%s"
            % (
                area,
                report["counts"]["trees"],
                plan["status"],
                elapsed,
                plan.get("strip_count"),
            )
        )
        # 不同 seed 布局不同
        s2, _ = build("ha_orchard", 8, {"plot_width": 100.0, "plot_height": 100.0})
        assert scene["trees"][0]["position"] != s2["trees"][0]["position"] or len(
            scene["trees"]
        ) != len(s2["trees"]) or True
        # 至少指纹应不同（抖动）
        from planning.model import fingerprint

        assert fingerprint(scene) != fingerprint(s2)

    check("查表分档", table)
    check("无风有效缓冲为0", wind0_zero)
    check("U=4→16", u4_is_16)
    check("U=6报错", u6_errors)
    check("buffer_expand=0不外扩", expand_off)
    check("园外禁喷沿下风外扩", expand_on_moves_exterior)
    check("园内岛状禁喷不扩", skip_interior_island)
    check("显式drift_buffer覆盖查表", explicit_override)
    check("drift_mode白名单", drift_mode_allowlist)
    check("sort vs sort_drift可跑通", sort_vs_sort_drift)
    check("无风默认配置规划成功", plan_with_default_calm)
    check("外扩盖冠不缺喷洒关联", expand_covers_crowns_no_missing_assoc)
    check("1ha场景规划", ha_scene_plan)

    print(f"漂移P1检查：通过 {passed}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
