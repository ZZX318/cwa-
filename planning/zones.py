"""禁喷/禁飞区目标分类与误喷度量（代码与论文统一口径）。

口径（技术负责人 2026-11-04 验收打回后修订）：
- exempt_no_spray：树冠圆（外扩 drift_buffer）完全落在某个禁喷区多边形内
  （scene.geometry.disk_in_polygon）。
- unreachable_no_fly：不是禁喷豁免；且在作业高度上，不存在任何「正面积覆盖该树、
  且中心线不进入有效禁飞净空」的 Y 向喷带。有效禁飞 = z_max+clearance ≥ 作业高度
  且 z_min-clearance ≤ 作业高度。判定不绑死 fixed-y 布局，候选喷带包括
  树心短带与 fixed-y 条带切割后的 spray 段。
- unreachable_no_spray：与禁喷区正面积相交、但切割后没有任何喷段能碰到（诊断类）。
- N_eligible = 总树数 − classify 排除数，只由 classify(scene, c) 决定，与计划无关。
- 误喷：喷洒足迹与禁喷多边形的正面积相交（面积为 0 的相切不算）。
"""

from __future__ import annotations

import math
from scene.geometry import disk_in_polygon, in_polygon, polygon_bounds, segments_intersect
from .footprint import overlaps_target, rectangle

_EPS = 1e-9
_OVERLAP_AREA_EPS = 1e-9


def work_height(scene, c):
    return max(t["canopy"]["z_max"] for t in scene["trees"]) + c["height_offset"]


def zone_box(zone):
    b = polygon_bounds(zone["footprint"])
    return (list(b["min"]), list(b["max"]))


def crown_disk(target, buffer=0.0):
    x, y = target["geometry"]["center"]
    return [x, y], target["geometry"]["radius"] + buffer


def active_no_fly(scene, c, height=None):
    """禁飞区在作业高度上挡住飞行时才生效。"""
    h = work_height(scene, c) if height is None else height
    pad = c["clearance"]
    out = []
    for z in scene.get("no_fly_zones", []):
        if z["z_max"] + pad + _EPS >= h and z["z_min"] - pad <= h + _EPS:
            out.append(z)
    return out


def _edge_crosses_disk(a, b, center, radius):
    """开集：线段与圆盘正长度相交（相切不算）。"""
    ax, ay = a[0] - center[0], a[1] - center[1]
    bx, by = b[0] - center[0], b[1] - center[1]
    dx, dy = bx - ax, by - ay
    aa = dx * dx + dy * dy
    if aa <= _EPS:
        return math.hypot(ax, ay) < radius - _EPS
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / aa))
    return math.hypot(ax + t * dx, ay + t * dy) < radius - _EPS


def _clip_polygon_to_rect(vertices, x0, y0, x1, y1):
    """Sutherland–Hodgman clipping; retain zero-width bridges for concave inputs."""
    points = [(v[0], v[1]) for v in vertices]
    for axis, bound, lower in ((0, x0, True), (0, x1, False),
                               (1, y0, True), (1, y1, False)):
        if not points:
            break
        clipped = []
        previous = points[-1]
        previous_inside = previous[axis] >= bound if lower else previous[axis] <= bound
        for current in points:
            current_inside = current[axis] >= bound if lower else current[axis] <= bound
            if current_inside != previous_inside:
                t = (bound - previous[axis]) / (current[axis] - previous[axis])
                other = 1 - axis
                coordinate = previous[other] + t * (current[other] - previous[other])
                clipped.append((bound, coordinate) if axis == 0 else (coordinate, bound))
            if current_inside:
                clipped.append(current)
            previous, previous_inside = current, current_inside
        points = clipped
    return points


def _shoelace_area(points):
    """Return unsigned polygon area, including degenerate clipped polygons."""
    if len(points) < 3:
        return 0.0
    # Translate to a local origin to reduce cancellation for offset coordinates.
    ox, oy = points[0]
    return abs(math.fsum(
        (a[0] - ox) * (b[1] - oy) - (b[0] - ox) * (a[1] - oy)
        for a, b in zip(points, points[1:] + points[:1])
    )) / 2.0


def rect_poly_positive_overlap(rect, polygon) -> bool:
    """矩形足迹与多边形是否正面积相交；纯相切 / 边界接触返回 False。"""
    (x0, y0), (x1, y1) = rect
    if x1 - x0 <= _EPS or y1 - y0 <= _EPS:
        return False
    points = _clip_polygon_to_rect(polygon["vertices"], x0, y0, x1, y1)
    return _shoelace_area(points) > _OVERLAP_AREA_EPS


def _on_poly_boundary(point, polygon) -> bool:
    from scene.geometry import on_segment

    x, y = point[:2]
    vs = polygon["vertices"]
    return any(on_segment([x, y], a, b) for a, b in zip(vs, vs[1:] + vs[:1]))


def overlap_area(a, b):
    """轴对齐矩形相交面积（误喷面积的保守上界，仅用于指标；判定用正面积函数）。"""
    w = min(a[1][0], b[1][0]) - max(a[0][0], b[0][0])
    h = min(a[1][1], b[1][1]) - max(a[0][1], b[0][1])
    return w * h if w > 0 and h > 0 else 0.0


def misspray_area(foot, no_spray_zones) -> float:
    """足迹与各禁喷多边形正面积相交的近似面积（AABB∩poly 的网格估计）。"""
    total = 0.0
    (x0, y0), (x1, y1) = foot
    for zone in no_spray_zones:
        if not rect_poly_positive_overlap(foot, zone["footprint"]):
            continue
        b = polygon_bounds(zone["footprint"])
        xa, xb = max(x0, b["min"][0]), min(x1, b["max"][0])
        ya, yb = max(y0, b["min"][1]), min(y1, b["max"][1])
        if xb - xa <= _EPS or yb - ya <= _EPS:
            continue
        # 0.1 m 网格估计正面积
        step = 0.1
        nx = max(1, int(math.ceil((xb - xa) / step)))
        ny = max(1, int(math.ceil((yb - ya) / step)))
        hit = 0
        for i in range(nx):
            for j in range(ny):
                p = [xa + (i + 0.5) * (xb - xa) / nx, ya + (j + 0.5) * (yb - ya) / ny]
                if x0 < p[0] < x1 and y0 < p[1] < y1 and in_polygon(p, zone["footprint"]):
                    hit += 1
        total += hit * (xb - xa) * (yb - ya) / (nx * ny)
    return total


def _centerline_clear(scene, c, x, y0, y1, height, active_nf):
    """Y 向中心线在作业高度上是否避开有效禁飞净空。"""
    pad = c["clearance"]
    lo, hi = min(y0, y1), max(y0, y1)
    for z in active_nf:
        b = polygon_bounds(z["footprint"])
        # 中心线 x±0 膨胀 pad：用点列采样
        if not (b["min"][0] - pad <= x <= b["max"][0] + pad):
            continue
        # 在重叠 Y 区间采样
        ya, yb = max(lo, b["min"][1] - pad), min(hi, b["max"][1] + pad)
        if yb - ya <= _EPS:
            continue
        for k in range(21):
            y = ya + (yb - ya) * k / 20
            if in_polygon([x, y], z["footprint"]):
                return False
            # 净空：到多边形的粗略距离——若点在膨胀 AABB 内且距边界 < pad
            # 简化：检查点周围 pad 的十字是否落入
            for dx, dy in ((pad, 0), (-pad, 0), (0, pad), (0, -pad), (pad * 0.7, pad * 0.7)):
                if in_polygon([x + dx, y + dy], z["footprint"]):
                    return False
    return True


def _spray_candidates(scene, c, target, active_nf):
    """返回可能正面积覆盖该树的候选喷段列表（已切割语义下的 spray 段）。"""
    from .planner import fixed_y_lanes, lane_parts

    height = work_height(scene, c)
    geometry = target["geometry"]
    cx, cy = geometry["center"]
    r = geometry["radius"]
    out = []

    # 候选 1：树心短 Y 带（naive）
    lane = dict(
        start=[cx, cy - r, height],
        end=[cx, cy + r, height],
        target_ids=[target["id"]],
    )
    for part in lane_parts(scene, lane, c):
        if part["type"] == "spray" and overlaps_target(rectangle(part, c["swath"]), geometry):
            if _centerline_clear(scene, c, part["start"][0], part["start"][1], part["end"][1], height, active_nf):
                out.append(part)

    # 候选 2：fixed-y 布局中覆盖该树的条带
    for lane in fixed_y_lanes(scene, c)["lanes"]:
        if target["id"] not in lane["target_ids"]:
            continue
        for part in lane_parts(scene, lane, c):
            if part["type"] == "spray" and overlaps_target(rectangle(part, c["swath"]), geometry):
                if _centerline_clear(scene, c, part["start"][0], part["start"][1], part["end"][1], height, active_nf):
                    out.append(part)
    return out


def classify(scene, c, buffer=None):
    """返回 {target_id: entry}；未列出的即应喷目标。N 只由此决定。

    入参 scene 仍是原场景（与 scene_hash 一致）；若 config.buffer_expand 开启，
    禁喷/切割几何按孔令标外扩副本判定，与 generate_plan 切带口径对齐。
    """
    from .drift import expand_sensitive_inward

    if buffer is None:
        buffer = float(c.get("drift_buffer", 0.0) or 0.0)
    # 外扩仅影响禁喷多边形与切带；指纹仍由调用方对原场景计算。
    geo = expand_sensitive_inward(scene, c)
    height = work_height(geo, c)
    active_nf = active_no_fly(geo, c, height)
    no_spray = list(geo.get("no_spray_zones", []))
    out = {}
    for t in geo["targets"]:
        center, radius = crown_disk(t, buffer)
        holders = [
            z["id"]
            for z in no_spray
            if disk_in_polygon(center, radius, z["footprint"])
        ]
        if holders:
            out[t["id"]] = dict(target_id=t["id"], reason="no_spray", zone_ids=holders)
            continue
        cands = _spray_candidates(geo, c, t, active_nf)
        if cands:
            continue
        # 不可达：区分禁飞还是禁喷切割
        flies = []
        for z in active_nf:
            # 树冠与禁飞多边形/其净空是否有关：圆盘与膨胀足迹
            if disk_in_polygon(center, radius, z["footprint"]) or rect_poly_positive_overlap(
                ([center[0] - radius, center[1] - radius], [center[0] + radius, center[1] + radius]),
                z["footprint"],
            ):
                flies.append(z["id"])
            else:
                # 净空垫：AABB 触碰
                b = polygon_bounds(z["footprint"])
                pad = c["clearance"] + c["swath"] / 2.0
                box = ([center[0] - radius, center[1] - radius], [center[0] + radius, center[1] + radius])
                zb = ([b["min"][0] - pad, b["min"][1] - pad], [b["max"][0] + pad, b["max"][1] + pad])
                if all(box[0][i] <= zb[1][i] + _EPS and zb[0][i] <= box[1][i] + _EPS for i in (0, 1)):
                    flies.append(z["id"])
        if flies:
            out[t["id"]] = dict(target_id=t["id"], reason="no_fly", zone_ids=sorted(set(flies)))
            continue
        sprays = [
            z["id"]
            for z in no_spray
            if rect_poly_positive_overlap(
                ([center[0] - radius, center[1] - radius], [center[0] + radius, center[1] + radius]),
                z["footprint"],
            )
        ]
        if sprays:
            out[t["id"]] = dict(target_id=t["id"], reason="no_spray_cut", zone_ids=sprays)
        else:
            # 「新增，不改已冻结主表」：no legal candidate, no zone overlap.
            out[t["id"]] = dict(target_id=t["id"], reason="unreachable", zone_ids=[])
    return out


def summary(scene, c=None, excluded=None):
    """N 与名单以 classify 为准；excluded 仅作交叉核对时可传入。"""
    if c is None:
        from .model import configuration

        c = configuration({})
    truth = classify(scene, c)
    items = list(truth.values())
    total = len(scene["targets"])
    by = lambda r: sorted(e["target_id"] for e in items if e["reason"] == r)
    return dict(
        N_total=total,
        N_eligible=total - len(items),
        exempt_no_spray=by("no_spray"),
        unreachable_no_fly=by("no_fly"),
        unreachable_no_spray=by("no_spray_cut"),
        unreachable=by("unreachable"),
        exemption_rate=len(items) / total if total else 0.0,
        classified=items,
    )
