import json
import subprocess
import sys
from pathlib import Path
from tempfile import gettempdir

from planning import check, generate_plan, load_plan, save_plan
from planning.model import config_fingerprint, configuration, with_transition_mode
from scene import generate

ROOT = Path(__file__).resolve().parent


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _copy(plan):
    return json.loads(json.dumps(plan))


def _rejects(scene, plan, expected):
    try:
        check(scene, plan)
    except ValueError as error:
        assert expected in str(error), (expected, str(error))
        return
    raise AssertionError(f"篡改计划未被拒绝：{expected}")


def run():
    scene = generate()

    fixed = generate_plan(scene, {})
    assert fixed["status"] == "success"
    assert fixed["version"] == "1.1"
    assert fixed["config"]["transition_mode"] == "fixed"
    assert fixed["method"] == "fixed-y-boustrophedon"
    assert fixed["config_hash"] == config_fingerprint(configuration(fixed["config"]))

    searched = generate_plan(scene, {"transition_mode": "search"})
    assert searched["status"] == "success"
    assert searched["config"]["transition_mode"] == "search"
    assert searched["method"] == "fixed-y-boustrophedon+clearance-search"
    assert searched["config_hash"] == config_fingerprint(configuration(searched["config"]))
    assert len(searched["segments"]) > len(fixed["segments"])

    extent = scene["extent"]
    blocked = dict(scene)
    blocked["obstacles"] = [
        {
            "id": "wall",
            "kind": "box",
            "min": [-0.2, extent["min"][1], 0],
            "max": [0.2, extent["max"][1], 10],
        }
    ]
    failed = generate_plan(blocked, {"transition_mode": "search"})
    assert failed["status"] == "failed"
    assert "转场搜索失败" in failed["reason"] and failed["segments"] == []

    path = Path(gettempdir()) / "orchard.transition.plan.json"
    save_plan(scene, searched, path)
    assert load_plan(scene, path) == searched

    tampered = _copy(searched)
    tampered["config"]["transition_mode"] = "fixed"
    _rejects(scene, tampered, "配置指纹不匹配")

    tampered = _copy(searched)
    tampered["config_hash"] = "0" * 64
    _rejects(scene, tampered, "配置指纹不匹配")

    tampered = _copy(searched)
    del tampered["config_hash"]
    _rejects(scene, tampered, "配置指纹不匹配")

    tampered = _copy(fixed)
    tampered["method"] = "fixed-y-boustrophedon+clearance-search"
    _rejects(scene, tampered, "计划方法与转场模式不一致")

    assert with_transition_mode({}, None) == {}
    assert with_transition_mode({}, "search") == {"transition_mode": "search"}
    assert with_transition_mode({"transition_mode": "fixed"}, "search")["transition_mode"] == "search"
    assert with_transition_mode({"transition_mode": "search"}, None)["transition_mode"] == "search"

    legacy_path = ROOT / "examples" / "default.plan.json"
    if legacy_path.exists():
        legacy = load_plan(scene, legacy_path)
        assert legacy["version"] == "1.0" and "config_hash" not in legacy

    job_path = Path(gettempdir()) / "orchard.job.json"
    job_path.write_text(json.dumps({"transition_mode": "fixed"}), encoding="utf8")
    fixed_cli = _cli("--plan", "--job", str(job_path))
    assert fixed_cli.returncode == 0, fixed_cli.stderr
    assert json.loads(fixed_cli.stdout)["config"]["transition_mode"] == "fixed"

    search_cli = _cli("--plan", "--job", str(job_path), "--transition-mode", "search")
    assert search_cli.returncode == 0, search_cli.stderr
    search_result = json.loads(search_cli.stdout)
    assert search_result["config"]["transition_mode"] == "search"
    assert search_result["method"] == "fixed-y-boustrophedon+clearance-search"

    blocked_path = Path(gettempdir()) / "orchard.blocked.scene.json"
    blocked_path.write_text(json.dumps(blocked), encoding="utf8")
    failed_cli = _cli("--load", str(blocked_path), "--plan", "--transition-mode", "search")
    assert failed_cli.returncode == 1
    assert json.loads(failed_cli.stdout)["status"] == "failed"

    print("通过 · 可选转场搜索：CLI 覆盖、模式/指纹篡改拒绝与旧计划兼容")
    return 0
