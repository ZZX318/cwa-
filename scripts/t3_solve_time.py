#!/usr/bin/env python3
"""T3 求解耗时：sort vs sort_drift，seeds 0-14，与主消融同场景/同参数。

单进程顺序跑（不并行，避免互相抢 CPU），逐行计时：
- scene_seconds：生成场景 + 注入 ns-ablation
- solve_seconds：CawAStarPlanner.plan() 全程（作业带、排序、分段、3D 转场）——论文报告此列
- total_seconds：以上之和
并记录 plan_hash，用于与主消融 CSV 逐行比对是否同一解。

用法：python3 scripts/t3_solve_time.py --seeds 0-14
"""
from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import argparse, csv, json, os, platform, statistics, time

from ablation_sort_vs_sort_drift import MODES, _git_sha, _inject_downwind_no_spray, _parse_seeds
from planning import configuration, fingerprint
from planner_api import make_planner
from random_scene import generate_with_report

FIELDS = ["seed", "drift_mode", "status", "reason", "scene_seconds", "solve_seconds",
          "total_seconds", "plan_hash", "git_sha"]


def cpu_model() -> str:
    try:
        for line in open("/proc/cpuinfo", encoding="utf8"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def p95(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = 0.95 * (len(xs) - 1)  # 线性插值，同 numpy 默认
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0-14")
    ap.add_argument("--job", type=Path, default=ROOT / "configs" / "job.ablation.crosswind.json")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    sha = _git_sha()
    out = a.out or ROOT / "results" / f"t3_solve_time_{sha[:7]}.csv"
    raw = {**json.loads(a.job.read_text(encoding="utf8")), "buffer_expand": 0.0}
    opts = dict(step_xy=2.0, max_grid_nodes=5_000_000, max_expansions=500_000)
    seeds = _parse_seeds(a.seeds)
    meta = dict(git_sha=sha, seeds=seeds, modes=list(MODES), planner_options=opts,
                job=str(a.job), buffer_expand=0.0, cpu_model=cpu_model(),
                logical_cpus=os.cpu_count(), python=platform.python_version(),
                os=platform.platform(), loadavg_start=os.getloadavg(),
                started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                note="单进程顺序运行，solve_seconds=plan() 墙钟时间（单线程）。")
    rows = []
    with out.open("w", newline="", encoding="utf8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for seed in seeds:
            for mode in MODES:
                t0 = time.perf_counter()
                scene, _ = generate_with_report("ha_orchard", seed, {"plot_width": 100.0, "plot_height": 100.0})
                scene = _inject_downwind_no_spray(scene)
                cfg = configuration({**raw, "drift_mode": mode})
                t1 = time.perf_counter()
                row = dict(seed=seed, drift_mode=mode, git_sha=sha, status="failed", reason="", plan_hash="")
                try:
                    plan = make_planner("caw").plan(scene, cfg, options=opts)
                    row["status"] = plan.get("status")
                    row["reason"] = plan.get("reason") or ""
                    if plan.get("status") == "success":
                        row["plan_hash"] = fingerprint(plan)
                except (ValueError, KeyError, TypeError) as e:
                    row["reason"] = str(e)
                t2 = time.perf_counter()
                row.update(scene_seconds=round(t1 - t0, 3), solve_seconds=round(t2 - t1, 3),
                           total_seconds=round(t2 - t0, 3))
                w.writerow(row); fh.flush(); rows.append(row)
                print(f"seed={seed} mode={mode} {row['status']} solve={row['solve_seconds']}s", flush=True)
    summ = {}
    for mode in MODES:
        xs = [r["solve_seconds"] for r in rows if r["drift_mode"] == mode and r["status"] == "success"]
        summ[mode] = dict(n=len(xs), mean=statistics.mean(xs) if xs else None,
                          sd=statistics.stdev(xs) if len(xs) > 1 else None,
                          p95=p95(xs), min=min(xs) if xs else None, max=max(xs) if xs else None)
    meta.update(summary_solve_seconds=summ, loadavg_end=os.getloadavg(),
                finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), out=str(out))
    out.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(summ, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
