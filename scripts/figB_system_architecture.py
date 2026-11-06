"""Figure B: system architecture flowchart for paper §1.8 appendix (render only)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import matplotlib.pyplot as plt

PREFIX = ROOT / "results/figB_system_architecture"
MM = 1 / 25.4
LW = 0.8


def configure_fonts():
    path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not path.exists():
        listing = subprocess.check_output(
            ["fc-list", "--format=%{file}\t%{family}\n"], text=True
        )
        candidates = [
            line.split("\t", 1)[0]
            for line in listing.splitlines()
            if "Noto Sans CJK SC" in line or "Noto Serif CJK SC" in line
        ]
        assert candidates, "No Noto CJK font"
        path = Path(candidates[0])
    font_manager.fontManager.addfont(str(path))
    names = {f.name for f in font_manager.fontManager.ttflist}
    family = next(
        (n for n in ("Noto Sans CJK SC", "Noto Serif CJK SC") if n in names),
        font_manager.FontProperties(fname=str(path)).get_name(),
    )
    matplotlib.rcParams.update(
        {
            "font.family": family,
            "font.size": 7,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
        }
    )


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# Verified against ARCHITECTURE.md / tree (no invented modules).
NODES = [
    dict(
        key="scene",
        title="① 场景生成",
        code="scene/generator.py\nscene/random_map.py\nrandom_scene.py",
        primary=True,
    ),
    dict(
        key="buffer",
        title="② 约束与缓冲",
        code="planning/drift.py\nplanning/zones.py\n（禁喷区 · 上风外扩）",
        primary=True,
    ),
    dict(
        key="phase",
        title="③ 条带相位对齐",
        code="S_h / B-boundary\nscripts/a_trial_heading.py\n（heuristic_offset 等）",
        primary=True,
    ),
    dict(
        key="plan",
        title="④ 规划",
        code="planning/planner.py\n（fixed-y 条带 · 禁区切割）",
        primary=True,
        secondary=dict(
            title="CAW-A*（实现手段）",
            code="planner_api.py\nplanning/routing3d.py\nplanning/order.py",
        ),
    ),
    dict(
        key="exec",
        title="⑤ 执行时间",
        code="execution/__init__.py",
        primary=True,
    ),
    dict(
        key="eval",
        title="⑥ 评价",
        code="evaluation/__init__.py\nscripts/a_trial_eval.py\nA_extra · 时间 · violations",
        primary=True,
    ),
    dict(
        key="freeze",
        title="⑦ 冻结复现",
        code="planning/model.py（fingerprint）\n*checks.py · main.py --check\n固定种子 · hash · 检查",
        primary=True,
    ),
]


def draw_box(ax, x, y, w, h, title, code, *, fc, ec, title_color="#111111"):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=LW,
        facecolor=fc,
        edgecolor=ec,
        mutation_aspect=0.5,
        zorder=2,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h - 0.22,
        title,
        ha="center",
        va="top",
        fontsize=7.5,
        color=title_color,
        fontweight="bold",
        zorder=3,
    )
    ax.text(
        x + w / 2,
        y + h / 2 - 0.05,
        code,
        ha="center",
        va="center",
        fontsize=5.8,
        color="#333333",
        linespacing=1.25,
        zorder=3,
    )


def main():
    configure_fonts()
    # Wide appendix figure: left-to-right primary chain; CAW as secondary under planning.
    fig_w, fig_h = 170 * MM, 95 * MM
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, 17)
    ax.set_ylim(0, 9.5)
    ax.axis("off")
    ax.set_title("系统架构与数据流（附录）", fontsize=9, pad=6)

    # Layout: 7 primary boxes in a row (wrapped? better 4 + 3 or single row compressed)
    # Use two rows: 1-4 on top, 5-7 on bottom, with flow arrows.
    # Planning (4) has secondary CAW below it.

    box_w, box_h = 3.6, 2.35
    gap = 0.45
    top_y = 5.9
    bot_y = 1.15

    # Top row: ①–④
    top_keys = ["scene", "buffer", "phase", "plan"]
    top_nodes = [n for k in top_keys for n in NODES if n["key"] == k]
    xs_top = []
    x0 = 0.55
    for i, n in enumerate(top_nodes):
        x = x0 + i * (box_w + gap)
        xs_top.append(x)
        draw_box(
            ax,
            x,
            top_y,
            box_w,
            box_h,
            n["title"],
            n["code"],
            fc="#E8F1DE",
            ec="#3D5A2A",
        )
        if n.get("secondary"):
            s = n["secondary"]
            sx, sy = x + 0.35, top_y - 1.95
            draw_box(
                ax,
                sx,
                sy,
                box_w - 0.7,
                1.60,
                s["title"],
                s["code"],
                fc="#F2F2F2",
                ec="#888888",
                title_color="#555555",
            )
            # dashed link from planning to CAW
            ax.annotate(
                "",
                xy=(sx + (box_w - 0.7) / 2, sy + 1.60),
                xytext=(x + box_w / 2, top_y),
                arrowprops=dict(
                    arrowstyle="->",
                    lw=0.9,
                    linestyle="--",
                    color="#888888",
                ),
            )

    # Bottom row: ⑤–⑦ centered-ish
    bot_keys = ["exec", "eval", "freeze"]
    bot_nodes = [n for k in bot_keys for n in NODES if n["key"] == k]
    total_bot = 3 * box_w + 2 * gap
    x0b = (17 - total_bot) / 2
    xs_bot = []
    for i, n in enumerate(bot_nodes):
        x = x0b + i * (box_w + gap)
        xs_bot.append(x)
        draw_box(
            ax,
            x,
            bot_y,
            box_w,
            box_h,
            n["title"],
            n["code"],
            fc="#E8F1DE",
            ec="#3D5A2A",
        )

    def arrow(x1, y1, x2, y2, dashed=False):
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(
                arrowstyle="->",
                lw=1.1,
                color="#333333",
                linestyle="--" if dashed else "-",
            ),
        )

    # Horizontal arrows on top row
    for i in range(3):
        arrow(
            xs_top[i] + box_w,
            top_y + box_h / 2,
            xs_top[i + 1],
            top_y + box_h / 2,
        )
    # From ④ down to ⑤
    arrow(
        xs_top[3] + box_w / 2,
        top_y,
        xs_bot[0] + box_w / 2,
        bot_y + box_h,
    )
    # Bottom row arrows
    for i in range(2):
        arrow(
            xs_bot[i] + box_w,
            bot_y + box_h / 2,
            xs_bot[i + 1],
            bot_y + box_h / 2,
        )

    # Legend
    ax.add_patch(
        Rectangle((0.5, 0.25), 0.45, 0.35, facecolor="#E8F1DE", edgecolor="#3D5A2A", lw=LW)
    )
    ax.text(1.1, 0.42, "主流程模块", va="center", fontsize=6.5)
    ax.add_patch(
        Rectangle((4.2, 0.25), 0.45, 0.35, facecolor="#F2F2F2", edgecolor="#888888", lw=LW)
    )
    ax.text(4.8, 0.42, "次级：CAW-A* 实现手段（非主张主线）", va="center", fontsize=6.5)

    fig.tight_layout(pad=0.4)
    fig.savefig(str(PREFIX) + ".png", dpi=300)
    fig.savefig(str(PREFIX) + ".pdf")
    plt.close(fig)

    commit = git_sha()
    meta = dict(
        figure="B",
        section="§1.8 appendix",
        commit=commit,
        planning_ran=False,
        nodes=[
            {
                "key": n["key"],
                "title": n["title"],
                "code": n["code"].replace("\n", " | "),
                **(
                    {"secondary": n["secondary"]}
                    if n.get("secondary")
                    else {}
                ),
            }
            for n in NODES
        ],
        note="模块路径对照 ARCHITECTURE.md 与仓库实际文件；未画不存在的模块。CAW-A* 仅作实现手段。",
        outputs={
            "png": str(PREFIX) + ".png",
            "pdf": str(PREFIX) + ".pdf",
            "json": str(PREFIX) + ".json",
        },
    )
    PREFIX.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    caption = f"""图B 系统架构与数据流（附录）。主流程：场景生成 → 约束与缓冲 → 条带相位对齐（S_h 或 B）→ 规划 → 执行时间 → 评价（A_extra、时间、violations）→ 冻结复现。灰色虚线框为 CAW-A*，仅作为规划步骤的实现手段。各模块标注对应代码路径，依据 ARCHITECTURE.md。本图由脚本生成，未运行规划。

Fig. B System architecture and data flow (appendix). Main pipeline: scene generation → constraints & buffer → strip phase alignment (S_h or B) → planning → execution time → evaluation (A_extra, time, violations) → frozen reproduction. The grey dashed box is CAW-A*, shown only as an implementation means inside planning. Module labels cite code paths per ARCHITECTURE.md. Generated by script; no planning was run.

脚本 / Script: scripts/figB_system_architecture.py; commit {commit}.
"""
    PREFIX.with_suffix(".caption.md").write_text(caption, encoding="utf-8")
    print("Wrote", PREFIX.with_suffix(".png"))
    print("commit=", commit, "planning_ran=False")


if __name__ == "__main__":
    main()
