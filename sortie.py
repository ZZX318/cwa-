"""Greedy payload-limited multi-sortie baseline for one UAV.

Assumptions (explicit, not a battery/refill model): each sortie starts with a
full payload and the UAV returns to its assigned end point between sorties.
Between batches a configurable fixed ``refill_seconds`` + ``recharge_seconds``
gap is added; both default to 0 so legacy results are unchanged.  Sorties are
packed deterministically in lane order.
"""

import copy
import math

from execution import build
from planning import check, config_fingerprint, configuration, fingerprint
from planning.energy import energy_config, energy_fingerprint, timeline_energy
from planning.model import options_fingerprint
from planning.planner import fixed_y_lanes
from planning.wind import segment_time
from scene.launch import resolve

METHOD = "multi-sortie-uav"


def _sortie_plan(scene, config, assignment, lanes, indices, height):
    start = list(assignment["start"]["position"])
    end_point = list(assignment["end"]["position"])
    explicit = assignment["explicit"] or start != end_point
    plan = dict(
        version="1.2" if explicit else "1.1",
        scene_hash=fingerprint(scene),
        method=METHOD,
        status="success",
        reason="",
        segments=[],
        allow_partial=True,
        work_height=height,
        config=config,
        config_hash=config_fingerprint(config),
    )
    if explicit:
        plan.update(
            planner=METHOD,
            objective="time",
            planner_options={},
            planner_options_hash=options_fingerprint({}),
            uav=1,
            start_point_id=assignment["start_id"],
            end_point_id=assignment["end_id"],
        )
    current = start[:]

    def add(end, kind, targets=None):
        nonlocal current
        if math.dist(current, end) <= 1e-8:
            return
        plan["segments"].append(
            dict(
                start=current[:],
                end=list(end),
                type=kind,
                spray=kind == "spray",
                speed=config["speed"],
                target_ids=sorted(targets or []),
            )
        )
        current = list(end)

    add([start[0], start[1], height], "takeoff")
    for index in indices:
        lane = lanes[index]
        add(lane["start"], "transit")
        add(lane["end"], "spray", lane["target_ids"])
    add([end_point[0], end_point[1], height], "transit")
    add(end_point, "landing")
    return plan


def _non_negative(value, label):
    if (
        type(value) not in (int, float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} 必须是有限非负数")
    return float(value)


def plan_sorties(scene, config=None, options=None):
    options = dict(options or {})
    allowed = {
        "payload_capacity_kg",
        "flow_rate_kg_per_s",
        "refill_seconds",
        "recharge_seconds",
        "energy",
    }
    unknown = set(options) - allowed
    if unknown:
        raise ValueError(f"未知多批次参数：{sorted(unknown)}")
    capacity = options.get("payload_capacity_kg")
    flow = options.get("flow_rate_kg_per_s")
    refill = _non_negative(options.get("refill_seconds", 0.0), "refill_seconds")
    recharge = _non_negative(options.get("recharge_seconds", 0.0), "recharge_seconds")
    if (
        type(capacity) not in (int, float)
        or isinstance(capacity, bool)
        or not math.isfinite(capacity)
        or capacity <= 0
    ):
        raise ValueError("payload_capacity_kg 必须是有限正数")
    if (
        type(flow) not in (int, float)
        or isinstance(flow, bool)
        or not math.isfinite(flow)
        or flow <= 0
    ):
        raise ValueError("flow_rate_kg_per_s 必须是有限正数")
    c = configuration(config or {})
    energy = energy_config(options.get("energy"))
    result = dict(
        version="1.0",
        method="greedy-payload-sorties",
        status="failed",
        stage="plan",
        reason="",
        payload_capacity_kg=capacity,
        flow_rate_kg_per_s=flow,
        refill_seconds=refill,
        recharge_seconds=recharge,
        gap_seconds=refill + recharge,
        sorties=[],
        sortie_count=0,
        total_time=None,
        total_flight_time=None,
        total_gap_seconds=None,
        makespan=None,
        total_spray_seconds=None,
        total_energy_eu=None,
        scene_hash=fingerprint(scene),
        config_hash=config_fingerprint(c),
        energy_config_hash=energy_fingerprint(energy),
    )
    try:
        layout = fixed_y_lanes(scene, c)
        lanes = layout["lanes"]
        height = layout["work_height"]
        if not lanes:
            raise ValueError("没有喷洒航段")
        assignment = resolve(scene, 1)
        for lane in lanes:
            spray = segment_time(lane["start"], lane["end"], c["speed"], c, "1.2")
            if spray * flow > capacity + 1e-9:
                raise ValueError(
                    f"单条喷洒航段需要 {spray * flow:.3f} kg，超过载药上限 {capacity} kg"
                )
        groups = []
        current = []
        payload = 0.0
        for index, lane in enumerate(lanes):
            spray = segment_time(lane["start"], lane["end"], c["speed"], c, "1.2")
            mass = spray * flow
            if current and payload + mass > capacity + 1e-9:
                groups.append(current)
                current = []
                payload = 0.0
            current.append(index)
            payload += mass
        if current:
            groups.append(current)
        rows = []
        for number, indices in enumerate(groups, start=1):
            plan = _sortie_plan(scene, c, assignment, lanes, indices, height)
            try:
                check(scene, plan)
                timeline = build(scene, plan)
                report = timeline_energy(timeline, c, energy)
                spray_seconds = sum(
                    segment["duration"]
                    for segment in timeline["segments"]
                    if segment["spray"]
                )
            except (ValueError, KeyError, TypeError) as error:
                result.update(reason=f"第 {number} 批失败：{error}", stage="execution")
                return result
            payload_kg = spray_seconds * flow
            if payload_kg > capacity + 1e-9:
                result.update(
                    reason=f"第 {number} 批载药 {payload_kg:.3f} kg 超过上限 {capacity} kg",
                    stage="payload",
                )
                return result
            rows.append(
                dict(
                    index=number,
                    lane_indices=indices,
                    gap_before_seconds=0.0 if number == 1 else refill + recharge,
                    duration=timeline["duration"],
                    path_length=sum(s["length"] for s in timeline["segments"]),
                    spray_seconds=spray_seconds,
                    payload_kg=payload_kg,
                    plan_version=plan["version"],
                    plan_hash=fingerprint(plan),
                    safety="pass",
                    energy_eu=report["total_eu"],
                    energy_wh=report.get("energy_wh"),
                    calibrated=report["calibrated"],
                )
            )
        total_spray = sum(row["spray_seconds"] for row in rows)
        total_flight = sum(row["duration"] for row in rows)
        total_gap = (len(rows) - 1) * (refill + recharge)
        result.update(
            status="success",
            stage="done",
            uav=1,
            start_point_id=assignment["start_id"],
            end_point_id=assignment["end_id"],
            sorties=rows,
            sortie_count=len(rows),
            total_time=total_flight + total_gap,
            total_flight_time=total_flight,
            total_gap_seconds=total_gap,
            makespan=total_flight + total_gap,
            total_spray_seconds=total_spray,
            total_payload_kg=total_spray * flow,
            total_energy_eu=sum(row["energy_eu"] for row in rows),
            total_energy_wh=(
                sum(row["energy_wh"] for row in rows)
                if all(row["energy_wh"] is not None for row in rows)
                else None
            ),
            calibrated=bool(rows) and all(row["calibrated"] for row in rows),
            config_hash=plan["config_hash"],
        )
        return result
    except (ValueError, KeyError, TypeError) as error:
        result["reason"] = str(error)
        return result


def save(result, path):
    import json
    from pathlib import Path

    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )
