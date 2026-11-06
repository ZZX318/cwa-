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
        code="planning/model.py\n（fingerprint）\n*checks.py · main.py --check\n固定种子 · hash · 检查",
        primary=True,
    ),
]


def draw_box(ax, x, y, w, h, title, code, *, fc, ec, title_color="#111111",
             title_fs=7.5, code_fs=5.8, title_pad=0.18, body_y_frac=0.38):
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
        y + h - title_pad,
        title,
        ha="center",
        va="top",
        fontsize=title_fs,
        color=title_color,
        fontweight="bold",
        zorder=3,
    )
    ax.text(
        x + w / 2,
        y + h * body_y_frac,
        code,
        ha="center",
        va="center",
        fontsize=code_fs,
        color="#333333",
        linespacing=1.25,
        zorder=3,
    )


def main():
    configure_fonts()
    # Snake layout: row1 ①→②→③→④; CAW right of ④; ⑤ under ④; row2 ⑤→⑥→⑦ (R→L).
    fig_w, fig_h = 170 * MM, 105 * MM
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, 17.4)
    ax.set_ylim(0, 10.0)
    ax.axis("off")
    ax.set_title("系统架构与数据流（附录）", fontsize=9, pad=4)

    box_w, box_h = 3.12, 2.28
    gap = 0.32
    top_y = 6.40
    bot_y = 1.55
    x0 = 0.30

    top_keys = ["scene", "buffer", "phase", "plan"]
    top_nodes = [n for k in top_keys for n in NODES if n["key"] == k]
    xs_top = [x0 + i * (box_w + gap) for i in range(4)]
    for x, n in zip(xs_top, top_nodes):
        draw_box(
            ax, x, top_y, box_w, box_h, n["title"], n["code"],
            fc="#E8F1DE", ec="#3D5A2A",
        )

    # CAW to the RIGHT of ④, short dashed link into its left side.
    plan = next(n for n in NODES if n["key"] == "plan")
    s = plan["secondary"]
    caw_w, caw_h = 3.05, 2.35
    caw_gap = 0.28
    caw_x = xs_top[3] + box_w + caw_gap
    caw_y = top_y + (box_h - caw_h) / 2
    from matplotlib.patches import FancyBboxPatch as _FBP
    ax.add_patch(_FBP(
        (caw_x, caw_y), caw_w, caw_h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=LW, facecolor="#F2F2F2", edgecolor="#888888",
        mutation_aspect=0.5, zorder=2,
    ))
    ax.text(caw_x + caw_w / 2, caw_y + caw_h - 0.18, "CAW-A*",
            ha="center", va="top", fontsize=6.8, color="#555555",
            fontweight="bold", zorder=5)
    ax.text(caw_x + caw_w / 2, caw_y + caw_h - 0.44, "（实现手段）",
            ha="center", va="top", fontsize=6.2, color="#555555", zorder=5)
    ax.text(caw_x + caw_w / 2, caw_y + 0.58,
            "planner_api.py\nplanning/routing3d.py\nplanning/order.py",
            ha="center", va="center", fontsize=5.5, color="#333333",
            linespacing=1.4, zorder=5)

    # Bottom row R→L: ⑤ under ④, then ⑥ left, then ⑦ left.
    bot_keys = ["exec", "eval", "freeze"]  # drawn as ⑤,⑥,⑦ positions
    bot_nodes = [n for k in bot_keys for n in NODES if n["key"] == k]
    xs_bot = [
        xs_top[3],                          # ⑤ under ④
        xs_top[3] - (box_w + gap),          # ⑥
        xs_top[3] - 2 * (box_w + gap),      # ⑦
    ]
    for x, n in zip(xs_bot, bot_nodes):
        draw_box(
            ax, x, bot_y, box_w, box_h, n["title"], n["code"],
            fc="#E8F1DE", ec="#3D5A2A",
        )

    def arrow(x1, y1, x2, y2, *, dashed=False, color="#333333", lw=1.15):
        # Short gap so the shaft does not sit on the box border.
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(
                arrowstyle="->",
                lw=lw,
                color=color,
                linestyle="--" if dashed else "-",
                shrinkA=1.5,
                shrinkB=1.5,
            ),
            zorder=3,
        )

    # Row1 L→R
    y_mid_top = top_y + box_h / 2
    for i in range(3):
        arrow(xs_top[i] + box_w, y_mid_top, xs_top[i + 1], y_mid_top)

    # ④ → CAW (rightward, dashed)
    arrow(
        xs_top[3] + box_w, y_mid_top,
        caw_x, caw_y + caw_h / 2,
        dashed=True, color="#888888", lw=0.95,
    )

    # ④ → ⑤ straight down
    arrow(
        xs_top[3] + box_w / 2, top_y,
        xs_bot[0] + box_w / 2, bot_y + box_h,
    )

    # Row2 R→L: ⑤→⑥→⑦
    y_mid_bot = bot_y + box_h / 2
    arrow(xs_bot[0], y_mid_bot, xs_bot[1] + box_w, y_mid_bot)  # ⑤→⑥ leftward
    arrow(xs_bot[1], y_mid_bot, xs_bot[2] + box_w, y_mid_bot)  # ⑥→⑦ leftward

    ax.add_patch(Rectangle((0.35, 0.28), 0.38, 0.30, facecolor="#E8F1DE", edgecolor="#3D5A2A", lw=LW))
    ax.text(0.88, 0.43, "主流程模块", va="center", fontsize=6.5)
    ax.add_patch(Rectangle((3.9, 0.28), 0.38, 0.30, facecolor="#F2F2F2", edgecolor="#888888", lw=LW))
    ax.text(4.45, 0.43, "次级：CAW-A* 实现手段（非主张主线）", va="center", fontsize=6.5)
    ax.text(
        12.2, 0.43,
        "流向：①→②→③→④↓⑤→⑥→⑦（蛇形）",
        va="center", fontsize=6.0, color="#555555",
    )

    fig.tight_layout(pad=0.3)
    fig.savefig(str(PREFIX) + ".png", dpi=300)
    fig.savefig(str(PREFIX) + ".pdf")
    plt.close(fig)

    commit = git_sha()
    meta = dict(
        figure="B",
        section="§1.8 appendix",
        commit=commit,
        planning_ran=False,
        layout="snake: row1 L→R ①②③④; CAW right of ④; ⑤ under ④; row2 R→L ⑤⑥⑦",
        nodes=[
            {
                "key": n["key"],
                "title": n["title"],
                "code": n["code"].replace("\n", " | "),
                **({"secondary": n["secondary"]} if n.get("secondary") else {}),
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
    caption = f"""图B 系统架构与数据流（附录）。主流程呈蛇形：①场景生成 → ②约束与缓冲 → ③条带相位对齐（S_h 或 B）→ ④规划，再向下至 ⑤执行时间，随后自右向左 ⑥评价（A_extra、时间、violations）→ ⑦冻结复现。灰色框 CAW-A* 置于④右侧，仅作规划步骤的实现手段。各模块标注对应代码路径，依据 ARCHITECTURE.md。本图由脚本生成，未运行规划。

Fig. B System architecture and data flow (appendix). Snake layout: ① scene generation → ② constraints & buffer → ③ strip phase alignment (S_h or B) → ④ planning, then down to ⑤ execution time, then right-to-left ⑥ evaluation (A_extra, time, violations) → ⑦ frozen reproduction. The grey CAW-A* box sits to the right of ④ as an implementation means only. Module labels cite code paths per ARCHITECTURE.md. Generated by script; no planning was run.

脚本 / Script: scripts/figB_system_architecture.py; commit {commit}.
"""
    PREFIX.with_suffix(".caption.md").write_text(caption, encoding="utf-8")
    print("Wrote", PREFIX.with_suffix(".png"))
    print("commit=", commit, "planning_ran=False")
    print("CAW right edge", caw_x + caw_w, "⑤ x", xs_bot[0], "⑦ x", xs_bot[2])


if __name__ == "__main__":
    main()
