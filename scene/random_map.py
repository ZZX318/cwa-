"""Reproducible random orchard scenes.

Pure scene layer: no planner, server or UI imports.  Every style builds a
complete materialized scene with one target per tree.  All randomness comes
from one ``random.Random(seed)`` with a fixed call order, and every coordinate
is quantized to millimetres so the same version + seed + parameters encode
byte-for-byte identically.
"""

import copy
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from .config import validate_config
from .generator import generate as regular_generate
from .geometry import disk_in_polygon
from .presets import PRESETS, preset_names
from .schema import DEFAULT, VERSION, Scene, SceneError
from .shapes import (
    boxes_overlap,
    point_in_box,
    quantize,
    rectangle_footprint,
    rectangle_overlaps_polygon,
)
from .validation import validate_scene

GENERATOR_VERSION = 1

COORDINATES = dict(
    unit="m",
    origin=[0, 0, 0],
    x="跨行方向",
    y="沿行方向",
    z="竖直向上",
    handedness="right",
)

TARGET_MEANING = "需喷洒的树冠体积；不规定航高或路径"


def _defaults() -> Dict[str, Dict[str, Any]]:
    return {
        "regular": copy.deepcopy(DEFAULT),
        "jitter_rows": dict(
            rows=4,
            trees_per_row=6,
            row_spacing=6.0,
            plant_spacing=4.0,
            jitter_xy=0.6,
            canopy_radius_range=[1.2, 1.8],
            canopy_height_range=[2.0, 3.2],
            trunk_radius=0.15,
            trunk_height=1.8,
            plot_margin=2.5,
            reserve=6.0,
            ground_z=0.0,
        ),
        "clusters_gaps": dict(
            cluster_rows=2,
            cluster_cols=3,
            cluster_spacing_x=12.0,
            cluster_spacing_y=14.0,
            trees_per_cluster_range=[3, 7],
            cluster_radius=4.5,
            missing_prob=0.15,
            min_tree_distance=2.5,
            canopy_radius_range=[1.2, 1.8],
            canopy_height_range=[2.0, 3.2],
            trunk_radius=0.15,
            trunk_height=1.8,
            margin=2.5,
            reserve=6.0,
            ground_z=0.0,
        ),
        "size_mix": dict(
            rows=4,
            trees_per_row=6,
            row_spacing=6.0,
            plant_spacing=4.0,
            classes=[
                dict(name="幼树", p=0.6, radius=[0.8, 1.2], height=[1.8, 2.4]),
                dict(name="成树", p=0.4, radius=[1.5, 2.0], height=[2.8, 3.6]),
            ],
            trunk_radius=0.15,
            trunk_height=1.8,
            plot_margin=3.0,
            reserve=6.0,
            ground_z=0.0,
        ),
        "random_obstacles_zones": dict(
            base_style="jitter_rows",
            base_params={},
            obstacle_count=3,
            obstacle_size_range=[1.5, 4.0],
            obstacle_height_range=[2.0, 6.0],
            no_fly_count=1,
            no_spray_count=1,
            zone_size_range=[2.0, 6.0],
            no_fly_z_offset_range=[0.0, 8.0],
            no_spray_z_offset_range=[0.0, 5.0],
            allow_inside_plot=False,
        ),
    }


STYLE_ALIASES = {"clustered": "clusters_gaps"}


def canonical_style(style: str) -> str:
    return STYLE_ALIASES.get(style, style)


STYLES = {
    "regular": dict(
        label="规则果园",
        description="确定性行列布局；seed 不参与几何",
        defaults=_defaults()["regular"],
    ),
    "jitter_rows": dict(
        label="抖动行株",
        description="规则网格 + 独立位置抖动 + 冠层尺寸采样",
        defaults=_defaults()["jitter_rows"],
    ),
    "clusters_gaps": dict(
        label="簇状缺株",
        description="簇中心网格 + 圆内拒绝采样 + 概率缺株",
        defaults=_defaults()["clusters_gaps"],
    ),
    "size_mix": dict(
        label="冠层尺寸混合",
        description="规则位置 + 多尺寸类概率采样",
        defaults=_defaults()["size_mix"],
    ),
    "random_obstacles_zones": dict(
        label="随机障碍与区域",
        description="基础布局 + 预设障碍 + 随机禁飞/禁喷区域",
        defaults=_defaults()["random_obstacles_zones"],
    ),
}


def _num(value: Any, field: str, positive: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SceneError(f"{field} = {value!r}：必须是有限数值", field=field)
    if positive and value <= 0:
        raise SceneError(f"{field} = {value!r}：必须大于 0", field=field)
    return float(value)


def _int(value: Any, field: str, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise SceneError(
            f"{field} = {value!r}：需要 {lo} 至 {hi} 的整数", field=field
        )
    return value


def _range(value: Any, field: str, positive: bool = True) -> List[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SceneError(f"{field} = {value!r}：需要两个数值", field=field)
    low = _num(value[0], field + "[0]", positive)
    high = _num(value[1], field + "[1]", positive)
    if low > high:
        raise SceneError(f"{field} = {value!r}：下限不能高于上限", field=field)
    return [low, high]


def _unknown(raw: Dict[str, Any], allowed: set, field: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise SceneError(
            f"{field} = {extra!r}：不支持的字段", field=field
        )


def _normalize(style: str, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge defaults, reject unknown keys and enforce per-style ranges."""
    style = canonical_style(style)
    if style not in STYLES:
        raise SceneError(
            f"style = {style!r}：未知样式；可选：{', '.join(sorted(STYLES))}",
            field="style",
        )
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SceneError("params = %r：需要 JSON 对象" % (raw,), field="params")
    if style == "regular":
        return validate_config(raw)
    defaults = copy.deepcopy(STYLES[style]["defaults"])
    allowed = set(defaults)
    if style == "random_obstacles_zones":
        allowed.add("zone_z_offset_range")
    _unknown(raw, allowed, "params")
    p = copy.deepcopy(defaults)
    p.update(copy.deepcopy(raw))

    if style == "jitter_rows":
        p["rows"] = _int(p["rows"], "rows", 1, 100)
        p["trees_per_row"] = _int(p["trees_per_row"], "trees_per_row", 1, 100)
        if p["rows"] * p["trees_per_row"] > 2500:
            raise SceneError("tree_count = %d：交互版本最多 2500 棵" % (p["rows"] * p["trees_per_row"]), field="tree_count")
        for key in ("row_spacing", "plant_spacing", "trunk_radius", "trunk_height", "plot_margin", "reserve"):
            _num(p[key], key, positive=True)
        _num(p["ground_z"], "ground_z")
        p["jitter_xy"] = _num(p["jitter_xy"], "jitter_xy")
        if not 0 <= p["jitter_xy"] <= 2.0:
            raise SceneError("jitter_xy = %r：需要在 0 至 2 米" % p["jitter_xy"], field="jitter_xy")
        p["canopy_radius_range"] = _range(p["canopy_radius_range"], "canopy_radius_range")
        p["canopy_height_range"] = _range(p["canopy_height_range"], "canopy_height_range")
        if p["trunk_radius"] > p["canopy_radius_range"][0]:
            raise SceneError("trunk_radius：不能超过最小树冠半径", field="trunk_radius")
        if p["plot_margin"] + 1e-9 < p["canopy_radius_range"][1] + p["jitter_xy"] + 0.1:
            raise SceneError(
                "plot_margin：必须至少为最大树冠半径 + jitter_xy + 0.1 米",
                field="plot_margin",
            )
        if p["reserve"] < 2:
            raise SceneError("reserve = %r：起降预留空间至少 2 米" % p["reserve"], field="reserve")

    elif style == "clusters_gaps":
        for key in ("cluster_rows", "cluster_cols"):
            p[key] = _int(p[key], key, 1, 100)
        for key in ("cluster_spacing_x", "cluster_spacing_y", "cluster_radius", "min_tree_distance", "trunk_radius", "trunk_height", "margin", "reserve"):
            _num(p[key], key, positive=True)
        _num(p["ground_z"], "ground_z")
        p["trees_per_cluster_range"] = [
            _int(v, f"trees_per_cluster_range[{i}]", 0, 100)
            for i, v in enumerate(_range_like(p["trees_per_cluster_range"], "trees_per_cluster_range"))
        ]
        if p["trees_per_cluster_range"][0] > p["trees_per_cluster_range"][1]:
            raise SceneError("trees_per_cluster_range：下限不能高于上限", field="trees_per_cluster_range")
        if p["cluster_rows"] * p["cluster_cols"] * p["trees_per_cluster_range"][1] > 2500:
            raise SceneError(
                "tree_count：交互版本最多 2500 棵", field="trees_per_cluster_range"
            )
        p["missing_prob"] = _num(p["missing_prob"], "missing_prob")
        if not 0 <= p["missing_prob"] <= 1:
            raise SceneError("missing_prob：需要在 0 至 1", field="missing_prob")
        p["canopy_radius_range"] = _range(p["canopy_radius_range"], "canopy_radius_range")
        p["canopy_height_range"] = _range(p["canopy_height_range"], "canopy_height_range")
        if p["trunk_radius"] > p["canopy_radius_range"][0]:
            raise SceneError("trunk_radius：不能超过最小树冠半径", field="trunk_radius")
        if p["min_tree_distance"] < 2 * p["trunk_radius"]:
            raise SceneError("min_tree_distance：必须大于树干直径", field="min_tree_distance")
        if p["reserve"] < 2:
            raise SceneError("reserve：起降预留空间至少 2 米", field="reserve")

    elif style == "size_mix":
        p["rows"] = _int(p["rows"], "rows", 1, 100)
        p["trees_per_row"] = _int(p["trees_per_row"], "trees_per_row", 1, 100)
        if p["rows"] * p["trees_per_row"] > 2500:
            raise SceneError("tree_count：交互版本最多 2500 棵", field="tree_count")
        for key in ("row_spacing", "plant_spacing", "trunk_radius", "trunk_height", "plot_margin", "reserve"):
            _num(p[key], key, positive=True)
        _num(p["ground_z"], "ground_z")
        classes = p["classes"]
        if not isinstance(classes, list) or len(classes) < 2:
            raise SceneError("classes：至少需要两个尺寸类", field="classes")
        total = 0.0
        max_radius = 0.0
        min_radius = float("inf")
        for index, cls in enumerate(classes):
            field = f"classes[{index}]"
            if not isinstance(cls, dict):
                raise SceneError(f"{field}：需要对象", field=field)
            if not isinstance(cls.get("name"), str) or not cls["name"]:
                raise SceneError(f"{field}.name：需要非空字符串", field=field + ".name")
            cls["p"] = _num(cls.get("p"), field + ".p", positive=True)
            cls["radius"] = _range(cls.get("radius"), field + ".radius")
            cls["height"] = _range(cls.get("height"), field + ".height")
            total += cls["p"]
            max_radius = max(max_radius, cls["radius"][1])
            min_radius = min(min_radius, cls["radius"][0])
        if abs(total - 1.0) > 1e-6:
            raise SceneError("classes：概率之和必须为 1", field="classes.p")
        if p["trunk_radius"] > min_radius:
            raise SceneError("trunk_radius：不能超过最小树冠半径", field="trunk_radius")
        if p["plot_margin"] + 1e-9 < max_radius + 0.1:
            raise SceneError("plot_margin：必须至少为最大树冠半径 + 0.1 米", field="plot_margin")
        if p["reserve"] < 2:
            raise SceneError("reserve：起降预留空间至少 2 米", field="reserve")

    elif style == "random_obstacles_zones":
        if "zone_z_offset_range" in p:
            shared = _range(p.pop("zone_z_offset_range"), "zone_z_offset_range")
            p["no_fly_z_offset_range"] = list(shared)
            p["no_spray_z_offset_range"] = list(shared)
        base_style = p["base_style"]
        if base_style not in ("regular", "jitter_rows", "clusters_gaps", "size_mix"):
            raise SceneError(
                "base_style = %r：必须是 regular、jitter_rows、clusters_gaps 或 size_mix"
                % (base_style,),
                field="base_style",
            )
        if not isinstance(p["base_params"], dict):
            raise SceneError("base_params：需要对象", field="base_params")
        p["base_params"] = _normalize(base_style, p["base_params"])
        p["obstacle_count"] = _int(p["obstacle_count"], "obstacle_count", 0, 10)
        p["no_fly_count"] = _int(p["no_fly_count"], "no_fly_count", 0, 5)
        p["no_spray_count"] = _int(p["no_spray_count"], "no_spray_count", 0, 5)
        p["obstacle_size_range"] = _range(p["obstacle_size_range"], "obstacle_size_range")
        p["obstacle_height_range"] = _range(p["obstacle_height_range"], "obstacle_height_range")
        p["zone_size_range"] = _range(p["zone_size_range"], "zone_size_range")
        p["no_fly_z_offset_range"] = _range(p["no_fly_z_offset_range"], "no_fly_z_offset_range", positive=False)
        p["no_spray_z_offset_range"] = _range(p["no_spray_z_offset_range"], "no_spray_z_offset_range", positive=False)
        if p["no_fly_z_offset_range"][0] < 0 or p["no_spray_z_offset_range"][0] < 0:
            raise SceneError("区域高度偏移必须不小于 0（相对地面）", field="zone_z_offset_range")
        if not isinstance(p["allow_inside_plot"], bool):
            raise SceneError("allow_inside_plot：必须是布尔值", field="allow_inside_plot")

    return p


def _range_like(value: Any, field: str) -> List[Any]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SceneError(f"{field} = {value!r}：需要两个整数", field=field)
    return list(value)


def _shell(
    width: float, height: float, ground: float, reserve: float, top: float
) -> Scene:
    width, height, ground, reserve = (
        quantize(width),
        quantize(height),
        quantize(ground),
        quantize(reserve),
    )
    return dict(
        format_version=VERSION,
        coordinates=copy.deepcopy(COORDINATES),
        source={},
        terrain=dict(kind="flat", height=ground),
        plot=dict(
            kind="polygon",
            vertices=[[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
        ),
        extent=dict(
            min=[quantize(-reserve), quantize(-reserve), ground],
            max=[
                quantize(width + reserve),
                quantize(height + reserve),
                quantize(ground + max(12.0, top)),
            ],
        ),
        trees=[],
        targets=[],
        launch_points=[dict(id="launch-1", position=[quantize(-reserve / 2.0), quantize(height / 2.0), ground])],
        obstacles=[],
        no_fly_zones=[],
        no_spray_zones=[],
    )


def _add_tree(
    scene: Scene,
    tree_id: str,
    x: float,
    y: float,
    ground: float,
    trunk_radius: float,
    trunk_height: float,
    canopy_radius: float,
    canopy_height: float,
) -> None:
    x, y = quantize(x), quantize(y)
    trunk = dict(
        kind="cylinder",
        center=[x, y],
        radius=quantize(trunk_radius),
        z_min=quantize(ground),
        z_max=quantize(ground + trunk_height),
    )
    canopy = dict(
        kind="cylinder",
        center=[x, y],
        radius=quantize(canopy_radius),
        z_min=trunk["z_max"],
        z_max=quantize(trunk["z_max"] + canopy_height),
    )
    scene["trees"].append(
        dict(id=tree_id, position=[x, y, quantize(ground)], trunk=trunk, canopy=canopy)
    )
    scene["targets"].append(
        dict(
            id="target-" + tree_id,
            tree_id=tree_id,
            geometry=copy.deepcopy(canopy),
            meaning=TARGET_MEANING,
        )
    )


def _layout_regular(
    rng: random.Random, p: Dict[str, Any]
) -> Tuple[Scene, Dict[str, Any]]:
    scene = regular_generate(p)
    return scene, dict(deterministic=True)


def _layout_jitter(
    rng: random.Random, p: Dict[str, Any]
) -> Tuple[Scene, Dict[str, Any]]:
    rows, cols = p["rows"], p["trees_per_row"]
    margin, reserve = p["plot_margin"], p["reserve"]
    width = 2 * margin + (rows - 1) * p["row_spacing"]
    height = 2 * margin + (cols - 1) * p["plant_spacing"]
    top = p["trunk_height"] + p["canopy_height_range"][1] + 3.0
    scene = _shell(width, height, p["ground_z"], reserve, top)
    used = set()
    for i in range(rows):
        for j in range(cols):
            base_x = margin + i * p["row_spacing"]
            base_y = margin + j * p["plant_spacing"]
            x = y = None
            for _ in range(40):
                x = quantize(base_x + rng.uniform(-p["jitter_xy"], p["jitter_xy"]))
                y = quantize(base_y + rng.uniform(-p["jitter_xy"], p["jitter_xy"]))
                if (x, y) not in used:
                    break
            else:
                raise SceneError(
                    f"抖动布局在 40 次尝试后仍产生重复位置 ({base_x:.3f}, {base_y:.3f})",
                    field="jitter_xy",
                )
            used.add((x, y))
            radius = rng.uniform(*p["canopy_radius_range"])
            canopy_height = rng.uniform(*p["canopy_height_range"])
            _add_tree(
                scene,
                f"tree-{i + 1:02}-{j + 1:02}",
                x,
                y,
                p["ground_z"],
                p["trunk_radius"],
                p["trunk_height"],
                radius,
                canopy_height,
            )
    return scene, dict(deterministic=False)


def _layout_clusters(
    rng: random.Random, p: Dict[str, Any]
) -> Tuple[Scene, Dict[str, Any]]:
    max_radius = p["canopy_radius_range"][1]
    left = p["margin"] + max_radius + p["cluster_radius"]
    width = 2 * left + (p["cluster_cols"] - 1) * p["cluster_spacing_x"]
    height = 2 * left + (p["cluster_rows"] - 1) * p["cluster_spacing_y"]
    top = p["trunk_height"] + p["canopy_height_range"][1] + 3.0
    scene = _shell(width, height, p["ground_z"], p["reserve"], top)
    plot = scene["plot"]
    placed: List[Tuple[float, float]] = []
    requested = 0
    missing = 0
    lo, hi = p["trees_per_cluster_range"]
    for ci in range(p["cluster_cols"]):
        for cj in range(p["cluster_rows"]):
            cx = left + ci * p["cluster_spacing_x"]
            cy = left + cj * p["cluster_spacing_y"]
            count = rng.randint(lo, hi)
            requested += count
            for k in range(count):
                found = False
                for _ in range(200):
                    angle = rng.uniform(0.0, 2.0 * math.pi)
                    radius = math.sqrt(rng.random()) * p["cluster_radius"]
                    x = quantize(cx + radius * math.cos(angle))
                    y = quantize(cy + radius * math.sin(angle))
                    if any(
                        math.dist((x, y), other) < p["min_tree_distance"]
                        for other in placed
                    ):
                        continue
                    if not disk_in_polygon([x, y], max_radius, plot):
                        continue
                    found = True
                    break
                if not found:
                    raise SceneError(
                        f"簇 ({ci + 1}, {cj + 1}) 第 {k + 1} 棵树在 200 次尝试内无法满足最小树距与地块约束；请减小树木数量或簇半径",
                        field="trees_per_cluster_range",
                    )
                if rng.random() < p["missing_prob"]:
                    missing += 1
                    continue
                placed.append((x, y))
                canopy_radius = rng.uniform(*p["canopy_radius_range"])
                canopy_height = rng.uniform(*p["canopy_height_range"])
                _add_tree(
                    scene,
                    f"tree-{len(placed):03}",
                    x,
                    y,
                    p["ground_z"],
                    p["trunk_radius"],
                    p["trunk_height"],
                    canopy_radius,
                    canopy_height,
                )
    if not placed:
        raise SceneError("簇状布局丢失了全部树木；请降低 missing_prob", field="missing_prob")
    return scene, dict(
        deterministic=False,
        requested_trees=requested,
        missing_trees=missing,
        actual_trees=len(placed),
    )


def _layout_size_mix(
    rng: random.Random, p: Dict[str, Any]
) -> Tuple[Scene, Dict[str, Any]]:
    rows, cols = p["rows"], p["trees_per_row"]
    margin = p["plot_margin"]
    width = 2 * margin + (rows - 1) * p["row_spacing"]
    height = 2 * margin + (cols - 1) * p["plant_spacing"]
    top = p["trunk_height"] + max(cls["height"][1] for cls in p["classes"]) + 3.0
    scene = _shell(width, height, p["ground_z"], p["reserve"], top)
    counts = {cls["name"]: 0 for cls in p["classes"]}
    for i in range(rows):
        for j in range(cols):
            draw = rng.random()
            cumulative = 0.0
            chosen = p["classes"][-1]
            for cls in p["classes"]:
                cumulative += cls["p"]
                if draw <= cumulative + 1e-12:
                    chosen = cls
                    break
            radius = rng.uniform(*chosen["radius"])
            canopy_height = rng.uniform(*chosen["height"])
            counts[chosen["name"]] += 1
            _add_tree(
                scene,
                f"tree-{i + 1:02}-{j + 1:02}",
                margin + i * p["row_spacing"],
                margin + j * p["plant_spacing"],
                p["ground_z"],
                p["trunk_radius"],
                p["trunk_height"],
                radius,
                canopy_height,
            )
    return scene, dict(deterministic=False, class_counts=counts)


def _target_boxes(scene: Scene) -> List[Dict[str, Any]]:
    boxes = []
    for t in scene["targets"]:
        g = t["geometry"]
        x, y = g["center"]
        r = g["radius"]
        boxes.append(
            dict(
                id=t["id"],
                min=[x - r, y - r, g["z_min"]],
                max=[x + r, y + r, g["z_max"]],
            )
        )
    return boxes


def _zone_box(zone: Dict[str, Any]) -> Dict[str, Any]:
    xs = [v[0] for v in zone["footprint"]["vertices"]]
    ys = [v[1] for v in zone["footprint"]["vertices"]]
    return dict(
        min=[min(xs), min(ys), zone["z_min"]],
        max=[max(xs), max(ys), zone["z_max"]],
    )


def _launch_xy_hits(scene: Scene, low: List[float], high: List[float]) -> bool:
    return any(
        low[0] <= p["position"][0] <= high[0]
        and low[1] <= p["position"][1] <= high[1]
        for p in scene["launch_points"]
    )


def _launch_box_hits(scene: Scene, box: Dict[str, Any]) -> bool:
    return any(point_in_box(p["position"], box) for p in scene["launch_points"])


def _decorate(
    scene: Scene, rng: random.Random, p: Dict[str, Any]
) -> Dict[str, Any]:
    ground = scene["terrain"]["height"]
    extent = scene["extent"]
    plot = scene["plot"]
    allow_inside = p["allow_inside_plot"]
    target_boxes = _target_boxes(scene)
    used_ids = {
        o["id"]
        for key in ("obstacles", "no_fly_zones", "no_spray_zones")
        for o in scene[key]
    }
    occupied_boxes = [_zone_box(o) if o["kind"] != "box" else o for key in ("obstacles", "no_fly_zones", "no_spray_zones") for o in scene[key]]
    occupied_boxes.extend(target_boxes)
    attempts = 0
    inside_plot = 0

    def next_id(prefix: str) -> str:
        index = 1
        while f"{prefix}-{index:02}" in used_ids:
            index += 1
        uid = f"{prefix}-{index:02}"
        used_ids.add(uid)
        return uid

    def sample_center(size_x: float, size_y: float):
        x_low = extent["min"][0] + size_x / 2.0
        x_high = extent["max"][0] - size_x / 2.0
        y_low = extent["min"][1] + size_y / 2.0
        y_high = extent["max"][1] - size_y / 2.0
        if x_low >= x_high or y_low >= y_high:
            raise SceneError("外圈空间不足以放置装饰对象；请增大 reserve 或减小尺寸", field="reserve")
        return rng.uniform(x_low, x_high), rng.uniform(y_low, y_high)

    def footprint_overlaps_plot(low, high) -> bool:
        return rectangle_overlaps_polygon(low, high, plot)

    # Obstacles from the preset library.
    presets = preset_names()
    for _ in range(p["obstacle_count"]):
        preset = presets[rng.randrange(len(presets))]
        base_x, base_y, _base_z = PRESETS[preset]["size"]
        target_long = rng.uniform(*p["obstacle_size_range"])
        scale = target_long / max(base_x, base_y)
        size_x = quantize(base_x * scale)
        size_y = quantize(base_y * scale)
        size_z = quantize(rng.uniform(*p["obstacle_height_range"]))
        placed = False
        for _ in range(200):
            attempts += 1
            cx, cy = sample_center(size_x, size_y)
            low = [quantize(cx - size_x / 2.0), quantize(cy - size_y / 2.0)]
            high = [quantize(cx + size_x / 2.0), quantize(cy + size_y / 2.0)]
            box = dict(
                id=next_id("obstacle"),
                kind="box",
                min=[low[0], low[1], ground],
                max=[high[0], high[1], quantize(ground + size_z)],
                preset=preset,
            )
            used_ids.discard(box["id"])
            if not allow_inside and footprint_overlaps_plot(low, high):
                continue
            if _launch_box_hits(scene, box):
                continue
            if any(boxes_overlap(box, other) for other in occupied_boxes):
                continue
            if allow_inside and footprint_overlaps_plot(low, high):
                inside_plot += 1
            box["id"] = next_id("obstacle")
            scene["obstacles"].append(box)
            occupied_boxes.append(box)
            placed = True
            break
        if not placed:
            raise SceneError(
                f"第 {len(scene['obstacles']) + 1} 个随机障碍在 200 次采样内无法放置；请减少数量、增大 reserve 或允许地块内放置",
                field="obstacle_count",
            )

    def place_zone(key: str, count: int, prefix: str, offsets: List[float]) -> None:
        nonlocal attempts, inside_plot
        for _ in range(count):
            size_x = quantize(rng.uniform(*p["zone_size_range"]))
            size_y = quantize(rng.uniform(*p["zone_size_range"]))
            placed = False
            for _ in range(200):
                attempts += 1
                cx, cy = sample_center(size_x, size_y)
                low = [quantize(cx - size_x / 2.0), quantize(cy - size_y / 2.0)]
                high = [quantize(cx + size_x / 2.0), quantize(cy + size_y / 2.0)]
                zone = dict(
                    id=next_id(prefix),
                    kind="polygon_prism",
                    footprint=rectangle_footprint([cx, cy], size_x, size_y),
                    z_min=quantize(ground + offsets[0]),
                    z_max=quantize(ground + offsets[1]),
                )
                used_ids.discard(zone["id"])
                if not allow_inside and footprint_overlaps_plot(low, high):
                    continue
                if _launch_xy_hits(scene, low, high):
                    continue
                zone_box = _zone_box(zone)
                if any(boxes_overlap(zone_box, other) for other in occupied_boxes):
                    continue
                if allow_inside and footprint_overlaps_plot(low, high):
                    inside_plot += 1
                zone["id"] = next_id(prefix)
                scene[key].append(zone)
                occupied_boxes.append(zone_box)
                placed = True
                break
            if not placed:
                raise SceneError(
                    f"第 {len(scene[key]) + 1} 个随机区域在 200 次采样内无法放置；请减少数量、增大 reserve 或允许地块内放置",
                    field="no_fly_count" if key == "no_fly_zones" else "no_spray_count",
                )

    place_zone("no_fly_zones", p["no_fly_count"], "no-fly", p["no_fly_z_offset_range"])
    place_zone("no_spray_zones", p["no_spray_count"], "no-spray", p["no_spray_z_offset_range"])
    return dict(placement_attempts=attempts, inside_plot=inside_plot)


def _layout_random_obstacles(
    rng: random.Random, p: Dict[str, Any]
) -> Tuple[Scene, Dict[str, Any]]:
    base_style = p["base_style"]
    scene, info = _LAYOUTS[base_style](rng, p["base_params"])
    info = dict(info)
    info.update(_decorate(scene, rng, p))
    return scene, info


_LAYOUTS = {
    "regular": _layout_regular,
    "jitter_rows": _layout_jitter,
    "clusters_gaps": _layout_clusters,
    "size_mix": _layout_size_mix,
    "random_obstacles_zones": _layout_random_obstacles,
}


def build(
    style: str, seed: int, params: Optional[Dict[str, Any]] = None
) -> Tuple[Scene, Dict[str, Any]]:
    """Build, validate and report one random scene; deterministic for a seed."""
    if type(seed) is not int:
        raise SceneError(f"seed = {seed!r}：必须是整数", field="seed")
    style = canonical_style(style)
    p = _normalize(style, params)
    rng = random.Random(seed)
    scene, info = _LAYOUTS[style](rng, p)
    scene["source"] = dict(
        kind="random_orchard",
        generator="scene/random_map.py",
        generator_version=GENERATOR_VERSION,
        style=style,
        seed=seed,
        parameters=copy.deepcopy(p),
    )
    warnings = validate_scene(scene)
    if info.get("inside_plot"):
        warnings.append(
            f"{info['inside_plot']} 个随机障碍/区域位于作业地块内，"
            "固定条带规划可能失败。"
        )
    report = dict(
        style=style,
        seed=seed,
        generator_version=GENERATOR_VERSION,
        parameters=copy.deepcopy(p),
        counts=dict(
            trees=len(scene["trees"]),
            targets=len(scene["targets"]),
            obstacles=len(scene["obstacles"]),
            no_fly_zones=len(scene["no_fly_zones"]),
            no_spray_zones=len(scene["no_spray_zones"]),
        ),
        deterministic=style == "regular",
        attempts=1,
        warnings=warnings,
        reachability=dict(
            checked=False,
            status="not_checked",
            reason="未启用可达性检查",
            unreachable_targets=[],
        ),
        info=info,
    )
    return scene, report


def generate(
    style: str, seed: int, params: Optional[Dict[str, Any]] = None
) -> Scene:
    """Convenience wrapper for callers that only need the scene."""
    return build(style, seed, params)[0]
