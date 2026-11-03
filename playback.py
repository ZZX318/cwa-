"""Playback payloads built from unified executor timelines.

The browser never invents trajectories: every segment and time here comes from
``execution.build``.  Multi-UAV coordinates come either from the baseline
``multi.run`` plans or from the deterministic coordination result.
"""

from execution import build
from multi import run as multi_run
from planning import fingerprint, generate_plan
import joint

COLORS = [
    "#56d9ee",
    "#f2a35e",
    "#8fce7a",
    "#c58cf2",
    "#edc96c",
    "#ed9b68",
    "#7dbbea",
    "#f27ba8",
]

SEGMENT_FIELDS = (
    "index",
    "t_start",
    "t_end",
    "start",
    "end",
    "type",
    "spray",
    "speed",
    "heading",
    "length",
    "duration",
    "target_ids",
)


def track_payload(timeline, label, color, home=None):
    """Compact executor timeline for one track; ground hold is implicit before t_start."""
    return dict(
        label=label,
        color=color,
        offset=timeline.get("offset", 0.0),
        duration=timeline["duration"],
        home=list(home) if home is not None else None,
        execution_id=timeline.get("execution_id"),
        segments=[
            {field: segment.get(field) for field in SEGMENT_FIELDS}
            for segment in timeline["segments"]
        ],
    )


def _home(base_plan):
    if base_plan.get("segments"):
        return list(base_plan["segments"][0]["start"])
    return None


def _tracks(timelines, labels, home=None, homes=None):
    return [
        track_payload(
            timelines[index],
            labels[index],
            COLORS[index % len(COLORS)],
            home=(homes[index] if homes else home),
        )
        for index in range(len(timelines))
    ]


def coordinate_tracks(timelines, home=None, homes=None):
    return _tracks(
        timelines,
        [f"UAV {index + 1}" for index in range(len(timelines))],
        home,
        homes,
    )


def plan_from_item(base, item):
    """Rebuild a per-UAV plan from a multi.run item, preserving 1.1 fallback."""
    plan = dict(base)
    plan["allow_partial"] = True
    plan["segments"] = item["segments"]
    if item.get("start_point_id"):
        from planning.model import options_fingerprint

        plan.update(
            version="1.2",
            planner="multi-contiguous-uav",
            method="multi-contiguous-uav",
            objective="time",
            planner_options={},
            planner_options_hash=options_fingerprint({}),
            uav=item["uav"],
            start_point_id=item["start_point_id"],
            end_point_id=item["end_point_id"],
        )
    return plan


def multi_playback(scene, config=None, uavs=2, algorithm="fixed-y", options=None):
    """Multi-UAV playback, built from the same planner and executor.

    ``algorithm`` is ``fixed-y`` (the legacy baseline, unchanged) or ``caw``
    (per-UAV 3D-clearance plans from ``multi_caw``).
    """
    algorithm = _normalize_algorithm(algorithm)
    base = None
    if algorithm == "caw":
        import multi_caw

        result = multi_caw.run(scene, config or {}, uavs, options)
        if result.get("status") != "success":
            return dict(status="failed", reason=result.get("reason", "多机 CAW 失败"))
    else:
        result = multi_run(scene, config or {}, uavs)
        if result.get("status") != "success":
            return dict(status="failed", reason=result.get("reason", "多机基线失败"))
        base = generate_plan(scene, config or {})
        if base.get("status") != "success":
            return dict(status="failed", reason=base.get("reason", "基准计划失败"))
    timelines = []
    labels = []
    idle = []
    for item in result.get("uavs", []):
        if item.get("status") != "success":
            return dict(
                status="failed",
                reason=f"无人机 {item.get('uav')} 计划失败：{item.get('reason', '未知原因')}",
            )
        if not item["segments"]:
            idle.append(f"UAV {item.get('uav')}")
            continue
        if algorithm == "caw":
            import multi_caw

            plan = multi_caw.plan_from_item(scene, item, config or {})
        else:
            plan = plan_from_item(base, item)
        try:
            timelines.append(build(scene, plan))
        except (ValueError, KeyError, TypeError) as error:
            return dict(
                status="failed",
                reason=f"无人机 {item.get('uav')} 执行时间构建失败：{error}",
            )
        labels.append(f"UAV {item.get('uav')}")
    if not timelines:
        return dict(status="failed", reason="没有可回放的多机航段")
    homes = [list(timeline["segments"][0]["start"]) for timeline in timelines]
    payload = dict(
        status="success",
        mode="multi-caw" if algorithm == "caw" else "multi-baseline",
        home=homes[0],
        homes=homes,
        idle=idle,
        tracks=_tracks(timelines, labels, homes=homes),
        duration=max((timeline["duration"] for timeline in timelines), default=0.0),
        scene_hash=fingerprint(scene),
        config_hash=(result.get("config_hash") if algorithm == "caw" else base.get("config_hash")),
    )
    return payload


def _normalize_algorithm(value):
    if value in (None, "", "fixed-y", "fixed", "default"):
        return "fixed-y"
    if value in ("caw", "multi-caw"):
        return "caw"
    raise ValueError("多机回放算法必须为 fixed-y 或 caw")


def joint_playback(scene, config=None, order=None, options=None):
    """Optimal (given order) and baseline joint plans, both through the executor."""
    raw = {} if config is None else config
    if not isinstance(raw, dict):
        raise ValueError("作业配置必须是对象")
    baseline_plan = generate_plan(scene, raw)
    plans = []
    if order is not None:
        try:
            optimal_plan = joint.candidate_plan(scene, raw, order, options)
            plans.append(("最优", optimal_plan))
        except (ValueError, KeyError, TypeError) as error:
            return dict(status="failed", reason=f"最优计划重建失败：{error}")
    if baseline_plan.get("status") == "success":
        plans.append(("基准", baseline_plan))
    elif order is None:
        return dict(
            status="failed", reason=f"基准计划失败：{baseline_plan.get('reason', '未知原因')}"
        )
    timelines = []
    labels = []
    for label, plan in plans:
        try:
            timelines.append(build(scene, plan))
        except (ValueError, KeyError, TypeError) as error:
            return dict(status="failed", reason=f"{label}执行时间构建失败：{error}")
        labels.append(label)
    home = _home(plans[0][1]) if plans else None
    return dict(
        status="success",
        mode="joint",
        home=home,
        tracks=_tracks(timelines, labels, home),
        duration=max((timeline["duration"] for timeline in timelines), default=0.0),
        scene_hash=fingerprint(scene),
        config_hash=baseline_plan.get("config_hash"),
    )
