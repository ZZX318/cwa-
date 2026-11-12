import json
import math
import subprocess
import sys
from pathlib import Path
from tempfile import gettempdir

from multi import run as multi_run
from scene import generate

ROOT = str(Path(__file__).resolve().parent)
TMP = Path(gettempdir())


def _run(args, timeout=120):
    return subprocess.run(
        [sys.executable, "-X", "utf8", "main.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def run_checks():
    for name in ("fixed-y", "naive"):
        result = _run(
            ["--plan", "--job", "configs/job.default.json", "--algorithm", name, "--objective", "energy"]
        )
        assert result.returncode != 0
        assert "能量代理口径未实现" in result.stdout
        assert "Traceback" not in result.stderr + result.stdout
    default_energy = _run(["--plan", "--job", "configs/job.default.json", "--objective", "energy"])
    assert default_energy.returncode != 0
    assert "能量代理口径未实现" in default_energy.stdout

    bad_job_path = TMP / "job.badclear.json"
    bad_job_path.write_text(
        '{"swath":2,"height_offset":2,"clearance":2.0,"speed":2}', encoding="utf8"
    )
    bad_job = _run(
        [
            "--experiment",
            "--seeds",
            "0",
            "--methods",
            "fixed-y,multi",
            "--job",
            str(bad_job_path),
        ]
    )
    assert bad_job.returncode != 0
    assert "Traceback" not in bad_job.stderr + bad_job.stdout
    config_experiment = _run(
        ["--experiment", "--config", "configs/joint.blocked.json", "--seeds", "0", "--methods", "fixed-y"]
    )
    assert config_experiment.returncode != 0
    assert "实验暂不支持" in config_experiment.stdout

    sortie = _run(
        [
            "--sorties",
            "--payload-capacity-kg",
            "10",
            "--flow-rate-kg-per-s",
            "0.01",
            "--energy-wh-per-eu",
            "0.5",
            "--energy-calibration-id",
            "test-01",
        ]
    )
    assert sortie.returncode == 0, sortie.stderr
    sortie_data = json.loads(sortie.stdout)
    assert sortie_data["calibrated"]
    assert math.isclose(
        sortie_data["total_energy_wh"], sortie_data["total_energy_eu"] * 0.5
    )

    plan = _run(
        [
            "--plan",
            "--job",
            "configs/job.default.json",
            "--save-plan",
            str(TMP / "plan.hash.check.json"),
        ]
    )
    assert plan.returncode == 0, plan.stderr
    saved = json.loads((TMP / "plan.hash.check.json").read_text(encoding="utf8"))
    assert "plan_hash" in saved and len(saved["plan_hash"]) == 64

    scene = generate({"rows": 1, "trees_per_row": 2})
    fleet = multi_run(scene, {}, 6)
    assert fleet["status"] == "success"
    assert fleet["idle"]
    assert fleet["coverage_note"]
    assert all(unit["coverage"] is None for unit in fleet["uavs"] if unit.get("idle"))

    print("通过 · 回归修复：能量目标拒绝、CLI 无 traceback、实验参数、批次 Wh、计划指纹、空闲机")
    return 0
