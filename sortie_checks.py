import json
import math
from pathlib import Path

from scene import generate
from sortie import plan_sorties

ROOT = Path(__file__).resolve().parent
SMALL = json.loads((ROOT / "configs" / "joint.small.json").read_text(encoding="utf8"))
JOB = json.loads((ROOT / "configs" / "job.joint.small.json").read_text(encoding="utf8"))


def run_checks():
    scene = generate()
    one = plan_sorties(scene, {}, {"payload_capacity_kg": 10, "flow_rate_kg_per_s": 0.01})
    assert one["status"] == "success"
    assert one["sortie_count"] == 1
    assert math.isclose(one["total_time"], 127.3963848374023)
    assert math.isclose(one["total_payload_kg"], 0.69941125, rel_tol=1e-6)
    assert one["sorties"][0]["payload_kg"] <= 10

    two = plan_sorties(scene, {}, {"payload_capacity_kg": 0.5, "flow_rate_kg_per_s": 0.01})
    assert two["status"] == "success"
    assert two["sortie_count"] == 2
    assert all(row["payload_kg"] <= 0.5 + 1e-9 for row in two["sorties"])
    assert math.isclose(
        sum(row["payload_kg"] for row in two["sorties"]),
        one["total_payload_kg"],
        rel_tol=1e-9,
    )
    assert two["total_time"] > one["total_time"]
    assert all(row["safety"] == "pass" for row in two["sorties"])

    again = plan_sorties(scene, {}, {"payload_capacity_kg": 0.5, "flow_rate_kg_per_s": 0.01})
    assert again["sorties"] == two["sorties"]
    assert two["total_gap_seconds"] == 0.0 and two["makespan"] == two["total_time"]
    assert two["total_flight_time"] == two["total_time"]
    assert all(row["gap_before_seconds"] == 0.0 for row in two["sorties"])

    timed = plan_sorties(
        scene,
        {},
        {
            "payload_capacity_kg": 0.5,
            "flow_rate_kg_per_s": 0.01,
            "refill_seconds": 10.0,
            "recharge_seconds": 5.0,
        },
    )
    assert timed["status"] == "success"
    assert timed["total_flight_time"] == two["total_time"]
    assert timed["total_gap_seconds"] == 15.0 * (timed["sortie_count"] - 1)
    assert math.isclose(
        timed["total_time"], timed["total_flight_time"] + timed["total_gap_seconds"]
    )
    assert timed["makespan"] == timed["total_time"]
    assert [row["gap_before_seconds"] for row in timed["sorties"]] == [0.0, 15.0]
    for field, value in (
        ("refill_seconds", -1.0),
        ("recharge_seconds", -0.5),
        ("refill_seconds", float("nan")),
        ("recharge_seconds", float("inf")),
        ("refill_seconds", True),
    ):
        bad = {"payload_capacity_kg": 0.5, "flow_rate_kg_per_s": 0.01, field: value}
        try:
            plan_sorties(scene, {}, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法批次间隔未被拒绝: {bad}")

    impossible = plan_sorties(
        scene, {}, {"payload_capacity_kg": 0.001, "flow_rate_kg_per_s": 0.01}
    )
    assert impossible["status"] == "failed"
    assert "超过载药上限" in impossible["reason"]

    for bad in (
        {"payload_capacity_kg": 0, "flow_rate_kg_per_s": 0.01},
        {"payload_capacity_kg": 1, "flow_rate_kg_per_s": 0},
        {"payload_capacity_kg": 1, "flow_rate_kg_per_s": 0.01, "bogus": 1},
    ):
        try:
            plan_sorties(scene, {}, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法多批次参数未被拒绝: {bad}")

    explicit = generate(SMALL)
    explicit["launch_points"] = [
        {"id": "pad-west", "position": [-3, 12, 0], "role": "start"},
        {"id": "pad-east", "position": [14, 4.5, 0], "role": "return"},
    ]
    explicit["launch_assignments"] = [
        {"uav": 1, "start": "pad-west", "end": "pad-east"}
    ]
    assigned = plan_sorties(
        explicit, JOB, {"payload_capacity_kg": 10, "flow_rate_kg_per_s": 0.01}
    )
    assert assigned["status"] == "success"
    assert assigned["start_point_id"] == "pad-west"
    assert assigned["end_point_id"] == "pad-east"
    assert all(row["plan_version"] == "1.2" for row in assigned["sorties"])

    print("通过 · 多批次：载药切分、单批上限、失败原因、确定性与显式起降点")
    print("通过 · 多批次间隔：默认 0 兼容、非零总时间/间隔/makespan、负值与非有限值拒绝")
    return 0
