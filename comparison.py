"""Fair method comparison: real planner dispatch, one executor and evaluator."""

import json
from pathlib import Path

from evaluation import at
from evaluation import build as eval_build
from execution import build
from planning import configuration, config_fingerprint, fingerprint
from planner_api import make_planner, normalize_name

ALL_METHODS = ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-3d-wind")


def _methods(method):
    if method is None:
        return list(ALL_METHODS)
    if isinstance(method, (list, tuple)):
        raw = list(method)
    elif not isinstance(method, str):
        raise ValueError("method 必须是字符串或字符串列表")
    elif method in ("both", ""):
        return ["fixed-y-boustrophedon", "naive-target-order"]
    elif method == "all":
        return list(ALL_METHODS)
    else:
        raw = method.split(",")
    names = []
    for item in raw:
        name = normalize_name(item.strip())
        if name not in names:
            names.append(name)
    return names


def _blank_row(name):
    return dict(
        method=name,
        planner=name,
        plan_version=None,
        objective="time",
        status="failed",
        stage="plan",
        reason="",
        scene_hash=None,
        config_hash=None,
        plan_hash=None,
        timeline_id=None,
        path_length=None,
        transition_length=None,
        duration=None,
        spray_seconds=None,
        amount=None,
        coverage=None,
        covered=None,
        missed=None,
        repeated=None,
        missed_targets=None,
        repeated_targets=None,
        safety="not_run",
        safety_reason="",
        search_nodes=None,
        search_step=None,
        order=None,
        matrix_mode=None,
        lower_bound=None,
        gap_to_bound_abs=None,
        planner_options=None,
        planner_options_hash=None,
    )


def run(scene, config, method="both", resolution=0.5):
    names = _methods(method)
    effective = configuration(config or {})
    out = dict(
        version="1.1",
        scene_hash=fingerprint(scene),
        config=effective,
        config_hash=config_fingerprint(effective),
        resolution=resolution,
        methods=names,
        results=[],
    )
    for name in names:
        row = _blank_row(name)
        row["scene_hash"] = out["scene_hash"]
        row["config_hash"] = out["config_hash"]
        try:
            plan = make_planner(name).plan(scene, effective)
        except (ValueError, KeyError, TypeError) as error:
            row.update(status="failed", stage="plan", reason=str(error))
            out["results"].append(row)
            continue
        row["plan_version"] = plan.get("version")
        row["objective"] = plan.get("objective", "time")
        row["plan_hash"] = fingerprint(plan)
        row["planner_options"] = plan.get("planner_options")
        row["planner_options_hash"] = plan.get("planner_options_hash")
        search = plan.get("search") or {}
        row["search_nodes"] = search.get("expanded")
        row["search_step"] = search.get("step_xy")
        row["order"] = plan.get("order")
        row["matrix_mode"] = (plan.get("order_search") or {}).get("matrix_mode")
        row["lower_bound"] = (plan.get("order_search") or {}).get("lower_bound")
        row["gap_to_bound_abs"] = (plan.get("order_search") or {}).get("gap_to_bound_abs")
        if plan.get("status") != "success":
            row.update(
                status=plan.get("status", "failed"),
                stage=plan.get("stage", "plan"),
                reason=plan.get("reason", "未知原因"),
                plan_hash=fingerprint(plan) if isinstance(plan, dict) else None,
            )
            out["results"].append(row)
            continue
        row["safety"] = "pass"
        try:
            timeline = build(scene, plan)
        except (ValueError, KeyError, TypeError) as error:
            row.update(status="failed", stage="execution", reason=str(error), safety="failed", safety_reason=str(error))
            out["results"].append(row)
            continue
        try:
            evaluation = eval_build(scene, plan, timeline, resolution)
            metrics = at(evaluation, timeline, timeline["duration"])
        except (ValueError, KeyError, TypeError) as error:
            row.update(status="failed", stage="evaluation", reason=str(error))
            out["results"].append(row)
            continue
        row.update(
            status="success",
            stage="",
            reason="",
            timeline_id=timeline["execution_id"],
            path_length=sum(item["length"] for item in timeline["segments"]),
            transition_length=sum(
                item["length"] for item in timeline["segments"] if item["type"] == "transit"
            ),
            duration=timeline["duration"],
            spray_seconds=metrics["spray_seconds"],
            amount=metrics["total_spray_amount"],
            coverage=metrics["coverage"],
            covered=metrics["covered_cells"],
            missed=metrics["missed_cells"],
            repeated=metrics["repeated_cells"],
            missed_targets=len(metrics["missed_targets"]),
            repeated_targets=len(metrics["repeated_targets"]),
        )
        out["results"].append(row)
    return out


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )
