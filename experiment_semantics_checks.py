"""Regression for experiment dispatch, failure denominators and seed semantics."""

from experiment import one, run
from planning import config_fingerprint, configuration
from scene import generate

WALL = dict(
    rows=1,
    trees_per_row=3,
    obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
)


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

    def deterministic_semantics():
        result = run((0, 1), ("fixed-y", "naive"), (1,))
        assert len(result["rows"]) == 4
        assert len(result["summary"]) == 2
        for summary in result["summary"]:
            assert summary["attempts"] == 2
            assert summary["runs"] == 1
            assert summary["deterministic"] is True
            assert summary["coverage_std"] is None
            assert summary["successes"] == 2 and summary["feasibility_rate"] == 1.0
        first = [row for row in result["rows"] if row["method"] == "fixed-y"]
        assert first[0]["total_time"] == first[1]["total_time"]
        assert first[0]["scene_hash"] == first[1]["scene_hash"]
        assert all("violation" not in row for row in result["rows"])

    def failures_denominator():
        result = run((0, 1), ("fixed-y", "caw"), (1,), scene_config=WALL)
        by_method = {summary["method"]: summary for summary in result["summary"]}
        assert by_method["fixed-y"]["attempts"] == 2
        assert by_method["fixed-y"]["successes"] == 0
        assert by_method["fixed-y"]["feasibility_rate"] == 0.0
        assert by_method["fixed-y"]["failure_stages"].get("safety") == 2
        assert by_method["caw"]["successes"] == 2
        assert by_method["caw"]["feasibility_rate"] == 1.0

    def config_passed():
        calm = run((0,), ("fixed-y",), (1,), config={"wind_speed": 0.0})
        windy = run((0,), ("fixed-y",), (1,), config={"wind_speed": 2.0, "wind_direction": 0.0})
        assert calm["summary"][0]["time_mean"] != windy["summary"][0]["time_mean"]
        assert calm["config_hash"] == config_fingerprint(configuration({"wind_speed": 0.0}))
        assert windy["config_hash"] == config_fingerprint(
            configuration({"wind_speed": 2.0, "wind_direction": 0.0})
        )
        assert calm["config_hash"] != windy["config_hash"]

    def scenes_separate():
        small = run((0, 1), ("fixed-y",), (1,), scene_config={"rows": 1, "trees_per_row": 2})
        large = run((0, 1), ("fixed-y",), (1,), scene_config={"rows": 2, "trees_per_row": 2})
        assert small["summary"][0]["scene_hash"] != large["summary"][0]["scene_hash"]
        assert all(
            row["scene_hash"] == small["summary"][0]["scene_hash"]
            for row in small["rows"]
        )

    def reproducibility():
        first = run((0, 1), ("fixed-y", "multi"), (1, 2))
        second = run((0, 1), ("fixed-y", "multi"), (1, 2))
        assert first == second

    def random_semantics():
        scene = generate(dict(rows=1, trees_per_row=3))
        row = one(scene, {}, "rl", 0, 1)
        assert row["deterministic"] is False and row["seed_used"] is True
        assert row["total_time"] is not None and "violation" not in row
        multi = one(scene, {}, "multi", 0, 2)
        assert multi["deterministic"] is True and multi["seed_used"] is False
        result = run(
            (0,), ("rl",), (1,), scene_config={"rows": 1, "trees_per_row": 3}
        )
        assert result["summary"][0]["time_mean"] is not None
        assert all("violation" not in item for item in result["rows"])

    check("deterministic", deterministic_semantics)
    check("failures", failures_denominator)
    check("config", config_passed)
    check("scenes", scenes_separate)
    check("reproducible", reproducibility)
    check("random", random_semantics)
    return 1 if failed else 0
