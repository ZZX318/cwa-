"""Real planner protocol and registry.

Every planner returns a complete plan object.  A successful plan must pass the
shared independent safety check; a failed one must carry ``stage`` and
``reason``.  ``planner_options`` stay outside the job configuration so legacy
plan fingerprints are untouched.
"""

import math

from planning import (
    check,
    config_fingerprint,
    configuration,
    fingerprint,
    generate_plan,
    options_fingerprint,
)
from planning.order import solve_order
from planning.planner import fixed_y_lanes, lane_parts, zone_exclusions
from planning.routing3d import route3d
from scene import validate_scene
from scene.launch import resolve


def _home(scene):
    return list(sorted(scene["launch_points"], key=lambda p: tuple(p["position"]))[0]["position"])


def _failed(
    scene,
    config,
    planner,
    reason,
    stage,
    version="1.2",
    options=None,
    method=None,
    objective="time",
):
    plan = dict(
        version=version,
        planner=planner,
        method=method or planner,
        objective=objective,
        scene_hash=fingerprint(scene),
        status="failed",
        stage=stage,
        reason=reason,
        segments=[],
    )
    if isinstance(config, dict):
        try:
            effective = configuration(config)
            plan["config"] = effective
            plan["config_hash"] = config_fingerprint(effective)
        except (ValueError, KeyError, TypeError):
            pass
    if options is not None and version == "1.2":
        plan["planner_options"] = options
        plan["planner_options_hash"] = options_fingerprint(options)
    return plan


class Planner:
    name = "planner"
    version = "1.1"
    capabilities = {}

    def validate_options(self, options):
        if options not in (None, {}):
            raise ValueError(f"{self.name} 不支持规划器参数")
        return {}

    def plan(self, scene, config=None, options=None):
        raise NotImplementedError


class FixedYPlanner(Planner):
    name = "fixed-y-boustrophedon"
    version = "1.1"
    capabilities = dict(
        lane_geometry="fixed-y",
        transition="straight-or-legacy-search",
        objective=["time"],
    )

    def plan(self, scene, config=None, options=None):
        try:
            self.validate_options(options)
        except ValueError as error:
            return _failed(scene, config or {}, self.name, str(error), "plan", version="1.1")
        return generate_plan(scene, config or {})


class NaivePlanner(Planner):
    """One short Y spray per target, connected by same-height straight transits."""

    name = "naive-target-order"
    version = "1.1"
    capabilities = dict(
        lane_geometry="per-target-short-y",
        transition="straight",
        objective=["time"],
    )

    def validate_options(self, options):
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise ValueError("规划器参数必须是对象")
        unknown = set(options) - {"transition"}
        if unknown:
            raise ValueError("未知规划器参数")
        transition = options.get("transition", "straight")
        if transition != "straight":
            raise ValueError("naive 当前仅支持直线同高度转场")
        return dict(transition=transition)

    def plan(self, scene, config=None, options=None):
        try:
            normalized = self.validate_options(options)
        except (ValueError, TypeError) as error:
            return _failed(
                scene, config or {}, self.name, str(error), "plan", version="1.1"
            )
        try:
            validate_scene(scene)
            c = configuration(config or {})
            if not scene["targets"] or not scene["trees"]:
                raise ValueError("不支持空目标场景")
            height = max(t["canopy"]["z_max"] for t in scene["trees"]) + c["height_offset"]
            home = _home(scene)
            targets = sorted(scene["targets"], key=lambda t: t["id"])
            segments = []
            current = list(home)

            def add(end, kind, ids=None):
                nonlocal current
                if math.dist(current, end) <= 1e-8:
                    return
                segments.append(
                    dict(
                        start=current[:],
                        end=list(end),
                        type=kind,
                        spray=kind == "spray",
                        speed=c["speed"],
                        target_ids=sorted(ids or []),
                    )
                )
                current = list(end)

            add([home[0], home[1], height], "takeoff")
            for target in targets:
                geometry = target["geometry"]
                center = geometry["center"]
                radius = geometry["radius"]
                start = [center[0], center[1] - radius, height]
                end = [center[0], center[1] + radius, height]
                add(start, "transit")
                add(end, "spray", [target["id"]])
            add([home[0], home[1], height], "transit")
            add(home, "landing")
            plan = dict(
                version="1.1",
                planner=self.name,
                method=self.name,
                objective="time",
                scene_hash=fingerprint(scene),
                status="success",
                reason="",
                segments=segments,
                work_height=height,
                strip_count=len(targets),
                planner_options=normalized,
                planner_options_hash=options_fingerprint(normalized),
                config=c,
                config_hash=config_fingerprint(c),
            )
        except (ValueError, KeyError, TypeError) as error:
            return _failed(
                scene, config or {}, self.name, str(error), "plan", version="1.1"
            )
        try:
            check(scene, plan)
        except (ValueError, KeyError, TypeError) as error:
            return _failed(
                scene, config or {}, self.name, str(error), "safety", version="1.1"
            )
        return plan


class CawAStarPlanner(Planner):
    """Fixed-Y lanes + deterministic order + layered 3D clearance A* transits."""

    name = "caw-a*-3d-wind"
    version = "1.2"
    default_order = "nn+2opt"
    capabilities = dict(
        lane_geometry="fixed-y",
        transition="layered-3d-clearance-a-star",
        objective=["time", "energy"],
    )

    def validate_options(self, options):
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise ValueError("规划器参数必须是对象")
        allowed = {
            "step_xy",
            "step_z",
            "max_expansions",
            "max_grid_nodes",
            "order_strategy",
            "objective",
            "matrix_mode",
        }
        unknown = set(options) - allowed
        if unknown:
            raise ValueError("未知规划器参数")
        normalized = dict(
            step_xy=options.get("step_xy", 1.0),
            step_z=options.get("step_z", 1.0),
            max_expansions=options.get("max_expansions", 200000),
            max_grid_nodes=options.get("max_grid_nodes", 2000000),
            order_strategy=options.get("order_strategy", self.default_order),
            objective=options.get("objective", "time"),
            matrix_mode=options.get("matrix_mode", None),
        )
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
        if normalized["order_strategy"] not in ("fixed", "nn", "nn+2opt"):
            raise ValueError("order_strategy 必须为 fixed / nn / nn+2opt")
        if normalized["objective"] not in ("time", "energy"):
            raise ValueError("objective 必须为 time 或 energy")
        if normalized["matrix_mode"] not in (None, "exact3d", "euclidean_lb"):
            raise ValueError("matrix_mode 必须为 exact3d 或 euclidean_lb 或省略")
        return normalized

    def plan(self, scene, config=None, options=None):
        try:
            normalized = self.validate_options(options)
        except (ValueError, TypeError) as error:
            return _failed(scene, config or {}, self.name, str(error), "plan")
        try:
            scene = scene
            validate_scene(scene)
            c = configuration(config or {})
            layout = fixed_y_lanes(scene, c)
            lanes = layout["lanes"]
            height = layout["work_height"]
            resolved = resolve(scene, 1)
            home = list(resolved["start"]["position"])
            end_point = list(resolved["end"]["position"])
            explicit = resolved["explicit"] or home != end_point
            count = len(lanes)
            if count == 0:
                raise ValueError("没有喷洒航段")
            if normalized["order_strategy"] == "fixed":
                order_result = dict(
                    status="success",
                    order=list(range(count)),
                    evaluated=1,
                    matrix_mode=None,
                    routes_computed=0,
                    lower_bound=None,
                    gap_to_bound_abs=None,
                    gap_to_bound_rel=None,
                    route_failures=[],
                    route_failures_total=0,
                    order_cost=None,
                )
            else:
                order_result = solve_order(
                    scene,
                    c,
                    lanes,
                    strategy=normalized["order_strategy"],
                    objective=normalized["objective"],
                    home=[home[0], home[1], height],
                    matrix_mode=normalized["matrix_mode"],
                    step_xy=normalized["step_xy"],
                )
                if order_result["status"] != "success":
                    raise CawFailure("order", order_result["reason"])
            order = order_result["order"]
            grid_options = dict(
                step_xy=normalized["step_xy"],
                step_z=normalized["step_z"],
                max_expansions=normalized["max_expansions"],
                max_grid_nodes=normalized["max_grid_nodes"],
            )
            segments = []
            current = list(home)
            expanded = 0
            routes = 0
            grid_hash = None
            search_layers = None
            max_effective = None

            def add(end, kind, ids=None):
                nonlocal current
                if math.dist(current, end) <= 1e-8:
                    return
                segments.append(
                    dict(
                        start=current[:],
                        end=list(end),
                        type=kind,
                        spray=kind == "spray",
                        speed=c["speed"],
                        target_ids=sorted(ids or []),
                    )
                )
                current = list(end)

            def transit_leg(start, end):
                nonlocal expanded, routes, grid_hash, search_layers, max_effective, current
                result = route3d(
                    scene,
                    list(start),
                    list(end),
                    c,
                    objective=normalized["objective"],
                    grid=grid_options,
                )
                if result["status"] != "success":
                    raise CawFailure(
                        "search",
                        f"转场 {start} → {end} 搜索失败：{result.get('reason', '未知原因')}",
                    )
                expanded += result.get("expanded", 0)
                routes += 1
                grid_hash = result["grid"]["hash"]
                search_layers = result["grid"]["layers"]
                max_effective = result["max_effective_speed"]
                current = list(result["path"][0])
                for point in result["path"][1:]:
                    add(point, "transit")

            add([home[0], home[1], height], "takeoff")
            for index in order:
                lane = lanes[index]
                parts = lane_parts(scene, lane, c)
                if not parts:
                    continue
                transit_leg(current, parts[0]["start"])
                if list(current) != list(parts[0]["start"]):
                    add(parts[0]["start"], "transit")
                for part in parts:
                    if part["type"] == "detour":
                        transit_leg(current, part["end"])
                    else:
                        add(part["end"], part["type"], part["target_ids"])
            transit_leg(current, [end_point[0], end_point[1], height])
            add([end_point[0], end_point[1], height], "transit")
            add(end_point, "landing")

            plan = dict(
                version="1.2",
                planner=self.name,
                method=self.name,
                objective=normalized["objective"],
                scene_hash=fingerprint(scene),
                status="success",
                reason="",
                stage="plan",
                segments=segments,
                work_height=height,
                strip_count=layout["strip_count"],
                order=list(order),
                planner_options=normalized,
                planner_options_hash=options_fingerprint(normalized),
                config=c,
                config_hash=config_fingerprint(c),
                search=dict(
                    model="layered-3d-clearance-a-star",
                    step_xy=normalized["step_xy"],
                    step_z=normalized["step_z"],
                    layers=search_layers,
                    expanded=expanded,
                    routes=routes,
                    grid_hash=grid_hash,
                    max_effective_speed=max_effective,
                    objective=normalized["objective"],
                ),
                order_search=dict(
                    strategy=normalized["order_strategy"],
                    evaluated=order_result["evaluated"],
                    cost_model=(
                        "exact3d-time"
                        if order_result["matrix_mode"] == "exact3d"
                        else (
                            "euclidean-lb-time"
                            if order_result["matrix_mode"] == "euclidean_lb"
                            else "fixed-order"
                        )
                    ),
                    matrix_mode=order_result["matrix_mode"],
                    routes_computed=order_result["routes_computed"],
                    lower_bound=order_result.get("lower_bound"),
                    gap_to_bound_abs=order_result.get("gap_to_bound_abs"),
                    gap_to_bound_rel=order_result.get("gap_to_bound_rel"),
                    bound_type=order_result.get("bound_type"),
                    route_failures_total=order_result.get("route_failures_total", 0),
                ),
            )
            if explicit:
                plan.update(
                    uav=1,
                    start_point_id=resolved["start_id"],
                    end_point_id=resolved["end_id"],
                )
            excluded = zone_exclusions(scene, segments)
            if excluded:
                plan["excluded_targets"] = excluded
            try:
                check(scene, plan)
            except (ValueError, KeyError, TypeError) as error:
                raise CawFailure("safety", str(error))
            from execution import build as build_execution

            try:
                timeline = build_execution(scene, plan)
                if normalized["objective"] == "energy":
                    from planning.energy import timeline_energy

                    plan["objective_value"] = timeline_energy(timeline, c)["total_eu"]
                else:
                    plan["objective_value"] = timeline["duration"]
            except (ValueError, KeyError, TypeError) as error:
                raise CawFailure("execution", str(error))
            return plan
        except CawFailure as error:
            plan = _failed(
                scene,
                config or {},
                self.name,
                error.reason,
                error.stage,
                options=normalized,
            )
            return plan
        except (ValueError, KeyError, TypeError) as error:
            return _failed(
                scene,
                config or {},
                self.name,
                str(error),
                "plan",
                options=normalized,
            )

    def plan_sequence(
        self,
        scene,
        config=None,
        lane_indices=None,
        home=None,
        options=None,
        start=None,
        end=None,
        uav=None,
    ):
        """Plan one UAV over a lane subset with its own start/end point.

        ``uav`` resolves start/end (and their point IDs) from the scene's launch
        assignments; explicit ``start``/``end`` override the positions only.
        ``home`` is kept as a legacy alias for ``start=end=home``.  The plan is
        always v1.2 and carries ``uav``/``start_point_id``/``end_point_id``.
        """
        layout = fixed_y_lanes(scene, configuration(config or {}))
        lanes = layout["lanes"]
        indices = list(range(len(lanes))) if lane_indices is None else list(lane_indices)
        if sorted(indices) != sorted(set(indices)) or any(
            i < 0 or i >= len(lanes) for i in indices
        ):
            raise ValueError("lane_indices 必须是有效且不重复的索引")
        subset = [lanes[i] for i in indices]
        normalized = self.validate_options(options)
        index = 1 if uav is None else uav
        if type(index) is not int or index < 1:
            raise ValueError("uav 必须是正整数")
        try:
            resolved = resolve(scene, index)
            if home is not None and start is None and end is None:
                start = list(home)
                end = list(home)
            start = list(resolved["start"]["position"]) if start is None else list(start)
            end = list(resolved["end"]["position"]) if end is None else list(end)
            return _plan_subset(
                self,
                scene,
                config or {},
                subset,
                layout,
                indices,
                start,
                end,
                index,
                resolved["start_id"],
                resolved["end_id"],
                normalized,
            )
        except CawFailure as error:
            return _failed(
                scene,
                config or {},
                self.name,
                error.reason,
                error.stage,
                options=normalized,
            )
        except (ValueError, KeyError, TypeError) as error:
            return _failed(
                scene, config or {}, self.name, str(error), "plan", options=normalized
            )


class CawFailure(Exception):
    def __init__(self, stage, reason):
        self.stage = stage
        self.reason = reason
        super().__init__(reason)


def _plan_subset(
    planner,
    scene,
    config,
    lanes,
    layout,
    indices,
    start,
    end,
    uav,
    start_id,
    end_id,
    normalized,
):
    """Build a CAW plan over an explicit lane list (subset for one UAV)."""
    c = configuration(config)
    start = list(start)
    end = list(end)
    height = layout["work_height"]
    if not lanes:
        raise ValueError("没有分配给该机的喷洒航段")
    count = len(lanes)
    order_result = (
        dict(
            status="success",
            order=list(range(count)),
            evaluated=1,
            matrix_mode=None,
            routes_computed=0,
            lower_bound=None,
            gap_to_bound_abs=None,
            gap_to_bound_rel=None,
            route_failures_total=0,
        )
        if normalized["order_strategy"] == "fixed"
        else solve_order(
            scene,
            c,
            lanes,
            strategy=normalized["order_strategy"],
            objective=normalized["objective"],
            home=[start[0], start[1], height],
            matrix_mode=normalized["matrix_mode"],
            step_xy=normalized["step_xy"],
        )
    )
    if order_result["status"] != "success":
        return _failed(scene, c, planner.name, order_result["reason"], "order", options=normalized)
    grid_options = dict(
        step_xy=normalized["step_xy"],
        step_z=normalized["step_z"],
        max_expansions=normalized["max_expansions"],
        max_grid_nodes=normalized["max_grid_nodes"],
    )
    segments = []
    current = list(start)
    expanded = 0
    routes = 0
    grid_hash = None
    layers = None
    max_effective = None

    def add(end, kind, ids=None):
        nonlocal current
        if math.dist(current, end) <= 1e-8:
            return
        segments.append(
            dict(
                start=current[:],
                end=list(end),
                type=kind,
                spray=kind == "spray",
                speed=c["speed"],
                target_ids=sorted(ids or []),
            )
        )
        current = list(end)

    def leg(start, end):
        nonlocal expanded, routes, grid_hash, layers, max_effective, current
        result = route3d(
            scene,
            list(start),
            list(end),
            c,
            objective=normalized["objective"],
            grid=grid_options,
        )
        if result["status"] != "success":
            raise CawFailure(
                "search",
                f"转场 {start} → {end} 搜索失败：{result.get('reason', '未知原因')}",
            )
        expanded += result.get("expanded", 0)
        routes += 1
        grid_hash = result["grid"]["hash"]
        layers = result["grid"]["layers"]
        max_effective = result["max_effective_speed"]
        current = list(result["path"][0])
        for point in result["path"][1:]:
            add(point, "transit")

    add([start[0], start[1], height], "takeoff")
    for index in order_result["order"]:
        lane = lanes[index]
        parts = lane_parts(scene, lane, c)
        if not parts:
            continue
        leg(current, parts[0]["start"])
        if list(current) != list(parts[0]["start"]):
            add(parts[0]["start"], "transit")
        for part in parts:
            if part["type"] == "detour":
                leg(current, part["end"])
            else:
                add(part["end"], part["type"], part["target_ids"])
    leg(current, [end[0], end[1], height])
    add([end[0], end[1], height], "transit")
    add(end, "landing")
    plan = dict(
        version="1.2",
        planner=planner.name,
        method=planner.name,
        objective=normalized["objective"],
        scene_hash=fingerprint(scene),
        status="success",
        reason="",
        stage="plan",
        segments=segments,
        work_height=height,
        strip_count=len(indices),
        order=list(order_result["order"]),
        assigned_lane_indices=list(indices),
        uav=uav,
        start_point_id=start_id,
        end_point_id=end_id,
        planner_options=normalized,
        planner_options_hash=options_fingerprint(normalized),
        config=c,
        config_hash=config_fingerprint(c),
        search=dict(
            model="layered-3d-clearance-a-star",
            step_xy=normalized["step_xy"],
            step_z=normalized["step_z"],
            layers=layers,
            expanded=expanded,
            routes=routes,
            grid_hash=grid_hash,
            max_effective_speed=max_effective,
            objective=normalized["objective"],
        ),
        order_search=dict(
            strategy=normalized["order_strategy"],
            evaluated=order_result["evaluated"],
            matrix_mode=order_result["matrix_mode"],
            cost_model="fixed-order"
            if order_result["matrix_mode"] is None
            else ("exact3d-time" if order_result["matrix_mode"] == "exact3d" else "euclidean-lb-time"),
            routes_computed=order_result["routes_computed"],
            lower_bound=order_result.get("lower_bound"),
            gap_to_bound_abs=order_result.get("gap_to_bound_abs"),
            gap_to_bound_rel=order_result.get("gap_to_bound_rel"),
            bound_type=order_result.get("bound_type"),
        ),
    )
    all_indices = list(range(len(layout["lanes"])))
    if sorted(indices) != all_indices:
        plan["allow_partial"] = True
    excluded = zone_exclusions(scene, segments)
    if excluded:
        plan["excluded_targets"] = excluded
    try:
        check(scene, plan)
    except (ValueError, KeyError, TypeError) as error:
        raise CawFailure("safety", str(error))
    from execution import build as build_execution

    try:
        timeline = build_execution(scene, plan)
        if normalized["objective"] == "energy":
            from planning.energy import timeline_energy

            plan["objective_value"] = timeline_energy(timeline, c)["total_eu"]
        else:
            plan["objective_value"] = timeline["duration"]
    except (ValueError, KeyError, TypeError) as error:
        raise CawFailure("execution", str(error))
    return plan


class CawFixedOrderPlanner(CawAStarPlanner):
    name = "caw-a*-fixed-order"
    default_order = "fixed"


class CawNNPlanner(CawAStarPlanner):
    name = "caw-a*-nn"
    default_order = "nn"


PLANNERS = {x.name: x for x in (FixedYPlanner, NaivePlanner, CawAStarPlanner, CawFixedOrderPlanner, CawNNPlanner)}

ALIASES = {
    "fixed-y": "fixed-y-boustrophedon",
    "fixed": "fixed-y-boustrophedon",
    "naive": "naive-target-order",
    "caw": "caw-a*-3d-wind",
    "caw-a*": "caw-a*-3d-wind",
    "caw-3d": "caw-a*-3d-wind",
    "caw-fixed-order": "caw-a*-fixed-order",
    "caw-nn": "caw-a*-nn",
}


def normalize_name(name):
    if not isinstance(name, str):
        raise ValueError("规划器名称必须是字符串")
    return ALIASES.get(name, name)


def make_planner(name):
    key = normalize_name(name)
    try:
        return PLANNERS[key]()
    except KeyError:
        raise ValueError(f"未知规划器: {name}")
