"""禁喷缓冲的独立判定（oracle）：不调用 planning.drift.expand_sensitive_inward。

物理口径：wind_direction = 风的来向；上风单位向量 u = (cos wd, sin wd)，
下风 = -u。药液顺风向下风漂移 ≤ d，故园外敏感区（原始禁喷区）上风 d 米内不得喷洒。

(a) check_expanded_contains：扩展后的禁喷几何必须包含原区域，以及原区域沿 u
    平移 t·d（0≤t≤1）的全部位置（落在 extent 外的采样点豁免，场景外不可作业）；
    若扫掠未被 extent 裁剪，还要求面积等于 Minkowski 和的解析面积 A + d·W⊥
   （W⊥ 为原多边形在 u 法向上的投影宽度），防止过度外扩。
(b) check_plan_drift_clear：对计划里每条喷洒段沿程密采样（中心线与两侧喷幅边缘），
    任一采样点 p 沿下风前进 0..d 不得落入原始园外禁喷区。
只依赖 scene.geometry.in_polygon（边界含）与本文件内的几何。
"""

from __future__ import annotations

import math

from scene.geometry import in_polygon

_EPS = 1e-6


def upwind(wd: float):
    return math.cos(wd), math.sin(wd)


def area(vs) -> float:
    return 0.5 * abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(vs, vs[1:] + vs[:1])))


def zone_is_exterior(zone, plot) -> bool:
    """独立口径：足迹有任一顶点不在地块内（含边界）即视为园外/跨界敏感区。"""
    return any(not in_polygon(v, plot) for v in zone["footprint"]["vertices"])


def _polygon_samples(vs, step):
    pts = [list(v[:2]) for v in vs]
    for a, b in zip(vs, vs[1:] + vs[:1]):
        n = max(1, int(math.ceil(math.dist(a[:2], b[:2]) / step)))
        pts += [[a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n] for k in range(1, n)]
    xs = [v[0] for v in vs]
    ys = [v[1] for v in vs]
    poly = dict(kind="polygon", vertices=vs)
    nx = max(1, int(math.ceil((max(xs) - min(xs)) / step)))
    ny = max(1, int(math.ceil((max(ys) - min(ys)) / step)))
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = [min(xs) + (max(xs) - min(xs)) * i / nx, min(ys) + (max(ys) - min(ys)) * j / ny]
            if in_polygon(p, poly):
                pts.append(p)
    return pts


def _in_extent(p, extent, tol=1e-9):
    return all(extent["min"][k] - tol <= p[k] <= extent["max"][k] + tol for k in (0, 1))


def check_expanded_contains(original, expanded, d, wd, extent, step=0.5, sweep_steps=20):
    """(a) 断言 expanded ⊇ 原区域 ⊕ [0, d·u]（extent 内部分）；未裁剪时面积精确相等。"""
    ux, uy = upwind(wd)
    poly = dict(kind="polygon", vertices=expanded)
    base = _polygon_samples(original, step)
    bad = []
    checked = 0
    for k in range(sweep_steps + 1):
        t = d * k / sweep_steps
        for p in base:
            q = [p[0] + t * ux, p[1] + t * uy]
            if not _in_extent(q, extent):
                continue
            checked += 1
            if not in_polygon(q, poly):
                bad.append((round(t, 3), [round(q[0], 4), round(q[1], 4)]))
    if bad:
        raise AssertionError(
            "扩展几何未包含原区域/上风平移区域：%d/%d 采样点在外，例 %s" % (len(bad), checked, bad[:3])
        )
    swept = [list(v[:2]) for v in original] + [[v[0] + d * ux, v[1] + d * uy] for v in original]
    if all(_in_extent(p, extent) for p in swept):
        nx, ny = -uy, ux
        proj = [v[0] * nx + v[1] * ny for v in original]
        expect = area(original) + d * (max(proj) - min(proj))
        got = area(expanded)
        if abs(got - expect) > 1e-6 * max(1.0, expect):
            raise AssertionError("扩展面积 %.6f ≠ Minkowski 和解析面积 %.6f" % (got, expect))
    return checked


def check_plan_drift_clear(original_scene, plan, d, wd, swath, step=0.1, ray_step=0.05):
    """(b) 返回 (采样点数, 违规列表)。违规 = 喷洒点沿下风 0..d 进入原始园外禁喷区。"""
    ux, uy = upwind(wd)
    dx, dy = -ux, -uy
    plot = original_scene["plot"]
    zones = [z for z in original_scene.get("no_spray_zones") or [] if zone_is_exterior(z, plot)]
    reach = max(0.0, d - _EPS)
    n_ray = max(1, int(math.ceil(reach / ray_step)))
    samples = 0
    bad = []
    for i, seg in enumerate(plan.get("segments") or []):
        if not seg.get("spray"):
            continue
        a, b = seg["start"], seg["end"]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L <= 1e-12:
            continue
        tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        px, py = -ty, tx
        n = max(1, int(math.ceil(L / step)))
        half = swath / 2.0 - _EPS
        for k in range(n + 1):
            s = L * k / n
            for off in (-half, 0.0, half):
                p = [a[0] + tx * s + px * off, a[1] + ty * s + py * off]
                samples += 1
                hit = None
                for j in range(n_ray + 1):
                    t = reach * j / n_ray
                    q = [p[0] + dx * t, p[1] + dy * t]
                    for z in zones:
                        if in_polygon(q, z["footprint"]):
                            hit = (i, z["id"], [round(p[0], 4), round(p[1], 4)], round(t, 4))
                            break
                    if hit:
                        break
                if hit:
                    bad.append(hit)
    return samples, bad
