"""A 小试驱动：航向 {0°,90°} × 条带起点偏移 {0, w/4, w/2, 3w/4} × 缓冲两档，seed 0 only（默认）。

不修改 planning/。航向 90° = 整个场景绕地块中心旋转 +90°、wind_direction + π/2；
计划在旋转后的坐标系里由 CAW 规划器生成并通过 safety，之后航段逆旋转回原坐标系，
由 scripts/a_trial_eval.py 在原坐标系、原风向下独立评价。

偏移：fixed_y_lanes 的条带网格锚在 min(目标中心x − 半径)（随场景一起平移），
所以整体平移场景不会改变条带相对树的位置（本脚本 translation_probe 实测确认）。
最小且不改 planning/ 源码的做法：在本进程内把 planning.planner.fixed_y_lanes 替换成
逐字相同、只把锚点改为 xmin − offset 的版本（planner_api 与 planning.zones.classify
读取的是同一个模块属性，规划、切带、classify 与 safety 的排除理由保持一致）。
offset>0 等价于：条带网格不动，树相对网格沿 +x（规划坐标系的条带法向）平移 offset。

用法：/home/box/.venvs/mpl/bin/python scripts/a_trial_heading.py [--seed 0] [--workers 6]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import argparse
import copy
import csv
import inspect
import json
import math
import os
import platform
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor

import a_trial_eval as ev
from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from random_scene import generate_with_report

OPTIONS = dict(step_xy=2.0, max_grid_nodes=5_000_000, max_expansions=500_000)  # 与主消融/seed0 健全性相同
JOB = json.loads((ROOT / "configs/job.ablation.crosswind.json").read_text())
TIERS = {2.0: 10.0, 4.0: 16.0}  # U → d（孔令标 2026 查表）
HEADINGS = (0, 90)


# ---------- 场景变换 ----------
def _rot(p, k, c):
    """绕 c 逆时针旋转 k*90°（精确整数变换）。"""
    x, y = p[0] - c[0], p[1] - c[1]
    for _ in range(k % 4):
        x, y = -y, x
    return [c[0] + x, c[1] + y] + list(p[2:])


def _rot_box(lo, hi, k, c):
    pts = [_rot([lo[0], lo[1]], k, c), _rot([hi[0], hi[1]], k, c)]
    return ([min(p[0] for p in pts), min(p[1] for p in pts)] + list(lo[2:]),
            [max(p[0] for p in pts), max(p[1] for p in pts)] + list(hi[2:]))


def plot_center(scene):
    vs = scene["plot"]["vertices"]
    xs = [v[0] for v in vs]
    ys = [v[1] for v in vs]
    return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]


def rotate_scene(scene, k, c):
    s = copy.deepcopy(scene)
    if k % 4 == 0:
        return s
    s["plot"]["vertices"] = [_rot(v, k, c) for v in s["plot"]["vertices"]]
    s["extent"]["min"], s["extent"]["max"] = _rot_box(s["extent"]["min"], s["extent"]["max"], k, c)
    for t in s["trees"]:
        t["position"] = _rot(t["position"], k, c)
        for part in ("trunk", "canopy"):
            t[part]["center"] = _rot(t[part]["center"], k, c)
    for t in s["targets"]:
        t["geometry"]["center"] = _rot(t["geometry"]["center"], k, c)
    for lp in s["launch_points"]:
        lp["position"] = _rot(lp["position"], k, c)
    for o in s["obstacles"]:
        o["min"], o["max"] = _rot_box(o["min"], o["max"], k, c)
    for key in ("no_fly_zones", "no_spray_zones"):
        for z in s.get(key) or []:
            z["footprint"]["vertices"] = [_rot(v, k, c) for v in z["footprint"]["vertices"]]
    return s


def translate_scene(scene, dx):
    s = copy.deepcopy(scene)
    sh = lambda p: [p[0] + dx] + list(p[1:])  # noqa: E731
    s["plot"]["vertices"] = [sh(v) for v in s["plot"]["vertices"]]
    s["extent"]["min"], s["extent"]["max"] = sh(s["extent"]["min"]), sh(s["extent"]["max"])
    for t in s["trees"]:
        t["position"] = sh(t["position"])
        for part in ("trunk", "canopy"):
            t[part]["center"] = sh(t[part]["center"])
    for t in s["targets"]:
        t["geometry"]["center"] = sh(t["geometry"]["center"])
    for lp in s["launch_points"]:
        lp["position"] = sh(lp["position"])
    for o in s["obstacles"]:
        o["min"], o["max"] = sh(o["min"]), sh(o["max"])
    for key in ("no_fly_zones", "no_spray_zones"):
        for z in s.get(key) or []:
            z["footprint"]["vertices"] = [sh(v) for v in z["footprint"]["vertices"]]
    return s


# ---------- 偏移：进程内替换 fixed_y_lanes 锚点 ----------
_ORIG_SRC = None


def install_lane_offset(offset):
    import planning.planner as pp
    import planner_api

    global _ORIG_SRC
    if _ORIG_SRC is None:
        _ORIG_SRC = inspect.getsource(pp.fixed_y_lanes)
    needle = '    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in targets)\n'
    assert _ORIG_SRC.count(needle) == 1, "fixed_y_lanes 源码与预期不符"
    src = _ORIG_SRC.replace(needle, needle + f"    xmin = xmin - {float(offset)!r}\n")
    ns = {}
    exec(compile(src, "<fixed_y_lanes offset>", "exec"), pp.__dict__, ns)
    fn = ns["fixed_y_lanes"]
    pp.fixed_y_lanes = fn
    planner_api.fixed_y_lanes = fn
    return fn


def scene0(seed):
    s, _ = generate_with_report("ha_orchard", seed, {"plot_width": 100.0, "plot_height": 100.0})
    return _inject_downwind_no_spray(s)


def translation_probe(seed):
    """平移整个场景是否改变条带相对树的位置。"""
    from planning.planner import fixed_y_lanes

    s = scene0(seed)
    w = float(JOB["swath"])
    raw = {**JOB, "buffer_expand": 0.0}
    base = fixed_y_lanes(s, raw)["lanes"]
    shifted = fixed_y_lanes(translate_scene(s, w / 4), raw)["lanes"]
    diffs = [b["start"][0] - a["start"][0] for a, b in zip(base, shifted)]
    return dict(n=len(base), n_shifted=len(shifted), lane_x_shift_min=min(diffs), lane_x_shift_max=max(diffs),
                tree_shift=w / 4, lanes_move_with_trees=all(abs(d - w / 4) < 1e-9 for d in diffs))


# ---------- 单次运行 ----------
def run(job):
    seed, U, heading, offset, variant = job["seed"], job["U"], job["heading"], job["offset"], job["variant"]
    from planning import configuration, fingerprint
    from planning.drift import resolve_effective_buffer
    from planner_api import make_planner

    scene = scene0(seed)
    if variant == "rot180_aligned":
        # 180° 后条带锚在旋转系 xmin' = 2cx − xmax；取 o ≡ xmin − xmax (mod w) 使条带网格回映后与原网格重合
        g = [t["geometry"] for t in scene["targets"]]
        xmin = min(t["center"][0] - t["radius"] for t in g)
        xmax = max(t["center"][0] + t["radius"] for t in g)
        offset = (xmin - xmax) % float(JOB["swath"])
    install_lane_offset(offset)
    import planning.planner as pp

    wd0 = 0.0
    if variant == "no_zone":
        scene["no_spray_zones"] = []
    elif variant == "wind_away":
        wd0 = math.pi
    raw0 = {**JOB, "drift_mode": "sort", "wind_speed": float(U), "wind_direction": wd0, "buffer_expand": 1.0}
    c0 = configuration(raw0)
    d = resolve_effective_buffer(c0)
    assert d == TIERS[U], (d, U)
    k = {0: 0, 90: 1, 180: 2}[heading]
    ctr = plot_center(scene)
    pscene = rotate_scene(scene, k, ctr)
    praw = {**raw0, "wind_direction": wd0 + k * math.pi / 2}
    layout = pp.fixed_y_lanes(pscene, praw)
    n_lanes = len(layout["lanes"])
    t0 = time.perf_counter()
    plan = make_planner("caw").plan(pscene, praw, options=OPTIONS)
    solve = time.perf_counter() - t0
    row = dict(lane_offset_used=offset, seed=seed, variant=variant, U=U, d=d, heading=heading, offset=offset, wind_direction=wd0,
               plan_wind_direction=praw["wind_direction"], n_lanes=n_lanes, strip_count=layout["strip_count"],
               status=plan.get("status"), stage=plan.get("stage"), reason=(plan.get("reason") or "")[:300],
               solve_seconds=round(solve, 1))
    if plan.get("status") != "success":
        return row, None
    row["plan_hash"] = fingerprint(plan)
    row["matrix_mode"] = plan["order_search"]["matrix_mode"]
    row["order_strategy"] = plan["order_search"]["strategy"]
    row["plan_frame_duration"] = plan.get("objective_value")
    row["excluded_targets"] = len(plan.get("excluded_targets") or [])
    back = []
    for s in plan["segments"]:
        b = dict(s)
        b["start"] = _rot(s["start"], -k, ctr)
        b["end"] = _rot(s["end"], -k, ctr)
        back.append(b)
    res = ev.evaluate(scene, back, d, wd0, float(c0["swath"]), float(c0["speed"]), dict(c0))
    row["time_reeval_minus_plan_frame"] = res["total_time"] - row["plan_frame_duration"]
    for key in ("A_C", "A_excluded", "A_extra_tau0", "A_extra_tau0.5", "violations", "spray_samples",
                "cut_segments", "cut_boundaries", "total_time", "path_length", "path_spray", "path_cut_off",
                "path_transit_other"):
        row[key] = res[key]
    row["conv_rel"] = {k2: v["rel_diff"] for k2, v in res["convergence"].items()}
    row["conv_abs"] = {k2: v["abs_diff"] for k2, v in res["convergence"].items()}
    return row, dict(segments=[dict(start=s["start"], end=s["end"], spray=s["spray"], type=s["type"]) for s in back], F=res["F"])


def jobs_for(seed, w):
    out = []
    for U in TIERS:
        for h in HEADINGS:
            for off in (0.0, w / 4, w / 2, 3 * w / 4):
                out.append(dict(seed=seed, U=U, heading=h, offset=off, variant="main"))
        out.append(dict(seed=seed, U=U, heading=0, offset=0.0, variant="no_zone"))
        out.append(dict(seed=seed, U=U, heading=0, offset=0.0, variant="wind_away"))
        out.append(dict(seed=seed, U=U, heading=180, offset=0.0, variant="rot180"))
        out.append(dict(seed=seed, U=U, heading=180, offset=0.0, variant="rot180_aligned"))
    # 慢的（U=4）先跑
    return sorted(out, key=lambda j: -j["U"])


SCHEME_KEY = "min A_extra_tau0, tie-break min total_time; only safety-passed (status=success) main rows eligible"
SCHEME_DEFS = {
    "S1": "heading 0, offset 0",
    "S2": "best of heading {0,90} at offset 0",
    "S2'": "best offset {0,w/4,w/2,3w/4} at heading 0",
    "S3": "best of heading {0,90} x 4 offsets",
}


def schemes_summary(rows):
    """S1/S2/S2'/S3 选择（只在 safety 通过的 main 行里选）及差值。"""
    metrics = ("A_excluded", "A_extra_tau0", "A_extra_tau0.5", "total_time", "cut_segments", "n_lanes")
    out = dict(rule=SCHEME_KEY, defs=SCHEME_DEFS, tiers={})
    for U in sorted({r["U"] for r in rows}):
        main_rows = [r for r in rows if r["variant"] == "main" and r["U"] == U]
        ok = [r for r in main_rows if r.get("status") == "success"]
        pools = {
            "S1": [r for r in ok if r["heading"] == 0 and r["offset"] == 0.0],
            "S2": [r for r in ok if r["offset"] == 0.0],
            "S2'": [r for r in ok if r["heading"] == 0],
            "S3": list(ok),
        }
        tier = dict(failed_rows=[dict(heading=r["heading"], offset=r["offset"], stage=r.get("stage"), reason=r.get("reason"))
                                 for r in main_rows if r.get("status") != "success"], schemes={}, diffs={})
        for name, pool in pools.items():
            if not pool:
                tier["schemes"][name] = None
                continue
            b = min(pool, key=lambda r: (r["A_extra_tau0"], r["total_time"]))
            tier["schemes"][name] = dict(heading=b["heading"], offset=b["offset"], n_candidates=len(pool),
                                         **{m: b.get(m) for m in metrics})
        s3 = tier["schemes"].get("S3")
        for ref in ("S1", "S2", "S2'"):
            r = tier["schemes"].get(ref)
            tier["diffs"][f"S3-{ref}"] = None if (s3 is None or r is None) else {
                m: s3[m] - r[m] for m in ("A_excluded", "A_extra_tau0", "A_extra_tau0.5", "total_time", "cut_segments", "n_lanes")}
        out["tiers"][f"U={U:g}"] = tier
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only-rot180-aligned", action="store_true",
                    help="只跑 180° 且条带网格对齐的一致性对照（结果写 *_rot180aligned.*）")
    a = ap.parse_args()
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    w = float(JOB["swath"])
    probe = translation_probe(a.seed)
    print("translation_probe", json.dumps(probe), flush=True)
    jobs = jobs_for(a.seed, w)
    if a.only_rot180_aligned:
        jobs = [dict(seed=a.seed, U=U, heading=180, offset=0.0, variant="rot180_aligned") for U in TIERS]
    t0 = time.time()
    rows, geoms = [], {}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for row, g in ex.map(run, jobs):
            print(json.dumps({k: row.get(k) for k in ("variant", "U", "heading", "offset", "status", "A_excluded", "A_extra_tau0", "total_time", "violations", "solve_seconds")}), flush=True)
            rows.append(row)
            if g:
                geoms[f'{row["variant"]}_U{row["U"]:g}_h{row["heading"]}_o{row["offset"]:g}'] = g
    wall = time.time() - t0
    out = ROOT / f"results/a_trial_seed{a.seed}_{sha}" if not a.only_rot180_aligned else ROOT / f"results/a_trial_seed{a.seed}_{sha}_rot180aligned"
    cols = ["seed", "variant", "lane_offset_used", "U", "d", "heading", "offset", "wind_direction", "status", "stage", "A_excluded",
            "A_extra_tau0", "A_extra_tau0.5", "total_time", "path_length", "path_spray", "path_cut_off",
            "path_transit_other", "cut_segments", "cut_boundaries", "violations", "spray_samples", "excluded_targets",
            "n_lanes", "strip_count", "matrix_mode", "order_strategy", "plan_frame_duration",
            "time_reeval_minus_plan_frame", "A_C", "solve_seconds", "plan_hash", "reason"]
    with open(str(out) + ".csv", "w", newline="", encoding="utf8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in sorted(rows, key=lambda r: (r["variant"], r["U"], r["heading"], r["offset"])):
            wr.writerow(r)
    cpu = ""
    try:
        cpu = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception:
        pass
    meta = dict(commit=sha, worktree_dirty_tracked=bool(dirty), seed=a.seed, cpu=cpu, nproc=os.cpu_count(),
                python=platform.python_version(), workers=a.workers, wall_seconds=round(wall, 1), job=JOB,
                tiers={f"U={k:g}": f"d={v:g}" for k, v in TIERS.items()}, planner="caw", options=OPTIONS,
                drift_mode="sort", buffer_expand=1.0, scene="ha_orchard 100x100 + _inject_downwind_no_spray",
                resolutions=[0.1, 0.05], tau_s=[0.0, 0.5], tau_label="假设值（无设备数据）",
                offset_impl="in-process fixed_y_lanes anchor xmin-offset (planning/ source unchanged)",
                translation_probe=probe,
                convergence={f'{r["variant"]}_U{r["U"]:g}_h{r["heading"]}_o{r["offset"]:g}': dict(rel=r.get("conv_rel"), abs=r.get("conv_abs")) for r in rows},
                rows_full=rows)
    Path(str(out) + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    Path(str(out) + ".geom.json").write_text(json.dumps(geoms))
    summ = schemes_summary(rows)
    Path(str(out) + ".summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    print("schemes", json.dumps(summ, ensure_ascii=False), flush=True)
    print("wrote", str(out) + ".csv", "wall", round(wall, 1))


if __name__ == "__main__":
    main()
