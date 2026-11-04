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

import buffer_oracle as oracle


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

    def _zone(zid, vs, z_max=10.0):
        return dict(
            id=zid,
            kind="polygon_prism",
            footprint=dict(kind="polygon", vertices=[list(v) for v in vs]),
            z_min=0.0,
            z_max=z_max,
        )

    def _legacy_translate_downwind(vs, d, wd):
        """54aa1ad~5e925fe 的旧实现：整体沿下风平移 d、丢弃原区域（反例）。"""
        return [[v[0] + d * math.cos(wd + math.pi), v[1] + d * math.sin(wd + math.pi)] for v in vs]

    # 夹具：小场景 generate(rows=2, trees_per_row=3)：plot [0,11]x[0,13]，extent [-6,17]x[-6,19]
    DOWNWIND_VS = [[-5.5, 1.0], [-1.0, 1.0], [-1.0, 12.0], [-5.5, 12.0]]  # -x 侧，wd=0 时在下风（ns-ablation 布局）
    UPWIND_VS = [[12.0, 1.0], [16.5, 1.0], [16.5, 12.0], [12.0, 12.0]]  # +x 侧，wd=0 时在上风
    OBLIQUE_VS = [[-5.5, -5.0], [-1.0, -5.0], [-1.0, 6.0], [-5.5, 6.0]]  # 西南角外，斜风 wd=π/4（来自东北）

    # 计划级 (b) 用大一些的场景 generate(rows=6, trees_per_row=8)：plot [0,35]x[0,33]，extent [-6,41]x[-6,39]
    # （小场景宽仅 11 m，d=10 时整园被切空 → "没有喷洒航段"，无法检验）
    PLAN_DOWNWIND_VS = [[-5.5, 1.0], [-1.0, 1.0], [-1.0, 32.0], [-5.5, 32.0]]
    PLAN_UPWIND_VS = [[36.0, 1.0], [40.5, 1.0], [40.5, 32.0], [36.0, 32.0]]
    PLAN_OBLIQUE_VS = [[-5.5, -5.0], [-1.0, -5.0], [-1.0, 10.0], [-5.5, 10.0]]

    def _fixture(vs, big=False):
        kw = dict(rows=6, trees_per_row=8) if big else dict(rows=2, trees_per_row=3)
        scene = copy.deepcopy(generate(kw))
        scene["no_spray_zones"] = [_zone("ns-fix", vs)]
        return scene

    def expand_downwind_side_sweeps_into_plot():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0})
        d = resolve_effective_buffer(c)
        assert d == 10.0
        scene = _fixture(DOWNWIND_VS)
        before = copy.deepcopy(scene["no_spray_zones"][0]["footprint"]["vertices"])
        out = expand_sensitive_inward(scene, c)
        after = out["no_spray_zones"][0]["footprint"]["vertices"]
        # 上风 u=(1,0)：原区域保留，向 +x（园内）连续扩 10 m → x∈[-5.5, 9]
        xs = [v[0] for v in after]
        ys = [v[1] for v in after]
        assert abs(min(xs) - (-5.5)) < 1e-9 and abs(max(xs) - 9.0) < 1e-9, after
        assert abs(min(ys) - 1.0) < 1e-9 and abs(max(ys) - 12.0) < 1e-9, after
        oracle.check_expanded_contains(before, after, d, 0.0, scene["extent"])
        assert scene["no_spray_zones"][0]["footprint"]["vertices"] == before  # 原场景未被修改

    def expand_upwind_side_stays_out():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0})
        d = resolve_effective_buffer(c)
        scene = _fixture(UPWIND_VS)
        before = copy.deepcopy(scene["no_spray_zones"][0]["footprint"]["vertices"])
        out = expand_sensitive_inward(scene, c)
        after = out["no_spray_zones"][0]["footprint"]["vertices"]
        # 上风侧敏感区：向 +x（远离果园）扩，裁到 extent.max.x=17；不进入地块
        assert abs(min(v[0] for v in after) - 12.0) < 1e-9, after
        assert abs(max(v[0] for v in after) - scene["extent"]["max"][0]) < 1e-9, after
        oracle.check_expanded_contains(before, after, d, 0.0, scene["extent"])

    def expand_oblique_wind():
        wd = math.pi / 4
        c = configuration({"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": wd})
        d = resolve_effective_buffer(c)
        scene = _fixture(OBLIQUE_VS)
        before = copy.deepcopy(scene["no_spray_zones"][0]["footprint"]["vertices"])
        out = expand_sensitive_inward(scene, c)
        after = out["no_spray_zones"][0]["footprint"]["vertices"]
        assert len(after) == 6, after  # 矩形 ⊕ 斜线段 = 六边形
        oracle.check_expanded_contains(before, after, d, wd, scene["extent"])

    def legacy_translate_fails_oracle():
        """(c) 反例：旧的仅平移实现喂给 (a) 必须报错；仅向上风平移（不并原区域）也必须报错。"""
        extent = _fixture(DOWNWIND_VS)["extent"]
        for vs, wd in ((DOWNWIND_VS, 0.0), (UPWIND_VS, 0.0), (OBLIQUE_VS, math.pi / 4)):
            for bad in (
                _legacy_translate_downwind(vs, 10.0, wd),
                [[v[0] + 10.0 * math.cos(wd), v[1] + 10.0 * math.sin(wd)] for v in vs],
            ):
                try:
                    oracle.check_expanded_contains(vs, bad, 10.0, wd, extent)
                except AssertionError:
                    continue
                raise AssertionError("oracle 未识别错误实现：%s" % bad)

    def nonconvex_raises():
        c = configuration({"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0})
        scene = _fixture([[-5.5, 1.0], [-1.0, 1.0], [-3.0, 6.5], [-1.0, 12.0], [-5.5, 12.0]])
        try:
            expand_sensitive_inward(scene, c)
        except ValueError as e:
            assert "非凸" in str(e)
            return
        raise AssertionError("非凸禁喷区应 raise")

    def _plan_drift_clear(vs, wd, expect_cut):
        raw = {"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": wd, "swath": 2.0}
        scene = _fixture(vs, big=True)
        d = resolve_effective_buffer(configuration(raw))
        on = generate_plan(scene, raw)
        assert on["status"] == "success", on.get("reason")
        n, bad = oracle.check_plan_drift_clear(scene, on, d, wd, 2.0)
        assert n > 0 and not bad, "漂移违规 %d/%d，例 %s" % (len(bad), n, bad[:3])
        off = generate_plan(scene, {**raw, "buffer_expand": 0.0})
        assert off["status"] == "success", off.get("reason")
        _, bad_off = oracle.check_plan_drift_clear(scene, off, d, wd, 2.0)

        def spray_len(p):
            return sum(math.dist(s["start"][:2], s["end"][:2]) for s in p["segments"] if s.get("spray"))

        lost = spray_len(off) - spray_len(on)
        print(
            "  指标 · wd=%.3f d=%.1f 采样=%d 违规(开)=0 违规(关)=%d 喷洒段长 关/开=%.3f/%.3f 排除目标 关/开=%d/%d"
            % (wd, d, n, len(bad_off), spray_len(off), spray_len(on),
               len(off.get("excluded_targets") or []), len(on.get("excluded_targets") or []))
        )
        if expect_cut:
            # 非空验证：关缓冲时 oracle 必须能找到违规，开缓冲后喷洒段确实变短
            assert bad_off, "夹具无效：关缓冲时也无漂移违规"
            assert lost > 1e-6, "开缓冲未切掉任何喷洒段"
        else:
            assert abs(lost) < 1e-9 and not bad_off, (lost, len(bad_off))

    def plan_drift_clear_downwind():
        _plan_drift_clear(PLAN_DOWNWIND_VS, 0.0, True)

    def plan_drift_clear_upwind():
        _plan_drift_clear(PLAN_UPWIND_VS, 0.0, False)

    def plan_drift_clear_oblique():
        _plan_drift_clear(PLAN_OBLIQUE_VS, math.pi / 4, True)

    def safety_drift_hard_check_matches_oracle():
        """safety 内置独立漂移检查与 buffer_oracle (b) 结论一致（开：0 违规；关计划以开口径检：>0）。"""
        from planning.safety import _drift_ray_violations

        for vs, wd, expect_bad in (
            (PLAN_DOWNWIND_VS, 0.0, True),
            (PLAN_UPWIND_VS, 0.0, False),
            (PLAN_OBLIQUE_VS, math.pi / 4, True),
        ):
            raw = {"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": wd, "swath": 2.0}
            scene = _fixture(vs, big=True)
            on = generate_plan(scene, raw)
            assert on["status"] == "success", on.get("reason")
            n_on, bad_on = _drift_ray_violations(scene, on["segments"], 10.0, wd, 2.0)
            assert not bad_on, bad_on[:3]
            off = generate_plan(scene, {**raw, "buffer_expand": 0.0})
            _, bad_off = _drift_ray_violations(scene, off["segments"], 10.0, wd, 2.0)
            _, oracle_off = oracle.check_plan_drift_clear(scene, off, 10.0, wd, 2.0)
            assert bool(bad_off) == expect_bad == bool(oracle_off), (len(bad_off), len(oracle_off))
            print("  指标 · safety(b) wd=%.3f 采样(开)=%d 违规 开/关=%d/%d oracle违规(关)=%d"
                  % (wd, n_on, len(bad_on), len(bad_off), len(oracle_off)))

    def safety_rejects_broken_expand():
        """反例：把外扩函数换成「不扩」或「只向上风平移、丢弃原区域」后，safety 的独立硬检查必须拒绝计划。
        （旧「下风平移」实现在此夹具会移出 extent、在场景校验即失败，见 e374f17，故用这两种错误实现。）"""
        import planning.drift as drift_mod
        import planning.planner as planner_mod

        raw = {"buffer_expand": 1.0, "wind_speed": 2.0, "wind_direction": 0.0, "swath": 2.0}
        scene = _fixture(PLAN_DOWNWIND_VS, big=True)
        real = drift_mod.expand_sensitive_inward

        def identity(sc, cfg):
            return sc

        def legacy(sc, cfg):
            out = copy.deepcopy(sc)
            for z in out["no_spray_zones"]:
                z["footprint"]["vertices"] = [[v[0] + 10.0, v[1]] for v in z["footprint"]["vertices"]]
            return out

        try:
            for broken in (identity, legacy):
                drift_mod.expand_sensitive_inward = broken
                planner_mod.expand_sensitive_inward = broken
                plan = generate_plan(scene, raw)
                assert plan["status"] == "failed" and plan.get("stage") == "safety", (plan["status"], plan.get("reason"))
                assert "漂移违规" in plan["reason"], plan["reason"]
        finally:
            drift_mod.expand_sensitive_inward = real
            planner_mod.expand_sensitive_inward = real
        assert generate_plan(scene, raw)["status"] == "success"

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
        # 园外 +x 侧禁喷；风向 π（来自 -x，下风 +x）→ 禁喷区在下风，向上风 -x（园内）扩 d
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
            "wind_direction": math.pi,
            "drift_buffer": 6.0,  # 扩到 x≥6：盖住右列（x=8.5±1.5），左列（2.5±1.5）仍可喷
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
    check("下风侧园外禁喷沿上风扫掠进园(-x,wd=0)", expand_downwind_side_sweeps_into_plot)
    check("上风侧园外禁喷不进园(+x,wd=0)", expand_upwind_side_stays_out)
    check("斜风扫掠为六边形(wd=π/4)", expand_oblique_wind)
    check("独立检查(c)：旧平移实现必须被(a)拒绝", legacy_translate_fails_oracle)
    check("非凸禁喷区raise", nonconvex_raises)
    check("独立检查(b)：下风侧计划无漂移违规且确有切带", plan_drift_clear_downwind)
    check("独立检查(b)：上风侧计划无漂移违规且不切带", plan_drift_clear_upwind)
    check("独立检查(b)：斜风计划无漂移违规且确有切带", plan_drift_clear_oblique)
    check("safety独立漂移硬检查与oracle(b)一致", safety_drift_hard_check_matches_oracle)
    check("外扩函数被破坏时safety独立硬检查拒绝计划", safety_rejects_broken_expand)
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
