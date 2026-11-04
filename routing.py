"""Explainable clearance-aware grid routing baseline for transition segments."""
import heapq, math
from planning import fingerprint
from scene.geometry import polygon_bounds


def _blocked(scene, p, clearance):
    """True when ``p`` lies inside an obstacle, tree, or no-fly box inflated by clearance."""
    x, y, z = p
    boxes = []
    for t in scene.get("trees", []):
        for kind in ("trunk", "canopy"):
            g = t[kind]
            cx, cy = g["center"]
            r = g["radius"]
            boxes.append(([cx - r, cy - r, g["z_min"]], [cx + r, cy + r, g["z_max"]]))
    boxes += [(o["min"], o["max"]) for o in scene.get("obstacles", [])]
    for o in scene.get("no_fly_zones", []):
        b = polygon_bounds(o["footprint"])
        boxes.append((b["min"] + [o["z_min"]], b["max"] + [o["z_max"]]))
    for lo, hi in boxes:
        if (
            lo[0] - clearance <= x <= hi[0] + clearance
            and lo[1] - clearance <= y <= hi[1] + clearance
            and lo[2] - clearance <= z <= hi[2] + clearance
        ):
            return True
    return False


def route(scene, start, goal, step=1.0, clearance=.5):
    if step <= 0:
        raise ValueError("step 必须为正数")
    z = max(start[2], goal[2])
    lo, hi = scene["extent"]["min"], scene["extent"]["max"]

    def key(p):
        return (round(p[0] / step), round(p[1] / step))

    s, g = key(start), key(goal)
    openq = [(0, s)]
    came = {}
    cost = {s: 0}
    nodes = 0
    while openq:
        _, u = heapq.heappop(openq)
        nodes += 1
        if u == g:
            path = []
            while u in came:
                path.append([u[0] * step, u[1] * step, z])
                u = came[u]
            path.append([start[0], start[1], z])
            path.reverse()
            path[-1] = [goal[0], goal[1], z]
            return {
                "status": "success",
                "path": path,
                "length": sum(math.dist(a, b) for a, b in zip(path, path[1:])),
                "expanded": nodes,
                "scene_hash": fingerprint(scene),
            }
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            v = (u[0] + dx, u[1] + dy)
            p = [v[0] * step, v[1] * step, z]
            if not (lo[0] <= p[0] <= hi[0] and lo[1] <= p[1] <= hi[1]) or _blocked(
                scene, p, clearance
            ):
                continue
            ng = cost[u] + step
            if ng < cost.get(v, 1e99):
                cost[v] = ng
                came[v] = u
                heapq.heappush(
                    openq, (ng + math.hypot(v[0] - g[0], v[1] - g[1]) * step, v)
                )
    return {
        "status": "failed",
        "reason": "离散搜索未找到满足净空的路径",
        "expanded": nodes,
        "scene_hash": fingerprint(scene),
    }
