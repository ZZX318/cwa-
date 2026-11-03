"""M0 shared-depot selection: evaluate candidate launch/return points.

Exactness is limited to the enumerated candidate set with the existing
planner/partition model; it is not continuous-space optimality.
"""

import copy
import math

from evaluation import at, build as build_evaluation
from execution import build as build_timeline
from multi import run as multi_run
from planner_api import make_planner
from planning import configuration, config_fingerprint, fingerprint, generate_plan
from planning.energy import energy_config, energy_fingerprint, timeline_energy
from planning.model import options_fingerprint
from planning.wind import max_effective_speed
from scene.geometry import polygon_bounds, terrain_height
from scene.shapes import point_in_box, point_in_footprint

MODES = ("launch", "grid")
OBJECTIVES = ("time", "energy")


def _inside(zone, point):
    if not (zone["z_min"] <= point[2] <= zone["z_max"]):
        return False
    return point_in_footprint([point[0], point[1]], zone["footprint"])


def _blocked(scene, point):
    for obstacle in scene["obstacles"]:
        if point_in_box(point, obstacle):
            return True
    for key in ("no_fly_zones", "no_spray_zones"):
        for zone in scene[key]:
            if _inside(zone, point):
                return True
    for tree in scene["trees"]:
        for kind in ("trunk", "canopy"):
            geometry = tree[kind]
            if (
                geometry["z_min"] <= point[2] <= geometry["z_max"]
                and math.dist(point[:2], geometry["center"]) <= geometry["radius"]
            ):
                return True
    return False


def candidate_points(scene, mode="launch", grid=3):
    if mode not in MODES:
        raise ValueError("候选来源必须为 launch 或 grid")
    if type(grid) is not int or not 2 <= grid <= 12:
        raise ValueError("grid 必须为 2..12 的整数")
    if mode == "launch":
        points = [list(p["position"]) for p in scene["launch_points"]]
    else:
        low, high = scene["extent"]["min"], scene["extent"]["max"]
        bounds = polygon_bounds(scene["plot"])
        pmin, pmax = bounds["min"][:2], bounds["max"][:2]

        def inside_plot(x, y):
            return pmin[0] <= x <= pmax[0] and pmin[1] <= y <= pmax[1]

        xs = [low[0] + (high[0] - low[0]) * (i + 1) / (grid + 1) for i in range(grid)]
        ys = [low[1] + (high[1] - low[1]) * (i + 1) / (grid + 1) for i in range(grid)]
        points = []
        for x in xs:
            for y in ys:
                if not inside_plot(x, y):
                    points.append([x, y, terrain_height(scene, x, y)])
        margin = max(
            1.0,
            min(
                pmin[0] - low[0],
                pmin[1] - low[1],
                high[0] - pmax[0],
                high[1] - pmax[1],
            ) / 2,
        )
        ring_x = [pmin[0] - margin, (pmin[0] + pmax[0]) / 2, pmax[0] + margin]
        ring_y = [pmin[1] - margin, (pmin[1] + pmax[1]) / 2, pmax[1] + margin]
        for x in ring_x:
            for y in ring_y:
                if inside_plot(x, y):
                    continue
                if low[0] <= x <= high[0] and low[1] <= y <= high[1]:
                    points.append([x, y, terrain_height(scene, x, y)])
        points = [p for p in points if not _blocked(scene, p)]
    unique = []
    seen = set()
    for point in points:
        key = (round(point[0], 6), round(point[1], 6), round(point[2], 6))
        if key in seen:
            continue
        seen.add(key)
        unique.append([float(point[0]), float(point[1]), float(point[2])])
    if not unique:
        raise ValueError("没有可用候选起降点")
    return sorted(unique)


def _materialize(scene, point):
    materialized = copy.deepcopy(scene)
    materialized["launch_points"] = [
        dict(id="depot-candidate", position=list(point), role="both")
    ]
    materialized.pop("launch_assignments", None)
    return materialized


def _energy_row(timeline, plan, energy):
    report = timeline_energy(timeline, plan["config"], energy)
    return report


def _evaluate(scene, config, point, options):
    materialized = _materialize(scene, point)
    row = dict(
        depot=list(point),
        status="failed",
        reason="",
        stage="plan",
        planner=options["planner"],
        duration=None,
        makespan=None,
        total_time=None,
        path_length=None,
        coverage=None,
        coverage_note="",
        energy_eu=None,
        energy_wh=None,
        calibrated=False,
        energy_components=None,
        feasibility_reason=None,
        feasible=False,
        coordinated=False,
        waiting_seconds=0.0,
        conflicts_after=None,
        scene_hash=fingerprint(materialized),
    )
    if options["uavs"] == 1:
        planner = make_planner(options["planner"])
        plan = planner.plan(materialized, config, options.get("planner_options"))
        if plan.get("status") != "success":
            row.update(reason=plan.get("reason", ""), stage=plan.get("stage", "plan"))
            return row
        try:
            timeline = build_timeline(materialized, plan)
            evaluation = build_evaluation(materialized, plan, timeline)
            metrics = at(evaluation, timeline, timeline["duration"])
            energy = _energy_row(timeline, plan, options["energy"])
        except (ValueError, KeyError, TypeError) as error:
            row.update(reason=str(error), stage="execution")
            return row
        row.update(
            status="success",
            stage="done",
            duration=timeline["duration"],
            makespan=timeline["duration"],
            total_time=timeline["duration"],
            path_length=sum(s["length"] for s in timeline["segments"]),
            coverage=metrics["coverage"],
            energy_eu=energy["total_eu"],
            energy_wh=energy.get("energy_wh"),
            calibrated=energy["calibrated"],
            energy_components=energy["components"],
            feasible=energy["feasible"],
            feasibility_reason=energy["reason"],
            config_hash=plan.get("config_hash"),
        )
        if not energy["feasible"]:
            row.update(status="failed", reason=energy["reason"], stage="energy")
        return row

    fleet = multi_run(materialized, config, options["uavs"])
    if fleet.get("status") != "success":
        row.update(reason=fleet.get("reason", "多机基线失败"), stage="multi")
        return row
    base = generate_plan(materialized, config)
    if base.get("status") != "success":
        row.update(reason=base.get("reason", ""), stage="plan")
        return row
    durations = []
    paths = []
    coverages = []
    energies = []
    energy_whs = []
    calibrated_flags = []
    components = None
    for unit in fleet["uavs"]:
        if unit["status"] != "success":
            row.update(reason=unit.get("reason", "单机计划失败"), stage="multi")
            return row
        plan = copy.deepcopy(base)
        plan["allow_partial"] = True
        plan["segments"] = unit["segments"]
        try:
            timeline = build_timeline(materialized, plan)
            evaluation = build_evaluation(materialized, plan, timeline)
            metrics = at(evaluation, timeline, timeline["duration"])
            energy = _energy_row(timeline, plan, options["energy"])
        except (ValueError, KeyError, TypeError) as error:
            row.update(reason=str(error), stage="execution")
            return row
        durations.append(timeline["duration"])
        paths.append(sum(s["length"] for s in timeline["segments"]))
        coverages.append(metrics["coverage"])
        energies.append(energy["total_eu"])
        energy_whs.append(energy.get("energy_wh"))
        calibrated_flags.append(energy["calibrated"])
        components = energy["components"]
        if not energy["feasible"]:
            row.update(status="failed", reason=energy["reason"], stage="energy")
            return row
    row.update(
        status="success",
        stage="done",
        duration=max(durations),
        makespan=max(durations),
        total_time=sum(durations),
        path_length=sum(paths),
        coverage=sum(coverages) / len(coverages) if coverages else 0.0,
        coverage_note="每机对全场景目标的平均值，不是机队并集覆盖率",
        energy_eu=sum(energies),
        energy_wh=(sum(energy_whs) if all(v is not None for v in energy_whs) else None),
        calibrated=bool(calibrated_flags) and all(calibrated_flags),
        energy_components=components,
        feasible=True,
    )
    if options["coordinate"] and options["uavs"] > 1:
        from coordination_plan import coordinate as coordinate_plan

        coordinated = coordinate_plan(
            materialized,
            config,
            options["uavs"],
            options["min_distance"],
        )
        if coordinated.get("status") != "success":
            row.update(
                status="failed",
                reason=coordinated.get("reason", "协调失败"),
                stage="coordination",
            )
            return row
        row.update(
            coordinated=True,
            makespan=coordinated["makespan"],
            total_time=coordinated["total_time"],
            waiting_seconds=coordinated["waiting_seconds"],
            conflicts_after=coordinated["conflicts_after"],
        )
    return row


def _time_lower_bound(scene, point, plan, config):
    speed = plan["config"]["speed"]
    v_max = max_effective_speed(speed, plan["config"])
    sprays = [s for s in plan["segments"] if s["type"] == "spray"]
    if not sprays:
        return 0.0
    spray_time = 0.0
    for segment in sprays:
        length = math.dist(segment["start"], segment["end"])
        spray_time += length / v_max
    nearest = min(
        min(
            math.hypot(point[0] - s["start"][0], point[1] - s["start"][1]),
            math.hypot(point[0] - s["end"][0], point[1] - s["end"][1]),
        )
        for s in sprays
    )
    vertical = min(s["start"][2] for s in sprays)
    return spray_time + 2.0 * nearest / v_max + 2.0 * max(0.0, vertical) / speed


def optimize(scene, config=None, options=None):
    options = dict(options or {})
    allowed = {"candidates", "grid", "budget", "uavs", "objective", "planner",
               "planner_options", "energy", "coordinate", "min_distance"}
    unknown = set(options) - allowed
    if unknown:
        raise ValueError(f"未知起降点优化参数：{sorted(unknown)}")
    config = dict(config or {})
    mode = options.get("candidates", "launch")
    grid = options.get("grid", 3)
    budget = options.get("budget", 64)
    uavs = options.get("uavs", 1)
    objective = options.get("objective", "time")
    planner = options.get("planner", "fixed-y-boustrophedon")
    if type(budget) is not int or budget < 1:
        raise ValueError("budget 必须为正整数")
    if type(uavs) is not int or not 1 <= uavs <= 32:
        raise ValueError("uavs 必须为 1..32")
    if objective not in OBJECTIVES:
        raise ValueError("objective 必须为 time 或 energy")
    if uavs > 1 and planner not in ("fixed-y", "fixed-y-boustrophedon"):
        raise ValueError("M0 多机起降点优化仅支持 fixed-y 规划器")
    coordinate = options.get("coordinate", False)
    min_distance = options.get("min_distance", 1.0)
    if type(coordinate) is not bool:
        raise ValueError("coordinate 必须是布尔值")
    if (
        type(min_distance) not in (int, float)
        or not math.isfinite(min_distance)
        or min_distance <= 0
    ):
        raise ValueError("min_distance 必须是有限正数")
    energy = energy_config(options.get("energy"))
    options.update(
        candidates=mode, grid=grid, budget=budget, uavs=uavs,
        objective=objective, planner=planner, energy=energy,
        coordinate=coordinate, min_distance=min_distance,
    )
    base = generate_plan(scene, config)
    if base.get("status") != "success":
        return dict(
            version="1.0", status="failed", stage="plan",
            reason=f"基准计划失败: {base.get('reason', '')}",
            scene_hash=fingerprint(scene),
        )
    points = candidate_points(scene, mode, grid)
    total = len(points)
    exact = total <= budget
    evaluation_points = points
    if not exact:
        sprays = [s for s in base["segments"] if s["type"] == "spray"]
        def cheap(point):
            return min(
                min(math.dist(point, s["start"]), math.dist(point, s["end"]))
                for s in sprays
            )
        evaluation_points = sorted(points, key=lambda p: (cheap(p), p))[:budget]
    rows = [_evaluate(scene, config, point, options) for point in evaluation_points]
    feasible = [r for r in rows if r["status"] == "success" and r["feasible"]]
    result = dict(
        version="1.0",
        method="shared-depot-enumeration",
        model="m0-shared-depot-start=end",
        status="failed",
        stage="done",
        objective=objective,
        exact=exact,
        optimality="exact-over-enumerated-candidates" if exact else "budget-limited",
        candidates_total=total,
        evaluated=len(rows),
        budget=budget,
        uavs=uavs,
        planner=planner,
        coordinate=coordinate,
        min_distance=min_distance,
        scene_hash=fingerprint(scene),
        config_hash=config_fingerprint(configuration(config)),
        energy_config_hash=energy_fingerprint(energy),
        planner_options_hash=options_fingerprint(options.get("planner_options") or {}),
        rows=rows[:50],
        truncated=len(rows) > 50,
        reasons=[r["reason"] for r in rows if r["status"] != "success"][:10],
    )
    if not feasible:
        result["reason"] = "所有候选起降点都不可行"
        return result
    key = (lambda r: (r["energy_eu"], r["makespan"], r["path_length"])) if objective == "energy" \
        else (lambda r: (r["makespan"], r["path_length"]))
    selected = min(feasible, key=key)
    result.update(
        status="success",
        selected=selected,
        objective_value=selected["energy_eu"] if objective == "energy" else selected["makespan"],
        lower_bound=None,
        gap=None,
        gap_note="M0 仅对单机时间目标给出有效下界；其余口径不下结论",
    )
    if uavs == 1 and objective == "time":
        lower = _time_lower_bound(
            scene, selected["depot"], base, config
        )
        result["lower_bound"] = lower
        if lower > 0:
            result["gap"] = (selected["makespan"] - lower) / lower
        result["gap_note"] = "相对下界（喷洒时间 + 起降最少往返），非证明最优"
    return result


def save(result, path):
    import json
    from pathlib import Path

    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )
