"""Deterministic regular planting is one map source, not a consumer assumption."""

import copy
import math
from typing import Optional
from .schema import VERSION, Config, Scene, require
from .config import validate_config
from .geometry import terrain_height, rectangle
from .validation import validate_scene


def generate(config: Optional[Config] = None) -> Scene:
    """Generate and validate explicit metre geometry from regular-orchard inputs.

    Each tree becomes an independent object. No display, file or server I/O.
    Source parameters record provenance; loading never replays this generator.
    """
    c = validate_config({} if config is None else config)
    w = 2 * c["plot_margin"] + (c["rows"] - 1) * c["row_spacing"]
    h = 2 * c["plot_margin"] + (c["trees_per_row"] - 1) * c["plant_spacing"]
    g = c["ground_z"]
    r = c["reserve"]
    s = dict(
        format_version=VERSION,
        coordinates=dict(
            unit="m",
            origin=[0, 0, 0],
            x="跨行方向",
            y="沿行方向",
            z="竖直向上",
            handedness="right",
        ),
        source=dict(kind="regular_orchard", parameters=c),
        terrain=dict(kind="flat", height=g),
        plot=rectangle(w, h),
        extent=dict(
            min=[-r, -r, g],
            max=[w + r, h + r, g + max(12, c["trunk_height"] + c["canopy_height"] + 3)],
        ),
        trees=[],
        targets=[],
        launch_points=[dict(id="launch-1", position=[-r / 2, h / 2, g])],
        obstacles=copy.deepcopy(c["obstacles"]),
        no_fly_zones=copy.deepcopy(c["no_fly_zones"]),
        no_spray_zones=copy.deepcopy(c["no_spray_zones"]),
    )
    for i in range(c["rows"]):
        for j in range(c["trees_per_row"]):
            tid = f"tree-{i+1:02}-{j+1:02}"
            x = c["plot_margin"] + i * c["row_spacing"]
            y = c["plot_margin"] + j * c["plant_spacing"]
            g = terrain_height(s, x, y)
            trunk = dict(
                kind="cylinder",
                center=[x, y],
                radius=c["trunk_radius"],
                z_min=g,
                z_max=g + c["trunk_height"],
            )
            canopy = dict(
                kind="cylinder",
                center=[x, y],
                radius=c["canopy_radius"],
                z_min=trunk["z_max"],
                z_max=trunk["z_max"] + c["canopy_height"],
            )
            s["trees"].append(
                dict(id=tid, position=[x, y, g], trunk=trunk, canopy=canopy)
            )
            s["targets"].append(
                dict(
                    id="target-" + tid,
                    tree_id=tid,
                    geometry=copy.deepcopy(canopy),
                    meaning="需喷洒的树冠体积；不规定航高或路径",
                )
            )
    validate_scene(s)
    _validate_generated_layout(s, c)
    return s


def _validate_generated_layout(scene: Scene, config: Config) -> None:
    """Check this generator's output contract only; never constrain loaded maps."""
    trees = scene["trees"]
    expected = config["rows"] * config["trees_per_row"]
    require(
        len(trees) == expected, "generated.trees", len(trees), f"应为 {expected} 棵"
    )
    xs = sorted({tree["position"][0] for tree in trees})
    ys = sorted({tree["position"][1] for tree in trees})
    require(
        len(xs) == config["rows"] and len(ys) == config["trees_per_row"],
        "generated.layout",
        [len(xs), len(ys)],
        "生成的行列数量不符",
    )
    pairs = {tuple(tree["position"][:2]) for tree in trees}
    require(
        len(pairs) == expected, "generated.positions", len(pairs), "生成位置存在重复"
    )
    for values, spacing_field in ((xs, "row_spacing"), (ys, "plant_spacing")):
        require(
            math.isclose(values[0], config["plot_margin"]),
            "generated.margin",
            values[0],
            "首个树心须符合边缘留白",
        )
        for a, b in zip(values, values[1:]):
            require(
                math.isclose(b - a, config[spacing_field]),
                "generated." + spacing_field,
                b - a,
                "生成间距与配置不符",
            )
