"""A 小试补跑器：在 a_trial_heading.run 的同一管线（同场景、同规划器选项、同评估器）上补跑额外方案行。

当前注册的方案：
  oh_rot  —— 航向 h 下的几何偏移 o_h(h)（S_h 公式推广到任意 90° 倍数航向），作为 S3 的第 5 个偏移候选。

o_h(h) 的算法（不搜索）：
  1. 把场景绕地块中心旋转 k=h/90 次（与 a_trial_heading.run 完全相同的 rotate_scene），风向 wd0 + k·π/2；
  2. 在该规划坐标系里求外扩禁喷集 F'（a_trial_eval.buffer_set，扫掠多边形）；
  3. 条带法向就是规划系 x'。取 F' 的 x' 端点中严格落在目标 x' 范围 (xmin', xmax') 内的那些边界 e；
  4. o_h = (xmin' − e) mod w，使条带 k 的范围 [xmin' − o + k·w, …] 有一条边恰好与 e 重合；
     若有多个 e，要求它们给出同一个 o_h（mod w，容差 1e-9），否则报错，不静默取其一。
  h=0 时只有 e = x_F（下风扫掠后的园内边界）落在目标范围内，退化为原 S_h 公式 (xmin − x_F) mod w（本脚本对每个 seed×档断言二者一致）。
  h=90 时 F' 的 x' 端点对应原坐标里禁喷区的 y 边界（扫掠沿 +x，不改变 y 范围），两条边都在目标范围内；
  因 95−5=90=45·w，二者给出同一 o_h，且与 d（风速档）无关。

扩展（下一项 1b 的 B-online / B-boundary）：在 VARIANTS 里注册新条目即可。每个条目提供
  jobs(seed, U) -> [dict(heading=..., offset_fn=..., ...)]，offset_fn(scene, pscene, d, wd_plan, w) -> (offset, info)
  若方案需要不同的规划调用，可提供 run_fn(job) -> (row, geom) 覆盖默认的 a_trial_heading.run。

用法：/home/box/.venvs/mpl/bin/python scripts/a_trial_extra_runs.py --variants oh_rot --headings 90 --seeds 0-4 --workers 7
输出：results/a_trial_extra_<variants>_<sha>.{csv,meta.json,geom.json}（行格式与 a_trial_heading 的 CSV 列一致，另加 extra_* 列）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import argparse
import csv
import json
import math
import os
import platform
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import a_trial_eval as ev
import a_trial_heading as H


def oh_rot(scene, heading, d, w):
    """返回 (o_h, info)。scene 为原坐标系场景，wd0=0（主实验风向）。"""
    k = {0: 0, 90: 1, 180: 2, 270: 3}[heading]
    ctr = H.plot_center(scene)
    ps = H.rotate_scene(scene, k, ctr)
    wd = 0.0 + k * math.pi / 2
    F = [f for f in ev.buffer_set(ps, d, wd) if f["swept"]]
    if not F:
        raise ValueError("oh_rot 需要扫掠后的禁喷多边形")
    xs = [v[0] for f in F for v in f["vertices"]]
    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in ps["targets"])
    xmax = max(t["geometry"]["center"][0] + t["geometry"]["radius"] for t in ps["targets"])
    edges = sorted({e for e in (min(xs), max(xs)) if xmin < e < xmax})
    if not edges:
        raise ValueError(f"heading {heading}: F' 的法向边界 {min(xs)}, {max(xs)} 都不在目标范围 ({xmin}, {xmax}) 内")
    offs = [(xmin - e) % w for e in edges]
    if any(min(abs(o - offs[0]), w - abs(o - offs[0])) > 1e-9 for o in offs):
        raise ValueError(f"heading {heading}: 多条边界给出不同 o_h {offs}")
    o = offs[0]
    # 与边界相邻（两侧）的条带里有没有目标（fixed_y_lanes 对无目标条带不生成航道）
    adj = []
    for e in edges:
        for lo in (e - w, e):
            hi = lo + w
            n = sum(1 for t in ps["targets"]
                    if max(lo - t["geometry"]["center"][0], 0, t["geometry"]["center"][0] - hi) < t["geometry"]["radius"])
            adj.append(dict(strip=[lo, hi], n_targets=n))
    return o, dict(frame_heading=heading, F_xprime_extent=[min(xs), max(xs)], target_xprime_extent=[xmin, xmax],
                   aligned_edges=edges, adjacent_strips=adj)


def _oh_jobs(seed, U, headings):
    return [dict(seed=seed, U=U, heading=h, variant="oh_rot") for h in headings]


VARIANTS = {
    "oh_rot": dict(jobs=_oh_jobs, label="S_h 推广：航向 h 下的几何偏移 o_h(h)，作为 S3 的第 5 个偏移候选"),
}


def run_job(job):
    """默认：算出 offset 后按 variant='main' 走 a_trial_heading.run 的同一管线。"""
    scene = H.scene0(job["seed"])
    d = H.TIERS[job["U"]]
    w = float(H.JOB["swath"])
    o, info = oh_rot(scene, job["heading"], d, w)
    row, geom = H.run(dict(seed=job["seed"], U=job["U"], heading=job["heading"], offset=o, variant="main"))
    row["variant"] = job["variant"]
    row["extra_info"] = info
    return row, geom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="oh_rot")
    ap.add_argument("--headings", default="90")
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--workers", type=int, default=7)
    a = ap.parse_args()
    variants = a.variants.split(",")
    headings = [int(h) for h in a.headings.split(",")]
    seeds = H.parse_seeds(a.seeds)
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    w = float(H.JOB["swath"])

    # 断言：h=0 时推广公式与原 S_h 公式一致
    sh_check = []
    for s in seeds:
        sc = H.scene0(s)
        for U, d in H.TIERS.items():
            o_new, _ = oh_rot(sc, 0, d, w)
            o_old, _, _ = H.heuristic_offset(sc, d, 0.0, w)
            assert abs(o_new - o_old) < 1e-12, (s, U, o_new, o_old)
            sh_check.append(dict(seed=s, U=U, o_h0=o_new))
    print("oh_rot(h=0) == heuristic_offset for all seed×tier:", json.dumps(sh_check), flush=True)

    jobs = [j for v in variants for s in seeds for U in H.TIERS for j in VARIANTS[v]["jobs"](s, U, headings)]
    t0 = time.time()
    rows, geoms = [], {}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(VARIANTS[j["variant"]].get("run_fn", run_job), j) for j in jobs]
        for fu in as_completed(futs):
            row, g = fu.result()
            print(json.dumps({k: row.get(k) for k in ("seed", "variant", "U", "heading", "offset", "status", "A_excluded",
                                                       "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time",
                                                       "violations", "solve_seconds")}), flush=True)
            rows.append(row)
            if g:
                geoms[f'{row["variant"]}_s{row["seed"]}_U{row["U"]:g}_h{row["heading"]}_o{row["offset"]:g}'] = g
    wall = time.time() - t0
    rows.sort(key=lambda r: (r["variant"], r["seed"], r["U"], r["heading"]))
    cols = ["seed", "variant", "lane_offset_used", "U", "d", "heading", "offset", "wind_direction", "status", "stage",
            "A_excluded", "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time", "path_length", "path_spray",
            "path_cut_off", "path_transit_other", "cut_segments", "cut_boundaries", "violations", "spray_samples",
            "excluded_targets", "n_lanes", "strip_count", "matrix_mode", "order_strategy", "plan_frame_duration",
            "time_reeval_minus_plan_frame", "A_C", "solve_seconds", "plan_hash", "reason"]
    out = ROOT / f"results/a_trial_extra_{'_'.join(variants)}_h{'_'.join(map(str, headings))}_{sha}"
    with open(str(out) + ".csv", "w", newline="", encoding="utf8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    meta = dict(commit=sha, worktree_dirty_tracked=bool(dirty), workers=a.workers, wall_seconds=round(wall, 1),
                cpu_count=os.cpu_count(), python=platform.python_version(), variants={v: VARIANTS[v]["label"] for v in variants},
                headings=headings, seeds=seeds, options=H.OPTIONS, job=H.JOB, tiers={f"U={k:g}": f"d={v:g}" for k, v in H.TIERS.items()},
                oh_rot_h0_check=sh_check, rows_full=rows)
    Path(str(out) + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    Path(str(out) + ".geom.json").write_text(json.dumps(geoms))
    print("wrote", str(out) + ".csv", "wall", round(wall, 1))


if __name__ == "__main__":
    main()
