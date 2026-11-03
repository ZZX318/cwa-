"""Exact small-scale joint optimization of spray-lane order and transitions.

This is a verification baseline, not a scalable solver.  Every candidate is a
complete plan (takeoff -> transitions -> unchanged spray lanes -> return ->
landing) that must pass the shared independent safety check and the shared
execution time model before it can be compared.

Limits are explicit: too many lanes (or too many permutations) return
``unsupported`` instead of silently falling back to a heuristic.
"""

import copy
import itertools
import json
import math
from pathlib import Path

from execution import build as build_execution
from planning import (
    check,
    config_fingerprint,
    configuration,
    fingerprint,
    generate_plan,
    options_fingerprint,
)
from planning.routing3d import route3d
from routing import route

METHOD_FIXED = "exact-permutation+transition-fixed"
METHOD_SEARCH = "exact-permutation+transition-search"
METHOD_CAW = "exact-permutation+transition-caw"
JOINT_OPTION_KEYS = {
    "transition",
    "step_xy",
    "step_z",
    "max_expansions",
    "max_grid_nodes",
    "objective",
}
MAX_EXACT_ORDERS = 40320  # 8!; hard guard against accidental huge enumeration
REJECT_LIMIT = 20


def _raw_config(config):
    """Accept only a job object; never let dict() turn a list into a config."""
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("config 必须是对象")
    return dict(config)


def _spray_lanes(plan):
    """Spray segments in their baseline fixed-y order; endpoints stay unchanged."""
    return [copy.deepcopy(segment) for segment in plan.get("segments", []) if segment["type"] == "spray"]


def _options(raw_options, config):
    """Validate joint planner options; default follows the job transition mode."""
    options = {} if raw_options is None else raw_options
    if not isinstance(options, dict):
        raise ValueError("联合规划参数必须是对象")
    unknown = set(options) - JOINT_OPTION_KEYS
    if unknown:
        raise ValueError("未知联合规划参数")
    normalized = dict(
        transition=options.get("transition", config["transition_mode"]),
        step_xy=options.get("step_xy", 1.0),
        step_z=options.get("step_z", 1.0),
        max_expansions=options.get("max_expansions", 200000),
        max_grid_nodes=options.get("max_grid_nodes", 2000000),
        objective=options.get("objective", "time"),
    )
    if normalized["transition"] not in ("fixed", "search", "caw"):
        raise ValueError("transition 必须为 fixed、search 或 caw")
    if normalized["step_xy"] not in (0.5, 1.0, 2.0):
        raise ValueError("step_xy 仅支持 0.5 / 1.0 / 2.0")
    if (
        type(normalized["step_z"]) not in (int, float)
        or not math.isfinite(normalized["step_z"])
        or normalized["step_z"] <= 0
    ):
        raise ValueError("step_z 必须为有限正数")
    for key in ("max_expansions", "max_grid_nodes"):
        value = normalized[key]
        if type(value) is not int or isinstance(value, bool) or value < 1:
            raise ValueError(f"{key} 必须为正整数")
    if normalized["objective"] != "time":
        raise ValueError("能量代理口径未实现（M2）")
    return normalized


def _context(scene, config, options=None):
    from scene.launch import resolve

    height = max(tree["canopy"]["z_max"] for tree in scene["trees"]) + config["height_offset"]
    resolved = resolve(scene, 1)
    start = list(resolved["start"]["position"])
    end = list(resolved["end"]["position"])
    if options and options["transition"] == "caw":
        method = METHOD_CAW
    elif config["transition_mode"] == "search":
        method = METHOD_SEARCH
    else:
        method = METHOD_FIXED
    return dict(
        height=height,
        home=start,
        start=start,
        end=end,
        explicit=resolved["explicit"] or start != end,
        start_point_id=resolved["start_id"],
        end_point_id=resolved["end_id"],
        method=method,
    )


def _transit(start, end, config, scene, cache, options=None):
    """Return (segments, length, search_nodes, search_routes) for one transition leg."""
    if math.dist(start, end) <= 1e-8:
        return [], 0.0, 0, 0
    transition = (options or {}).get("transition", config["transition_mode"])
    if transition == "fixed":
        segment = dict(
            start=list(start),
            end=list(end),
            type="transit",
            spray=False,
            speed=config["speed"],
            target_ids=[],
        )
        return [segment], math.dist(start, end), 0, 0

    key = (transition, tuple(start), tuple(end))
    if key not in cache:
        if transition == "caw":
            cache[key] = route3d(
                scene,
                list(start),
                list(end),
                config,
                objective=(options or {}).get("objective", "time"),
                grid=dict(
                    step_xy=(options or {}).get("step_xy", 1.0),
                    step_z=(options or {}).get("step_z", 1.0),
                    max_expansions=(options or {}).get("max_expansions", 200000),
                    max_grid_nodes=(options or {}).get("max_grid_nodes", 2000000),
                ),
            )
        else:
            cache[key] = route(scene, list(start), list(end), 1.0, config["clearance"])
    result = cache[key]
    if result["status"] != "success":
        raise ValueError(f"转场搜索失败: {result.get('reason', '未知原因')}")
    segments = []
    length = 0.0
    points = result["path"]
    for a, b in zip(points, points[1:]):
        distance = math.dist(a, b)
        if distance <= 1e-9:
            continue
        segments.append(
            dict(
                start=list(a),
                end=list(b),
                type="transit",
                spray=False,
                speed=config["speed"],
                target_ids=[],
            )
        )
        length += distance
    if not segments:
        raise ValueError("转场搜索路径为空，无法构造连续计划")
    return segments, length, result.get("expanded", 0), 1


def _build_plan(scene, config, lanes, order, context, cache, strip_count, options=None):
    """Construct one complete candidate plan for a lane order."""
    caw = context["method"] == METHOD_CAW
    start = context["start"]
    end = context["end"]
    explicit = context["explicit"]
    height = context["height"]
    segments = []
    current = list(start)

    def append(end_point, kind, target_ids=None):
        nonlocal current
        if math.dist(current, end_point) <= 1e-8:
            return
        segments.append(
            dict(
                start=list(current),
                end=list(end_point),
                type=kind,
                spray=kind == "spray",
                speed=config["speed"],
                target_ids=sorted(target_ids or []),
            )
        )
        current = list(end_point)

    append([start[0], start[1], height], "takeoff")
    transition_length = 0.0
    search_nodes = 0
    search_routes = 0
    for index in order:
        lane = lanes[index]
        legs, length, nodes, routes = _transit(
            current, lane["start"], config, scene, cache, options
        )
        for segment in legs:
            segments.append(segment)
        transition_length += length
        search_nodes += nodes
        search_routes += routes
        current = list(lane["start"])
        segments.append(copy.deepcopy(lane))
        current = list(lane["end"])
    legs, length, nodes, routes = _transit(
        current, [end[0], end[1], height], config, scene, cache, options
    )
    for segment in legs:
        segments.append(segment)
    transition_length += length
    search_nodes += nodes
    search_routes += routes
    current = [end[0], end[1], height]
    append(end, "landing")

    plan = dict(
        version="1.2" if (caw or explicit) else "1.1",
        scene_hash=fingerprint(scene),
        method=context["method"],
        status="success",
        reason="",
        segments=segments,
        strip_count=strip_count,
        work_height=height,
        config=copy.deepcopy(config),
        config_hash=config_fingerprint(config),
    )
    if caw:
        normalized = options or {}
        plan.update(
            planner=context["method"],
            objective=normalized.get("objective", "time"),
            planner_options=normalized,
            planner_options_hash=options_fingerprint(normalized),
            search=dict(
                model="layered-3d-clearance-a-star",
                step_xy=normalized.get("step_xy", 1.0),
                step_z=normalized.get("step_z", 1.0),
                clearance=config["clearance"],
                routes=search_routes,
                nodes=search_nodes,
            ),
        )
    elif config["transition_mode"] == "search":
        plan["search"] = dict(
            model="clearance-grid-a-star",
            step=1.0,
            clearance=config["clearance"],
            routes=search_routes,
            nodes=search_nodes,
        )
    if explicit and plan["version"] == "1.2":
        plan.update(
            uav=1,
            start_point_id=context["start_point_id"],
            end_point_id=context["end_point_id"],
        )
        if not caw:
            plan.update(
                planner=plan["method"],
                objective="time",
                planner_options={},
                planner_options_hash=options_fingerprint({}),
            )
    return plan, transition_length, search_nodes, search_routes


def _metrics(scene, plan):
    """Compile through the shared executor; return path/time metrics and identities."""
    check(scene, plan)
    timeline = build_execution(scene, plan)
    transition_length = sum(
        segment["length"] for segment in timeline["segments"] if segment["type"] == "transit"
    )
    total_path_length = sum(segment["length"] for segment in timeline["segments"])
    return dict(
        transition_length=transition_length,
        total_path_length=total_path_length,
        total_time=timeline["duration"],
        segments=len(timeline["segments"]),
        plan_hash=fingerprint(plan),
        execution_id=timeline["execution_id"],
        safety="pass",
    )


def _baseline(scene, plan):
    lanes = _spray_lanes(plan)
    row = dict(
        order=list(range(len(lanes))),
        spray_count=len(lanes),
        status=plan.get("status", "failed"),
        reason=plan.get("reason", ""),
        transition_length=None,
        total_path_length=None,
        total_time=None,
        safety="not_run",
        segments=len(plan.get("segments", [])),
        search_nodes=plan.get("search", {}).get("nodes", 0),
    )
    if plan.get("status") != "success":
        return row, lanes
    try:
        row.update(_metrics(scene, plan))
    except (ValueError, KeyError, TypeError) as error:
        row.update(status="failed", reason=str(error), safety="failed")
    return row, lanes


def _improvement(baseline, best):
    if baseline.get("total_time") is None:
        return None
    return dict(
        total_time_saved=baseline["total_time"] - best["total_time"],
        total_time_pct=100.0 * (baseline["total_time"] - best["total_time"]) / baseline["total_time"],
        total_path_length_saved=baseline["total_path_length"] - best["total_path_length"],
        transition_length_saved=baseline["transition_length"] - best["transition_length"],
    )


def optimize(scene, config=None, limit=8, options=None):
    """Enumerate all lane orders exactly, validating every candidate.

    Status semantics:
    - ``success``: at least one order passed safety and execution; ``order`` is
      the exact best among all feasible permutations.
    - ``failed``: the baseline plan failed, or no permutation was feasible.
    - ``unsupported``: lane count above ``limit`` (or permutation count above
      the 40320 hard guard), with an explicit reason and no best result.
    """
    result = dict(
        version="1.0",
        method=None,
        status="failed",
        reason="",
        order=None,
        transition_length=None,
        total_path_length=None,
        total_time=None,
        expanded=0,
        orders_total=None,
        feasible_orders=0,
        rejected=[],
        rejected_total=0,
        rejected_truncated=False,
        rejected_note="",
        scene_hash=None,
        config_hash=None,
        spray_count=0,
        baseline=None,
        improvement=None,
        optimality_gap=None,
        search_nodes=0,
        search_routes=0,
        transition=None,
        planner_options=None,
        planner_options_hash=None,
    )
    try:
        result["scene_hash"] = fingerprint(scene)
    except (TypeError, ValueError):
        result.update(status="failed", reason="场景无法计算指纹")
        return result
    try:
        raw = _raw_config(config)
    except (ValueError, TypeError) as error:
        result.update(status="failed", reason=f"配置无效: {error}")
        return result
    try:
        effective = configuration(raw)
        result["config_hash"] = config_fingerprint(effective)
        normalized = _options(options, effective)
    except (ValueError, KeyError, TypeError) as error:
        result.update(status="failed", reason=f"配置无效: {error}")
        return result
    result["transition"] = normalized["transition"]
    result["planner_options"] = normalized
    result["planner_options_hash"] = options_fingerprint(normalized)
    result["method"] = (
        METHOD_CAW
        if normalized["transition"] == "caw"
        else (METHOD_SEARCH if effective["transition_mode"] == "search" else METHOD_FIXED)
    )
    if type(limit) is not int or isinstance(limit, bool) or limit < 1:
        result.update(status="failed", reason="limit 必须为正整数")
        return result

    baseline_plan = generate_plan(scene, raw)
    baseline, lanes = _baseline(scene, baseline_plan)
    if baseline_plan.get("status") != "success" and normalized["transition"] == "caw":
        # The straight-line baseline may be blocked while 3D transitions are
        # feasible.  Keep the failed baseline row, but still enumerate orders.
        from planning.planner import fixed_y_lanes

        lanes = copy.deepcopy(fixed_y_lanes(scene, effective)["lanes"])
    count = len(lanes)
    result["baseline"] = baseline
    result["spray_count"] = count
    if baseline_plan.get("status") != "success" and normalized["transition"] != "caw":
        reason = baseline_plan.get("reason", "未知原因")
        result.update(
            status="failed",
            reason=f"基准计划失败: {reason}",
            rejected=[dict(order=[], stage="baseline", reason=reason)],
            rejected_total=1,
        )
        return result
    if count == 0:
        result.update(status="failed", reason="没有喷洒航段")
        return result

    orders_total = math.factorial(count)
    result["orders_total"] = orders_total
    if count > limit:
        result.update(
            status="unsupported",
            reason=f"航段 {count} 超过穷举上限 {limit}；未计算，不返回伪最优结果",
        )
        return result
    if orders_total > MAX_EXACT_ORDERS:
        result.update(
            status="unsupported",
            reason=(
                f"排列数 {orders_total} 超过精确穷举上限 {MAX_EXACT_ORDERS}"
                f"（航段 {count}，limit {limit}）；未计算，不返回伪最优结果"
            ),
        )
        return result

    context = _context(scene, effective, normalized)
    strip_count = baseline_plan.get("strip_count") or count
    route_cache = {}
    best = None
    rejected = []
    rejected_total = 0
    expanded = 0
    feasible = 0
    identity_reason = None
    for order in itertools.permutations(range(count)):
        expanded += 1
        try:
            plan, transition_length, search_nodes, search_routes = _build_plan(
                scene, effective, lanes, order, context, route_cache, strip_count, normalized
            )
        except (ValueError, KeyError, TypeError) as error:
            rejected_total += 1
            identity_reason = identity_reason or str(error)
            if len(rejected) < REJECT_LIMIT:
                rejected.append(dict(order=list(order), stage="transition", reason=str(error)))
            continue
        try:
            metrics = _metrics(scene, plan)
        except (ValueError, KeyError, TypeError) as error:
            rejected_total += 1
            identity_reason = identity_reason or str(error)
            if len(rejected) < REJECT_LIMIT:
                rejected.append(dict(order=list(order), stage="safety_or_execution", reason=str(error)))
            continue
        feasible += 1
        candidate = dict(
            order=list(order),
            transition_length=metrics["transition_length"],
            total_path_length=metrics["total_path_length"],
            total_time=metrics["total_time"],
            plan_hash=metrics["plan_hash"],
            execution_id=metrics["execution_id"],
            segments=metrics["segments"],
            search_nodes=search_nodes,
            search_routes=search_routes,
        )
        key = (candidate["total_time"], candidate["total_path_length"], tuple(order))
        if best is None or key < best[0]:
            best = (key, candidate)

    result["expanded"] = expanded
    result["feasible_orders"] = feasible
    result["rejected"] = rejected
    result["rejected_total"] = rejected_total
    result["rejected_truncated"] = rejected_total > len(rejected)
    result["rejected_note"] = (
        f"仅保留前 {len(rejected)} 条，共 {rejected_total} 条失败候选"
        if result["rejected_truncated"]
        else ""
    )
    if best is None:
        # Under current fixed/search semantics the identity order reproduces the
        # baseline, so a successful baseline always leaves one feasible candidate.
        # This branch remains as the required defensive outcome for future modes.
        result.update(
            status="failed",
            reason=(
                f"全部 {expanded} 个顺序均不可行；首个原因: {identity_reason or '未知原因'}"
            ),
            optimality_gap=None,
        )
        return result

    _, chosen = best
    result.update(
        status="success",
        order=chosen["order"],
        transition_length=chosen["transition_length"],
        total_path_length=chosen["total_path_length"],
        total_time=chosen["total_time"],
        optimality_gap=0.0,
        search_nodes=chosen["search_nodes"],
        search_routes=chosen["search_routes"],
        best=dict(
            plan_hash=chosen["plan_hash"],
            execution_id=chosen["execution_id"],
            segments=chosen["segments"],
            safety="pass",
        ),
    )
    result["improvement"] = _improvement(baseline, chosen)
    return result


def candidate_plan(scene, config=None, order=None, options=None):
    """Rebuild the complete plan for a given lane order (used for independent checks)."""
    raw = _raw_config(config)
    effective = configuration(raw)
    baseline = generate_plan(scene, raw)
    normalized = _options(options, effective)
    if baseline.get("status") == "success":
        lanes = _spray_lanes(baseline)
    elif normalized["transition"] == "caw":
        from planning.planner import fixed_y_lanes

        lanes = copy.deepcopy(fixed_y_lanes(scene, effective)["lanes"])
    else:
        raise ValueError(f"基准计划失败: {baseline.get('reason', '未知原因')}")
    chosen = list(range(len(lanes))) if order is None else list(order)
    if sorted(chosen) != list(range(len(lanes))):
        raise ValueError("order 必须是全部喷洒航段的一个排列")
    context = _context(scene, effective, normalized)
    plan, _, _, _ = _build_plan(
        scene,
        effective,
        lanes,
        chosen,
        context,
        {},
        baseline.get("strip_count", len(lanes)),
        normalized,
    )
    return plan


def verify(result, scene, config=None):
    """Reject stale or tampered joint results before they are displayed or saved."""
    if not isinstance(result, dict):
        raise ValueError("联合结果必须是对象")
    if result.get("scene_hash") != fingerprint(scene):
        raise ValueError("场景指纹不匹配：结果已失效")
    if config is not None:
        effective = configuration(_raw_config(config))
        if result.get("config_hash") != config_fingerprint(effective):
            raise ValueError("配置指纹不匹配：结果已失效")
    status = result.get("status")
    if status not in ("success", "failed", "unsupported"):
        raise ValueError("未知联合状态")
    if status == "success":
        order = result.get("order")
        count = result.get("spray_count")
        if (
            not isinstance(order, list)
            or not isinstance(count, int)
            or sorted(order) != list(range(count))
        ):
            raise ValueError("最优顺序不是完整排列")
        for key in ("total_time", "total_path_length", "transition_length"):
            value = result.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{key} 不是有限数值")
        if result.get("optimality_gap") != 0.0:
            raise ValueError("精确穷举结果的 optimality_gap 必须为 0")
        if result.get("expanded") != result.get("orders_total"):
            raise ValueError("未穷举全部顺序，不能声明精确最优")
        if result.get("feasible_orders", 0) < 1:
            raise ValueError("成功结果必须至少有一个可行顺序")
        if result.get("transition") == "caw":
            options = result.get("planner_options")
            if not isinstance(options, dict):
                raise ValueError("caw 结果缺少 planner_options")
            if result.get("planner_options_hash") != options_fingerprint(options):
                raise ValueError("caw 规划器参数指纹不匹配")
            if result.get("method") != METHOD_CAW:
                raise ValueError("caw 结果方法名不一致")
            plan = candidate_plan(scene, config, order, options)
            metrics = _metrics(scene, plan)
            for key in ("total_time", "total_path_length", "transition_length"):
                if abs(metrics[key] - result.get(key, math.inf)) > 1e-9:
                    raise ValueError(f"caw 成功结果复核不一致: {key}")
    else:
        if result.get("order") is not None or result.get("total_time") is not None:
            raise ValueError("失败或 unsupported 结果不得携带最优方案")
        if not result.get("reason"):
            raise ValueError("失败或 unsupported 结果必须保留原因")
    return True


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))
