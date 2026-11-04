"""A 小试独立评价器（不调用 planning/ 中任何缓冲/外扩函数）。

输入：原坐标系下的原始场景 scene（含原始禁喷区 Z）、已映射回原坐标系的计划航段 segments、
      缓冲距离 d、风向 wd（风的来向，弧度；上风单位向量 u=(cos wd, sin wd)）、喷幅 w、速度 v。
自算缓冲集：对园外禁喷区（足迹有任一顶点不在地块内）F_z = conv(Z ∪ (Z + d·u)) = Z ⊕ [0, d·u]；
            园内岛状区按本轮设计不扩（F_z = Z）。F = ∪ F_z。
栅格（cell 中心采样）面积：
  C = 全部树冠投影圆盘之并（scene["targets"] 的 geometry 圆）
  P = 每条喷洒段沿段向两侧各 w/2 展开的矩形之并（不在段端外延）
  A_excluded = |C ∩ F|（只报告）
  A_extra    = |(C \\ F) \\ P|（主指标）
几何违规：喷洒段沿程每 0.1 m 取中心线与两侧喷幅边缘（内缩 1e-6）三点，落在 F 内部（内缩 1e-7）的点数。
切带：与喷洒段首尾相接、共线同向、非喷洒、且其喷幅矩形与 F 正面积相交的航段 = 一个关喷切带；
      对应的 (喷洒段, 端) 是一个切带边界。
阀门滞后 τ（假设值）：每个切带边界处，把喷洒段在喷洒一侧缩短 τ·v（早关+晚开），重算 P 与 A_extra。
时间：用 planning.wind.segment_time（风模型，非缓冲函数）在原坐标系、原风向下逐段重算。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planning.wind import segment_time  # noqa: E402  风时间模型，与缓冲无关


# ---------- 纯几何 ----------
def _in_poly_xy(px, py, poly):
    """向量化射线法（边界不保证），poly: [[x,y],...]。"""
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        cond = (y1 > py) != (y2 > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (py - y1) / (y2 - y1) + x1
        inside ^= cond & (px < xint)
    return inside


def _point_in_poly(p, poly):
    return bool(_in_poly_xy(np.array([p[0]]), np.array([p[1]]), poly)[0])


def _hull(points):
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 1e-12:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cr(up[-2], up[-1], p) <= 1e-12:
            up.pop()
        up.append(p)
    return [list(p) for p in lo[:-1] + up[:-1]]


def _inside_strict(px, py, convex_ccw, tol=1e-7):
    """凸多边形（逆时针）严格内部：到每条边的有向距离 > tol。"""
    ok = np.ones(px.shape, dtype=bool)
    n = len(convex_ccw)
    for i in range(n):
        a = convex_ccw[i]
        b = convex_ccw[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey)
        dist = (ex * (py - a[1]) - ey * (px - a[0])) / L
        ok &= dist > tol
    return ok


def zone_is_exterior(zone, plot_vs):
    return any(not _point_in_poly(v, plot_vs) for v in zone["footprint"]["vertices"])


def buffer_set(scene, d, wd):
    """返回 F 的多边形列表（每项 dict(id, vertices, swept)）。"""
    ux, uy = math.cos(wd), math.sin(wd)
    plot_vs = scene["plot"]["vertices"]
    out = []
    for z in scene.get("no_spray_zones") or []:
        vs = [[float(v[0]), float(v[1])] for v in z["footprint"]["vertices"]]
        if d > 0 and zone_is_exterior(z, plot_vs):
            hull = _hull(vs + [[x + d * ux, y + d * uy] for x, y in vs])
            if abs(_area(hull) - _area(_hull(vs))) < 1e-12 and d > 0:
                pass
            if abs(_area(_hull(vs)) - _area(vs)) > 1e-9:
                raise ValueError(f"禁喷区 {z['id']} 非凸，评价器不支持")
            out.append(dict(id=z["id"], vertices=hull, swept=True))
        else:
            out.append(dict(id=z["id"], vertices=_hull(vs), swept=False))
    return out


def _area(vs):
    return 0.5 * abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(vs, vs[1:] + vs[:1])))


# ---------- 栅格 ----------
class Raster:
    def __init__(self, scene, res):
        g = [t["geometry"] for t in scene["targets"]]
        x0 = min(t["center"][0] - t["radius"] for t in g) - 2 * res
        x1 = max(t["center"][0] + t["radius"] for t in g) + 2 * res
        y0 = min(t["center"][1] - t["radius"] for t in g) - 2 * res
        y1 = max(t["center"][1] + t["radius"] for t in g) + 2 * res
        self.res = res
        self.x0 = math.floor(x0 / res) * res
        self.y0 = math.floor(y0 / res) * res
        self.nx = int(math.ceil((x1 - self.x0) / res))
        self.ny = int(math.ceil((y1 - self.y0) / res))
        self.xc = self.x0 + (np.arange(self.nx) + 0.5) * res
        self.yc = self.y0 + (np.arange(self.ny) + 0.5) * res
        self.cell = res * res

    def _window(self, xa, xb, ya, yb):
        i0 = max(0, int(math.floor((xa - self.x0) / self.res)) - 1)
        i1 = min(self.nx, int(math.ceil((xb - self.x0) / self.res)) + 1)
        j0 = max(0, int(math.floor((ya - self.y0) / self.res)) - 1)
        j1 = min(self.ny, int(math.ceil((yb - self.y0) / self.res)) + 1)
        return i0, i1, j0, j1

    def empty(self):
        return np.zeros((self.ny, self.nx), dtype=bool)

    def discs(self, geoms):
        m = self.empty()
        for g in geoms:
            (cx, cy), r = g["center"], g["radius"]
            i0, i1, j0, j1 = self._window(cx - r, cx + r, cy - r, cy + r)
            if i0 >= i1 or j0 >= j1:
                continue
            X, Y = np.meshgrid(self.xc[i0:i1], self.yc[j0:j1])
            m[j0:j1, i0:i1] |= (X - cx) ** 2 + (Y - cy) ** 2 <= r * r
        return m

    def polys(self, polys):
        m = self.empty()
        for vs in polys:
            xs = [v[0] for v in vs]
            ys = [v[1] for v in vs]
            i0, i1, j0, j1 = self._window(min(xs), max(xs), min(ys), max(ys))
            if i0 >= i1 or j0 >= j1:
                continue
            X, Y = np.meshgrid(self.xc[i0:i1], self.yc[j0:j1])
            m[j0:j1, i0:i1] |= _in_poly_xy(X, Y, vs)
        return m

    def rects(self, rects, half):
        """rects: [(a_xy, b_xy)] 段两端点；展开宽度 2*half。"""
        m = self.empty()
        for a, b in rects:
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L <= 1e-12:
                continue
            tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx_, ny_ = -ty, tx
            cs = [
                (a[0] + nx_ * half, a[1] + ny_ * half), (a[0] - nx_ * half, a[1] - ny_ * half),
                (b[0] + nx_ * half, b[1] + ny_ * half), (b[0] - nx_ * half, b[1] - ny_ * half),
            ]
            i0, i1, j0, j1 = self._window(min(c[0] for c in cs), max(c[0] for c in cs),
                                          min(c[1] for c in cs), max(c[1] for c in cs))
            if i0 >= i1 or j0 >= j1:
                continue
            X, Y = np.meshgrid(self.xc[i0:i1], self.yc[j0:j1])
            s = (X - a[0]) * tx + (Y - a[1]) * ty
            t = (X - a[0]) * nx_ + (Y - a[1]) * ny_
            m[j0:j1, i0:i1] |= (s >= 0) & (s <= L) & (np.abs(t) <= half)
        return m


# ---------- 航段分析 ----------
def _collinear_same_dir(s1, s2, tol=1e-6):
    a, b = s1["start"], s1["end"]
    c, e = s2["start"], s2["end"]
    d1 = (b[0] - a[0], b[1] - a[1])
    d2 = (e[0] - c[0], e[1] - c[1])
    L1, L2 = math.hypot(*d1), math.hypot(*d2)
    if L1 < 1e-9 or L2 < 1e-9:
        return False
    if abs(a[2] - b[2]) > 1e-9 or abs(c[2] - e[2]) > 1e-9 or abs(a[2] - c[2]) > 1e-9:
        return False
    cr = d1[0] * d2[1] - d1[1] * d2[0]
    dot = d1[0] * d2[0] + d1[1] * d2[1]
    if abs(cr) > tol * L1 * L2 or dot <= 0:
        return False
    # 同一条直线：c 在 a-b 直线上
    cr2 = d1[0] * (c[1] - a[1]) - d1[1] * (c[0] - a[0])
    return abs(cr2) <= tol * L1


def _rect_hits_F(seg, half, F, step=0.1):
    a, b = seg["start"], seg["end"]
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx_, ny_ = -ty, tx
    n = max(2, int(math.ceil(L / step)))
    s = np.linspace(0, L, n + 1)
    pts_x, pts_y = [], []
    for off in np.linspace(-half, half, 9):
        pts_x.append(a[0] + tx * s + nx_ * off)
        pts_y.append(a[1] + ty * s + ny_ * off)
    px, py = np.concatenate(pts_x), np.concatenate(pts_y)
    return any(_inside_strict(px, py, _ccw(f["vertices"])).any() for f in F)


def _ccw(vs):
    s = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(vs, vs[1:] + vs[:1]))
    return vs if s > 0 else list(reversed(vs))


def cut_analysis(segments, half, F):
    """返回 (cut_segment_indices, boundaries[(spray_idx, 'start'|'end')])。"""
    cuts = set()
    bounds = []
    for i, s in enumerate(segments):
        if not s.get("spray"):
            continue
        for j, side in ((i - 1, "start"), (i + 1, "end")):
            if not (0 <= j < len(segments)):
                continue
            n = segments[j]
            if n.get("spray"):
                continue
            pair = (n, s) if side == "start" else (s, n)
            if not _collinear_same_dir(*pair):
                continue
            if F and _rect_hits_F(n, half, F):
                cuts.add(j)
                bounds.append((i, side))
    return sorted(cuts), bounds


def spray_samples(segments, half, step=0.1):
    xs, ys = [], []
    h = half - 1e-6
    for s in segments:
        if not s.get("spray"):
            continue
        a, b = s["start"], s["end"]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L <= 1e-12:
            continue
        tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx_, ny_ = -ty, tx
        n = max(1, int(math.ceil(L / step)))
        t = np.linspace(0, L, n + 1)
        for off in (-h, 0.0, h):
            xs.append(a[0] + tx * t + nx_ * off)
            ys.append(a[1] + ty * t + ny_ * off)
    if not xs:
        return np.zeros(0), np.zeros(0)
    return np.concatenate(xs), np.concatenate(ys)


def evaluate(scene, segments, d, wd, swath, speed, config, taus=(0.0, 0.5), resolutions=(0.1, 0.05)):
    half = swath / 2.0
    F = buffer_set(scene, d, wd)
    cut_idx, bounds = cut_analysis(segments, half, F)
    # τ 缩短后的喷洒矩形
    rect_sets = {}
    for tau in taus:
        shrink = tau * speed
        rs = []
        cut_start = {i for i, sd in bounds if sd == "start"}
        cut_end = {i for i, sd in bounds if sd == "end"}
        for i, s in enumerate(segments):
            if not s.get("spray"):
                continue
            a, b = list(s["start"][:2]), list(s["end"][:2])
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            s0 = shrink if i in cut_start else 0.0
            s1 = L - (shrink if i in cut_end else 0.0)
            if s1 - s0 <= 1e-12:
                continue
            rs.append(([a[0] + tx * s0, a[1] + ty * s0], [a[0] + tx * s1, a[1] + ty * s1]))
        rect_sets[tau] = rs
    out = dict(d=d, wd=wd, F=[dict(id=f["id"], swept=f["swept"], vertices=[[round(v, 6) for v in p] for p in f["vertices"]]) for f in F])
    per_res = {}
    for res in resolutions:
        R = Raster(scene, res)
        C = R.discs([t["geometry"] for t in scene["targets"]])
        Fm = R.polys([f["vertices"] for f in F]) if F else R.empty()
        row = dict(A_C=float(C.sum() * R.cell), A_excluded=float((C & Fm).sum() * R.cell))
        for tau, rs in rect_sets.items():
            P = R.rects(rs, half)
            row[f"A_extra_tau{tau:g}"] = float((C & ~Fm & ~P).sum() * R.cell)
        per_res[res] = row
    out["by_resolution"] = {f"{k:g}": v for k, v in per_res.items()}
    fine, coarse = per_res[min(resolutions)], per_res[max(resolutions)]
    conv = {}
    for k in fine:
        a, b = coarse[k], fine[k]
        conv[k] = dict(coarse=a, fine=b, abs_diff=abs(a - b), rel_diff=(abs(a - b) / abs(b)) if b else (0.0 if a == 0 else math.inf))
    out["convergence"] = conv
    out.update({k: v for k, v in fine.items()})
    # 违规
    px, py = spray_samples(segments, half)
    viol = 0
    for f in F:
        if len(px):
            viol += int(_inside_strict(px, py, _ccw(f["vertices"])).sum())
    out["violations"] = viol
    out["spray_samples"] = int(len(px))
    out["cut_segments"] = len(cut_idx)
    out["cut_boundaries"] = len(bounds)
    # 时间/路程（原坐标系、原风向）
    t_total = 0.0
    L_spray = L_cut = L_other = 0.0
    for i, s in enumerate(segments):
        L = math.dist(s["start"], s["end"])
        t_total += segment_time(s["start"], s["end"], s["speed"], config, version="1.2")
        if s.get("spray"):
            L_spray += L
        elif i in set(cut_idx):
            L_cut += L
        else:
            L_other += L
    out.update(total_time=t_total, path_length=L_spray + L_cut + L_other, path_spray=L_spray,
               path_cut_off=L_cut, path_transit_other=L_other)
    return out
