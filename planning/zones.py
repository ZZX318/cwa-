"""禁喷/禁飞区目标分类与误喷度量（代码与论文统一口径）。

口径（技术负责人 2026-11-04，按论文写作定义）：
- exempt_no_spray：树冠外接框（外扩 drift_buffer 后）整个落在某个禁喷区 AABB 内。
- unreachable_no_fly：不是禁喷豁免，且在固定 Y 作业带模型下（同一 lane 布局、同一喷幅、
  禁喷/禁飞切割后），没有任何保留下来的喷洒足迹与树冠正面积相交，且树冠触及
  禁飞区外扩 (clearance + swath/2) 的范围——即不可达由禁飞区几何造成。
- unreachable_no_spray：部分重叠禁喷区、但切割后没有可行足迹能碰到（诊断类，计入豁免率）。
- 其余目标都是应喷目标，数量为 N_eligible；与规划器无关，基线与新方法共用同一个 N。
"""

from scene.geometry import polygon_bounds
from .footprint import boxes_touch, overlaps_target, rectangle

_EPS = 1e-9


def zone_box(zone):
    b = polygon_bounds(zone["footprint"])
    return (list(b["min"]), list(b["max"]))


def crown_box(target, buffer=0.0):
    x, y = target["geometry"]["center"]
    r = target["geometry"]["radius"] + buffer
    return ([x - r, y - r], [x + r, y + r])


def inside(box, outer):
    return all(outer[0][i] - _EPS <= box[0][i] and box[1][i] <= outer[1][i] + _EPS for i in (0, 1))


def overlap_area(a, b):
    w = min(a[1][0], b[1][0]) - max(a[0][0], b[0][0])
    h = min(a[1][1], b[1][1]) - max(a[0][1], b[0][1])
    return w * h if w > 0 and h > 0 else 0.0


def reachable_targets(scene, c):
    """固定 Y 作业带模型下，切割后仍有正面积喷洒足迹的目标 id 集合。"""
    from .planner import fixed_y_lanes, lane_parts

    out = set()
    geometry = {t["id"]: t["geometry"] for t in scene["targets"]}
    for lane in fixed_y_lanes(scene, c)["lanes"]:
        for part in lane_parts(scene, lane, c):
            if part["type"] != "spray":
                continue
            foot = rectangle(part, c["swath"])
            out.update(tid for tid in part["target_ids"] if overlaps_target(foot, geometry[tid]))
    return out


def classify(scene, c, buffer=0.0):
    """返回 {target_id: entry}，entry 含 reason 与 zone_ids；未列出的即应喷目标。"""
    no_spray = [(z["id"], zone_box(z)) for z in scene.get("no_spray_zones", [])]
    no_fly = [(z["id"], zone_box(z)) for z in scene.get("no_fly_zones", [])]
    reach = reachable_targets(scene, c) if (no_spray or no_fly) else None
    pad = c["clearance"] + c["swath"] / 2.0
    out = {}
    for t in scene["targets"]:
        box = crown_box(t, buffer)
        holders = [zid for zid, zb in no_spray if inside(box, zb)]
        if holders:
            out[t["id"]] = dict(target_id=t["id"], reason="no_spray", zone_ids=holders)
            continue
        if reach is None or t["id"] in reach:
            continue
        flies = [
            zid
            for zid, zb in no_fly
            if boxes_touch(box, ([zb[0][0] - pad, zb[0][1] - pad], [zb[1][0] + pad, zb[1][1] + pad]))
        ]
        if flies:
            out[t["id"]] = dict(target_id=t["id"], reason="no_fly", zone_ids=flies)
            continue
        sprays = [zid for zid, zb in no_spray if boxes_touch(box, zb)]
        if sprays:
            out[t["id"]] = dict(target_id=t["id"], reason="no_spray_cut", zone_ids=sprays)
    return out


def summary(scene, excluded):
    total = len(scene["targets"])
    by = lambda r: sorted(e["target_id"] for e in excluded if e["reason"] == r)
    return dict(
        N_total=total,
        N_eligible=total - len(excluded),
        exempt_no_spray=by("no_spray"),
        unreachable_no_fly=by("no_fly"),
        unreachable_no_spray=by("no_spray_cut"),
        exemption_rate=len(excluded) / total if total else 0.0,
    )
