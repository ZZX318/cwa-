"""Regular-orchard generator inputs, independent of experiment parameters."""

import copy
from .schema import DEFAULT, Config, require, number


def validate_config(raw: Config) -> Config:
    """Return a copied configuration with defaults; reject invalid counts/metre values.

    Raises SceneError with the offending field and value. No input is mutated.
    """
    require(isinstance(raw, dict), "config", raw, "需要 JSON 对象")
    require(
        not set(raw) - set(DEFAULT),
        "config",
        list(set(raw) - set(DEFAULT)),
        "不支持的字段",
    )
    c = copy.deepcopy(DEFAULT)
    c.update(copy.deepcopy(raw))
    for k in ("rows", "trees_per_row"):
        require(type(c[k]) is int and 1 <= c[k] <= 100, k, c[k], "需要 1 至 100 的整数")
    require(
        c["rows"] * c["trees_per_row"] <= 2500,
        "tree_count",
        c["rows"] * c["trees_per_row"],
        "交互版本最多 2500 棵",
    )
    for k in DEFAULT:
        if k not in (
            "rows",
            "trees_per_row",
            "obstacles",
            "no_fly_zones",
            "no_spray_zones",
        ):
            number(c[k], k, k != "ground_z")
            require(abs(c[k]) <= 10000, k, c[k], "绝对值不能超过 10000 米")
    require(
        c["plot_margin"] >= c["canopy_radius"],
        "plot_margin",
        c["plot_margin"],
        "必须容纳完整树冠半径",
    )
    require(
        c["trunk_radius"] <= c["canopy_radius"],
        "trunk_radius",
        c["trunk_radius"],
        "不能超过树冠半径",
    )
    require(c["reserve"] >= 2, "reserve", c["reserve"], "起降预留空间至少 2 米")
    for k in ("obstacles", "no_fly_zones", "no_spray_zones"):
        require(isinstance(c[k], list), k, c[k], "需要对象数组")
    return c
