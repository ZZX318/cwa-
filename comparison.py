"""Fair method comparison: real planner dispatch, one executor and evaluator."""

import copy
import json
import math
from pathlib import Path
from time import perf_counter

from evaluation import at
from evaluation import build as eval_build
from execution import build
from planning import configuration, config_fingerprint, fingerprint
from planning.model import options_fingerprint
from planner_api import make_planner, normalize_name

ALL_METHODS = ("fixed-y-boustrophedon", "naive-target-order", "caw-a*-3d-wind")
FIVE_METHODS = (
    "fixed-y-boustrophedon", "naive-target-order", "caw-a*-fixed-order",
    "caw-a*-nn", "caw-a*-3d-wind",
)


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
    elif method == "five":
        return list(FIVE_METHODS)
    elif method == "ablation":
        return ["fixed-y-boustrophedon", *FIVE_METHODS[2:]]
    else:
        raw = method.split(",")
    names = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("方法列表只能包含字符串")
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
        source_plan_hash=None,
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
        planning_seconds=None,
        evaluated_plan_version=None,
        transition_strategy=None,
        order_strategy=None,
        spray_segment_count=None,
        spray_geometry_hash=None,
        sprayable_coverage=None,
        extra_miss_area_m2=None,
        restricted_canopy_area_m2=None,
        illegal_count=None,
        relative_to_fixed_y=None,
    )


def _shared_time_plan(plan):
    """Use the v1.2 time model for all comparisons, preserving source plans."""
    if plan.get("version") == "1.2":
        return plan
    evaluated = copy.deepcopy(plan)
    evaluated.update(
        version="1.2", planner=plan["method"], objective="time",
        planner_options={}, planner_options_hash=options_fingerprint({}),
    )
    return evaluated


def _pair(rows, baseline_name, candidate_name, label):
    result = dict(
        label=label, baseline=baseline_name, candidate=candidate_name,
        available=False, reason="", time_saving_s=None, time_saving_pct=None,
        path_saving_m=None, same_transition_model=None,
    )
    baseline = rows.get(baseline_name)
    candidate = rows.get(candidate_name)
    if baseline is None or candidate is None:
        result["reason"] = "该组方法未同时选择"
    elif baseline["status"] != "success" or candidate["status"] != "success":
        result["reason"] = "存在失败方法，查看对应阶段和原因"
    elif baseline["spray_geometry_hash"] != candidate["spray_geometry_hash"]:
        result["reason"] = "喷洒段不同，原始指标可查看，未计算同任务节省率"
    elif not math.isclose(baseline["coverage"], candidate["coverage"], abs_tol=1e-9):
        result["reason"] = "覆盖结果不同，请结合覆盖和时间共同判断"
    elif baseline["safety"] != "pass" or candidate["safety"] != "pass":
        result["reason"] = "安全检查未通过"
    else:
        result.update(
            available=True,
            time_saving_s=baseline["duration"] - candidate["duration"],
            time_saving_pct=100 * (baseline["duration"] - candidate["duration"]) / baseline["duration"],
            path_saving_m=baseline["path_length"] - candidate["path_length"],
            same_transition_model=baseline["transition_strategy"] == candidate["transition_strategy"],
        )
    return result


def run(scene, config, method="both", resolution=0.5):
    if type(resolution) not in (int, float) or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("评价分辨率必须为有限正数")
    names = _methods(method)
    effective = configuration(config or {})
    out = dict(
        version="1.2",
        scene_hash=fingerprint(scene),
        config=effective,
        config_hash=config_fingerprint(effective),
        resolution=resolution,
        methods=names,
        execution_time_model="shared-v1.2",
        note="同一场景和评价网格，统一使用 v1.2 风场计时；时间为估算任务时间，规划耗时为本次程序运行测量。",
        results=[],
    )
    for name in names:
        row = _blank_row(name)
        row["scene_hash"] = out["scene_hash"]
        row["config_hash"] = out["config_hash"]
        started = perf_counter()
        try:
            plan = make_planner(name).plan(scene, effective)
        except (ValueError, KeyError, TypeError) as error:
            row.update(status="failed", stage="plan", reason=str(error), planning_seconds=perf_counter() - started)
            out["results"].append(row)
            continue
        row["planning_seconds"] = perf_counter() - started
        row["plan_version"] = plan.get("version")
        row["objective"] = plan.get("objective", "time")
        row["plan_hash"] = fingerprint(plan)
        row["source_plan_hash"] = row["plan_hash"]
        row["planner_options"] = plan.get("planner_options")
        row["planner_options_hash"] = plan.get("planner_options_hash")
        search = plan.get("search") or {}
        row["search_nodes"] = search.get("expanded", search.get("nodes"))
        row["search_step"] = search.get("step_xy", search.get("step"))
        row["transition_strategy"] = search.get("model", "straight")
        row["order_strategy"] = (plan.get("order_search") or {}).get(
            "strategy", "target-order" if name == "naive-target-order" else "fixed",
        )
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
        plan = _shared_time_plan(plan)
        row["evaluated_plan_version"] = plan["version"]
        row["plan_hash"] = fingerprint(plan)
        spray_segments = [s for s in plan["segments"] if s["spray"]]
        row["spray_segment_count"] = len(spray_segments)
        row["spray_geometry_hash"] = fingerprint(sorted(
            (s["start"], s["end"], sorted(s["target_ids"])) for s in spray_segments
        ))
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
            sprayable_coverage=metrics["sprayable_coverage"],
            extra_miss_area_m2=metrics["extra_miss_area_m2"],
            restricted_canopy_area_m2=metrics["restricted_canopy_area_m2"],
            illegal_count=len(metrics["illegal"]),
        )
        if metrics["illegal"]:
            row.update(
                status="failed", stage="evaluation", reason="执行喷洒足迹侵入限制区域",
                safety="failed", safety_reason="执行喷洒足迹侵入限制区域",
            )
        out["results"].append(row)
    rows = {row["method"]: row for row in out["results"]}
    for row in out["results"]:
        row["relative_to_fixed_y"] = _pair(rows, FIVE_METHODS[0], row["method"], "相对固定 Y")
    out["contributions"] = [
        _pair(rows, FIVE_METHODS[0], FIVE_METHODS[2], "固定顺序下的转场策略"),
        _pair(rows, FIVE_METHODS[2], FIVE_METHODS[3], "最近邻访问顺序"),
        _pair(rows, FIVE_METHODS[3], FIVE_METHODS[4], "2-opt 顺序修正"),
    ]
    return out


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )
