"""Independent regression for the layered 3D clearance A*."""

import json
import math
import subprocess
import sys
from pathlib import Path

from planning.model import configuration
from planning.routing3d import route3d
from planning.safety import intersects
from scene import generate

ROOT = Path(__file__).resolve().parent


def _blocks(scene):
    clearance = 0.5
    boxes = []
    for tree in scene["trees"]:
        for kind in ("trunk", "canopy"):
            g = tree[kind]
            x, y = g["center"]
            r = g["radius"]
            boxes.append(
                (
                    [x - r - clearance, y - r - clearance, g["z_min"] - clearance],
                    [x + r + clearance, y + r + clearance, g["z_max"] + clearance],
                )
            )
    for obstacle in scene["obstacles"]:
        boxes.append(
            (
                [v - clearance for v in obstacle["min"]],
                [v + clearance for v in obstacle["max"]],
            )
        )
    for zone in scene["no_fly_zones"]:
        vertices = zone["footprint"]["vertices"]
        boxes.append(
            (
                [min(v[0] for v in vertices) - clearance, min(v[1] for v in vertices) - clearance, zone["z_min"] - clearance],
                [max(v[0] for v in vertices) + clearance, max(v[1] for v in vertices) + clearance, zone["z_max"] + clearance],
            )
        )
    return boxes


def _edges_free(scene, result):
    boxes = _blocks(scene)
    for a, b in zip(result["path"], result["path"][1:]):
        assert all(intersects(a, b, lo, hi) is False for lo, hi in boxes), (a, b)


def _wall_scene():
    return generate(
        dict(
            rows=1,
            trees_per_row=3,
            obstacles=[dict(id="wall", kind="box", min=[-1, -5, 0], max=[0, 18, 7])],
        )
    )


def _nofly_scene():
    return generate(
        dict(
            rows=1,
            trees_per_row=3,
            no_fly_zones=[
                dict(
                    id="nf",
                    kind="polygon_prism",
                    footprint=dict(
                        kind="polygon",
                        vertices=[[-1, -5], [0, -5], [0, 18], [-1, 18]],
                    ),
                    z_min=0,
                    z_max=8,
                )
            ],
        )
    )


def run() -> int:
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

    c = configuration({})

    def fresh_import():
        proc = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0,'.'); from planning.routing3d import route3d; print('ok')"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok"

    def straight():
        scene = generate()
        start = [-3.0, 12.5, 6.2]
        goal = [2.0, 12.5, 6.2]
        result = route3d(scene, start, goal, c)
        assert result["status"] == "success", result["reason"]
        assert result["path"][0] == start and result["path"][-1] == goal
        assert abs(result["length"] - math.dist(start, goal)) < 1e-6
        assert result["time"] > 0 and result["stage"] == "search"
        _edges_free(scene, result)

    def wall_detour():
        scene = _wall_scene()
        result = route3d(scene, [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2], c)
        assert result["status"] == "success", result["reason"]
        straight = math.dist([-3.0, 6.5, 6.2], [2.0, 2.5, 6.2])
        assert result["length"] > straight + 1.0
        assert max(p[2] for p in result["path"]) > 7.0
        _edges_free(scene, result)

    def nofly_detour():
        scene = _nofly_scene()
        result = route3d(scene, [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2], c)
        assert result["status"] == "success", result["reason"]
        assert max(p[2] for p in result["path"]) > 8.0
        _edges_free(scene, result)

    def enclosed():
        scene = generate(
            dict(
                rows=1,
                trees_per_row=3,
                obstacles=[dict(id="w", kind="box", min=[-1, -5.5, 0], max=[0, 18.5, 11.2])],
            )
        )
        result = route3d(scene, [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2], c)
        assert result["status"] == "failed"
        assert "未找到" in result["reason"]
        assert result["expanded"] >= 0 and result["grid"]["hash"]

    def node_cap():
        scene = generate()
        result = route3d(
            scene, [-3.0, 12.5, 6.2], [2.0, 12.5, 6.2], c, grid={"max_grid_nodes": 10}
        )
        assert result["status"] == "failed" and "上限" in result["reason"]
        result = route3d(
            scene, [-3.0, 12.5, 6.2], [2.0, 12.5, 6.2], c, grid={"max_expansions": 1}
        )
        assert result["status"] == "failed"

    def deterministic():
        scene = _wall_scene()
        start, goal = [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2]
        first = route3d(scene, start, goal, c)
        second = route3d(scene, start, goal, c)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def clearance():
        scene = _wall_scene()
        loose = route3d(scene, [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2], configuration({"clearance": 0.5}))
        tight = route3d(scene, [-3.0, 6.5, 6.2], [2.0, 2.5, 6.2], configuration({"clearance": 1.0}))
        assert loose["grid"]["hash"] != tight["grid"]["hash"]
        assert tight["status"] == "success"
        assert max(p[2] for p in tight["path"]) > max(p[2] for p in loose["path"])

    def smoothing_non_worsening():
        scene = generate()
        windy = configuration(
            {"wind_speed": 4.0, "wind_direction": 0.0, "wind_cost": 0.4}
        )
        start, goal = [-3.0, 12.5, 6.2], [2.0, 12.5, 6.2]
        smoothed = route3d(scene, start, goal, windy)
        raw = route3d(scene, start, goal, windy, grid={"smoothing": False})
        assert smoothed["optimality"] == "grid-search-nonworsening"
        assert raw["optimality"] == "grid-optimal"
        assert smoothed["time"] <= raw["time"] + 1e-9
        _edges_free(scene, smoothed)

    def caps_and_alias():
        scene = generate()
        capped = route3d(
            scene,
            [0.5, 12.5, 6.2],
            [1.5, 12.5, 6.2],
            c,
            grid={"max_expansions": 1},
        )
        assert capped["status"] == "failed" and capped["expanded"] <= 1
        node_capped = route3d(
            scene, [-3.0, 12.5, 6.2], [2.0, 12.5, 6.2], c, grid={"max_grid_nodes": 5}
        )
        assert node_capped["status"] == "failed" and "上限" in node_capped["reason"]
        first = route3d(scene, [-3.0, 12.5, 6.2], [2.0, 12.5, 6.2], c)
        first["grid"]["bounds"]["min"][0] = 999
        second = route3d(scene, [-3.0, 12.5, 6.2], [3.0, 12.5, 6.2], c)
        assert second["grid"]["bounds"]["min"][0] != 999

    def endpoint_clearance():
        scene = generate()
        result = route3d(scene, [-3.0, 12.5, 0.2], [2.0, 12.5, 6.2], c)
        assert result["status"] == "failed" and "净空范围" in result["reason"]

    def occupied_start():
        scene = generate()
        tree = scene["trees"][0]["canopy"]
        start = [tree["center"][0], tree["center"][1], (tree["z_min"] + tree["z_max"]) / 2]
        result = route3d(scene, start, [2.0, 12.5, 6.2], c)
        assert result["status"] == "failed" and "起点" in result["reason"]

    def invalid():
        scene = generate()
        try:
            route3d(scene, [-3, 12.5, 6.2], [2, 12.5, 6.2], c, objective="fuel")
        except ValueError:
            pass
        else:
            raise AssertionError("未拒绝未知目标口径")
        try:
            route3d(scene, [-3, 12.5, 6.2], [2, 12.5, 6.2], c, grid={"step_xy": 0})
        except ValueError:
            pass
        else:
            raise AssertionError("未拒绝非正步长")

    check("fresh-import", fresh_import)
    check("straight", straight)
    check("wall", wall_detour)
    check("nofly", nofly_detour)
    check("enclosed", enclosed)
    check("limits", node_cap)
    check("determinism", deterministic)
    check("clearance", clearance)
    check("smoothing", smoothing_non_worsening)
    check("caps", caps_and_alias)
    check("endpoint", endpoint_clearance)
    check("occupied", occupied_start)
    check("invalid", invalid)
    return 1 if failed else 0
