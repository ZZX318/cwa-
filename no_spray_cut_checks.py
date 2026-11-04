"""禁喷切割专项验收：关喷头飞越、目标关联、失败口径与无区回归。

运行：python3 no_spray_cut_checks.py
所有几何判定与 planning.safety / planning.footprint 保持同一口径。
"""

import copy
import math

from scene import generate
from scene.geometry import polygon_bounds
from planning import generate_plan, check
from planning.footprint import rectangle as strip_rectangle, boxes_touch
from planning.planner import _split_lane
from planning.model import configuration


def _zone(zone_id, x0, y0, x1, y1, z_max=10.0):
    return dict(
        id=zone_id,
        kind="polygon_prism",
        footprint=dict(
            kind="polygon",
            vertices=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        ),
        z_min=0,
        z_max=z_max,
    )


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def run() -> int:
    base = generate()
    c = configuration({})

    # 1. 无禁喷区：切割函数输出单段且几何与原 lane 完全一致（字节级回归）。
    for lane in generate_plan_lanes(base):
        parts = _split_lane(base, lane, c)
        _assert(len(parts) == 1, "无区 lane 必须只输出一段")
        only = parts[0]
        _assert(only["type"] == "spray" and only["spray"], "无区输出必须为喷洒段")
        _assert(only["start"] == lane["start"] and only["end"] == lane["end"], "无区几何被改变")
        _assert(only["target_ids"] == lane["target_ids"], "无区目标关联被改变")
    plain = generate_plan(base)
    _assert(plain["status"] == "success", plain["reason"])

    # 2. 区落在单个 lane 条目内部：单元级 spray-transit-spray，端到端足迹不触区。
    target_lane = next(
        lane
        for lane in generate_plan_lanes(base)
        if abs(lane["start"][0] - 2.0) < 1e-8
        and abs(lane["start"][1] - 9.0) < 1e-8
    )
    mid = copy.deepcopy(base)
    mid["no_spray_zones"] = [_zone("ns-mid", 1.5, 10.0, 2.5, 11.0)]
    cut_parts = _split_lane(mid, target_lane, c)
    kinds = [s["type"] for s in cut_parts]
    _assert(kinds == ["spray", "transit", "spray"], f"lane 切割结构错误：{kinds}")
    _assert(not cut_parts[1]["spray"], "穿越段必须关喷头")
    _assert(
        cut_parts[0]["start"] == target_lane["start"]
        and cut_parts[-1]["end"] == target_lane["end"],
        "切割未完整覆盖原 lane",
    )
    mid_plan = generate_plan(mid)
    _assert(mid_plan["status"] == "success", mid_plan["reason"])
    check(mid, mid_plan)
    for seg in mid_plan["segments"]:
        if seg["spray"]:
            strip = strip_rectangle(seg, c["swath"])
            for zone in mid["no_spray_zones"]:
                b = polygon_bounds(zone["footprint"])
                _assert(
                    not boxes_touch(strip, (b["min"], b["max"])),
                    "喷洒足迹仍触及禁喷区",
                )
    associated = {tid for s in mid_plan["segments"] for tid in s["target_ids"]}
    _assert(associated == {t["id"] for t in base["targets"]}, "有目标丢失喷洒关联")

    # 3. 两个重叠禁喷区合并为一个穿越段（单元级）。
    merged_scene = copy.deepcopy(base)
    merged_scene["no_spray_zones"] = [
        _zone("ns-a", 1.5, 10.0, 2.5, 10.8),
        _zone("ns-b", 1.5, 10.5, 2.5, 11.5),
    ]
    merged_parts = _split_lane(merged_scene, target_lane, c)
    transit_count = sum(1 for s in merged_parts if s["type"] == "transit")
    _assert(transit_count == 1, f"重叠区未合并，穿越段数={transit_count}")
    merged_plan = generate_plan(merged_scene)
    _assert(merged_plan["status"] == "success", merged_plan["reason"])
    check(merged_scene, merged_plan)

    # 4. 禁喷区完全罩住目标：规划失败且原因指向任务完整性。
    covered = copy.deepcopy(base)
    covered["no_spray_zones"] = [_zone("ns-cover", 0.5, 0.5, 4.5, 4.5)]
    covered_plan = generate_plan(covered)
    _assert(covered_plan["status"] == "failed", "罩住目标不应成功")
    _assert(
        "缺少有效喷洒关联" in covered_plan["reason"],
        f"失败原因错误：{covered_plan['reason']}",
    )
    _assert(covered_plan["segments"] == [], "失败计划不得携带航段")

    # 5. search 转场模式下切割同样成立，独立安全检查通过。
    searched = generate_plan(mid, {"transition_mode": "search"})
    _assert(searched["status"] == "success", searched["reason"])
    check(mid, searched)
    _assert(
        searched["method"] == "fixed-y-boustrophedon+clearance-search",
        "搜索模式方法标记错误",
    )

    # 6. 反向 lane（第二条 lane）切割后方向保持、航段连续。
    reverse_scene = copy.deepcopy(base)
    reverse_scene["no_spray_zones"] = [_zone("ns-rev", 3.5, 8.0, 5.0, 12.0)]
    reverse_plan = generate_plan(reverse_scene)
    _assert(reverse_plan["status"] == "success", reverse_plan["reason"])
    check(reverse_scene, reverse_plan)
    previous = None
    for seg in reverse_plan["segments"]:
        if previous is not None:
            _assert(math.dist(previous, seg["start"]) <= 1e-8, "航段不连续")
        previous = seg["end"]

    print("通过 · 禁喷切割：无区回归/中间切割/多区合并/罩目标失败/搜索模式/反向连续")
    return 0


def generate_plan_lanes(scene):
    from planning.planner import fixed_y_lanes
    return fixed_y_lanes(scene, {})["lanes"]


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:
        print("失败 · 禁喷切割专项：", error)
        raise SystemExit(1)
