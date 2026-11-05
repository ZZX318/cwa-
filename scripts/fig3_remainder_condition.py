#!/usr/bin/env python3
"""T4 图3 余数条件图（论文版，双栏叠放）：(a) ΔA_extra vs 切带冠层；(b) 余数条带示意。

数据只读：results/a_trial_1c_sweep_7e7318e.{fit.json,table.csv}（d0d41d3）。
不重规划、不改 planning/。

用法：/workspace/.venv-fig/bin/python scripts/fig3_remainder_condition.py
出图：results/figures/fig3_remainder_condition.{png,pdf}
"""
from __future__ import annotations

import csv
import json
import math
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "results/a_trial_1c_sweep_7e7318e.fit.json"
TABLE = ROOT / "results/a_trial_1c_sweep_7e7318e.table.csv"
OUT_DIR = ROOT / "results/figures"
PNG = OUT_DIR / "fig3_remainder_condition.png"
PDF = OUT_DIR / "fig3_remainder_condition.pdf"

MM = 1 / 25.4
FIG_W_MM = 85.0
FIG_H_MM = 150.0
FIG_W = FIG_W_MM * MM
FIG_H = FIG_H_MM * MM
LW = 1.7
LW_AXIS = 0.8
FS = 7
PHASE = 1.0
DPI = 300

ROW_CENTERS_SEED0 = [
    2.96, 11.06, 18.87, 27.04, 35.09, 42.90, 51.04, 59.11, 67.05, 74.98, 82.98, 91.00
]
CANOPY_R_TYP = 1.5


def setup_font():
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    ):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            name = font_manager.FontProperties(fname=path).get_name()
            plt.rcParams["font.family"] = name
            plt.rcParams["font.sans-serif"] = [name, "Noto Sans CJK SC", "DejaVu Sans"]
            break
    else:
        plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42
    plt.rcParams["font.size"] = FS


def remainder(d: float, w: float) -> float:
    return d - math.floor(d / w) * w


def load_points():
    fit = json.loads(FIT.read_text(encoding="utf8"))
    pts = fit["points"]
    assert len(pts) == 150, len(pts)
    tau0 = [p for p in pts if float(p["tau"]) == 0.0]
    assert len(tau0) == 50
    max_resid = max(abs(float(p["dA"]) + float(p["strip_canopy_m2"])) for p in tau0)
    assert max_resid < 1e-6, max_resid

    by = {}
    for p in pts:
        key = (float(p["w"]), float(p["d"]), float(p["tau"]))
        by.setdefault(key, []).append(p)
    table_rows = []
    with open(TABLE, encoding="utf8") as fh:
        for row in csv.DictReader(fh):
            table_rows.append(row)
            key = (float(row["w"]), float(row["d"]), float(row["tau"]))
            dA = [float(x) for x in row["per_seed_dA"].split(";")]
            can = [float(x) for x in row["lost_strip_canopy_m2_per_seed"].split(";")]
            got = sorted(by[key], key=lambda p: int(p["seed"]))
            assert len(got) == 5
            for i, p in enumerate(got):
                assert abs(float(p["dA"]) - dA[i]) < 1e-6
                assert abs(float(p["strip_canopy_m2"]) - can[i]) < 1e-3
            w, d = float(row["w"]), float(row["d"])
            assert abs(remainder(d, w) - float(row["r"])) < 1e-9, (w, d, row["r"])
    return pts, table_rows


def parse_strip_xy(s: str):
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^\(([^)]+)\)$", s)
    assert m, s
    parts = [float(x.strip()) for x in m.group(1).split(",")]
    assert len(parts) == 4, s
    return parts


def style_ax(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(LW_AXIS)
    ax.tick_params(width=LW_AXIS, length=2.2, labelsize=FS)


def draw_a(ax, pts):
    cols = {0.0: "#1f77b4", 0.5: "#ff7f0e", 1.0: "#d62728"}
    ax.axhspan(-PHASE, PHASE, color="0.7", alpha=0.18, zorder=0, linewidth=0)

    xmax = max(float(p["strip_canopy_m2"]) for p in pts)
    xx = [0.0, max(xmax * 1.02, 1.0)]
    ax.plot(xx, [-v for v in xx], linestyle=(0, (4, 2)), color="0.2", linewidth=LW, zorder=1)

    for p in pts:
        tau = float(p["tau"])
        d = float(p["d"])
        mk = "o" if d == 10.0 else "s"
        mfc = cols[tau] if d == 10.0 else "white"
        ax.plot(
            float(p["strip_canopy_m2"]),
            float(p["dA"]),
            marker=mk,
            color=cols[tau],
            markerfacecolor=mfc,
            markersize=2.8,
            linestyle="None",
            markeredgewidth=0.5,
            alpha=0.85,
            zorder=2,
        )

    handles = [
        Line2D([0], [0], color="0.2", lw=LW, linestyle=(0, (4, 2)), label="τ=0 几何恒等"),
        Line2D([0], [0], marker="o", color="#1f77b4", ls="None", ms=3.2, label="τ=0 s"),
        Line2D([0], [0], marker="o", color="#ff7f0e", ls="None", ms=3.2, label="τ=0.5 s"),
        Line2D([0], [0], marker="o", color="#d62728", ls="None", ms=3.2, label="τ=1 s"),
        Line2D([0], [0], marker="o", color="k", ls="None", ms=3.2, label="d=10 m (U=2)"),
        Line2D([0], [0], marker="s", color="k", markerfacecolor="white", ls="None", ms=3.2, label="d=16 m (U=4)"),
    ]
    ax.legend(
        handles=handles,
        fontsize=FS,
        frameon=False,
        loc="lower left",
        handlelength=1.4,
        borderpad=0.1,
        labelspacing=0.18,
        handletextpad=0.3,
    )

    # 引出线：文字锚在空白区，不贴点、不贴顶边
    callouts = [
        ((40, -22), (58.2, -58.2), "w=3 与 w=4，d=10"),
        ((14, -50), (3.59, -3.59), "w=3.5，d=10"),
        ((22, -8), (0.06, -0.06), "w=3，d=16"),
        ((16, -30), (0.0, 0.0), "r=0 对照（条带空）"),
    ]
    for (tx, ty), (px, py), text in callouts:
        ax.annotate(
            text,
            xy=(px, py),
            xytext=(tx, ty),
            fontsize=FS,
            color="0.1",
            ha="left",
            va="center",
            arrowprops=dict(
                arrowstyle="-",
                color="0.35",
                lw=0.6,
                connectionstyle="arc3,rad=0.08",
                shrinkA=1,
                shrinkB=2,
            ),
            zorder=4,
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="0.75", lw=0.4, alpha=0.95),
            clip_on=True,
        )

    ax.set_xlabel("B-boundary(0°) 损失条带内冠层面积 / m²", fontsize=FS)
    ax.set_ylabel(r"$\Delta A_{\mathrm{extra}}=S_h-$B-boundary(0°) / m²", fontsize=FS)
    ax.axhline(0.0, color="k", linewidth=0.5, zorder=1)
    ax.set_xlim(-2, xmax * 1.05)
    ymin = min(float(p["dA"]) for p in pts)
    ymax = max(float(p["dA"]) for p in pts)
    ax.set_ylim(ymin - 6, ymax + 5)
    ax.set_title("(a)", fontsize=FS, loc="left", pad=2)
    style_ax(ax)


def draw_b(ax, table_rows):
    cases = []
    for row in table_rows:
        if float(row["tau"]) != 0.0:
            continue
        w, d = float(row["w"]), float(row["d"])
        r = float(row["r"])
        assert abs(remainder(d, w) - r) < 1e-9
        xy = parse_strip_xy(row["lost_strip_xy"])
        cans = [float(x) for x in row["lost_strip_canopy_m2_per_seed"].split(";")]
        mean_c = sum(cans) / len(cans)
        cases.append(
            dict(w=w, d=d, r=r, xy=xy, mean_c=mean_c, intersects=mean_c > 1e-6)
        )
    cases.sort(key=lambda c: (c["d"], c["w"]))

    x_lo, x_hi = 0.0, 20.0
    for xc in ROW_CENTERS_SEED0:
        if x_lo - 2 <= xc <= x_hi + 2:
            ax.axvspan(xc - CANOPY_R_TYP, xc + CANOPY_R_TYP, color="#c6e5b2", alpha=0.5, zorder=0, lw=0)
            ax.axvline(xc, color="#4a7c3a", lw=0.45, alpha=0.65, zorder=1)

    ax.axvline(9.0, color="#5555aa", lw=0.8, linestyle="--", zorder=1)
    ax.axvline(15.0, color="#5555aa", lw=0.8, linestyle=":", zorder=1)

    yticks = []
    ylabels = []
    for i, c in enumerate(cases):
        y = i
        yticks.append(y)
        ylabels.append(f"w={c['w']:g}\nd={c['d']:g}\nr={c['r']:g}")
        if c["xy"] is None:
            ax.plot([1.0], [y], marker="x", color="0.4", ms=3.5, zorder=3)
            ax.text(1.5, y, "无损失条带 (r=0)", fontsize=FS, va="center", color="0.35", zorder=3)
        else:
            x0, x1, _, _ = c["xy"]
            color = "#d62728" if c["intersects"] else "#1f77b4"
            ax.barh(
                y,
                x1 - x0,
                left=x0,
                height=0.62,
                color=color,
                edgecolor="0.2",
                linewidth=0.45,
                alpha=0.88,
                zorder=2,
            )
            if x1 - x0 >= 1.2:
                ax.text(
                    (x0 + x1) / 2,
                    y,
                    f"[{x0:g},{x1:g}]",
                    fontsize=FS,
                    ha="center",
                    va="center",
                    color="white",
                    zorder=3,
                )
            else:
                ax.text(
                    x1 + 0.25,
                    y,
                    f"[{x0:g},{x1:g}]",
                    fontsize=FS,
                    ha="left",
                    va="center",
                    color="0.15",
                    zorder=3,
                )

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=FS)
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(-0.8, len(cases) - 0.2)
    ax.set_xlabel("园地 x / m（示意，seed0 行心；绿带≈冠层）", fontsize=FS)
    ax.set_title("(b) 损失条带相对树行 「示意」", fontsize=FS, loc="left", pad=2)

    # x_F 注释放在图内右上角，避开条带
    ax.text(
        0.98,
        0.97,
        "$x_F{=}9$ (d=10, 虚线)\n$x_F{=}15$ (d=16, 点线)",
        transform=ax.transAxes,
        fontsize=FS,
        ha="right",
        va="top",
        color="#5555aa",
        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="0.8", lw=0.35, alpha=0.9),
    )
    ax.text(
        0.02,
        0.02,
        r"$r=d-\lfloor d/w\rfloor\cdot w$（$0\leq r<w$）",
        transform=ax.transAxes,
        fontsize=FS,
        ha="left",
        va="bottom",
        color="0.2",
        bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="0.8", lw=0.35, alpha=0.9),
    )

    handles = [
        Rectangle((0, 0), 1, 1, fc="#d62728", ec="0.2", lw=0.45, label="切带压到树行"),
        Rectangle((0, 0), 1, 1, fc="#1f77b4", ec="0.2", lw=0.45, label="切带落在行间"),
        Line2D([0], [0], color="#4a7c3a", lw=0.8, label="树行中心"),
    ]
    ax.legend(
        handles=handles,
        fontsize=FS,
        frameon=False,
        loc="lower right",
        handlelength=1.1,
        borderpad=0.1,
        labelspacing=0.12,
        bbox_to_anchor=(1.0, 0.12),
    )
    style_ax(ax)


def verify_pdf_width_mm(path: Path, expect_mm: float = 85.0, tol_mm: float = 0.5):
    out = subprocess.check_output(["pdfinfo", str(path)], text=True)
    m = re.search(r"Page size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", out)
    assert m, out
    w_pts, h_pts = float(m.group(1)), float(m.group(2))
    w_mm = w_pts * 25.4 / 72.0
    h_mm = h_pts * 25.4 / 72.0
    assert abs(w_mm - expect_mm) <= tol_mm, (w_mm, expect_mm, out)
    return dict(pdfinfo=out, width_mm=w_mm, height_mm=h_mm)


def main():
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pts, table_rows = load_points()

    fig, (ax_a, ax_b) = plt.subplots(
        2,
        1,
        figsize=(FIG_W, FIG_H),
        gridspec_kw={"height_ratios": [1.0, 1.25], "hspace": 0.30},
    )
    draw_a(ax_a, pts)
    draw_b(ax_b, table_rows)

    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.055, top=0.965, hspace=0.34)
    fig.savefig(PNG, dpi=DPI)
    fig.savefig(PDF)
    plt.close(fig)

    info = verify_pdf_width_mm(PDF, FIG_W_MM, tol_mm=0.5)
    print(f"wrote {PNG} ({PNG.stat().st_size} bytes)")
    print(f"wrote {PDF} ({PDF.stat().st_size} bytes)")
    print(f"figsize_mm=({FIG_W_MM},{FIG_H_MM}) dpi={DPI} lw={LW} fs={FS}")
    print("--- pdfinfo ---")
    print(info["pdfinfo"].rstrip())
    print(f"PDF page width = {info['width_mm']:.3f} mm, height = {info['height_mm']:.3f} mm")
    print("assertions OK")


if __name__ == "__main__":
    main()
