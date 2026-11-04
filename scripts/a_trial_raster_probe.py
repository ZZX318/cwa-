r"""A_extra 栅格不单调的取证（只读已存几何，不跑规划）。

对给定行（默认 seed 1, U=2, 0°/offset 0, 数据 commit 2ff2df1）：
  1. 用 a_trial_eval.evaluate 原样复算 0.2/0.1/0.05 m，确认与 CSV 一致（排除“复算口径不同”）；
  2. 栅格原点亚格平移扫描：x、y 各平移 {0, 1/4, 1/2, 3/4}·res（res = 0.2/0.1/0.05/0.025），看 A_extra 随相位的摆动；
  3. 更细栅格 0.025 / 0.0125 m；
  4. 精确面积（半解析）：0° 航向下 F 和喷洒矩形都是轴对齐矩形，按 x 积分 f(x) = |∪圆盘弦 \ ∪(F∪P) 的 y 区间|，
     在所有圆盘 x 端点和矩形 x 边上断开，各段用 Gauss–Legendre 复合求积，两种面板宽度互相核对；
  5. 相位模型：栅格只按格心判内外，一条未被覆盖区域的竖直边界 x=e 在栅格上等效于“最近的格边”，
     预测 ΔA(res) ≈ (e_eff(res) − e)·L_e（L_e 为该线上未覆盖冠层弦长），与实测差比较。
用法：python scripts/a_trial_raster_probe.py [--seed 1 --U 2 --key main_U2_h0_o0 --sha 2ff2df1]
输出：results/a_trial_raster_probe_s{seed}_{key}_{sha}.json
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import argparse
import csv
import json
import math

import numpy as np

import a_trial_eval as ev
import a_trial_heading as H
from planning import configuration


def make_shifted_raster(sx, sy):
    class R(ev.Raster):
        def __init__(self, scene, res):
            super().__init__(scene, res)
            self.x0 -= sx * res
            self.y0 -= sy * res
            self.nx += 1
            self.ny += 1
            self.xc = self.x0 + (np.arange(self.nx) + 0.5) * res
            self.yc = self.y0 + (np.arange(self.ny) + 0.5) * res
    return R


def rect_sets(segments, F, half, speed, taus):
    """与 a_trial_eval.evaluate 内部相同的 τ 缩短喷洒矩形（逐行复刻，并在下方用栅格结果核对一致）。"""
    cut_idx, bounds = ev.cut_analysis(segments, half, F)
    out = {}
    cut_start = {i for i, sd in bounds if sd == "start"}
    cut_end = {i for i, sd in bounds if sd == "end"}
    for tau in taus:
        shrink = tau * speed
        rs = []
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
        out[tau] = rs
    return out


def axis_rects(rs, half):
    out = []
    for a, b in rs:
        if abs(a[0] - b[0]) < 1e-9:  # 竖直段
            out.append((a[0] - half, a[0] + half, min(a[1], b[1]), max(a[1], b[1])))
        elif abs(a[1] - b[1]) < 1e-9:
            out.append((min(a[0], b[0]), max(a[0], b[0]), a[1] - half, a[1] + half))
        else:
            raise ValueError("非轴对齐喷洒段，半解析精确面积不适用")
    return out


def _union_len(iv):
    iv = sorted(iv)
    tot, cur_lo, cur_hi = 0.0, None, None
    for lo, hi in iv:
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                tot += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        tot += cur_hi - cur_lo
    return tot


def _diff_len(A, B):
    """|∪A \\ ∪B|。"""
    return _union_len(A) - _inter_len(A, B)


def _merge(iv):
    iv = sorted(iv)
    m = []
    for lo, hi in iv:
        if m and lo <= m[-1][1]:
            m[-1][1] = max(m[-1][1], hi)
        else:
            m.append([lo, hi])
    return m


def _inter_len(A, B):
    A, B = _merge(A), _merge(B)
    i = j = 0
    t = 0.0
    while i < len(A) and j < len(B):
        lo, hi = max(A[i][0], B[j][0]), min(A[i][1], B[j][1])
        if hi > lo:
            t += hi - lo
        if A[i][1] < B[j][1]:
            i += 1
        else:
            j += 1
    return t


def fx(x, discs, rects):
    A = []
    for cx, cy, r in discs:
        dx = x - cx
        if abs(dx) < r:
            h = math.sqrt(r * r - dx * dx)
            A.append((cy - h, cy + h))
    if not A:
        return 0.0
    B = [(y0, y1) for x0, x1, y0, y1 in rects if x0 <= x <= x1]
    return _diff_len(A, B) if B else _union_len(A)


def exact_area(discs, rects, panel):
    brk = sorted({c - r for c, _, r in discs} | {c + r for c, _, r in discs} | {r[0] for r in rects} | {r[1] for r in rects})
    lo, hi = min(c - r for c, _, r in discs), max(c + r for c, _, r in discs)
    brk = [b for b in brk if lo <= b <= hi]
    gx, gw = np.polynomial.legendre.leggauss(6)
    tot = 0.0
    for a, b in zip(brk, brk[1:]):
        if b - a <= 0:
            continue
        n = max(1, int(math.ceil((b - a) / panel)))
        h = (b - a) / n
        for k in range(n):
            p0 = a + k * h
            for xg, wg in zip(gx, gw):
                tot += wg * h / 2 * fx(p0 + (xg + 1) * h / 2, discs, rects)
    return tot


def chord_uncovered(x, discs, rects):
    """竖直线 x 上、在 F∪P 之外的冠层弦长（用于相位模型）。"""
    return fx(x, discs, rects)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--U", type=float, default=2.0)
    ap.add_argument("--key", default="main_U2_h0_o0")
    ap.add_argument("--sha", default="2ff2df1")
    a = ap.parse_args()
    seed, U = a.seed, a.U
    geoms = json.loads((ROOT / f"results/a_trial_seed{seed}_{a.sha}.geom.json").read_text())
    segs = geoms[a.key]["segments"]
    scene = H.scene0(seed)
    d = H.TIERS[U]
    raw0 = {**H.JOB, "drift_mode": "sort", "wind_speed": U, "wind_direction": 0.0, "buffer_expand": 1.0}
    c0 = configuration(raw0)
    half = float(c0["swath"]) / 2
    # geom.json 未存 speed；只影响时间，不影响面积。为调用 evaluate 填配置航速
    segs = [dict(s_, speed=float(c0["speed"])) for s_ in segs]
    taus = (0.0, 0.5, 1.0)
    # CSV 原值
    variant, _, rest = a.key.partition("_U")
    csvrow = None
    for r in csv.DictReader(open(ROOT / f"results/a_trial_seed{seed}_{a.sha}.csv", encoding="utf8")):
        if f'{r["variant"]}_U{float(r["U"]):g}_h{int(float(r["heading"]))}_o{float(r["offset"]):g}' == a.key:
            csvrow = r
    out = dict(seed=seed, U=U, key=a.key, data_commit=a.sha, csv={t: float(csvrow[f"A_extra_tau{t:g}"]) for t in taus})
    # 1. 原样复算
    res0 = ev.evaluate(scene, segs, d, 0.0, float(c0["swath"]), float(c0["speed"]), dict(c0))
    out["reeval_by_resolution"] = res0["by_resolution"]
    out["reeval_matches_csv_0.05"] = all(abs(res0["by_resolution"]["0.05"][f"A_extra_tau{t:g}"] - out["csv"][t]) < 1e-9 for t in taus)
    # 2/3. 原点平移扫描 + 更细栅格
    sweep = {}
    orig = ev.Raster
    try:
        for res in (0.2, 0.1, 0.05, 0.025, 0.0125):
            fr = (0.0, 0.25, 0.5, 0.75) if res >= 0.025 else (0.0, 0.5)
            for sx in fr:
                for sy in (0.0, 0.5):
                    ev.Raster = make_shifted_raster(sx, sy)
                    r = ev.evaluate(scene, segs, d, 0.0, float(c0["swath"]), float(c0["speed"]), dict(c0), resolutions=(res,))
                    sweep[f"res={res:g} sx={sx:g} sy={sy:g}"] = {k: r["by_resolution"][f"{res:g}"][k] for k in ("A_C", "A_excluded", "A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")}
                    print(f"res={res:g} sx={sx:g} sy={sy:g}", sweep[f"res={res:g} sx={sx:g} sy={sy:g}"], flush=True)
    finally:
        ev.Raster = orig
    out["origin_sweep"] = sweep
    # 4. 精确面积
    F = ev.buffer_set(scene, d, 0.0)
    Frects = []
    for f in F:
        xs = [v[0] for v in f["vertices"]]
        ys = [v[1] for v in f["vertices"]]
        assert len({round(v, 9) for v in xs}) == 2 and len({round(v, 9) for v in ys}) == 2, "F 非轴对齐矩形"
        Frects.append((min(xs), max(xs), min(ys), max(ys)))
    discs = [(t["geometry"]["center"][0], t["geometry"]["center"][1], t["geometry"]["radius"]) for t in scene["targets"]]
    RS = rect_sets(segs, F, half, float(c0["speed"]), taus)
    exact = {}
    for t in taus:
        P = axis_rects(RS[t], half)
        e1 = exact_area(discs, Frects + P, 0.02)
        e2 = exact_area(discs, Frects + P, 0.005)
        exact[f"A_extra_tau{t:g}"] = dict(panel_0p02=e1, panel_0p005=e2, diff=abs(e1 - e2))
        print("exact", t, exact[f"A_extra_tau{t:g}"], flush=True)
    exact["A_C"] = exact_area(discs, [], 0.005)
    exact["A_excluded"] = exact["A_C"] - exact_area(discs, Frects, 0.005)
    out["exact"] = exact
    # 5. 相位模型：未覆盖区域的竖直边界 = F 与各喷洒矩形的 x 边中，两侧 f(x) 有跳变的
    P0 = axis_rects(RS[0.0], half)
    allr = Frects + P0
    edges = sorted({r[0] for r in allr} | {r[1] for r in allr})
    eps = 1e-6
    jumps = []
    for e in edges:
        l, rr = fx(e - eps, discs, allr), fx(e + eps, discs, allr)
        if abs(l - rr) > 1e-3:
            jumps.append(dict(x=e, f_left=l, f_right=rr, jump=rr - l))
    out["uncovered_vertical_edges_tau0"] = jumps
    pred = {}
    for res in (0.2, 0.1, 0.05, 0.025, 0.0125):
        R = ev.Raster(scene, res)
        tot = 0.0
        for j in jumps:
            # 格心 xc 被判“在矩形内”当且仅当 xc 落在边界哪一侧；等效边界 = 边界所在格的格边（取格心不越过的那一侧）
            i = math.floor((j["x"] - R.x0) / res)
            xc = R.x0 + (i + 0.5) * res
            e_eff = R.x0 + (i + 1) * res if xc < j["x"] else R.x0 + i * res
            # 跳变 >0：右侧未覆盖多 → 边界右移 Δ 使未覆盖面积减少 Δ·jump
            tot += -(e_eff - j["x"]) * j["jump"]
        pred[f"{res:g}"] = dict(pred_A_extra_tau0=exact["A_extra_tau0"]["panel_0p005"] + tot, pred_shift_term=tot)
    out["phase_model"] = pred
    p = ROOT / f"results/a_trial_raster_probe_s{seed}_{a.key}_{a.sha}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("csv", "reeval_by_resolution", "reeval_matches_csv_0.05", "exact", "uncovered_vertical_edges_tau0", "phase_model")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
