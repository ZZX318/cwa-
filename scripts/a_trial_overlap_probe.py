"""A 小试 seed0：在规划坐标系里逐条带复现 planner 的禁喷 Y 切片扫描（0.05 m 切片 × 喷幅宽），
分别用旧网格实现与新精确面积实现判定，列出旧实现漏判（新判有重叠、旧判无）的条带。
解释修复前后哪些行变化及原因。用法：python scripts/a_trial_overlap_probe.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import a_trial_heading as H  # noqa: E402
from a_trial_diff import old_grid_overlap  # noqa: E402
import planning.zones as zones  # noqa: E402
from planning.model import configuration  # noqa: E402
from planning.drift import expand_sensitive_inward  # noqa: E402
from scene.geometry import polygon_bounds  # noqa: E402


def scan(fn, zone, xa, xb, lo, hi, step=0.05):
    n = 0
    y = lo
    while y < hi - 1e-12:
        y1 = min(hi, y + step)
        if fn(([xa, y], [xb, y1]), zone["footprint"]):
            n += 1
        y = y1
    return n


def probe(U, heading, offset, variant="main"):
    scene = H.scene0(0)
    if variant == "rot180_aligned":
        g = [t["geometry"] for t in scene["targets"]]
        offset = (min(t["center"][0] - t["radius"] for t in g) - max(t["center"][0] + t["radius"] for t in g)) % float(H.JOB["swath"])
    H.install_lane_offset(offset)
    import planning.planner as pp
    wd0 = math.pi if variant == "wind_away" else 0.0
    if variant == "no_zone":
        scene["no_spray_zones"] = []
    k = {0: 0, 90: 1, 180: 2}[heading]
    ctr = H.plot_center(scene)
    pscene = H.rotate_scene(scene, k, ctr)
    praw = {**H.JOB, "drift_mode": "sort", "wind_speed": float(U), "wind_direction": wd0 + k * math.pi / 2, "buffer_expand": 1.0}
    c0 = configuration(praw)
    ex = expand_sensitive_inward(pscene, c0)
    layout = pp.fixed_y_lanes(ex, praw)
    sw = float(layout["config"]["swath"])
    diffs = []
    for li, lane in enumerate(layout["lanes"]):
        x = lane["start"][0]
        lo_l, hi_l = sorted([lane["start"][1], lane["end"][1]])
        for z in ex.get("no_spray_zones", []):
            b = polygon_bounds(z["footprint"])
            xa, xb = x - sw / 2, x + sw / 2
            if not (xa < b["max"][0] - 1e-9 and b["min"][0] < xb - 1e-9):
                continue
            lo, hi = max(lo_l, b["min"][1]), min(hi_l, b["max"][1])
            n_old = scan(old_grid_overlap, z, xa, xb, lo, hi)
            n_new = scan(zones.rect_poly_positive_overlap, z, xa, xb, lo, hi)
            if n_old != n_new:
                area = zones._shoelace_area(zones._clip_polygon_to_rect(z["footprint"]["vertices"], xa, lo_l, xb, hi_l))
                xov = min(xb, b["max"][0]) - max(xa, b["min"][0])
                diffs.append(dict(lane=li, lane_x=round(x, 6), zone=z["id"], slices_old=n_old, slices_new=n_new,
                                  x_overlap_aabb=round(xov, 6), exact_area_lane_vs_zone=round(area, 6)))
    return dict(variant=variant, U=U, heading=heading, offset=offset, n_lanes=len(layout["lanes"]), lanes_changed=diffs)


def main():
    out = []
    for U in H.TIERS:
        for h in H.HEADINGS:
            for off in (0.0, 0.5, 1.0, 1.5):
                out.append(probe(U, h, off))
        for v, h in (("no_zone", 0), ("wind_away", 0), ("rot180", 180), ("rot180_aligned", 180)):
            out.append(probe(U, h, 0.0, v))
    for r in out:
        print(f'{r["variant"]} U={r["U"]:g} h={r["heading"]} o={r["offset"]:g} lanes={r["n_lanes"]} changed={len(r["lanes_changed"])} {r["lanes_changed"]}')
    (ROOT / "results/a_trial_seed0_overlap_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
