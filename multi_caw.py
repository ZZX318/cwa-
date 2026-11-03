"""Multi-UAV CAW planning over contiguous spray-lane chunks.

Each UAV gets a deterministic contiguous block of the shared fixed-Y lane
indices (the same split rule as ``multi.run``), then plans that block with
``CawAStarPlanner.plan_sequence`` using its own start/end point.  Every plan is
rebuilt through the shared safety check, executor and evaluator; a failed UAV
keeps ``stage``/``reason`` and the fleet result is ``failed``.

This is a descriptive single-scene baseline, not a claim that CAW beats the
fixed-Y multi-UAV baseline.
"""

import math

from evaluation import at, build as evaluation_build
from execution import build
from planning import check, config_fingerprint, configuration, fingerprint
from planning.model import options_fingerprint
from planning.planner import fixed_y_lanes
from planner_api import CawAStarPlanner
from scene.launch import resolve_all

METHOD = "multi-caw-uav"


def chunk_indices(count, uavs):
    """Same contiguous split as ``multi.run``: i*n//uavs .. (i+1)*n//uavs."""
    return [list(range(i * count // uavs, (i + 1) * count // uavs)) for i in range(uavs)]


def plan_from_item(scene, item, config=None):
    """Rebuild one UAV's checkable v1.2 CAW plan from a result item."""
    c = configuration(config or {})
    planner_options = item.get("planner_options") or {}
    plan = dict(
        version=item.get("plan_version", "1.2"),
        planner=item.get("planner", "caw-a*-3d-wind"),
        method=item.get("planner", "caw-a*-3d-wind"),
        objective=item.get("objective", "time"),
        scene_hash=fingerprint(scene),
        status="success",
        reason="",
        stage="plan",
        segments=[dict(segment) for segment in item["segments"]],
        allow_partial=True,
        work_height=item["work_height"],
        strip_count=item.get("strip_count", len(item.get("assigned_lane_indices", []))),
        planner_options=planner_options,
        planner_options_hash=item["planner_options_hash"],
        config=c,
        config_hash=item["config_hash"],
        uav=item["uav"],
        start_point_id=item["start_point_id"],
        end_point_id=item["end_point_id"],
    )
    if item.get("assigned_lane_indices") is not None:
        plan["assigned_lane_indices"] = list(item["assigned_lane_indices"])
    return plan


def run(scene, config=None, uavs=2, options=None):
    if type(uavs) is not int or not 1 <= uavs <= 32:
        raise ValueError("无人机数量需为 1..32")
    plan_options = {} if options is None else options
    if not isinstance(plan_options, dict):
        raise ValueError("规划器参数必须是对象")
    planner = CawAStarPlanner()
    normalized_options = planner.validate_options(plan_options)
    c = configuration(config or {})
    result = dict(
        version="1.0",
        method=METHOD,
        status="failed",
        reason="",
        stage="plan",
        algorithm="caw",
        planner="caw-a*-3d-wind",
        uavs=[],
        uav_count=uavs,
        scene_hash=fingerprint(scene),
        config_hash=config_fingerprint(c),
        planner_options=normalized_options,
        planner_options_hash=options_fingerprint(normalized_options),
    )
    try:
        layout = fixed_y_lanes(scene, c)
    except (ValueError, KeyError, TypeError) as error:
        result.update(reason=str(error), stage="plan")
        return result
    lanes = layout["lanes"]
    if not lanes:
        result.update(reason="没有喷洒航段", stage="plan")
        return result
    try:
        resolved = resolve_all(scene, uavs)
    except ValueError as error:
        result.update(reason=str(error), stage="launch")
        return result

    rows = []
    for index, chunk in enumerate(chunk_indices(len(lanes), uavs)):
        assignment = resolved[index]
        start = list(assignment["start"]["position"])
        end = list(assignment["end"]["position"])
        if not chunk:
            rows.append(
                dict(
                    uav=index + 1,
                    status="success",
                    segments=[],
                    duration=0.0,
                    idle=True,
                    start=start,
                    end=end,
                    start_point_id=assignment["start_id"],
                    end_point_id=assignment["end_id"],
                )
            )
            continue
        plan = planner.plan_sequence(
            scene,
            c,
            lane_indices=chunk,
            start=start,
            end=end,
            uav=index + 1,
            options=normalized_options,
        )
        if plan.get("status") != "success":
            rows.append(
                dict(
                    uav=index + 1,
                    status="failed",
                    stage=plan.get("stage", "plan"),
                    reason=plan.get("reason", "规划失败"),
                )
            )
            continue
        try:
            check(scene, plan)
            timeline = build(scene, plan)
            evaluation = evaluation_build(scene, plan, timeline)
            metrics = at(evaluation, timeline, timeline["duration"])
        except (ValueError, KeyError, TypeError) as error:
            rows.append(
                dict(uav=index + 1, status="failed", stage="execution", reason=str(error))
            )
            continue
        rows.append(
            dict(
                uav=index + 1,
                status="success",
                segments=plan["segments"],
                duration=timeline["duration"],
                path_length=sum(segment["length"] for segment in timeline["segments"]),
                coverage=metrics["coverage"],
                missed=metrics["missed_cells"],
                repeated=metrics["repeated_cells"],
                target_ids=sorted(
                    {tid for segment in plan["segments"] for tid in segment["target_ids"]}
                ),
                start=start,
                end=end,
                start_point_id=plan["start_point_id"],
                end_point_id=plan["end_point_id"],
                plan_version=plan["version"],
                planner=plan["planner"],
                objective=plan["objective"],
                planner_options=plan["planner_options"],
                planner_options_hash=plan["planner_options_hash"],
                config_hash=plan["config_hash"],
                work_height=plan["work_height"],
                strip_count=plan["strip_count"],
                assigned_lane_indices=list(chunk),
                search=plan.get("search"),
                order_search=plan.get("order_search"),
                objective_value=plan.get("objective_value"),
                safety="pass",
            )
        )

    failures = [row for row in rows if row["status"] != "success"]
    result["uavs"] = rows
    if failures:
        first = failures[0]
        result.update(
            status="failed",
            stage=first.get("stage", "uav"),
            reason=f"UAV {first['uav']} 计划失败：{first.get('reason', '未知原因')}",
        )
        return result
    success = [row for row in rows if not row.get("idle")]
    if not success:
        result.update(reason="没有可规划的喷洒航段", stage="plan")
        return result
    result.update(
        status="success",
        stage="done",
        work_height=success[0]["work_height"],
    )
    return result


def verify(result, scene, config=None):
    """Reject forged/stale fleet results by rebuilding every UAV plan."""
    if not isinstance(result, dict):
        raise ValueError("多机 CAW 结果必须是对象")
    if result.get("scene_hash") != fingerprint(scene):
        raise ValueError("多机 CAW 结果与场景指纹不匹配")
    c = configuration(config or {})
    if result.get("config_hash") != config_fingerprint(c):
        raise ValueError("多机 CAW 结果与配置指纹不匹配")
    units = result.get("uavs")
    if not isinstance(units, list) or not units:
        raise ValueError("多机 CAW 结果缺少无人机明细")
    if result.get("uav_count") != len(units):
        raise ValueError("多机 CAW 无人机数量不一致")
    status = result.get("status")
    if status not in ("success", "failed"):
        raise ValueError("多机 CAW 结果状态非法")
    options = result.get("planner_options")
    if not isinstance(options, dict):
        raise ValueError("多机 CAW 规划器参数必须是对象")
    if result.get("planner_options_hash") != options_fingerprint(options):
        raise ValueError("多机 CAW 规划器参数指纹不匹配")
    normalized = CawAStarPlanner().validate_options(options)
    failures = [row for row in units if row.get("status") != "success"]
    if status == "failed":
        if not failures:
            raise ValueError("失败结果必须包含至少一架失败无人机")
        if not result.get("reason"):
            raise ValueError("失败结果缺少原因")
        rebuilt = run(scene, c, len(units), options)
        if rebuilt.get("status") == "success":
            raise ValueError("失败结果与当前输入不一致：当前多机 CAW 成功")
        return True
    if failures:
        raise ValueError("成功结果不得包含失败无人机")
    for row in units:
        if row.get("idle"):
            if row.get("segments"):
                raise ValueError("空闲无人机不得携带航段")
            continue
        if row.get("planner_options") != normalized:
            raise ValueError(f"UAV {row.get('uav')} 规划器参数与结果不一致")
        plan = plan_from_item(scene, row, c)
        check(scene, plan)
        timeline = build(scene, plan)
        if not math.isclose(timeline["duration"], row["duration"], abs_tol=1e-9):
            raise ValueError(f"UAV {row.get('uav')} 时长与重建计划不一致")
        if row.get("safety") != "pass":
            raise ValueError(f"UAV {row.get('uav')} 安全状态不一致")
    return True
