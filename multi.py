"""Deterministic multi-UAV contiguous strip partition baseline."""
import copy
import math

from evaluation import at, build as eb
from execution import build
from planning import check, fingerprint
from planning.model import options_fingerprint
from planning.planner import generate_plan
from scene.launch import resolve_all


def _legacy_base(scene, config):
    """Build the lane/transit baseline with one legacy launch point."""
    legacy = copy.deepcopy(scene)
    first = sorted(scene["launch_points"], key=lambda p: tuple(p["position"]))[0]
    first = copy.deepcopy(first)
    first.pop("role", None)
    legacy["launch_points"] = [first]
    legacy.pop("launch_assignments", None)
    return generate_plan(legacy, config)


def run(scene, config, uavs=2):
    if type(uavs) is not int or not 1 <= uavs <= 32:
        raise ValueError("无人机数量需为 1..32")
    base = _legacy_base(scene, config)
    if base["status"] != "success":
        return {"status": "failed", "reason": base["reason"], "uavs": []}
    sprays = [(i, s) for i, s in enumerate(base["segments"]) if s["type"] == "spray"]
    chunks = [
        sprays[i * len(sprays) // uavs : (i + 1) * len(sprays) // uavs]
        for i in range(uavs)
    ]
    try:
        resolved = resolve_all(scene, uavs)
    except ValueError as error:
        return {
            "status": "failed",
            "reason": str(error),
            "stage": "launch",
            "uavs": [],
        }
    out = []
    for i, chunk in enumerate(chunks):
        assignment = resolved[i]
        if not chunk:
            entry = {
                "uav": i + 1,
                "status": "success",
                "segments": [],
                "duration": 0,
                "idle": True,
                "coverage": None,
                "path_length": None,
            }
            if assignment["explicit"]:
                entry.update(
                    start=list(assignment["start"]["position"]),
                    end=list(assignment["end"]["position"]),
                    start_point_id=assignment["start_id"],
                    end_point_id=assignment["end_id"],
                )
            out.append(entry)
            continue
        ids = {tid for _, s in chunk for tid in s["target_ids"]}
        first, last = chunk[0][0], chunk[-1][0]
        selected = base["segments"][first : last + 1]
        start = list(assignment["start"]["position"])
        end_point = list(assignment["end"]["position"])
        height = base["work_height"]
        p = dict(base)
        p["scene_hash"] = fingerprint(scene)
        p["segments"] = []
        p["allow_partial"] = True
        p["assigned_target_ids"] = sorted(ids)
        explicit = assignment["explicit"] or math.dist(start, end_point) > 1e-8
        if explicit:
            p.update(
                version="1.2",
                planner="multi-contiguous-uav",
                method="multi-contiguous-uav",
                objective="time",
                planner_options={},
                planner_options_hash=options_fingerprint({}),
                uav=i + 1,
                start_point_id=assignment["start_id"],
                end_point_id=assignment["end_id"],
            )
        current = start[:]

        def add(end, kind, targets=None):
            nonlocal current
            if math.dist(current, end) > 1e-8:
                p["segments"].append(
                    dict(
                        start=current[:],
                        end=list(end),
                        type=kind,
                        spray=kind == "spray",
                        speed=base["config"]["speed"],
                        target_ids=sorted(targets or []),
                    )
                )
            current = list(end)

        add([start[0], start[1], height], "takeoff")
        for segment in selected:
            add(segment["start"], "transit")
            add(segment["end"], segment["type"], segment.get("target_ids", []))
        add([end_point[0], end_point[1], height], "transit")
        add(end_point, "landing")
        p["status"] = "success"
        p["method"] = "multi-contiguous-uav"
        # base 若因禁飞绕行已升到 1.2，非 explicit 子机也必须同步 planner，
        # 否则 safety 会报「规划器与方法不一致」。
        if p.get("version") == "1.2":
            p["planner"] = "multi-contiguous-uav"
            p.setdefault("objective", "time")
            if "planner_options" not in p:
                p["planner_options"] = {}
            if "planner_options_hash" not in p:
                p["planner_options_hash"] = options_fingerprint(p["planner_options"])
            p.setdefault("uav", i + 1)
        try:
            check(scene, p)
            timeline = build(scene, p)
            evaluation = eb(scene, p, timeline)
            metrics = at(evaluation, timeline, timeline["duration"])
            entry = {
                "uav": i + 1,
                "status": "success",
                "segments": p["segments"],
                "duration": timeline["duration"],
                "path_length": sum(x["length"] for x in timeline["segments"]),
                "coverage": metrics["coverage"],
                "missed": metrics["missed_cells"],
                "repeated": metrics["repeated_cells"],
                "target_ids": sorted(ids),
            }
            if explicit:
                entry.update(
                    start=start,
                    end=end_point,
                    start_point_id=assignment["start_id"],
                    end_point_id=assignment["end_id"],
                )
            out.append(entry)
        except Exception as error:
            out.append({"uav": i + 1, "status": "failed", "reason": str(error)})
    active = [
        unit
        for unit in out
        if unit["status"] == "success" and not unit.get("idle") and unit.get("duration")
    ]
    coverages = [unit["coverage"] for unit in active if unit.get("coverage") is not None]
    failed = [unit for unit in out if unit.get("status") == "failed"]
    return {
        "status": "failed" if failed else "success",
        "reason": failed[0]["reason"] if failed else "",
        "uavs": out,
        "uav_count": uavs,
        "makespan": max((unit["duration"] for unit in active), default=0.0),
        "total_time": sum(unit["duration"] for unit in active),
        "coverage_mean": sum(coverages) / len(coverages) if coverages else None,
        "coverage_note": "每机对全场景目标的平均值，不是机队并集覆盖率",
        "idle": [unit["uav"] for unit in out if unit.get("idle")],
    }
