"""总览项 2：覆盖率异常最小复现（seed 0 缓冲健全性：d=10 coverage=0.9546，d=16 coverage=1.0）。

数字来源：results/buffer_fix_seed0_00a596b.json（commit 9903568，scripts/buffer_fix_seed0.py）
  coverage = experiment._metrics -> evaluation.at()["coverage"]
           = covered_cells / total_cells
  total_cells = evaluation.build() 里 0.5 m 采样、只含"应喷目标"（不在 planning.zones.classify 结果里的树）的树冠单元数
  covered_cells = 被至少一个喷洒段矩形（rectangle(seg, swath)）盖住的上述单元数

本脚本逐条检验技术负责人的三个假设：
  H1 d=16 时缓冲没生效
  H2 分母被缩小（可喷面积/应喷目标排除了缓冲区）
  H3 缓冲区被裁到场地外
Part A（不规划，秒级）：几何 + classify + 分母单元统计，并给出"任何合法计划"的覆盖率上界
  UB = 1 - (应喷树冠单元中落在外扩禁喷区内部的单元数) / total_cells。
Part B（--plan，CAW 规划，与 buffer_fix_seed0.py 同 JOB/OPTIONS）：复算 coverage，
  按树列出未覆盖单元，并用独立栅格评价器 scripts/a_trial_eval.py 交叉核对 A_C/A_excluded/A_extra。
用法：/home/box/.venvs/mpl/bin/python scripts/coverage_anomaly_repro.py [--plan] [--out results/coverage_anomaly_<sha>.json]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import argparse
import json
import math
import subprocess
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from planning import configuration
from planning.drift import expand_sensitive_inward, resolve_effective_buffer
from planning.zones import classify
from random_scene import generate_with_report

OPTIONS = dict(step_xy=2.0, max_grid_nodes=5_000_000, max_expansions=500_000)
JOB = json.loads((ROOT / "configs/job.ablation.crosswind.json").read_text())
RES = 0.5  # evaluation.build 默认分辨率


def scene0():
    s, _ = generate_with_report("ha_orchard", 0, {"plot_width": 100.0, "plot_height": 100.0})
    return _inject_downwind_no_spray(s)


def raw_for(U, be):
    return {**JOB, "drift_mode": "sort", "wind_speed": float(U), "buffer_expand": float(be)}


def _in_rect_strict(x, y, b):
    return b[0][0] < x < b[1][0] and b[0][1] < y < b[1][1]


def eligible_cells(scene, excl):
    """与 evaluation.build 完全相同的采样规则。"""
    cells = []
    for t in scene["targets"]:
        if t["id"] in excl:
            continue
        g = t["geometry"]
        x, y = g["center"]
        r = g["radius"]
        for ix in range(math.floor((x - r) / RES), math.ceil((x + r) / RES)):
            for iy in range(math.floor((y - r) / RES), math.ceil((y + r) / RES)):
                cx, cy = (ix + 0.5) * RES, (iy + 0.5) * RES
                if math.hypot(cx - x, cy - y) <= r:
                    cells.append((t["id"], ix, iy, cx, cy))
    return cells


def part_a(U, be):
    scene = scene0()
    raw = raw_for(U, be)
    c = configuration(raw)
    d = resolve_effective_buffer(c)
    geo = expand_sensitive_inward(scene, c)
    zv = geo["no_spray_zones"][0]["footprint"]["vertices"]
    zb = ([min(v[0] for v in zv), min(v[1] for v in zv)], [max(v[0] for v in zv), max(v[1] for v in zv)])
    excl = classify(scene, c)
    cells = eligible_cells(scene, excl)
    inside = [cl for cl in cells if _in_rect_strict(cl[3], cl[4], zb)]
    # 与缓冲边界 x=zb.max 相交（跨界）的应喷树
    straddle = []
    for t in scene["targets"]:
        if t["id"] in excl:
            continue
        g = t["geometry"]
        x, y = g["center"]
        r = g["radius"]
        if x - r < zb[1][0] < x + r and zb[0][1] < y < zb[1][1]:
            straddle.append(dict(id=t["id"], cx=x, cy=y, r=r))
    # 第 1..4 列树的 x 范围（列号取 id 中 target-tree-CC-RR 的 CC）
    cols = {}
    for t in scene["targets"]:
        parts = t["id"].split("-")
        if len(parts) >= 4 and parts[2].isdigit():
            col = int(parts[2])
            if col <= 4:
                g = t["geometry"]
                lo, hi = g["center"][0] - g["radius"], g["center"][0] + g["radius"]
                a = cols.setdefault(col, [math.inf, -math.inf, 0])
                a[0] = min(a[0], lo); a[1] = max(a[1], hi); a[2] += 1
    # 不规划的预测：只用 fixed_y_lanes + lane_parts 的喷洒子段（buffer_fix_seed0.json 已证 plan_spray_len == lane_spray_len）
    from planning.footprint import rectangle
    from planning.planner import fixed_y_lanes, lane_parts
    lay = fixed_y_lanes(geo, raw)
    rects, cut_x = [], []
    for L in lay["lanes"]:
        ps = lane_parts(geo, L, lay["config"])
        if any(p["type"] != "spray" for p in ps):
            cut_x.append(round(L["start"][0], 4))
        for p in ps:
            if p["type"] == "spray":
                rects.append(rectangle(dict(start=p["start"], end=p["end"]), float(lay["config"]["swath"])))
    lost = [cl for cl in cells if not any(f[0][0] <= cl[3] <= f[1][0] and f[0][1] <= cl[4] <= f[1][1] for f in rects)]
    lost_by_tree = dict(Counter(cl[0] for cl in lost))
    w = float(lay["config"]["swath"])
    cut_strips = sorted({(round(x - w / 2, 4), round(x + w / 2, 4)) for x in cut_x})
    return dict(
        U=U, buffer_expand=be, d=d,
        lane_cut_strips_x=cut_strips,
        predicted_lost_cells_no_plan=len(lost),
        predicted_coverage_no_plan=1 - len(lost) / len(cells) if cells else None,
        predicted_lost_by_tree=lost_by_tree,
        lost_cells_x_range=[min(cl[3] for cl in lost), max(cl[3] for cl in lost)] if lost else None,
        extent=scene["extent"], plot=scene["plot"]["vertices"],
        zone_original=scene["no_spray_zones"][0]["footprint"]["vertices"], zone_expanded=zv,
        expanded_xmax_minus_original=zb[1][0] - (-1.0),
        N_total=len(scene["targets"]), classify_excluded=len(excl),
        classify_reasons=dict(Counter(e["reason"] for e in excl.values())),
        total_cells=len(cells), eligible_cells_inside_expanded_zone=len(inside),
        coverage_upper_bound_any_legal_plan=1 - len(inside) / len(cells) if cells else None,
        straddling_eligible_trees=straddle,
        tree_columns_x_range={str(k): dict(xmin=round(v[0], 4), xmax=round(v[1], 4), n=v[2]) for k, v in sorted(cols.items())},
    )


def part_b(args):
    U, be = args
    import a_trial_eval as ev
    from evaluation import at, build as eval_build
    from execution import build
    from planning import fingerprint
    from planner_api import make_planner

    scene = scene0()
    raw = raw_for(U, be)
    c = configuration(raw)
    d = resolve_effective_buffer(c)
    plan = make_planner("caw").plan(scene, raw, options=OPTIONS)
    out = dict(U=U, buffer_expand=be, d=d, status=plan.get("status"))
    if plan.get("status") != "success":
        out["reason"] = plan.get("reason")
        return out
    tl = build(scene, plan)
    evb = eval_build(scene, plan, tl)
    m = at(evb, tl, tl["duration"])
    per_tree_missed = {x["target_id"]: x["missed"] for x in m["target_stats"] if x["missed"] > 0}
    out.update(
        plan_hash=fingerprint(plan),
        coverage=m["coverage"], total_cells=m["total_cells"], covered_cells=m["covered_cells"],
        missed_cells=m["missed_cells"], N_eligible=m.get("N_eligible"), target_coverage=m.get("target_coverage"),
        per_tree_missed_cells=per_tree_missed, misspray_area=m["misspray"]["area"],
    )
    r = ev.evaluate(scene, plan["segments"], d, float(raw["wind_direction"]), float(c["swath"]), float(c["speed"]), dict(c),
                    taus=(0.0,), resolutions=(0.1, 0.05))
    A_C, A_ex, A_x = r["A_C"], r["A_excluded"], r["A_extra_tau0"]
    out.update(
        eval_A_C=A_C, eval_A_excluded=A_ex, eval_A_extra_tau0=A_x, eval_violations=r["violations"],
        eval_res=0.05,
        # 两种基于独立评价器的对照口径
        eval_cov_of_canopy=(A_C - A_ex - A_x) / A_C,
        eval_cov_of_sprayable=(A_C - A_ex - A_x) / (A_C - A_ex) if A_C > A_ex else None,
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"], text=True).strip()
    jobs = [(2, 0.0), (2, 1.0), (4, 0.0), (4, 1.0)]
    res = dict(sha=sha, job=JOB, options=OPTIONS, eval_resolution=RES)
    res["part_a"] = [part_a(U, be) for U, be in jobs]
    for r in res["part_a"]:
        print(json.dumps({k: v for k, v in r.items() if k not in ("plot", "extent", "zone_original")}, ensure_ascii=False))
    if a.plan:
        with ProcessPoolExecutor(max_workers=4) as ex:
            res["part_b"] = list(ex.map(part_b, jobs))
        for r in res["part_b"]:
            print(json.dumps(r, ensure_ascii=False))
    p = Path(a.out) if a.out else ROOT / f"results/coverage_anomaly_{sha}.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("wrote", p)


if __name__ == "__main__":
    main()
