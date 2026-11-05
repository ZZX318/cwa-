"""Layered three-dimensional clearance A* for transition legs.

Occupancy uses the very same closed-slab predicate as the independent safety
check (``planning.safety.intersects``), so a route that the search accepts is
also accepted by ``planning.safety.check``.  The graph is layered: eight
same-layer neighbours plus vertical moves between adjacent layers.  That keeps
the node count linear in area x layers while still allowing climb-over detours.

No-spray zones are deliberately *not* obstacles here: they constrain the spray
footprint only (禁喷 != 禁飞).
"""

import copy
import heapq
import math
from collections import OrderedDict

try:  # package import (normal path)
    from .model import configuration, config_fingerprint, fingerprint
    from .safety import intersects
    from .wind import effective_speed, horizon_heuristic, max_effective_speed, segment_energy, segment_time
except ImportError:  # direct ``import routing3d`` from the project root
    from planning.model import configuration, config_fingerprint, fingerprint
    from planning.safety import intersects
    from planning.wind import effective_speed, horizon_heuristic, max_effective_speed, segment_energy, segment_time

MODEL = "layered-3d-clearance-a-star"
EPS = 1e-6
DEFAULT_STEP = 1.0
DEFAULT_MAX_EXPANSIONS = 200000
DEFAULT_MAX_GRID_NODES = 2000000
MAX_CACHE = 2048

_GRID_CACHE = OrderedDict()
_ROUTE_CACHE = OrderedDict()


def _float_key(value):
    """Exact float identity for cache keys (no rounding)."""
    return float(value).hex()


def _point_key(point):
    return tuple(_float_key(v) for v in point)


class _GridTooLarge(Exception):
    """Raised before allocating a free mask that would exceed the node cap."""

    def __init__(self, total, layers, grid_hash, step_xy, bounds):
        self.total = total
        self.layers = layers
        self.grid_hash = grid_hash
        self.step_xy = step_xy
        self.bounds = bounds
        super().__init__(f"网格节点 {total} 超过上限")

# Deterministic neighbour order: (dx, dy, dz) lexicographic.
_NEIGHBOURS = (
    (-1, -1, 0),
    (-1, 0, 0),
    (-1, 1, 0),
    (0, -1, 0),
    (0, 0, -1),
    (0, 0, 1),
    (0, 1, 0),
    (1, -1, 0),
    (1, 0, 0),
    (1, 1, 0),
)


def _boxes(scene, clearance):
    boxes = []
    for tree in scene["trees"]:
        for kind in ("trunk", "canopy"):
            g = tree[kind]
            x, y = g["center"]
            r = g["radius"]
            boxes.append(
                (
                    [x - r - clearance, y - r - clearance, g["z_min"] - clearance],
                    [x + r + clearance, y + r + clearance, g["z_max"] + clearance],
                )
            )
    for obstacle in scene["obstacles"]:
        boxes.append(
            (
                [v - clearance for v in obstacle["min"]],
                [v + clearance for v in obstacle["max"]],
            )
        )
    for zone in scene["no_fly_zones"]:
        bounds = zone["footprint"]
        lo = [
            min(v[0] for v in bounds["vertices"]) - clearance,
            min(v[1] for v in bounds["vertices"]) - clearance,
            zone["z_min"] - clearance,
        ]
        hi = [
            max(v[0] for v in bounds["vertices"]) + clearance,
            max(v[1] for v in bounds["vertices"]) + clearance,
            zone["z_max"] + clearance,
        ]
        boxes.append((lo, hi))
    return boxes


def _point_free(boxes, point):
    for lo, hi in boxes:
        if all(lo[i] <= point[i] <= hi[i] for i in range(3)):
            return False
    return True


def _segment_free(boxes, a, b):
    for lo, hi in boxes:
        if intersects(a, b, lo, hi):
            return False
    return True


def _critical_layers(scene, config, extra_z):
    clearance = config["clearance"]
    work_height = max(t["canopy"]["z_max"] for t in scene["trees"]) + config["height_offset"]
    values = {scene["extent"]["min"][2] + clearance, scene["extent"]["max"][2] - clearance, work_height}
    for tree in scene["trees"]:
        for kind in ("canopy", "trunk"):
            values.add(tree[kind]["z_max"] + clearance + EPS)
    for obstacle in scene["obstacles"]:
        values.add(obstacle["max"][2] + clearance + EPS)
    for zone in scene["no_fly_zones"]:
        values.add(zone["z_max"] + clearance + EPS)
    values.update(extra_z)
    return values


def _make_grid(scene, config, step_xy, step_z, start, goal, max_nodes):
    clearance = config["clearance"]
    extent = scene["extent"]
    floor = extent["min"][2] + clearance
    ceiling = extent["max"][2] - clearance
    if floor > ceiling:
        raise ValueError("场景高度不足以容纳安全净空")
    critical = _critical_layers(scene, config, (start[2], goal[2]))
    layers = set()
    count = int(math.floor((ceiling - floor) / step_z)) + 1
    for k in range(count + 1):
        z = floor + k * step_z
        if z <= ceiling + 1e-9:
            layers.add(round(z, 9))
    for z in critical:
        if floor - 1e-9 <= z <= ceiling + 1e-9:
            layers.add(round(z, 9))
    layers = sorted(layers)
    x0, x1 = extent["min"][0], extent["max"][0]
    y0, y1 = extent["min"][1], extent["max"][1]
    xs = []
    x = x0 + step_xy / 2
    while x <= x1 + 1e-9:
        xs.append(round(x, 9))
        x += step_xy
    ys = []
    y = y0 + step_xy / 2
    while y <= y1 + 1e-9:
        ys.append(round(y, 9))
        y += step_xy
    if not xs or not ys:
        raise ValueError("网格范围为空")
    nx, ny, nz = len(xs), len(ys), len(layers)
    meta = dict(
        model=MODEL,
        step_xy=step_xy,
        step_z=step_z,
        clearance=clearance,
        bounds=dict(min=list(extent["min"]), max=list(extent["max"])),
        layers=layers,
        counts=[nx, ny, nz],
        scene_hash=fingerprint(scene),
    )
    meta_hash = fingerprint(meta)
    total = nx * ny * nz
    if total > max_nodes:
        raise _GridTooLarge(
            total,
            len(layers),
            meta_hash,
            step_xy,
            dict(min=list(extent["min"]), max=list(extent["max"])),
        )
    boxes = _boxes(scene, clearance)
    free = [False] * total
    for iz, z in enumerate(layers):
        for iy, y in enumerate(ys):
            for ix, x in enumerate(xs):
                if _point_free(boxes, [x, y, z]):
                    free[(iz * ny + iy) * nx + ix] = True
    return dict(
        xs=xs,
        ys=ys,
        layers=layers,
        nx=nx,
        ny=ny,
        nz=nz,
        free=free,
        boxes=boxes,
        clearance=clearance,
        step_xy=step_xy,
        step_z=step_z,
        hash=meta_hash,
        meta=meta,
    )


def _grid_for(scene, config, step_xy, step_z, start, goal, max_nodes):
    # Exact Z identity: layers already round Z internally, but key must not
    # alias ULP-distinct callers the way round(..., 9) did for routes.
    key = (
        fingerprint(scene),
        config_fingerprint(config),
        step_xy,
        step_z,
        _float_key(start[2]),
        _float_key(goal[2]),
    )
    grid = _GRID_CACHE.get(key)
    if grid is None:
        grid = _make_grid(scene, config, step_xy, step_z, start, goal, max_nodes)
        _GRID_CACHE[key] = grid
        while len(_GRID_CACHE) > 8:
            _GRID_CACHE.popitem(last=False)
    return grid


def _node_point(grid, ix, iy, iz):
    return [grid["xs"][ix], grid["ys"][iy], grid["layers"][iz]]


def _layer_index(grid, z):
    for iz, value in enumerate(grid["layers"]):
        if abs(value - z) <= 1e-9:
            return iz
    best = min(range(len(grid["layers"])), key=lambda i: (abs(grid["layers"][i] - z), i))
    return best


def _nearest_node(grid, point):
    iz = _layer_index(grid, point[2])
    nx, ny = grid["nx"], grid["ny"]
    base = iz * ny * nx
    candidates = []
    for iy, y in enumerate(grid["ys"]):
        row = base + iy * nx
        for ix, x in enumerate(grid["xs"]):
            if not grid["free"][row + ix]:
                continue
            candidates.append((math.hypot(x - point[0], y - point[1]), ix, iy))
    candidates.sort()
    for _, ix, iy in candidates[:512]:
        node = _node_point(grid, ix, iy, iz)
        if _segment_free(grid["boxes"], list(point), node):
            return ix, iy, iz
    return None


def _is_free(grid, ix, iy, iz):
    if not (0 <= ix < grid["nx"] and 0 <= iy < grid["ny"] and 0 <= iz < grid["nz"]):
        return False
    return grid["free"][(iz * grid["ny"] + iy) * grid["nx"] + ix]


def _edge_cost(a, b, speed, config, objective, vertical_speed):
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    horizontal = math.hypot(dx, dy)
    if objective == "time":
        cost = 0.0
        if horizontal > 1e-12:
            cost += horizontal / effective_speed(a, b, speed, config)
        cost += abs(dz) / vertical_speed
        return cost
    return segment_energy(a, b, speed, config)


def _heuristic(point, goal_node, speed, config, objective, vertical_speed):
    return horizon_heuristic(
        point, goal_node, speed, config, objective=objective, vertical_speed=vertical_speed
    )


def _line_of_sight(path, boxes, cost):
    """Greedy shortcutting that never increases the objective cost.

    A shortcut is accepted only when its own cost is no larger than the cost of
    the nodes it replaces, so the smoothed path can never be slower than the
    grid path under anisotropic wind.
    """
    if len(path) <= 2:
        return path
    prefix = [0.0]
    for a, b in zip(path, path[1:]):
        prefix.append(prefix[-1] + cost(a, b))
    out = [path[0]]
    i = 0
    last = len(path) - 1
    while i < last:
        chosen = i + 1
        for j in range(last, i + 1, -1):
            if not _segment_free(boxes, path[i], path[j]):
                continue
            if cost(path[i], path[j]) <= prefix[j] - prefix[i] + 1e-12:
                chosen = j
                break
        out.append(path[chosen])
        i = chosen
    return out


def _result_failure(reason, expanded, generated, grid, objective, config, scene):
    return dict(
        version="1.0",
        model=MODEL,
        status="failed",
        stage="search",
        reason=reason,
        path=[],
        length=None,
        cost=None,
        time=None,
        energy=None,
        expanded=expanded,
        generated=generated,
        grid=dict(
            hash=grid["hash"],
            step_xy=grid["step_xy"],
            layers=len(grid.get("layers", [])),
            bounds=dict(
                min=list(grid["meta"]["bounds"]["min"]),
                max=list(grid["meta"]["bounds"]["max"]),
            ),
        ),
        objective=objective,
        clearance=config["clearance"],
        max_effective_speed=max_effective_speed(config["speed"], config),
        scene_hash=fingerprint(scene),
        config_hash=config_fingerprint(config),
    )


def route3d(scene, start, goal, config, objective="time", grid=None):
    """Search a clearance-aware 3D transition path.

    ``grid`` may carry ``step_xy``, ``step_z``, ``max_expansions`` and
    ``max_grid_nodes``.  Invalid input raises ``ValueError``; an unsolved
    instance returns ``status="failed"`` with a reason and the search counters.
    """
    if objective not in ("time", "energy"):
        raise ValueError("objective 必须为 time 或 energy")
    if not isinstance(config, dict):
        raise ValueError("config 必须是对象")
    effective = configuration(config)
    options = dict(grid or {})
    unknown = set(options) - {
        "step_xy",
        "step_z",
        "max_expansions",
        "max_grid_nodes",
        "smoothing",
    }
    if unknown:
        raise ValueError("未知网格参数")
    smoothing = options.get("smoothing", True)
    if type(smoothing) is not bool:
        raise ValueError("smoothing 必须为布尔值")
    step_xy = options.get("step_xy", DEFAULT_STEP)
    step_z = options.get("step_z", DEFAULT_STEP)
    for name, value in (("step_xy", step_xy), ("step_z", step_z)):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为有限正数")
    max_expansions = options.get("max_expansions", DEFAULT_MAX_EXPANSIONS)
    max_grid_nodes = options.get("max_grid_nodes", DEFAULT_MAX_GRID_NODES)
    for name, value in (("max_expansions", max_expansions), ("max_grid_nodes", max_grid_nodes)):
        if type(value) is not int or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} 必须为正整数")
    for name, point in (("起点", start), ("终点", goal)):
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
        ):
            raise ValueError(f"{name}坐标非法")
    start = [float(v) for v in start]
    goal = [float(v) for v in goal]
    if math.dist(start, goal) <= 1e-9:
        raise ValueError("起点与终点重合")

    # Exact start/goal identity via float.hex — round(..., 9) falsely aliased
    # ULP-near lane endpoints (F3 seed2 heuristic→B) and returned the first
    # caller's path endpoints, changing plan_hash while metrics stayed equal.
    cache_key = (
        fingerprint(scene),
        config_fingerprint(effective),
        objective,
        _point_key(start),
        _point_key(goal),
        step_xy,
        step_z,
        max_expansions,
        max_grid_nodes,
        smoothing,
    )
    cached = _ROUTE_CACHE.get(cache_key)
    if cached is not None:
        hit = copy.deepcopy(cached)
        if (
            hit.get("status") == "success"
            and hit.get("path")
            and (list(hit["path"][0]) != start or list(hit["path"][-1]) != goal)
        ):
            pass  # treat as miss; fall through to recompute
        else:
            return hit

    try:
        grid_data = _grid_for(
            scene, effective, step_xy, step_z, start, goal, max_grid_nodes
        )
    except _GridTooLarge as error:
        return dict(
            version="1.0",
            model=MODEL,
            status="failed",
            stage="search",
            reason=f"网格节点 {error.total} 超过上限 {max_grid_nodes}",
            path=[],
            length=None,
            cost=None,
            time=None,
            energy=None,
            expanded=0,
            generated=0,
            grid=dict(
                hash=error.grid_hash,
                step_xy=error.step_xy,
                layers=error.layers,
                bounds=error.bounds,
            ),
            objective=objective,
            clearance=effective["clearance"],
            max_effective_speed=max_effective_speed(effective["speed"], effective),
            scene_hash=fingerprint(scene),
            config_hash=config_fingerprint(effective),
        )
    nodes_total = grid_data["nx"] * grid_data["ny"] * grid_data["nz"]
    if nodes_total > max_grid_nodes:
        result = _result_failure(
            f"网格节点 {nodes_total} 超过上限 {max_grid_nodes}", 0, 0, grid_data, objective, effective, scene
        )
        return result

    if not _point_free(grid_data["boxes"], start):
        return _result_failure("起点位于实体净空或禁飞包围盒内", 0, 0, grid_data, objective, effective, scene)
    if not _point_free(grid_data["boxes"], goal):
        return _result_failure("终点位于实体净空或禁飞包围盒内", 0, 0, grid_data, objective, effective, scene)
    for name, point in (("起点", start), ("终点", goal)):
        if any(
            v < lo or v > hi
            for v, lo, hi in zip(point, scene["extent"]["min"], scene["extent"]["max"])
        ):
            return _result_failure(f"{name}超出场景范围", 0, 0, grid_data, objective, effective, scene)
    transit_floor = scene["extent"]["min"][2] + effective["clearance"]
    transit_ceiling = scene["extent"]["max"][2] - effective["clearance"]
    for name, point in (("起点", start), ("终点", goal)):
        if point[2] < transit_floor - 1e-9 or point[2] > transit_ceiling + 1e-9:
            return _result_failure(
                f"{name}高度超出净空范围 [{transit_floor}, {transit_ceiling}]",
                0,
                0,
                grid_data,
                objective,
                effective,
                scene,
            )

    start_node = _nearest_node(grid_data, start)
    goal_node = _nearest_node(grid_data, goal)
    if start_node is None or goal_node is None:
        return _result_failure("起点或终点无法接入自由网格节点", 0, 0, grid_data, objective, effective, scene)

    speed = effective["speed"]
    vertical_speed = speed
    goal_point = _node_point(grid_data, *goal_node)
    openq = [
        (
            _heuristic(_node_point(grid_data, *start_node), goal_point, speed, effective, objective, vertical_speed),
            0.0,
            start_node[0],
            start_node[1],
            start_node[2],
        )
    ]
    best = {start_node: 0.0}
    came = {}
    expanded = 0
    generated = 1
    found = False
    while openq:
        _, g, ix, iy, iz = heapq.heappop(openq)
        node = (ix, iy, iz)
        if g > best.get(node, math.inf) + 1e-12:
            continue
        if expanded >= max_expansions:
            return _result_failure(
                f"展开节点达到上限 {max_expansions}", expanded, generated, grid_data, objective, effective, scene
            )
        expanded += 1
        if node == goal_node:
            found = True
            break
        for dx, dy, dz in _NEIGHBOURS:
            nx, ny, nz = ix + dx, iy + dy, iz + dz
            if not _is_free(grid_data, nx, ny, nz):
                continue
            if dx and dy and iz == nz:
                if not _is_free(grid_data, ix + dx, iy, iz) or not _is_free(grid_data, ix, iy + dy, iz):
                    continue
            a = _node_point(grid_data, ix, iy, iz)
            b = _node_point(grid_data, nx, ny, nz)
            if not _segment_free(grid_data["boxes"], a, b):
                continue
            neighbour = (nx, ny, nz)
            ng = g + _edge_cost(a, b, speed, effective, objective, vertical_speed)
            if ng + 1e-12 >= best.get(neighbour, math.inf):
                continue
            best[neighbour] = ng
            came[neighbour] = node
            heapq.heappush(
                openq,
                (
                    ng + _heuristic(b, goal_point, speed, effective, objective, vertical_speed),
                    ng,
                    nx,
                    ny,
                    nz,
                ),
            )
            generated += 1
    if not found:
        return _result_failure(
            "离散搜索未找到满足净空的路径", expanded, generated, grid_data, objective, effective, scene
        )

    nodes = [goal_node]
    while nodes[-1] != start_node:
        nodes.append(came[nodes[-1]])
    nodes.reverse()
    path = [start]
    for ix, iy, iz in nodes:
        point = _node_point(grid_data, ix, iy, iz)
        if math.dist(path[-1], point) > 1e-9:
            path.append(point)
    if math.dist(path[-1], goal) > 1e-9:
        path.append(goal)
    if smoothing:
        path = _line_of_sight(
            path,
            grid_data["boxes"],
            lambda a, b: _edge_cost(
                a, b, speed, effective, objective, vertical_speed
            ),
        )
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    time = sum(
        segment_time(a, b, speed, effective, version="1.2")
        for a, b in zip(path, path[1:])
    )
    energy = (
        sum(segment_energy(a, b, speed, effective) for a, b in zip(path, path[1:]))
        if objective == "energy"
        else None
    )
    result = dict(
        version="1.0",
        model=MODEL,
        status="success",
        stage="search",
        reason="",
        path=path,
        length=length,
        cost=time if objective == "time" else energy,
        time=time,
        energy=energy,
        expanded=expanded,
        generated=generated,
        grid=dict(
            hash=grid_data["hash"],
            step_xy=step_xy,
            step_z=step_z,
            layers=len(grid_data["layers"]),
            bounds=dict(
                min=list(grid_data["meta"]["bounds"]["min"]),
                max=list(grid_data["meta"]["bounds"]["max"]),
            ),
        ),
        objective=objective,
        clearance=effective["clearance"],
        max_effective_speed=max_effective_speed(speed, effective),
        smoothing=smoothing,
        optimality=(
            "proxy"
            if objective != "time"
            else ("grid-optimal" if not smoothing else "grid-search-nonworsening")
        ),
        epsilon=1.0,
        scene_hash=fingerprint(scene),
        config_hash=config_fingerprint(effective),
    )
    _ROUTE_CACHE[cache_key] = copy.deepcopy(result)
    while len(_ROUTE_CACHE) > MAX_CACHE:
        _ROUTE_CACHE.popitem(last=False)
    return result


def clear_cache():
    _GRID_CACHE.clear()
    _ROUTE_CACHE.clear()
