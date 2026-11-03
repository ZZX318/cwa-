"""Launch-point resolution with an explicit compatibility fallback.

L1 keeps the planner unchanged: callers may use ``resolve`` for previews and
validation, while the planner still takes the sorted first point.  When no
point has an explicit ``role`` and there are no ``launch_assignments``, this
module returns exactly that old behaviour (first sorted point, start == end).
"""

from typing import Any, Dict, List

ROLES = ("both", "start", "return")


def role_of(point: Dict[str, Any]) -> str:
    role = point.get("role", "both")
    if role not in ROLES:
        raise ValueError(f"起降点 {point.get('id')!r} 的 role {role!r} 无效")
    return role


def _sorted_points(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    points = scene.get("launch_points") or []
    if not points:
        raise ValueError("场景至少需要一个起降点")
    return sorted(points, key=lambda p: tuple(p["position"]))


def _by_id(scene: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p["id"]: p for p in scene.get("launch_points") or []}


def _result(start, end, explicit):
    return dict(
        start=start,
        end=end,
        start_id=start["id"],
        end_id=end["id"],
        explicit=bool(explicit),
    )


def resolve(scene: Dict[str, Any], uav: int = 1) -> Dict[str, Any]:
    """Resolve one UAV's start/end point, or raise ValueError with the reason."""
    points = scene.get("launch_points") or []
    if not points:
        raise ValueError("场景至少需要一个起降点")
    assignments = scene.get("launch_assignments") or []
    explicit_roles = any("role" in p for p in points)
    if not assignments:
        if not explicit_roles:
            first = _sorted_points(scene)[0]
            return _result(first, first, False)
        starts = [p for p in _sorted_points(scene) if role_of(p) in ("both", "start")]
        ends = [p for p in _sorted_points(scene) if role_of(p) in ("both", "return")]
        if not starts:
            raise ValueError("显式 role 配置缺少可作起点的起降点")
        if not ends:
            raise ValueError("显式 role 配置缺少可作终点的起降点")
        return _result(starts[0], ends[0], True)
    matches = [a for a in assignments if a.get("uav") == uav]
    if not matches:
        raise ValueError(f"缺少 UAV {uav} 的起降点分配")
    assignment = matches[0]
    lookup = _by_id(scene)
    start = lookup.get(assignment.get("start"))
    end = lookup.get(assignment.get("end"))
    if start is None:
        raise ValueError(f"UAV {uav} 的起点 {assignment.get('start')!r} 不存在")
    if end is None:
        raise ValueError(f"UAV {uav} 的终点 {assignment.get('end')!r} 不存在")
    if role_of(start) not in ("both", "start"):
        raise ValueError(f"起降点 {start['id']!r} 的 role 不能作为起点")
    if role_of(end) not in ("both", "return"):
        raise ValueError(f"起降点 {end['id']!r} 的 role 不能作为终点")
    return _result(start, end, True)


def resolve_all(scene: Dict[str, Any], uavs: int) -> List[Dict[str, Any]]:
    if type(uavs) is not int or uavs < 1:
        raise ValueError("uavs 必须是正整数")
    return [resolve(scene, uav) for uav in range(1, uavs + 1)]
