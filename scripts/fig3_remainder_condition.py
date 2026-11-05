#!/usr/bin/env python3
"""T4 图3 余数条件图（论文版）：ΔA_extra vs 切带冠层面积。

数据只读：results/a_trial_1c_sweep_7e7318e.fit.json + .table.csv（d0d41d3 交付，基线 463badb 仍在）。
不重规划、不改 planning/。

用法：/workspace/.venv-fig/bin/python scripts/fig3_remainder_condition.py
出图：results/figures/fig3_remainder_condition.{png,pdf}
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "results/a_trial_1c_sweep_7e7318e.fit.json"
TABLE = ROOT / "results/a_trial_1c_sweep_7e7318e.table.csv"
OUT_DIR = ROOT / "results/figures"
PNG = OUT_DIR / "fig3_remainder_condition.png"
PDF = OUT_DIR / "fig3_remainder_condition.pdf"

MM = 1 / 25.4
FIG_W = 85 * MM
FIG_H = 72 * MM
LW = 1.7  # pt
LW_AXIS = 0.8
FS = 7
PHASE = 1.0
DPI = 300


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
    with open(TABLE, encoding="utf8") as fh:
        for row in csv.DictReader(fh):
            key = (float(row["w"]), float(row["d"]), float(row["tau"]))
            dA = [float(x) for x in row["per_seed_dA"].split(";")]
            can = [float(x) for x in row["lost_strip_canopy_m2_per_seed"].split(";")]
            got = sorted(by[key], key=lambda p: int(p["seed"]))
            assert len(got) == 5
            for i, p in enumerate(got):
                assert abs(float(p["dA"]) - dA[i]) < 1e-6, (key, i, p["dA"], dA[i])
                assert abs(float(p["strip_canopy_m2"]) - can[i]) < 1e-3, (
                    key,
                    i,
                    p["strip_canopy_m2"],
                    can[i],
                )
    return pts


def main():
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pts = load_points()

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    for spine in ax.spines.values():
        spine.set_linewidth(LW_AXIS)
    ax.tick_params(width=LW_AXIS, length=2.5, labelsize=FS)

    cols = {0.0: "#1f77b4", 0.5: "#ff7f0e", 1.0: "#d62728"}
    ax.axhspan(-PHASE, PHASE, color="0.7", alpha=0.18, zorder=0, linewidth=0)

    xmax = max(float(p["strip_canopy_m2"]) for p in pts)
    xx = [0.0, max(xmax * 1.02, 1.0)]
    # 不画合并 R²；仅 τ=0 几何恒等
    ax.plot(
        xx,
        [-v for v in xx],
        linestyle=(0, (4, 2)),
        color="0.2",
        linewidth=LW,
        zorder=1,
        label="τ=0 几何恒等",
    )

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
            markersize=3.0,
            linestyle="None",
            markeredgewidth=0.55,
            alpha=0.85,
            zorder=2,
        )

    for tau, c in cols.items():
        ax.plot([], [], "o", color=c, markersize=3.2, label=f"τ={tau:g} s")
    ax.plot([], [], "ko", markersize=3.2, label="d=10 m (U=2)")
    ax.plot([], [], "ks", markerfacecolor="white", markersize=3.2, label="d=16 m (U=4)")

    # 手工摆放 (w,d) 标注，避免质心重叠误标
    # 大簇 w=3/4 @ d=10 同在 ~58；原点簇多个 r=0 对照叠在 (0,0)
    annotations = [
        # (x, y, text, dx, dy)
        (58.2, -58.2, "w=3/4, d=10", -28, 10),
        (3.59, -3.59, "w=3.5, d=10", 4, -10),
        (0.06, -0.06, "w=3, d=16", 6, -12),
        (0.0, 0.0, "r=0 对照\n(w=2; 2.5@d10;\n4@d16; 3.5@d16)", -2, 14),
    ]
    for x, y, text, dx, dy in annotations:
        ax.annotate(
            text,
            (x, y),
            textcoords="offset points",
            xytext=(dx, dy),
            fontsize=FS,
            color="0.15",
            zorder=3,
            ha="left",
            va="bottom",
        )

    ax.set_xlabel("B-boundary(0°) 损失条带内冠层面积 / m²", fontsize=FS)
    ax.set_ylabel(r"$\Delta A_{\mathrm{extra}}=S_h-$B-boundary(0°) / m²", fontsize=FS)
    ax.axhline(0.0, color="k", linewidth=0.5, zorder=1)
    ax.set_xlim(-2, xmax * 1.08)
    ymin = min(float(p["dA"]) for p in pts)
    ymax = max(float(p["dA"]) for p in pts)
    ax.set_ylim(ymin - 4, ymax + 6)
    ax.legend(
        fontsize=FS,
        frameon=False,
        loc="lower left",
        handlelength=1.5,
        borderpad=0.15,
        labelspacing=0.2,
        handletextpad=0.35,
    )
    fig.subplots_adjust(left=0.16, right=0.98, bottom=0.14, top=0.98)
    # 固定画布为 85 mm 宽，不用 bbox_inches='tight' 以免撑破栏宽
    fig.savefig(PNG, dpi=DPI)
    fig.savefig(PDF)
    plt.close(fig)

    assert PNG.exists() and PDF.exists()
    print(f"wrote {PNG} ({PNG.stat().st_size} bytes)")
    print(f"wrote {PDF} ({PDF.stat().st_size} bytes)")
    print(f"figsize_in=({FIG_W:.4f},{FIG_H:.4f}) dpi={DPI} lw={LW} fs={FS}")
    print("assertions: n=150, tau0 geometric identity, table.csv match OK")


if __name__ == "__main__":
    main()
