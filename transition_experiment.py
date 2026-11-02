"""Descriptive fixed vs clearance-search transition comparison; not a superiority claim."""
import json
from pathlib import Path

from evaluation import at, build as build_evaluation
from execution import build as build_timeline
from planning import (
    check,
    config_fingerprint,
    configuration,
    fingerprint,
    generate_plan,
)

MODES = ("fixed", "search")


def one(scene, base_config, mode):
    config = dict(base_config)
    config["transition_mode"] = mode
    plan = generate_plan(scene, config)
    row = dict(
        transition_mode=mode,
        status=plan["status"],
        reason=plan.get("reason", ""),
        segments=len(plan.get("segments", [])),
        path_length=None,
        total_time=None,
        search_nodes=0,
        safety="not_run",
        scene_hash=plan.get("scene_hash"),
        config_hash=plan.get("config_hash"),
        plan_version=plan.get("version"),
        plan_method=plan.get("method"),
    )
    if plan["status"] != "success":
        return row
    try:
        check(scene, plan)
        timeline = build_timeline(scene, plan)
        evaluation = build_evaluation(scene, plan, timeline)
        at(evaluation, timeline, timeline["duration"])
        row.update(
            safety="pass",
            segments=len(plan["segments"]),
            path_length=sum(segment["length"] for segment in timeline["segments"]),
            total_time=timeline["duration"],
            search_nodes=plan.get("search", {}).get("nodes", 0)
            if mode == "search"
            else 0,
        )
    except (ValueError, KeyError, TypeError) as error:
        row.update(status="failed", reason=str(error), safety="failed")
    return row


def run(scene, config=None):
    base = dict(config or {})
    return dict(
        version="1.0",
        note="fixed 与 search 的描述性单场景对照；不构成 search 普遍更优或更差的结论",
        scene=dict(
            trees=len(scene["trees"]),
            targets=len(scene["targets"]),
            launch_points=len(scene["launch_points"]),
        ),
        scene_hash=fingerprint(scene),
        config_base_hash=config_fingerprint(configuration(base)),
        rows=[one(scene, base, mode) for mode in MODES],
    )


def save(result, path):
    Path(path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf8",
    )


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))
