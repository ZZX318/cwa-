"""Deterministic spray-lane ordering heuristics over transition cost matrices.

Two matrix modes are reported explicitly:

* ``exact3d`` for ``n <= 20``: every ordered pair (including home) is routed by
  ``routing3d`` with the shared time model.
* ``euclidean_lb`` for ``n > 20``: straight-line 3D distance / best effective
  speed, which is a lower bound on any feasible route.  The resulting order is
  only a proxy decision; it is *not* claimed optimal under 3D costs.

The reported ``lower_bound`` is the incoming-minimum relaxation of the
order-related objective.  Gaps are therefore "distance to a lower bound", never
"distance to the optimum".
"""

import math

from .model import configuration
from .drift import drift_cost_buffer, lane_drift_proxy
from .routing3d import route3d
from .wind import horizon_heuristic, max_effective_speed, segment_time

HOME_INDEX = 0
ROUTE_FAILURE_LIMIT = 50
DEFAULT_2OPT_ROUNDS = 20


def _spray_seconds(lanes, config):
    return sum(
        segment_time(lane["start"], lane["end"], lane["speed"], config, version="1.2")
        for lane in lanes
    )


def _work_home(scene, config):
    """Home at the spray work height: takeoff/landing are order-independent."""
    launch = sorted(scene["launch_points"], key=lambda p: tuple(p["position"]))[0]["position"]
    height = max(t["canopy"]["z_max"] for t in scene["trees"]) + config["height_offset"]
    return [launch[0], launch[1], height]


def _pair_cost(scene, config, a, b, objective, matrix_mode, step_xy):
    if matrix_mode == "euclidean_lb":
        speed = config["speed"]
        if objective == "time":
            return math.dist(a, b) / max_effective_speed(speed, config), None
        return horizon_heuristic(a, b, speed, config, objective="energy"), None
    result = route3d(
        scene,
        list(a),
        list(b),
        config,
        objective=objective,
        grid={"step_xy": step_xy},
    )
    if result["status"] != "success":
        return math.inf, result
    return result["cost"], result


def cost_matrix(scene, config, lanes, home=None, objective="time", matrix_mode=None, step_xy=1.0):
    """Return ``C`` with home as index 0 and lanes as 1..n, plus diagnostics."""
    if objective not in ("time", "energy"):
        raise ValueError("objective 必须为 time 或 energy")
    count = len(lanes)
    if matrix_mode is None:
        matrix_mode = "exact3d" if count <= 20 else "euclidean_lb"
    if matrix_mode not in ("exact3d", "euclidean_lb"):
        raise ValueError("matrix_mode 必须为 exact3d 或 euclidean_lb")
    if count > 20 and matrix_mode == "exact3d":
        raise ValueError("超过 20 条航段时不允许完整 exact3d 矩阵")
    if home is None:
        home = _work_home(scene, config)
    points = [list(home)] + [
        list(lane["start"]) for lane in lanes
    ]
    ends = [list(home)] + [list(lane["end"]) for lane in lanes]
    size = count + 1
    matrix = [[math.inf] * size for _ in range(size)]
    failures = []
    routes = 0
    failures_total = 0
    drift_mode = config.get("drift_mode", "sort")
    # 与 buffer_expand 解耦：关外扩仍可跑 sort_drift 消融
    drift_buffer_m = drift_cost_buffer(config) if drift_mode == "sort_drift" else 0.0
    for i in range(size):
        for j in range(size):
            if i == j:
                matrix[i][j] = 0.0
                continue
            cost, detail = _pair_cost(
                scene, config, ends[i], points[j], objective, matrix_mode, step_xy
            )
            if matrix_mode == "exact3d":
                routes += 1
            if not math.isfinite(cost):
                failures_total += 1
                if len(failures) < ROUTE_FAILURE_LIMIT:
                    failures.append(
                        dict(
                            from_index=i,
                            to_index=j,
                            start=ends[i],
                            end=points[j],
                            stage="search",
                            reason=(detail or {}).get("reason", "路径不可行"),
                        )
                    )
                continue
            # sort_drift：进入该喷带时叠加侧风–漂移代理（与转场代价相加）
            if drift_mode == "sort_drift" and j >= 1 and drift_buffer_m > 0:
                cost = cost + lane_drift_proxy(lanes[j - 1], scene, config, drift_buffer_m)
            matrix[i][j] = cost
    return dict(
        matrix=matrix,
        home=points[0],
        matrix_mode=matrix_mode,
        routes_computed=routes,
        route_failures=failures,
        route_failures_total=failures_total,
        failure_truncated=failures_total > len(failures),
    )


def _order_cost(matrix, order):
    total = matrix[HOME_INDEX][order[0] + 1]
    for a, b in zip(order, order[1:]):
        total += matrix[a + 1][b + 1]
    total += matrix[order[-1] + 1][HOME_INDEX]
    return total


def _nn_order(matrix, count, start):
    """Nearest neighbour from a fixed first lane; None when an edge is infeasible."""
    remaining = set(range(count))
    order = [start]
    remaining.remove(start)
    current = start + 1
    while remaining:
        nxt = min(remaining, key=lambda j: (matrix[current][j + 1], j))
        if not math.isfinite(matrix[current][nxt + 1]):
            return None
        order.append(nxt)
        remaining.remove(nxt)
        current = nxt + 1
    return order


def _two_opt(matrix, order, rounds):
    best = list(order)
    best_cost = _order_cost(matrix, best)
    evaluated = 0
    for _ in range(rounds):
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                if j - i < 1:
                    continue
                candidate = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                evaluated += 1
                cost = _order_cost(matrix, candidate)
                if cost < best_cost - 1e-9:
                    best, best_cost = candidate, cost
                    improved = True
        if not improved:
            break
    return best, best_cost, evaluated


def lower_bound(matrix, spray_seconds, count):
    """Incoming-minimum relaxation; None when any required edge is infeasible."""
    incoming = 0.0
    for lane in range(1, count + 1):
        options = [matrix[u][lane] for u in range(count + 1) if u != lane]
        if not options or any(not math.isfinite(v) for v in options):
            return None
        incoming += min(options)
    returns = [matrix[u][HOME_INDEX] for u in range(1, count + 1)]
    if not returns or any(not math.isfinite(v) for v in returns):
        return None
    return spray_seconds + incoming + min(returns)


def _failure(reason, **extra):
    result = dict(
        version="1.0",
        status="failed",
        reason=reason,
        strategy=None,
        order=None,
        order_cost=None,
        lower_bound=None,
        gap_to_bound_abs=None,
        gap_to_bound_rel=None,
        bound_type="incoming-min-relaxation",
        matrix_mode=None,
        routes_computed=0,
        evaluated=0,
        route_failures=[],
        route_failures_total=0,
        matrix=None,
    )
    result.update(extra)
    return result


def solve_order(
    scene,
    config=None,
    lanes=None,
    strategy="nn+2opt",
    objective="time",
    home=None,
    matrix_mode=None,
    step_xy=1.0,
    rounds=DEFAULT_2OPT_ROUNDS,
):
    """Return a deterministic lane order plus explicit cost-model diagnostics."""
    if not isinstance(config, dict):
        raise ValueError("config 必须是对象")
    effective = configuration(config)
    if not isinstance(lanes, list) or not lanes:
        raise ValueError("lanes 必须是非空列表")
    if strategy not in ("fixed", "nn", "nn+2opt"):
        raise ValueError("strategy 必须为 fixed、nn 或 nn+2opt")
    if objective not in ("time", "energy"):
        raise ValueError("objective 必须为 time 或 energy")
    if type(rounds) is not int or isinstance(rounds, bool) or rounds < 0:
        raise ValueError("rounds 必须为非负整数")
    count = len(lanes)
    home = _work_home(scene, effective) if home is None else list(home)
    spray_seconds = _spray_seconds(lanes, effective)
    if strategy == "fixed":
        matrix_info = None
        order = list(range(count))
        return dict(
            version="1.0",
            status="success",
            reason="",
            strategy=strategy,
            objective=objective,
            order=order,
            order_cost=None,
            lower_bound=None,
            gap_to_bound_abs=None,
            gap_to_bound_rel=None,
            bound_type="incoming-min-relaxation",
            matrix_mode=None,
            routes_computed=0,
            evaluated=1,
            route_failures=[],
            route_failures_total=0,
            matrix=None,
        )
    matrix_info = cost_matrix(
        scene,
        effective,
        lanes,
        home=home,
        objective=objective,
        matrix_mode=matrix_mode,
        step_xy=step_xy,
    )
    matrix = matrix_info["matrix"]
    evaluated = 0
    candidates = []
    for start in range(count):
        evaluated += 1
        order = _nn_order(matrix, count, start)
        if order is not None:
            cost = _order_cost(matrix, order)
            if math.isfinite(cost):
                candidates.append((cost, start, order))
    if not candidates:
        failures = matrix_info["route_failures"]
        first = failures[0]["reason"] if failures else "顺序相关转场边不可行"
        result = _failure(
            f"全部 {count} 个最近邻起点均不可行；首个原因: {first}",
            strategy=strategy,
            objective=objective,
            matrix_mode=matrix_info["matrix_mode"],
            routes_computed=matrix_info["routes_computed"],
            evaluated=evaluated,
            route_failures=failures,
            route_failures_total=matrix_info["route_failures_total"],
        )
        return result
    candidates.sort(key=lambda item: (item[0], item[1]))
    best_cost, _, best_order = candidates[0]
    two_opt_evaluated = 0
    if strategy == "nn+2opt":
        best_order, best_cost, two_opt_evaluated = _two_opt(matrix, best_order, rounds)
    evaluated += two_opt_evaluated
    order_cost = spray_seconds + best_cost
    bound = lower_bound(matrix, spray_seconds, count)
    gap_abs = None if bound is None else order_cost - bound
    gap_rel = None
    if bound not in (None, 0) and gap_abs is not None:
        gap_rel = gap_abs / bound
    return dict(
        version="1.0",
        status="success",
        reason="",
        strategy=strategy,
        objective=objective,
        order=best_order,
        order_cost=order_cost,
        spray_seconds=spray_seconds,
        lower_bound=bound,
        gap_to_bound_abs=gap_abs,
        gap_to_bound_rel=gap_rel,
        bound_type="incoming-min-relaxation",
        matrix_mode=matrix_info["matrix_mode"],
        routes_computed=matrix_info["routes_computed"],
        evaluated=evaluated,
        route_failures=matrix_info["route_failures"],
        route_failures_total=matrix_info["route_failures_total"],
        failure_truncated=matrix_info["failure_truncated"],
        matrix_stats=dict(
            size=count + 1,
            finite=sum(1 for row in matrix for value in row if math.isfinite(value)),
            infinite=sum(1 for row in matrix for value in row if not math.isfinite(value)),
        ),
    )
