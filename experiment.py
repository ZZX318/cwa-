"""Reproducible experiment runner with real planner dispatch.

Failure rows stay in ``rows`` and count in every denominator.  Statistics are
descriptive only.  Deterministic planners get ``runs=1`` and ``std=None`` even
when several seeds were requested, because the seed cannot change their output.
"""

import json
import statistics
from pathlib import Path

from evaluation import at
from evaluation import build as eval_build
from execution import build
from multi import run as multi_run
from planning import configuration, config_fingerprint, fingerprint
from planner_api import make_planner, normalize_name
from rl import evaluate as rl_eval, train
from scene import generate

DETERMINISTIC = {"fixed-y-boustrophedon", "naive-target-order", "caw-a*-3d-wind", "caw-a*-nn", "caw-a*-fixed-order", "multi-contiguous-uav"}


def _metrics(scene, plan):
    timeline = build(scene, plan)
    evaluation = eval_build(scene, plan, timeline)
    metrics = at(evaluation, timeline, timeline["duration"])
    return dict(
        coverage=metrics["coverage"],
        missed_target_rate=(
            len(metrics["missed_targets"]) / len(metrics["target_stats"])
            if metrics["target_stats"]
            else None
        ),
        repeated_target_rate=(
            len(metrics["repeated_targets"]) / len(metrics["target_stats"])
            if metrics["target_stats"]
            else None
        ),
        spray_seconds=metrics["spray_seconds"],
        amount=metrics["total_spray_amount"],
        total_time=timeline["duration"],
        path_length=sum(item["length"] for item in timeline["segments"]),
        safety="pass",
    )


def _multi(scene, config, uavs):
    result = multi_run(scene, config, uavs)
    if result["status"] != "success":
        return dict(status="failed", stage="multi", reason=result.get("reason", "multi failed"), safety="not_run")
    effective = configuration(config or {})
    rows = []
    failures = []
    for item in result.get("uavs", []):
        if item.get("status") != "success":
            failures.append(item.get("reason", "未知原因"))
            continue
        if not item.get("segments"):
            continue
        plan = dict(
            version="1.1",
            scene_hash=fingerprint(scene),
            config=effective,
            config_hash=config_fingerprint(effective),
            method="multi-contiguous-uav",
            status="success",
            reason="",
            segments=item.get("segments", []),
            allow_partial=True,
        )
        try:
            rows.append(dict(uav=item["uav"], **_metrics(scene, plan)))
        except (ValueError, KeyError, TypeError) as error:
            failures.append(str(error))
    if not rows:
        if failures:
            return dict(status="failed", stage="multi", reason=failures[0], safety="not_run")
        return dict(
            status="success",
            stage="",
            reason="",
            coverage=None,
            coverage_scope="per_uav_mean_not_union",
            missed_target_rate=None,
            repeated_target_rate=None,
            spray_seconds=0.0,
            amount=0.0,
            total_time=0.0,
            path_length=0.0,
            safety="pass",
            uavs_ok=0,
            uavs_failed=0,
            idle=list(item.get("uav") for item in result.get("uavs", [])),
        )
    row = dict(
        status="failed" if failures else "success",
        stage="multi" if failures else "",
        reason=failures[0] if failures else "",
        coverage=statistics.mean(x["coverage"] for x in rows),
        coverage_scope="per_uav_mean_not_union",
        missed_target_rate=None,
        repeated_target_rate=None,
        spray_seconds=sum(x["spray_seconds"] for x in rows),
        amount=sum(x["amount"] for x in rows),
        total_time=max(x["total_time"] for x in rows),
        path_length=sum(x["path_length"] for x in rows),
        safety="pass",
        uavs_ok=len(rows),
        uavs_failed=len(failures),
    )
    return row


def one(scene, config, method, seed, uavs):
    name = normalize_name(method)
    row = dict(
        status="failed",
        stage="plan",
        reason="",
        coverage=None,
        missed_target_rate=None,
        repeated_target_rate=None,
        spray_seconds=None,
        amount=None,
        total_time=None,
        path_length=None,
        safety="not_run",
    )
    try:
        if name == "multi" or method == "multi":
            row = _multi(scene, config, uavs)
            row["deterministic"] = True
            row["seed_used"] = False
            return row
        if method == "rl":
            result = rl_eval(scene, train(scene, config, uavs, 5, seed), config)
            result = dict(result)
            result.pop("violation", None)
            result.update(
                status=result.get("status", "failed"),
                stage="" if result.get("status") == "success" else "rl",
                reason=result.get("reason", ""),
                total_time=result.get("total_time", result.get("duration")),
                spray_seconds=result.get("spray_seconds"),
                amount=None,
                missed_target_rate=result.get("missed_target_rate"),
                repeated_target_rate=result.get("repeated_target_rate"),
                deterministic=False,
                seed_used=True,
                safety="pass" if result.get("status") == "success" else "not_run",
            )
            return result
        plan = make_planner(name).plan(scene, config)
        row["plan_version"] = plan.get("version")
        row["plan_hash"] = fingerprint(plan)
        row["objective"] = plan.get("objective", "time")
        row["search_nodes"] = (plan.get("search") or {}).get("expanded")
        row["matrix_mode"] = (plan.get("order_search") or {}).get("matrix_mode")
        if plan.get("status") != "success":
            row.update(
                status=plan.get("status", "failed"),
                stage=plan.get("stage", "plan"),
                reason=plan.get("reason", "未知原因"),
                deterministic=name in DETERMINISTIC,
                seed_used=False,
            )
            return row
        row.update(_metrics(scene, plan))
        row.update(status="success", stage="", reason="", deterministic=name in DETERMINISTIC, seed_used=False)
        return row
    except (ValueError, KeyError, TypeError) as error:
        row.update(status="failed", stage="plan", reason=str(error))
        return row


def run(seeds=(0,), methods=("fixed-y", "naive", "multi", "rl"), uavs=(1,), config=None, scene_config=None):
    job = configuration(config or {})
    rows = []
    for seed in seeds:
        scene = generate(scene_config or {})
        scene_hash = fingerprint(scene)
        config_hash = config_fingerprint(job)
        for n in uavs:
            for method in methods:
                result = one(scene, job, method, seed, n)
                result.update(
                    seed=seed,
                    uavs=n,
                    method=method,
                    scene_hash=scene_hash,
                    config_hash=config_hash,
                )
                rows.append(result)
    groups = {}
    for row in rows:
        key = (row["scene_hash"], row["method"], row["uavs"], row.get("objective"), job.get("wind_speed"), job.get("wind_direction"))
        groups.setdefault(key, []).append(row)
    summary = []
    for (scene_hash, method, n, objective, wind_speed, wind_direction), items in groups.items():
        successes = [x for x in items if x["status"] == "success"]
        failures = [x for x in items if x["status"] != "success"]
        deterministic = all(x.get("deterministic", False) for x in items)
        coverages = [x["coverage"] for x in successes if x["coverage"] is not None]
        times = [x["total_time"] for x in successes if x["total_time"] is not None]
        effective_runs = 1 if deterministic else len(items)
        summary.append(
            dict(
                scene_hash=scene_hash,
                method=method,
                uavs=n,
                objective=objective,
                wind_speed=wind_speed,
                wind_direction=wind_direction,
                attempts=len(items),
                runs=effective_runs,
                successes=len(successes),
                failures=len(failures),
                feasibility_rate=len(successes) / len(items),
                failure_stages={
                    str(stage): sum(1 for x in failures if x.get("stage") == stage)
                    for stage in sorted({x.get("stage") for x in failures}, key=str)
                },
                deterministic=deterministic,
                coverage_mean=statistics.mean(coverages) if coverages else None,
                coverage_std=(
                    None
                    if deterministic or len(coverages) <= 1
                    else statistics.pstdev(coverages)
                ),
                time_mean=statistics.mean(times) if times else None,
            )
        )
    summary.sort(key=lambda x: (x["method"], x["uavs"], x["scene_hash"]))
    return dict(
        version="1.1",
        rows=rows,
        summary=summary,
        seeds=list(seeds),
        seed_note="确定性规划器不使用 seed；同场景不同 seed 的结果必然相同（runs=1, std=None）。rl 与未来随机多起点才使用 seed。",
        config=job,
        config_hash=config_fingerprint(job),
    )


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))
