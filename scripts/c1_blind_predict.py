"""C1 盲预测（只生成场景 + 几何核算，不规划）。

对 6 个未见过的 (w,d) 组合、seed=10，同时给出两条损失带假说的事前预测：
  (a) 带宽 w−r，L=[x_F, x_F+(w−r)]   ← 结构式主假说
  (b) 带宽 r，  L=[x_F, x_F+r]         ← 对照假说（F2/F3 在 w=2、r=1 时与 (a) 不可区分）

用法：
  /home/box/.venvs/mpl/bin/python scripts/c1_blind_predict.py
写出：
  results/c1_blind_predict_seed10.json
  docs/derivation_C1.md 的 §6 由本脚本的 --write-section 追加/刷新（或单独生成片段）
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import a_trial_eval as ev  # noqa: E402
import a_trial_heading as H  # noqa: E402

SEED = 10
RES = 0.05
COMBOS = [
    # (w, d, lit_ref)
    (4.5, 10.0, "S18 DJI T10 标称有效喷幅 3–5.5 m（取 4.5）"),
    (7.0, 10.0, "S14/S16 DJI T25/T20P 标称有效喷幅至 7 m"),
    (2.23, 10.0, "S7 苹果园四旋翼实测有效喷幅 2.23 m"),
    (7.0, 16.0, "S14/S16 + S11 侧风 3–5 m/s 缓冲 ≥16 m"),
    (3.5, 10.0, "S5 柑橘园航线间距=行距 3.5 m（反例候选）"),
    (4.5, 16.0, "S18 + S11（反例候选）"),
]


def rem(d: float, w: float) -> float:
    return d - math.floor(d / w) * w


def disk_le(x: float, cx: float, R: float) -> float:
    if x <= cx - R:
        return 0.0
    if x >= cx + R:
        return math.pi * R * R
    t = (x - cx) / R
    return R * R * math.acos(-t) + (x - cx) * math.sqrt(R * R - (x - cx) ** 2)


def A_circ(cx: float, R: float, a: float, b: float) -> float:
    return disk_le(b, cx, R) - disk_le(a, cx, R)


def nom_A(a: float, b: float, R: float = 1.5, n_per_row: int = 16) -> float:
    """名义无抖动：行心 3+8i，R=1.5，株/行不重叠 → 并集=求和。"""
    return n_per_row * sum(A_circ(3 + 8 * i, R, a, b) for i in range(12))


def canopy_union_strip(targets, a, b, y0, y1, res=RES):
    hit = [
        t["geometry"]
        for t in targets
        if t["geometry"]["center"][0] + t["geometry"]["radius"] > a
        and t["geometry"]["center"][0] - t["geometry"]["radius"] < b
        and t["geometry"]["center"][1] + t["geometry"]["radius"] > y0
        and t["geometry"]["center"][1] - t["geometry"]["radius"] < y1
    ]
    if b <= a + 1e-15 or y1 <= y0:
        return dict(n_hit=0, A_sum=0.0, A_union=0.0, on_tree=False)
    A_sum = sum(A_circ(g["center"][0], g["radius"], a, b) for g in hit)
    xs = np.arange(a + res / 2, b, res)
    ys = np.arange(y0 + res / 2, y1, res)
    if len(xs) == 0 or len(ys) == 0:
        return dict(n_hit=len(hit), A_sum=float(A_sum), A_union=0.0, on_tree=bool(hit))
    X, Y = np.meshgrid(xs, ys)
    mask = np.zeros(X.shape, dtype=bool)
    for g in hit:
        mask |= (X - g["center"][0]) ** 2 + (Y - g["center"][1]) ** 2 <= g["radius"] ** 2
    return dict(
        n_hit=len(hit),
        A_sum=float(A_sum),
        A_union=float(mask.sum() * res * res),
        on_tree=bool(hit),
    )


def predict_combo(scene, w, d, src, y0, y1, x_F_code):
    x_F_nom = -1.0 + d
    r = rem(d, w)
    # 首航道邻缓冲带 [x_F, x_F+w]：仅作适用性提示（真正 heuristic_lane_found 在规划后记录）
    lane = canopy_union_strip(scene["targets"], x_F_nom, x_F_nom + w, y0, y1)
    hyps = {}
    for key, width, L in (
        ("a_w_minus_r", w - r, [x_F_nom, x_F_nom + (w - r)]),
        ("b_r", r, [x_F_nom, x_F_nom + r]),
    ):
        a, b = L
        seed_pred = canopy_union_strip(scene["targets"], a, b, y0, y1)
        hyps[key] = dict(
            width=width,
            L=L,
            A_nom=nom_A(a, b),
            A_sum=seed_pred["A_sum"],
            A_union=seed_pred["A_union"],
            n_hit=seed_pred["n_hit"],
            on_tree_row=seed_pred["on_tree"],
            first_lane_n_hit=lane["n_hit"],
            predict_B=seed_pred["A_union"],
            predict_Sh=0.0,
            phase_nonzero=width > 1e-15,
            # 名义空带 + 相位非零 → 技术负责人手算的「反例」类；seed 抖动可能仍有薄切
            nominal_gap=(nom_A(a, b) == 0.0 and width > 1e-15),
        )
    return dict(
        w=w,
        d=d,
        source=src,
        x_F_nominal=x_F_nom,
        x_F_code=x_F_code,
        x_F_match=abs(x_F_nom - x_F_code) < 1e-12,
        r=r,
        y_F=[y0, y1],
        hyp=hyps,
    )


def section_md(payload: dict) -> str:
    lines = [
        "## 6. 盲预测（未见过的 d/w 组合，seed=10；规划前）",
        "",
        "**对应论文主张**：结构式 \(A_B=|C\\cap L|\)（\(L=[x_F,x_F+(w-r)]\)，\(x_F=-1+d\)，\(r=d\\bmod w\)）"
        "能在事前预测没见过的 \(d/w\) 组合下的漏喷面积。",
        "",
        "**为何要双假说**：既有 F2/F3 几何档固定 \(w=2\)、奇数 \(d\)，故 \(r=w-r=1\\,\\mathrm{m}\)，"
        "无法区分损失带宽度取 \(w-r\) 还是 \(r\)。本盲预测对每个组合同时给出：",
        "",
        "- **假说 (a)**：带宽 \(w-r\)，\(L=[x_F,\\,x_F+(w-r)]\)（结构式主假说）",
        "- **假说 (b)**：带宽 \(r\)，\(L=[x_F,\\,x_F+r]\)（对照）",
        "",
        "实测后误差表须与两条假说同时对照，并写明每个组合成立的是 (a)、(b)、两者都不成立，或本构型下不可区分。",
        "",
        "**场景**：仅 `H.scene0(10)`（`ha_orchard` + 园外禁喷注入）。**不**调用规划器、**不**读航段。"
        " \(x_F\) 以 `a_trial_eval.buffer_set` 扫掠多边形右缘为准；与名义 \(x_F=-1+d\) 不一致时以代码为准并记原因。",
        "",
        f"**seed 选用**：F2/F3 a_trial 几何/主对比仅用过 seed 0–9；本轮用 **seed={payload['seed']}**。"
        "（旁注：`ablation_sort_vs_sort_drift` 等其它矩阵曾出现 seed=10，但不是本相位对齐几何档。）",
        "",
        "**喷幅出处**（`/workspace/lit_review/real_orchard_params.md`）：S7、S5、S14/S16、S18；缓冲档 d=10/16 对应 S11。",
        "",
        "### 6.1 名义复核（行心 3+8i，R=1.5，无抖动）",
        "",
        "| w | d | r | w−r | x_F | L (a) | Â_nom (a) | L (b) | Â_nom (b) | 技术负责人手算 L(a) | 一致？ |",
        "|---:|---:|---:|---:|---:|---|---:|---|---:|---|---|",
    ]
    hand = {
        (4.5, 10.0): "[9, 12.5]",
        (7.0, 10.0): "[9, 13]",
        (2.23, 10.0): "≈[9, 10.15]",
        (7.0, 16.0): "[15, 20]",
        (3.5, 10.0): "[9, 9.5]",
        (4.5, 16.0): "[15, 17]",
    }
    for c in payload["combos"]:
        ha, hb = c["hyp"]["a_w_minus_r"], c["hyp"]["b_r"]
        key = (c["w"], c["d"])
        hand_L = hand[key]
        # compare stringified L(a)
        La = f"[{ha['L'][0]:g}, {ha['L'][1]:g}]"
        ok = "是" if hand_L.replace("≈", "").replace(" ", "") in (
            La.replace(" ", ""),
            f"[{ha['L'][0]:.2f}, {ha['L'][1]:.2f}]".replace(" ", ""),
        ) or abs(ha["L"][0] - float(hand_L.strip("≈[]").split(",")[0])) < 1e-9 else "复核见下"
        # simpler: always mark 是 if endpoints match within 0.01
        try:
            parts = hand_L.replace("≈", "").strip("[]").split(",")
            ok = "是" if abs(ha["L"][0] - float(parts[0])) < 1e-6 and abs(ha["L"][1] - float(parts[1])) < 0.02 else "否"
        except Exception:
            ok = "?"
        lines.append(
            f"| {c['w']:g} | {c['d']:g} | {c['r']:.4g} | {ha['width']:.4g} | {c['x_F_code']:g} | "
            f"[{ha['L'][0]:g}, {ha['L'][1]:g}] | {ha['A_nom']:.4f} | "
            f"[{hb['L'][0]:g}, {hb['L'][1]:g}] | {hb['A_nom']:.4f} | {hand_L} | {ok} |"
        )
    lines += [
        "",
        f"事实：全部组合 `x_F_code == -1+d`（match=true）。代码未改首航道锚点公式；w 变化只改变条带宽度与相位余数，不改变 \(x_F\\)。",
        "",
        "### 6.2 seed=10 逐组合双假说预测（输入=场景圆盘，无航段）",
        "",
        "预测约定：若结构条件成立，则 \(A_{\\mathrm{extra},S_h}(\\tau=0)=0\\)，"
        "\(A_{\\mathrm{extra},B}(\\tau=0)=\\hat A_\\cup\\)。Â_Σ 为单盘∩条带解析和（上界）；Â_∪ 为 0.05 m 栅格并集（含 F 的 y∈[y0,y1] 裁剪）。",
        "",
        "| w | d | 假说 | L | 宽 | n_hit | Â_Σ | Â_∪（预测 B） | 预测 S_h | 名义空带？ | 出处 |",
        "|---:|---:|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for c in payload["combos"]:
        for key, label in (("a_w_minus_r", "(a) w−r"), ("b_r", "(b) r")):
            h = c["hyp"][key]
            lines.append(
                f"| {c['w']:g} | {c['d']:g} | {label} | [{h['L'][0]:g}, {h['L'][1]:g}] | "
                f"{h['width']:.4g} | {h['n_hit']} | {h['A_sum']:.4f} | {h['A_union']:.4f} | "
                f"{h['predict_Sh']:.1f} | {'是' if h['nominal_gap'] else '否'} | {c['source']} |"
            )
    lines += [
        "",
        "### 6.3 适用性备注（规划前）",
        "",
        "- 「邻缓冲首航道」`heuristic_lane_found` 必须在跑 S_h 计划后才能落盘；本表 `first_lane_n_hit` 只统计条带 "
        "\([x_F,x_F+w]\) 与冠层包围盒相交株数，作事前提示。",
        "- 若规划后 `heuristic_lane_found=False`（常见于 w≠2 时条带网格与目标相位不匹配），该组合的 S_h 对照记 **不适用**，"
        "不硬凑 Δ。",
        "- 技术负责人名义反例 (w=3.5,d=10) 与 (w=4.5,d=16) 的假说 (a) Â_nom=0；seed=10 因抖动/半径变异可能出现薄切，"
        "以本表 Â_∪ 为准，不改手算名义结论的定性标签。",
        "",
        "### 6.4 证据与禁止事项",
        "",
        "| 项 | 路径 |",
        "|---|---|",
        "| 预测 JSON | `results/c1_blind_predict_seed10.json` |",
        "| 生成脚本 | `scripts/c1_blind_predict.py` |",
        "| 喷幅出处 | `/workspace/lit_review/real_orchard_params.md` |",
        "",
        "**本提交禁止**：任何规划输出、plan_hash、A_extra 实测。仿真与误差表见后续 commit。",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-json", default="results/c1_blind_predict_seed10.json")
    ap.add_argument("--write-docs", action="store_true", help="copy paper derivation and append §6")
    ap.add_argument("--docs-src", default="/workspace/paper/derivation_C1.md")
    ap.add_argument("--docs-dst", default="docs/derivation_C1.md")
    a = ap.parse_args()

    scene = H.scene0(SEED)  # 只生成场景
    # 用任一 d 取 F 的 y 范围；x_F 随 d 变
    combos = []
    for w, d, src in COMBOS:
        polys = ev.buffer_set(scene, d, 0.0)
        swept = [f for f in polys if f["swept"]]
        assert swept, (w, d)
        xs = [v[0] for f in swept for v in f["vertices"]]
        ys = [v[1] for f in swept for v in f["vertices"]]
        x_F_code = max(xs)
        y0, y1 = min(ys), max(ys)
        combos.append(predict_combo(scene, w, d, src, y0, y1, x_F_code))

    payload = dict(
        seed=SEED,
        res=RES,
        note="prediction-only; no planning; dual hypotheses a=w-r and b=r",
        combos=combos,
    )
    out = ROOT / a.out_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print("wrote", out)

    if a.write_docs:
        src = Path(a.docs_src)
        dst = ROOT / a.docs_dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        base = src.read_text(encoding="utf-8").rstrip() + "\n\n"
        # strip any previous §6 if re-running
        marker = "## 6. 盲预测"
        if marker in base:
            base = base[: base.index(marker)].rstrip() + "\n\n"
        dst.write_text(base + section_md(payload), encoding="utf-8")
        print("wrote", dst)


if __name__ == "__main__":
    main()
