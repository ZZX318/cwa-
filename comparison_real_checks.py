"""Regression for real planner dispatch in comparison tables."""

import json

from comparison import run
from planning import config_fingerprint, configuration, fingerprint
from scene import generate


def run_checks() -> int:
    passed = 0
    failed = 0

    def check(name, f):
        nonlocal passed, failed
        try:
            f()
            passed += 1
            print("通过 · " + name)
        except Exception as error:
            failed += 1
            print("失败 · " + name + "：" + str(error))

    def three_methods():
        scene = generate()
        result = run(scene, {}, "all")
        assert [row["method"] for row in result["results"]] == [
            "fixed-y-boustrophedon",
            "naive-target-order",
            "caw-a*-3d-wind",
        ]
        fixed, naive, caw = result["results"]
        assert fixed["status"] == naive["status"] == caw["status"] == "success"
        assert fixed["path_length"] != naive["path_length"]
        assert fixed["duration"] != naive["duration"]
        assert caw["plan_version"] == "1.2"
        assert fixed["plan_version"] == naive["plan_version"] == "1.1"
        assert caw["safety"] == fixed["safety"] == "pass"
        assert "violation" not in fixed
        assert caw["search_nodes"] and caw["order"] and caw["matrix_mode"]
        assert result["config_hash"] == config_fingerprint(configuration({}))
        assert all(row["scene_hash"] == fingerprint(scene) for row in result["results"])
        json.dumps(result, allow_nan=False)

    def both_semantics():
        scene = generate()
        result = run(scene, {}, "both")
        assert len(result["results"]) == 2
        fixed, naive = result["results"]
        assert fixed["method"] != naive["method"]
        assert fixed["path_length"] != naive["path_length"]

    def failures_retained():
        wall = generate(
            dict(
                rows=1,
                trees_per_row=3,
                obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
            )
        )
        result = run(wall, {}, "all")
        rows = {row["method"]: row for row in result["results"]}
        assert rows["fixed-y-boustrophedon"]["status"] == "failed"
        assert rows["fixed-y-boustrophedon"]["stage"] == "safety"
        assert rows["fixed-y-boustrophedon"]["reason"]
        assert rows["naive-target-order"]["status"] == "failed"
        assert rows["caw-a*-3d-wind"]["status"] == "success"
        assert rows["caw-a*-3d-wind"]["safety"] == "pass"

    def unknown_method():
        result = run(generate(), {}, "not-a-planner")
        assert len(result["results"]) == 1
        row = result["results"][0]
        assert row["status"] == "failed" and "未知规划器" in row["reason"]

    def caw_metrics():
        result = run(generate(dict(rows=1, trees_per_row=3)), {}, "caw")
        row = result["results"][0]
        assert row["status"] == "success"
        assert row["coverage"] == 1.0
        assert row["transition_length"] > 0
        assert row["spray_seconds"] > 0
        assert row["amount"] == row["spray_seconds"] * 1.0

    check("three", three_methods)
    check("both", both_semantics)
    check("failures", failures_retained)
    check("unknown", unknown_method)
    check("metrics", caw_metrics)
    return 1 if failed else 0
