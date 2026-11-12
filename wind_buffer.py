"""Explicit upwind footprint exclusion; no empirical wind-to-distance law."""
import copy
import math
from scene import validate_scene, summary, encode
from scene.geometry import polygon_bounds


def apply_buffer(scene, sources, distance, wind_speed, wind_direction):
    validate_scene(scene)
    for name, value in (("distance", distance), ("wind_speed", wind_speed), ("wind_direction", wind_direction)):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(name + " 必须为有限非负数")
    if not isinstance(sources, list) or not sources:
        raise ValueError("请提供至少一个敏感区（polygon_prism 数组）")
    out = copy.deepcopy(scene)
    old = out.get("wind_buffer", {})
    previous = old.get("generated_zones", [])
    # Only replace exactly the geometry that this module previously generated.
    for zone in previous:
        actual = [z for z in out["no_spray_zones"] if z["id"] == zone["id"]]
        if actual != [zone]:
            raise ValueError("自动缓冲区已被编辑或删除，请重新加载原场景后生成，避免覆盖手动修改")
    ids = {z["id"] for z in previous}
    out["no_spray_zones"] = [z for z in out["no_spray_zones"] if z["id"] not in ids]
    probe = copy.deepcopy(out)
    probe["no_spray_zones"] += copy.deepcopy(sources)
    validate_scene(probe)
    # The input is a distance from the spray footprint edge, not its centre.
    # Come-from vector points toward potential upwind release positions.
    effective = distance if wind_speed > 0 else 0.0
    dx, dy = effective * math.cos(wind_direction), effective * math.sin(wind_direction)
    dx = 0.0 if abs(dx) < 1e-10 else dx
    dy = 0.0 if abs(dy) < 1e-10 else dy
    generated = []
    for i, source in enumerate(sources):
        b = polygon_bounds(source["footprint"])
        x0, y0 = b["min"]
        x1, y1 = b["max"]
        x0, x1 = x0 + min(0, dx), x1 + max(0, dx)
        y0, y1 = y0 + min(0, dy), y1 + max(0, dy)
        # Do not silently truncate protection to the current extent.
        zone = dict(id="wind-buffer-" + source["id"], kind="polygon_prism",
                    footprint=dict(kind="polygon", vertices=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]),
                    z_min=source["z_min"], z_max=source["z_max"])
        generated.append(zone)
    out["no_spray_zones"] += generated
    out["wind_buffer"] = dict(version=1, sources=copy.deepcopy(sources), generated_zones=copy.deepcopy(generated),
        distance=distance, effective_distance=effective, wind_speed=wind_speed, wind_direction=wind_direction,
        model="upwind-sweep-conservative-aabb", distance_reference="spray-footprint-edge",
        note="输入距离为实验假设；静风只保留原区包围盒；斜风/非矩形采用扫掠包围盒，非真实漂移预测。")
    validate_scene(out)
    return dict(scene=out, summary=summary(out), serialized=encode(out), report=out["wind_buffer"])


def check_buffer_wind(scene, config):
    b = scene.get("wind_buffer")
    if b and any(abs(config[k] - b[k]) > 1e-9 for k in ("wind_speed", "wind_direction")):
        raise ValueError("风参数已改变，请先重新生成敏感区缓冲，再规划或比较")

    if b:
        for zone in b["generated_zones"]:
            if [z for z in scene["no_spray_zones"] if z["id"] == zone["id"]] != [zone]:
                raise ValueError("自动缓冲区被编辑，请重新加载原场景并生成缓冲")
