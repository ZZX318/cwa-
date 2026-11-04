"""A 小试 seed0：重叠判定修复前后逐行对比（旧 c92be77 + 0f3a583 rot180aligned vs 新表）。

“为什么变”的证据：用旧表 geom.json 里的旧计划喷洒航段（原坐标系）与评价器 F（原坐标系，
与修复无关），分别用旧网格实现（drift_checks 里逐字拷贝）和新精确面积实现判断足迹∩F，
统计旧实现漏判（old=False, new=True）的航段数与精确重叠面积。足迹 = 航段两侧各 swath/2。
用法：python scripts/a_trial_diff.py NEW_PREFIX  （如 results/a_trial_seed0_22ed961）
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import planning.zones as zones  # noqa: E402
from planning.zones import _EPS, _on_poly_boundary  # noqa: E402
from scene.geometry import in_polygon, segments_intersect  # noqa: E402

SWATH = 2.0
FIELDS = ["status", "stage", "A_excluded", "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time", "n_lanes", "strip_count",
          "cut_segments", "cut_boundaries", "excluded_targets", "violations", "spray_samples", "path_spray", "plan_hash"]
NUM_TOL = 1e-6


def old_grid_overlap(rect, polygon) -> bool:
    """bb22ae6 之前的 rect_poly_positive_overlap（逐字）。"""
    (x0, y0), (x1, y1) = rect
    if x1 - x0 <= _EPS or y1 - y0 <= _EPS:
        return False
    vs = polygon["vertices"]
    samples = [
        [(x0 + x1) / 2, (y0 + y1) / 2],
        [x0 + (x1 - x0) * 0.25, y0 + (y1 - y0) * 0.25],
        [x0 + (x1 - x0) * 0.75, y0 + (y1 - y0) * 0.25],
        [x0 + (x1 - x0) * 0.25, y0 + (y1 - y0) * 0.75],
        [x0 + (x1 - x0) * 0.75, y0 + (y1 - y0) * 0.75],
    ]
    if any(in_polygon(p, polygon) and not _on_poly_boundary(p, polygon) for p in samples):
        if any(
            in_polygon(p, polygon)
            and min(p[0] - x0, x1 - p[0], p[1] - y0, y1 - p[1]) > _EPS
            for p in samples
            if in_polygon(p, polygon)
        ):
            return True
    for v in vs:
        if x0 + _EPS < v[0] < x1 - _EPS and y0 + _EPS < v[1] < y1 - _EPS:
            return True
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    redges = list(zip(corners, corners[1:] + corners[:1]))
    pedges = list(zip(vs, vs[1:] + vs[:1]))
    for a, b in redges:
        for c, d in pedges:
            if segments_intersect(a, b, c, d):
                mx, my = (a[0] + b[0] + c[0] + d[0]) / 4, (a[1] + b[1] + c[1] + d[1]) / 4
                if x0 + _EPS < mx < x1 - _EPS and y0 + _EPS < my < y1 - _EPS and in_polygon([mx, my], polygon):
                    return True
    nx = max(3, int((x1 - x0) / 0.1))
    ny = max(3, int((y1 - y0) / 0.1))
    for i in range(1, nx):
        for j in range(1, ny):
            p = [x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny]
            if in_polygon(p, polygon):
                return True
    return False


def footprint(seg):
    (ax, ay), (bx, by) = seg["start"][:2], seg["end"][:2]
    h = SWATH / 2
    if abs(ax - bx) < 1e-9:  # 沿 Y
        return ([ax - h, min(ay, by)], [ax + h, max(ay, by)])
    assert abs(ay - by) < 1e-9, seg
    return ([min(ax, bx), ay - h], [max(ax, bx), ay + h])


def missed_by_old(geom):
    out = dict(n_spray=0, old_true=0, new_true=0, missed=0, missed_area=0.0, missed_max_area=0.0, false_pos=0, missed_examples=[])
    for seg in geom["segments"]:
        if not seg["spray"]:
            continue
        out["n_spray"] += 1
        r = footprint(seg)
        for z in geom["F"]:
            poly = {"vertices": z["vertices"]}
            o, n = old_grid_overlap(r, poly), zones.rect_poly_positive_overlap(r, poly)
            area = zones._shoelace_area(zones._clip_polygon_to_rect(poly["vertices"], r[0][0], r[0][1], r[1][0], r[1][1]))
            out["old_true"] += o
            out["new_true"] += n
            if n and not o:
                out["missed"] += 1
                out["missed_area"] += area
                out["missed_max_area"] = max(out["missed_max_area"], area)
                if len(out["missed_examples"]) < 3:
                    out["missed_examples"].append(dict(rect=r, zone=z["id"], area=round(area, 6)))
            if o and not n:
                out["false_pos"] += 1
    return out


def key(r):
    return (r["variant"], float(r["U"]), int(float(r["heading"])), float(r["offset"]))


def load(path):
    with open(path, encoding="utf8") as fh:
        return {key(r): r for r in csv.DictReader(fh)}


def kname(k):
    return f"{k[0]}_U{k[1]:g}_h{k[2]}_o{k[3]:g}"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    new_prefix = sys.argv[1]
    old = load(ROOT / "results/a_trial_seed0_c92be77.csv")
    old_al = load(ROOT / "results/a_trial_seed0_0f3a583_rot180aligned.csv")
    for k, r in old_al.items():  # rot180_aligned 在旧表里 offset 列=1.75；新表 offset 列同样记 used offset
        old[k] = r
    og = json.loads((ROOT / "results/a_trial_seed0_c92be77.geom.json").read_text())
    og.update(json.loads((ROOT / "results/a_trial_seed0_0f3a583_rot180aligned.geom.json").read_text()))
    new = load(ROOT / (new_prefix + ".csv"))
    ng = json.loads((ROOT / (new_prefix + ".geom.json")).read_text())
    keys = sorted(set(old) | set(new))
    rows = []
    for k in keys:
        o, n = old.get(k), new.get(k)
        d = dict(row=kname(k), in_old=o is not None, in_new=n is not None, changes={})
        if o and n:
            for f in FIELDS:
                if f not in o:  # 旧表无此列（如 A_extra_tau1）：不算变化
                    continue
                a, b = o.get(f, ""), n.get(f, "")
                fa, fb = num(a), num(b)
                if fa is not None and fb is not None:
                    if abs(fa - fb) > NUM_TOL:
                        d["changes"][f] = dict(old=fa, new=fb, delta=fb - fa)
                elif a != b:
                    d["changes"][f] = dict(old=a, new=b)
        gk = kname(k)
        if gk in og:
            d["old_plan_vs_F"] = missed_by_old(og[gk])
        if gk in og and gk in ng:
            d["F_identical"] = og[gk]["F"] == ng[gk]["F"]
        if gk in ng:
            nchk = missed_by_old(ng[gk])
            d["new_plan_vs_F"] = dict(n_spray=nchk["n_spray"], new_true=nchk["new_true"], old_true=nchk["old_true"])
        d["reason_old"] = (o or {}).get("reason", "")
        d["reason_new"] = (n or {}).get("reason", "")
        rows.append(d)
    out = ROOT / (new_prefix + ".diff_vs_c92be77.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for d in rows:
        ch = ", ".join(f"{f}:{v.get('old')}→{v.get('new')}" for f, v in d["changes"].items() if f != "plan_hash")
        m = d.get("old_plan_vs_F", {})
        print(f"{d['row']}: {'UNCHANGED' if not d['changes'] else ch} | old-plan missed={m.get('missed')} "
              f"area={m.get('missed_area', 0):.6f} | hash_changed={'plan_hash' in d['changes']}")
    print("wrote", out)


if __name__ == "__main__":
    main()
