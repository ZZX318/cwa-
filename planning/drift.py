"""孔令标 2026 侧风漂移缓冲查表与园外敏感区内扩。

来源：孔令标等，农业工程学报，2026，42(6)：24–34
DOI：10.11975/j.issn.1002-6819.202509207

正文确认前提：作业速度 5 m/s、高度 3 m；航向–风向夹角约 (90±30)°。
试验作物为约 7 cm 小麦，**不是果园冠层**——果园使用属于外推，须在论文中写明，
并最好后续补果园标定。风速 >5 m/s 原文无推荐，禁止静默外推。

配置开关（均在 planning.model.DEFAULT，改默认只改一处）：
- buffer_expand: 0/1，是否启用外扩约束（消融可关）
- drift_mode: "off"|"sort"|"sort_drift"（排序是否加漂移代理代价）
- drift_buffer: 显式缓冲(m)；>0 时覆盖查表结果（仍受 buffer_expand / 风速门控）
- wind_speed==0 时有效缓冲恒为 0，避免无风回归被默认开缓冲打断
"""

from __future__ import annotations

import copy
import math

from scene.geometry import in_polygon, polygon_bounds

# 90% 累积飘移距离（CDR90），正文图12 / 摘要
CDR90 = {1.0: 9.2, 3.0: 9.58, 5.0: 15.37}

SPEED_REF = 5.0
HEIGHT_REF = 3.0


def buffer_distance_m(U_cross: float):
    """侧风风速 U_cross (m/s) → 下风向缓冲距离 (m)；超出原文范围返回 None。"""
    if type(U_cross) not in (int, float) or not math.isfinite(U_cross) or U_cross < 0:
        raise ValueError(f"U_cross={U_cross!r}：需要非负有限风速")
    if U_cross <= 3.0:
        return 10.0
    if U_cross <= 5.0:
        return 16.0
    return None


def resolve_effective_buffer(config) -> float:
    """有效缓冲距离 (m)。

    门控顺序：
    1. buffer_expand 关（0/false）→ 0
    2. wind_speed == 0 → 0（保护无风回归；即使 buffer_expand 默认开也不外扩）
    3. 显式 drift_buffer > 0 → 用该值（覆盖查表）
    4. 否则查表；U>5 → ValueError，禁止静默外推
    """
    expand = config.get("buffer_expand", 1.0)
    if expand in (0, 0.0, False):
        return 0.0
    wind = float(config.get("wind_speed", 0.0) or 0.0)
    if wind == 0.0:
        return 0.0
    explicit = float(config.get("drift_buffer", 0.0) or 0.0)
    if explicit > 0.0:
        return explicit
    looked = buffer_distance_m(wind)
    if looked is None:
        raise ValueError(
            f"风速 {wind} m/s 超出孔令标 2026 推荐范围（≤5 m/s），"
            "禁止静默外推；请关闭 buffer_expand 或给出显式 drift_buffer"
        )
    return float(looked)


def drift_cost_buffer(config) -> float:
    """排序漂移代理用的缓冲尺度：不受 buffer_expand 门控。

    这样消融可独立开关：
    - buffer_expand 0/1：是否做园外→园内几何外扩
    - drift_mode sort / sort_drift：是否在条带排序里加侧风代理
    wind_speed==0 → 0；显式 drift_buffer>0 覆盖查表；U>5 → ValueError。
    """
    wind = float(config.get("wind_speed", 0.0) or 0.0)
    if wind == 0.0:
        return 0.0
    explicit = float(config.get("drift_buffer", 0.0) or 0.0)
    if explicit > 0.0:
        return explicit
    looked = buffer_distance_m(wind)
    if looked is None:
        raise ValueError(
            f"风速 {wind} m/s 超出孔令标 2026 推荐范围（≤5 m/s），"
            "禁止静默外推；请降低风速或给出显式 drift_buffer"
        )
    return float(looked)


def _centroid(vertices):
    n = len(vertices)
    return [sum(v[0] for v in vertices) / n, sum(v[1] for v in vertices) / n]


def _min_dist_to_plot_boundary(point, plot) -> float:
    """点到地块边界的近似距离；点在地块外时返回 0。"""
    if not in_polygon(point, plot):
        return 0.0
    vs = plot["vertices"]
    best = math.inf
    x, y = point[0], point[1]
    for a, b in zip(vs, vs[1:] + vs[:1]):
        ax, ay = a[0], a[1]
        bx, by = b[0], b[1]
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        if den <= 1e-18:
            dist = math.hypot(x - ax, y - ay)
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / den))
            dist = math.hypot(x - ax - t * dx, y - ay - t * dy)
        best = min(best, dist)
    return best


def _zone_is_exterior_sensitive(zone, plot, buffer_m) -> bool:
    """园外/贴边敏感区才外扩；地块内且离边界 > buffer 的岛状区跳过。"""
    vs = zone["footprint"]["vertices"]
    c = _centroid(vs)
    if not in_polygon(c, plot):
        return True
    if any(not in_polygon(v, plot) for v in vs):
        return True
    b = polygon_bounds(zone["footprint"])
    pb = polygon_bounds(plot)
    # AABB 伸出地块
    if (
        b["min"][0] < pb["min"][0] - 1e-9
        or b["min"][1] < pb["min"][1] - 1e-9
        or b["max"][0] > pb["max"][0] + 1e-9
        or b["max"][1] > pb["max"][1] + 1e-9
    ):
        return True
    return _min_dist_to_plot_boundary(c, plot) <= buffer_m + 1e-9


def expand_sensitive_inward(scene: dict, config) -> dict:
    """深拷贝场景；仅当有效缓冲 >0 时，把园外/贴边禁喷区沿下风向外扩。

    wind_direction = 风的来向；下风向 = wind_direction + π。
    不从园内障碍往外扩；不改 no_fly / obstacles。
    调用方应以原场景做 scene_hash / safety.check，以本返回值做几何切割与排序。
    """
    d = resolve_effective_buffer(config)
    if d <= 0:
        return scene
    out = copy.deepcopy(scene)
    plot = out["plot"]
    wind_dir = float(config.get("wind_direction", 0.0) or 0.0)
    # 下风向单位向量
    dx = math.cos(wind_dir + math.pi)
    dy = math.sin(wind_dir + math.pi)
    zones = out.get("no_spray_zones") or []
    for zone in zones:
        if not _zone_is_exterior_sensitive(zone, plot, d):
            continue
        fp = zone["footprint"]
        fp["vertices"] = [
            [v[0] + d * dx, v[1] + d * dy] + (list(v[2:]) if len(v) > 2 else [])
            for v in fp["vertices"]
        ]
    return out


def lane_drift_proxy(lane, scene, config, effective_buffer: float) -> float:
    """侧风–漂移代理代价：横风强度 × 缓冲 ×「喷幅下风向邻近敏感区」指示。

    与 CAW 转场代价相加；仅在 drift_mode==sort_drift 时由 order 调用。
    """
    if effective_buffer <= 0:
        return 0.0
    wind_speed = float(config.get("wind_speed", 0.0) or 0.0)
    if wind_speed <= 0:
        return 0.0
    wind_dir = float(config.get("wind_direction", 0.0) or 0.0)
    sx, sy = lane["start"][0], lane["start"][1]
    ex, ey = lane["end"][0], lane["end"][1]
    heading = math.atan2(ey - sy, ex - sx)
    # 横风分量：航向与来风正交时最大
    cross = abs(math.sin(heading - wind_dir)) * wind_speed
    if cross <= 1e-12:
        return 0.0
    down_x = math.cos(wind_dir + math.pi)
    down_y = math.sin(wind_dir + math.pi)
    mid = [(sx + ex) / 2.0, (sy + ey) / 2.0]
    # 沿下风向探测缓冲带内是否碰到禁喷区（原场景或已外扩场景均可）
    zones = scene.get("no_spray_zones") or []
    hit = False
    steps = max(4, int(math.ceil(effective_buffer / 2.0)))
    for k in range(1, steps + 1):
        t = effective_buffer * k / steps
        p = [mid[0] + down_x * t, mid[1] + down_y * t]
        for zone in zones:
            if in_polygon(p, zone["footprint"]):
                hit = True
                break
        if hit:
            break
    if not hit:
        return 0.0
    return cross * effective_buffer
