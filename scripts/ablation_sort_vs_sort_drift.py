#!/usr/bin/env python3
"""路径2主消融：sort vs sort_drift（buffer_expand=0），1 ha ha_orchard。

现有 ``--experiment`` 无法一次扫两个 drift_mode，且 1 ha 上默认 step_xy=1
会使 CAW 3D 转场网格超限。本脚本：
- 场景：ha_orchard 100×100；每个 seed 独立几何
- 固定在园外下风侧注入一块禁喷（id=ns-ablation），否则无禁喷时
  sort_drift 代理恒为 0，消融无差异（纯几何仍由 seed 决定）
- 规划：caw，step_xy=2 / max_grid_nodes=5e6（1 ha 必需，不改 DEFAULT）
- 指标：order_cost（solve_order，与排序消融同口径）+ 全链路评估指标
- 失败行保留并计入分母；CSV 逐行追加，可断点续跑

用法：
  python3 scripts/ablation_sort_vs_sort_drift.py --seeds 0-2
  python3 scripts/ablation_sort_vs_sort_drift.py --seeds 0-29
"""

from __future__ import annotations

import sys
from pathlib import Path as _PathForSys
_ROOT = _PathForSys(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import csv
import json
import statistics
import subprocess
import time
from pathlib import Path

from experiment import _metrics
from planning import config_fingerprint, configuration, fingerprint
from planning.order import solve_order
from planning.planner import fixed_y_lanes
from planner_api import make_planner
from random_scene import generate_with_report

ROOT = Path(__file__).resolve().parents[1]
MODES = ("sort", "sort_drift")
FIELDNAMES = [
    "seed",
    "drift_mode",
    "status",
    "stage",
    "reason",
    "order_cost",
    "order",
    "n_lanes",
    "target_coverage",
    "N_eligible",
    "exemption_rate",
    "misspray_area",
    "total_time",
    "path_length",
    "coverage",
    "spray_seconds",
    "scene_hash",
    "config_hash",
    "plan_hash",
    "wall_seconds",
    "trees",
    "plot_area_ha",
    "git_sha",
]


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _parse_seeds(text: str) -> list[int]:
    text = text.strip()
    if "-" in text and "," not in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",") if x.strip() != ""]


def _inject_downwind_no_spray(scene: dict) -> dict:
    """园外 -x 侧禁喷：wind_direction=0 时下风为 -x，使 lane_drift_proxy 可非零。"""
    out = json.loads(json.dumps(scene))  # deepcopy via json（场景可 JSON 化）
    out["no_spray_zones"] = [
        dict(
            id="ns-ablation",
            kind="polygon_prism",
            footprint=dict(
                kind="polygon",
                vertices=[[-8.0, 5.0], [-1.0, 5.0], [-1.0, 95.0], [-8.0, 95.0]],
            ),
            z_min=0.0,
            z_max=10.0,
        )
    ]
    return out


def _load_done(path: Path) -> set[tuple[int, str]]:
    done: set[tuple[int, str]] = set()
    if not path.exists():
        return done
    with path.open(newline="", encoding="utf8") as fh:
        for row in csv.DictReader(fh):
            try:
                done.add((int(row["seed"]), row["drift_mode"]))
            except (KeyError, ValueError):
                continue
    return done


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k) for k in FIELDNAMES})


def _summary(path: Path) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf8")))
    print("\n=== summary (all rows in denominator; failures keep null metrics) ===")
    for mode in MODES:
        items = [r for r in rows if r["drift_mode"] == mode]
        n = len(items)
        ok = [r for r in items if r["status"] == "success"]
        fail = [r for r in items if r["status"] != "success"]
        print(f"\n[{mode}] N={n} success={len(ok)} fail={len(fail)}")
        if fail:
            print(
                "  failed seeds:",
                sorted({int(r["seed"]) for r in fail}),
            )
            for r in fail:
                print(f"    seed={r['seed']} stage={r['stage']} reason={r['reason'][:100]}")

        def mean_std(key: str):
            vals = []
            for r in items:
                raw = r.get(key)
                if raw is None or raw == "":
                    continue
                try:
                    vals.append(float(raw))
                except ValueError:
                    continue
            if not vals:
                return None, None, 0
            if len(vals) == 1:
                return vals[0], 0.0, 1
            return statistics.mean(vals), statistics.pstdev(vals), len(vals)

        for key in (
            "order_cost",
            "target_coverage",
            "N_eligible",
            "exemption_rate",
            "misspray_area",
            "total_time",
            "path_length",
        ):
            mu, sd, k = mean_std(key)
            if mu is None:
                print(f"  {key}: n/a")
            else:
                print(f"  {key}: {mu:.6g} ± {sd:.6g} (n={k}/{n})")


def run_one(seed: int, drift_mode: str, base_job: dict, sha: str, planner_options: dict) -> dict:
    t0 = time.perf_counter()
    scene, report = generate_with_report(
        "ha_orchard", seed, {"plot_width": 100.0, "plot_height": 100.0}
    )
    scene = _inject_downwind_no_spray(scene)
    cfg = configuration({**base_job, "drift_mode": drift_mode, "buffer_expand": 0.0})
    scene_hash = fingerprint(scene)
    config_hash = config_fingerprint(cfg)
    row = dict(
        seed=seed,
        drift_mode=drift_mode,
        status="failed",
        stage="plan",
        reason="",
        order_cost="",
        order="",
        n_lanes="",
        target_coverage="",
        N_eligible="",
        exemption_rate="",
        misspray_area="",
        total_time="",
        path_length="",
        coverage="",
        spray_seconds="",
        scene_hash=scene_hash,
        config_hash=config_hash,
        plan_hash="",
        wall_seconds="",
        trees=report["counts"]["trees"],
        plot_area_ha=report["info"].get("plot_area_ha"),
        git_sha=sha,
    )
    try:
        lanes = fixed_y_lanes(scene, cfg)["lanes"]
        row["n_lanes"] = len(lanes)
        order_result = solve_order(
            scene, cfg, lanes, strategy="nn+2opt"
        )
        if order_result.get("status") != "success":
            row.update(
                status="failed",
                stage="order",
                reason=order_result.get("reason") or "order failed",
                wall_seconds=round(time.perf_counter() - t0, 3),
            )
            return row
        row["order_cost"] = order_result.get("order_cost")
        row["order"] = json.dumps(order_result.get("order"), ensure_ascii=False)

        plan = make_planner("caw").plan(scene, cfg, options=planner_options)
        if plan.get("status") != "success":
            row.update(
                status=plan.get("status") or "failed",
                stage=plan.get("stage") or "plan",
                reason=plan.get("reason") or "plan failed",
                wall_seconds=round(time.perf_counter() - t0, 3),
            )
            return row
        metrics = _metrics(scene, plan)
        row.update(
            status="success",
            stage="",
            reason="",
            target_coverage=metrics.get("target_coverage"),
            N_eligible=metrics.get("N_eligible"),
            exemption_rate=metrics.get("exemption_rate"),
            misspray_area=metrics.get("misspray_area"),
            total_time=metrics.get("total_time"),
            path_length=metrics.get("path_length"),
            coverage=metrics.get("coverage"),
            spray_seconds=metrics.get("spray_seconds"),
            plan_hash=fingerprint(plan),
            wall_seconds=round(time.perf_counter() - t0, 3),
        )
        return row
    except (ValueError, KeyError, TypeError) as error:
        row.update(
            status="failed",
            stage="plan",
            reason=str(error),
            wall_seconds=round(time.perf_counter() - t0, 3),
        )
        return row


def main() -> int:
    p = argparse.ArgumentParser(description="sort vs sort_drift 1ha 消融")
    p.add_argument("--seeds", default="0-29", help="如 0-29 或 0,1,2")
    p.add_argument(
        "--job",
        type=Path,
        default=ROOT / "configs" / "job.ablation.crosswind.json",
        help="基线 job（drift_mode 会被脚本覆盖）",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="CSV 路径；默认 results/ablation_sort_vs_sort_drift_<sha7>.csv",
    )
    p.add_argument("--step-xy", type=float, default=2.0, choices=(0.5, 1.0, 2.0))
    p.add_argument("--max-grid-nodes", type=int, default=5_000_000)
    p.add_argument("--max-expansions", type=int, default=500_000)
    p.add_argument("--force", action="store_true", help="忽略已有 CSV 行，重跑全部")
    args = p.parse_args()

    sha = _git_sha()
    sha7 = sha[:7]
    out = args.out or (ROOT / "results" / f"ablation_sort_vs_sort_drift_{sha7}.csv")
    raw = json.loads(args.job.read_text(encoding="utf8"))
    if not isinstance(raw, dict):
        raise SystemExit("job JSON 顶层必须是对象")
    # 强制关缓冲；drift_mode 由循环覆盖
    raw = {**raw, "buffer_expand": 0.0}
    seeds = _parse_seeds(args.seeds)
    planner_options = dict(
        step_xy=args.step_xy,
        max_grid_nodes=args.max_grid_nodes,
        max_expansions=args.max_expansions,
    )
    done = set() if args.force else _load_done(out)
    print(
        f"git={sha7} out={out} seeds={seeds[0]}..{seeds[-1]} (N={len(seeds)}) "
        f"modes={MODES} resume_skip={len(done)} options={planner_options}"
    )

    for seed in seeds:
        for mode in MODES:
            if (seed, mode) in done:
                print(f"skip seed={seed} mode={mode}")
                continue
            print(f"run seed={seed} mode={mode} ...", flush=True)
            row = run_one(seed, mode, raw, sha, planner_options)
            _append(out, row)
            print(
                f"  -> {row['status']} order_cost={row.get('order_cost')} "
                f"total_time={row.get('total_time')} wall={row.get('wall_seconds')}s "
                f"reason={str(row.get('reason') or '')[:80]}",
                flush=True,
            )

    _summary(out)
    meta = dict(
        git_sha=sha,
        out=str(out),
        seeds=seeds,
        modes=list(MODES),
        buffer_expand=0.0,
        scene="ha_orchard 100x100 + ns-ablation exterior downwind no_spray",
        planner="caw",
        planner_options=planner_options,
        job=str(args.job),
        note="失败行保留；均值分母含失败（对应指标跳过空值）。未改 DEFAULT。",
    )
    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"\nmeta -> {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
