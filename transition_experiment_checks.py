import json
from pathlib import Path
from tempfile import gettempdir

from planning import config_fingerprint, configuration, fingerprint
from scene import generate
from transition_experiment import load, run, save

ROOT = Path(__file__).resolve().parent
SMALL = json.loads(
    (ROOT / "configs" / "transition.small.json").read_text(encoding="utf8")
)


def run_checks():
    scene = generate(SMALL)
    result = run(scene)
    assert result["version"] == "1.0"
    assert "不构成" in result["note"]
    assert result["scene"]["trees"] == 6 and result["scene"]["targets"] == 6
    assert result["scene_hash"] == fingerprint(scene)
    assert result["config_base_hash"] == config_fingerprint(configuration({}))

    rows = {row["transition_mode"]: row for row in result["rows"]}
    assert sorted(rows) == ["fixed", "search"]
    for mode in ("fixed", "search"):
        row = rows[mode]
        assert row["status"] == "success" and row["safety"] == "pass"
        assert row["reason"] == "" and row["segments"] > 0
        assert row["path_length"] > 0 and row["total_time"] > 0
        assert row["scene_hash"] == fingerprint(scene)
        assert row["config_hash"] == config_fingerprint(
            configuration({"transition_mode": mode})
        )
        assert row["plan_version"] == "1.1"
    assert rows["fixed"]["plan_method"] == "fixed-y-boustrophedon"
    assert rows["search"]["plan_method"] == "fixed-y-boustrophedon+clearance-search"
    assert rows["fixed"]["search_nodes"] == 0
    assert rows["search"]["search_nodes"] > 0
    assert rows["search"]["segments"] > rows["fixed"]["segments"]

    path = Path(gettempdir()) / "transition.experiment.json"
    save(result, path)
    assert load(path) == result

    extent = scene["extent"]
    blocked_scene = dict(scene)
    blocked_scene["obstacles"] = [
        {
            "id": "wall",
            "kind": "box",
            "min": [-1.5, extent["min"][1], 0],
            "max": [-1.3, extent["max"][1], 10],
        }
    ]
    blocked = run(blocked_scene)
    assert blocked["scene_hash"] == fingerprint(blocked_scene)
    brows = {row["transition_mode"]: row for row in blocked["rows"]}
    for mode in ("fixed", "search"):
        row = brows[mode]
        assert row["status"] == "failed" and row["reason"]
        assert row["path_length"] is None and row["total_time"] is None
        assert row["safety"] == "not_run"
        assert row["config_hash"] == config_fingerprint(
            configuration({"transition_mode": mode})
        )
    assert "冲突" in brows["fixed"]["reason"]
    assert "转场搜索失败" in brows["search"]["reason"]

    print("通过 · 转场对照实验：字段、指纹、成功/失败保留与保存加载")
    return 0
