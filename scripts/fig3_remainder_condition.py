#!/usr/bin/env python3
"""T4 图3：(a) ΔA_extra vs 切带冠层；(b) 余数条带示意。d0d41d3 只读数据。"""
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
FIG_W_MM, FIG_H_MM = 85.0, 160.0
FIG_W, FIG_H = FIG_W_MM * MM, FIG_H_MM * MM
LW, LW_AXIS, FS, PHASE, DPI = 1.7, 0.8, 7, 1.0, 300

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


def remainder(d, w):
    return d - math.floor(d / w) * w


def load_points():
    fit = json.loads(FIT.read_text(encoding="utf8"))
    pts = fit["points"]
    assert len(pts) == 150
    tau0 = [p for p in pts if float(p["tau"]) == 0.0]
    assert len(tau0) == 50
    assert max(abs(float(p["dA"]) + float(p["strip_canopy_m2"])) for p in tau0) < 1e-6
    by = {}
    for p in pts:
        by.setdefault((float(p["w"]), float(p["d"]), float(p["tau"])), []).append(p)
    table_rows = []
    with open(TABLE, encoding="utf8") as fh:
        for row in csv.DictReader(fh):
            table_rows.append(row)
            key = (float(row["w"]), float(row["d"]), float(row["tau"]))
            dA = [float(x) for x in row["per_seed_dA"].split(";")]
            can = [float(x) for x in row["lost_strip_canopy_m2_per_seed"].split(";")]
            got = sorted(by[key], key=lambda p: int(p["seed"]))
            for i, p in enumerate(got):
                assert abs(float(p["dA"]) - dA[i]) < 1e-6
                assert abs(float(p["strip_canopy_m2"]) - can[i]) < 1e-3
            assert abs(remainder(float(row["d"]), float(row["w"])) - float(row["r"])) < 1e-9
    return pts, table_rows


def parse_strip_xy(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^\(([^)]+)\)$", s)
    assert m, s
    parts = [float(x.strip()) for x in m.group(1).split(",")]
    assert len(parts) == 4
    return parts


def style_ax(ax):
    for sp in ax.spines.values():
        sp.set_linewidth(LW_AXIS)
    ax.tick_params(width=LW_AXIS, length=2.0, labelsize=FS)


def draw_a(ax, pts):
    cols = {0.0: "#1f77b4", 0.5: "#ff7f0e", 1.0: "#d62728"}
    ax.axhspan(-PHASE, PHASE, color="0.7", alpha=0.18, zorder=0, lw=0)
    xmax = max(float(p["strip_canopy_m2"]) for p in pts)
    xx = [0.0, xmax * 1.02]
    ax.plot(xx, [-v for v in xx], ls=(0, (4, 2)), color="0.25", lw=LW, zorder=1)

    for p in pts:
        tau, d = float(p["tau"]), float(p["d"])
        ax.plot(
            float(p["strip_canopy_m2"]),
            float(p["dA"]),
            marker="o" if d == 10 else "s",
            color=cols[tau],
            mfc=cols[tau] if d == 10 else "white",
            ms=2.5,
            ls="None",
            mew=0.5,
            alpha=0.85,
            zorder=2,
        )

    ax.legend(
        handles=[
            Line2D([0], [0], color="0.25", lw=LW, ls=(0, (4, 2)), label="τ=0 几何恒等"),
            Line2D([0], [0], marker="o", color="#1f77b4", ls="None", ms=3, label="τ=0 s"),
            Line2D([0], [0], marker="o", color="#ff7f0e", ls="None", ms=3, label="τ=0.5 s"),
            Line2D([0], [0], marker="o", color="#d62728", ls="None", ms=3, label="τ=1 s"),
            Line2D([0], [0], marker="o", color="k", ls="None", ms=3, label="d=10 m (U=2)"),
            Line2D([0], [0], marker="s", color="k", mfc="white", ls="None", ms=3, label="d=16 m (U=4)"),
        ],
        fontsize=FS,
        frameon=False,
        loc="lower left",
        handlelength=1.15,
        borderpad=0.05,
        labelspacing=0.1,
        handletextpad=0.2,
    )

    # (a) r=0：axes 分数坐标，保证整框在轴内；簇说明无引线
    box = dict(boxstyle="round,pad=0.12", fc="white", ec="0.6", lw=0.3, alpha=0.97)
    ax.annotate(
        "r=0 对照（条带空）",
        xy=(1.2, 0.8),
        xycoords="data",
        xytext=(0.28, 0.90),
        textcoords="axes fraction",
        fontsize=FS,
        ha="left",
        va="top",
        arrowprops=dict(arrowstyle="-", color="0.35", lw=0.5, shrinkA=1, shrinkB=1, connectionstyle="arc3,rad=0"),
        bbox=box,
        zorder=5,
        clip_on=True,
    )
    ax.text(
        0.48,
        0.72,
        "簇说明（无引线）\n"
        "· (4,−4)：w=3.5，d=10\n"
        "· (58,−58)：w=3 与 w=4，d=10\n"
        "· 原点微条带含 w=3,d=16 等",
        transform=ax.transAxes,
        fontsize=FS,
        ha="left",
        va="top",
        color="0.15",
        linespacing=1.35,
        bbox=box,
        zorder=5,
        clip_on=True,
    )

    ax.set_xlabel("B-boundary(0°) 损失条带内冠层面积 / m²", fontsize=FS)
    ax.set_ylabel(r"$\Delta A_{\mathrm{extra}}=S_h-$B-boundary(0°) / m²", fontsize=FS)
    ax.axhline(0, color="k", lw=0.45, zorder=1)
    ax.set_xlim(-1, 68)
    ymin = min(float(p["dA"]) for p in pts)
    ymax = max(float(p["dA"]) for p in pts)
    ax.set_ylim(ymin - 6, max(ymax + 10, 12))
    ax.set_title("(a)", fontsize=FS, loc="left", pad=2)
    style_ax(ax)


def draw_b(ax, table_rows):
    cases = []
    for row in table_rows:
        if float(row["tau"]) != 0.0:
            continue
        w, d, r = float(row["w"]), float(row["d"]), float(row["r"])
        assert abs(remainder(d, w) - r) < 1e-9
        xy = parse_strip_xy(row["lost_strip_xy"])
        cans = [float(x) for x in row["lost_strip_canopy_m2_per_seed"].split(";")]
        mean_c = sum(cans) / len(cans)
        cases.append(dict(w=w, d=d, r=r, xy=xy, intersects=mean_c > 1e-6))
    cases.sort(key=lambda c: (c["d"], c["w"]))

    x_lo, x_hi = 0.0, 23.5
    for xc in ROW_CENTERS_SEED0:
        if x_lo - 2 <= xc <= x_hi + 2:
            ax.axvspan(xc - CANOPY_R_TYP, xc + CANOPY_R_TYP, color="#c6e5b2", alpha=0.42, zorder=0, lw=0)
            ax.axvline(xc, color="#4a7c3a", lw=0.35, alpha=0.55, zorder=1)
    ax.axvline(9.0, color="#5555aa", lw=0.7, ls="--", zorder=1)
    ax.axvline(15.0, color="#5555aa", lw=0.7, ls=":", zorder=1)

    yticks, ylabels = [], []
    y, prev_d, gap_y = 0.0, None, None
    for c in cases:
        if prev_d is not None and c["d"] != prev_d:
            gap_y = y - 0.45
            y += 0.5
        prev_d = c["d"]
        yticks.append(y)
        # 紧凑单行，避免自动换行：用窄空格分隔
        ylabels.append(f"w={c['w']:g}, d={c['d']:g} (r={c['r']:g})")
        if c["xy"] is None:
            ax.plot([0.6], [y], marker="x", color="0.4", ms=3, zorder=3)
            ax.text(1.1, y, "无损失条带", fontsize=FS, va="center", color="0.35", zorder=3)
        else:
            x0, x1, _, _ = c["xy"]
            color = "#d62728" if c["intersects"] else "#1f77b4"
            ax.barh(y, x1 - x0, left=x0, height=0.5, color=color, ec="0.2", lw=0.35, alpha=0.9, zorder=2)
            # 区间文字始终在条外右侧
            ax.text(x1 + 0.3, y, f"[{x0:g}, {x1:g}]", fontsize=FS, ha="left", va="center", color="0.1", zorder=3, clip_on=False)
        y += 1.15

    if gap_y is not None:
        ax.axhline(gap_y, color="0.78", lw=0.45, zorder=1)

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=FS)
    # 强制不换行：matplotlib 对长标签可能 wrap；用 Fixed 宽度字体度量后若仍 wrap，缩短
    for lab in ax.get_yticklabels():
        lab.set_linespacing(1.0)

    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(-0.65, y - 0.4)
    ax.set_xlabel("园地 x / m（示意，seed0 行心；绿带≈冠层）", fontsize=FS)
    ax.set_title("(b) 损失条带相对树行（示意）", fontsize=FS, loc="left", pad=2)

    ax.text(
        0.99,
        0.99,
        "$x_F{=}9$ (d=10, 虚线)\n$x_F{=}15$ (d=16, 点线)",
        transform=ax.transAxes,
        fontsize=FS,
        ha="right",
        va="top",
        color="#5555aa",
        bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="0.8", lw=0.25, alpha=0.92),
    )
    ax.figure.text(
        0.5,
        0.018,
        r"$r=d-\lfloor d/w\rfloor\cdot w$（$0\leq r<w$）",
        transform=ax.figure.transFigure,
        fontsize=FS,
        ha="center",
        va="bottom",
        color="0.2",
        bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="0.8", lw=0.25, alpha=0.92),
    )
    ax.legend(
        handles=[
            Rectangle((0, 0), 1, 1, fc="#d62728", ec="0.2", lw=0.35, label="切带压到树行"),
            Rectangle((0, 0), 1, 1, fc="#1f77b4", ec="0.2", lw=0.35, label="切带落在行间"),
            Line2D([0], [0], color="#4a7c3a", lw=0.75, label="树行中心"),
        ],
        fontsize=FS,
        frameon=False,
        loc="lower right",
        handlelength=1.0,
        borderpad=0.06,
        labelspacing=0.08,
        bbox_to_anchor=(0.99, 0.07),
    )
    style_ax(ax)


def verify_pdf_width_mm(path, expect_mm=85.0, tol_mm=0.5):
    out = subprocess.check_output(["pdfinfo", str(path)], text=True)
    m = re.search(r"Page size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", out)
    assert m, out
    w_mm = float(m.group(1)) * 25.4 / 72.0
    h_mm = float(m.group(2)) * 25.4 / 72.0
    assert abs(w_mm - expect_mm) <= tol_mm, (w_mm, out)
    return dict(pdfinfo=out, width_mm=w_mm, height_mm=h_mm)


def main():
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pts, table_rows = load_points()
    fig, (ax_a, ax_b) = plt.subplots(
        2, 1, figsize=(FIG_W, FIG_H), gridspec_kw={"height_ratios": [1.0, 1.55], "hspace": 0.25}
    )
    draw_a(ax_a, pts)
    draw_b(ax_b, table_rows)
    # 左侧为单行 y 标签留宽，防止自动折行
    fig.subplots_adjust(left=0.34, right=0.985, bottom=0.105, top=0.955, hspace=0.25)
    fig.savefig(PNG, dpi=DPI)
    fig.savefig(PDF)
    plt.close(fig)
    info = verify_pdf_width_mm(PDF)
    print(f"wrote {PNG} ({PNG.stat().st_size} bytes)")
    print(f"wrote {PDF} ({PDF.stat().st_size} bytes)")
    print("--- pdfinfo ---")
    print(info["pdfinfo"].rstrip())
    print(f"PDF page = {info['width_mm']:.3f} x {info['height_mm']:.3f} mm")
    print("OK")


if __name__ == "__main__":
    main()
