"""Figure A: scene-construction panel for paper §1.2 (render only, no planning)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import numpy as np
import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.patches import Circle, Polygon, Patch, FancyArrowPatch, Rectangle
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt

import a_trial_heading as H
import a_trial_eval as ev
from planning.model import configuration
from planning.drift import (
    resolve_effective_buffer,
    expand_sensitive_inward,
    _zone_is_exterior_sensitive,
)
from scene.random_map import build

LW_AXIS = 0.8
PREFIX = ROOT / "results/figA_scene_construction"
MM = 1 / 25.4

# Panel (a): main-experiment scene + demonstrative interior island.
ISLAND = dict(
    id="ns-island-demo",
    kind="polygon_prism",
    footprint=dict(
        kind="polygon",
        vertices=[[45.0, 45.0], [55.0, 45.0], [55.0, 55.0], [45.0, 55.0]],
    ),
    z_min=0.0,
    z_max=10.0,
)

# Panels (b)–(d): style, seed, title fragment.
RANDOM_PANELS = [
    ("jitter_rows", 1),
    ("clusters_gaps", 2),
    ("random_obstacles_zones", 0),
]


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
        assert candidates, "No requested Noto CJK font found"
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
            "axes.titlesize": 7,
            "axes.labelsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 6.5,
            "figure.titlesize": 7,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "axes.linewidth": LW_AXIS,
            "xtick.major.width": LW_AXIS,
            "ytick.major.width": LW_AXIS,
        }
    )


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def main_scene():
    import copy

    scene = copy.deepcopy(H.scene0(0))
    scene["no_spray_zones"] = list(scene.get("no_spray_zones") or []) + [
        json.loads(json.dumps(ISLAND))
    ]
    raw = {
        **H.JOB,
        "buffer_expand": 1.0,
        "wind_speed": 2.0,
        "wind_direction": 0.0,
    }
    cfg = configuration(raw)
    d = resolve_effective_buffer(cfg)
    assert d == 10.0, d
    expanded = expand_sensitive_inward(scene, cfg)
    F = ev.buffer_set(scene, d, 0.0)
    # Geometry assertions: exterior expands to x_F=9; island unchanged.
    by_id = {z["id"]: z for z in scene["no_spray_zones"]}
    exp_by_id = {z["id"]: z for z in expanded["no_spray_zones"]}
    assert _zone_is_exterior_sensitive(by_id["ns-ablation"], scene["plot"], d)
    assert not _zone_is_exterior_sensitive(by_id["ns-island-demo"], scene["plot"], d)
    assert max(v[0] for v in exp_by_id["ns-ablation"]["footprint"]["vertices"]) == 9.0
    assert (
        by_id["ns-island-demo"]["footprint"]["vertices"]
        == exp_by_id["ns-island-demo"]["footprint"]["vertices"]
    )
    f_map = {f["id"]: f for f in F}
    assert f_map["ns-ablation"]["swept"] is True
    assert f_map["ns-island-demo"]["swept"] is False
    assert max(v[0] for v in f_map["ns-ablation"]["vertices"]) == 9.0
    return scene, expanded, F, d, cfg


def draw_canopies(ax, scene, face="#D9E9C5", edge="#365B35", lw=0.35):
    for t in scene["targets"]:
        g = t["geometry"]
        ax.add_patch(
            Circle(
                g["center"][:2],
                g["radius"],
                facecolor=face,
                edgecolor=edge,
                linewidth=lw,
                zorder=2,
            )
        )


def draw_zones(ax, zones, *, face, edge, hatch=None, alpha=0.55, lw=LW_AXIS, zorder=3, label=None):
    for zone in zones:
        ax.add_patch(
            Polygon(
                zone["footprint"]["vertices"],
                facecolor=face,
                edgecolor=edge,
                hatch=hatch,
                linewidth=lw,
                alpha=alpha,
                zorder=zorder,
                label=label,
            )
        )
        label = None


def draw_buffer_rings(ax, F, exterior_zones):
    """Orange F minus Z for swept exterior buffers only."""
    from matplotlib.path import Path as MplPath
    from matplotlib.patches import PathPatch

    swept = [f for f in F if f["swept"]]
    if not swept:
        return
    rings, codes = [], []
    zone_vs = [z["footprint"]["vertices"] for z in exterior_zones]
    for vertices, reverse in [(f["vertices"], False) for f in swept] + [
        (z, True) for z in zone_vs
    ]:
        v = np.asarray(vertices)[:, :2]
        area = np.sum(v[:, 0] * np.roll(v[:, 1], -1) - v[:, 1] * np.roll(v[:, 0], -1))
        if (area > 0) == reverse:
            v = v[::-1]
        rings.extend([*v, v[0]])
        codes.extend(
            [MplPath.MOVETO] + [MplPath.LINETO] * (len(v) - 1) + [MplPath.CLOSEPOLY]
        )
    ax.add_patch(
        PathPatch(
            MplPath(rings, codes),
            facecolor="#F6B65C",
            edgecolor="#D68416",
            alpha=0.40,
            linewidth=LW_AXIS,
            zorder=1,
        )
    )


def panel_a(ax, scene, F, d):
    exterior = [
        z
        for z in scene["no_spray_zones"]
        if _zone_is_exterior_sensitive(z, scene["plot"], d)
    ]
    islands = [
        z
        for z in scene["no_spray_zones"]
        if not _zone_is_exterior_sensitive(z, scene["plot"], d)
    ]
    draw_buffer_rings(ax, F, exterior)
    ax.add_patch(
        Polygon(
            scene["plot"]["vertices"],
            fill=False,
            edgecolor="black",
            linewidth=0.7,
            zorder=4,
        )
    )
    draw_canopies(ax, scene)
    draw_zones(
        ax,
        exterior,
        face="white",
        edge="#802020",
        hatch="////",
        alpha=1.0,
        zorder=3,
    )
    draw_zones(
        ax,
        islands,
        face="#6BAED6",
        edge="#08519C",
        hatch="\\\\\\",
        alpha=0.55,
        zorder=3,
    )
    # Wind-from arrow (wd=0 → from +x). Match fig1 convention: arrow points to wind origin.
    ax.annotate(
        "",
        xy=(92, 92),
        xytext=(68, 92),
        arrowprops=dict(arrowstyle="->", lw=1.2, color="#333333"),
    )
    ax.text(
        80,
        95.5,
        "风来向 U=2 m/s",
        ha="center",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=0.3),
    )
    ax.text(
        -5.2,
        50,
        "园外禁喷",
        rotation=90,
        ha="center",
        va="center",
        color="#802020",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=0.3),
    )
    ax.annotate(
        f"上风缓冲 F (d={d:g} m)",
        xy=(4.5, 80),
        xytext=(22, 84),
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=0.4),
        arrowprops=dict(arrowstyle="-", color="#D68416", lw=LW_AXIS),
    )
    ax.annotate(
        "园内岛状禁喷\n(示意，不外扩)",
        xy=(50, 50),
        xytext=(62, 30),
        color="#08519C",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.92, pad=0.4),
        arrowprops=dict(arrowstyle="-", color="#08519C", lw=LW_AXIS),
    )
    ax.set_aspect("equal")
    ax.set(xlim=(-12, 104), ylim=(-4, 104), title="(a) 主实验果园（ha_orchard seed 0）")
    ax.set_xlabel("x/m")
    ax.set_ylabel("y/m")
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])


def panel_random(ax, style, seed, label):
    scene, meta = build(style, seed, {})
    # Obstacles
    for ob in scene.get("obstacles") or []:
        vs = None
        fp = ob.get("footprint") or {}
        if isinstance(fp, dict) and fp.get("vertices"):
            vs = fp["vertices"]
        elif ob.get("vertices"):
            vs = ob["vertices"]
        if vs:
            ax.add_patch(
                Polygon(
                    vs,
                    facecolor="#C0C0C0",
                    edgecolor="#555555",
                    linewidth=0.5,
                    zorder=2,
                )
            )
            continue
        # box obstacles: top-level min/max (scene.random_map)
        if "min" in ob and "max" in ob:
            x0, y0 = ob["min"][0], ob["min"][1]
            x1, y1 = ob["max"][0], ob["max"][1]
            ax.add_patch(
                Rectangle(
                    (x0, y0),
                    x1 - x0,
                    y1 - y0,
                    facecolor="#C0C0C0",
                    edgecolor="#555555",
                    linewidth=0.5,
                    zorder=2,
                )
            )
    for z in scene.get("no_fly_zones") or []:
        ax.add_patch(
            Polygon(
                z["footprint"]["vertices"],
                facecolor="#F0E6FF",
                edgecolor="#6A3D9A",
                hatch="xx",
                linewidth=0.6,
                alpha=0.7,
                zorder=3,
            )
        )
    for z in scene.get("no_spray_zones") or []:
        ax.add_patch(
            Polygon(
                z["footprint"]["vertices"],
                facecolor="white",
                edgecolor="#802020",
                hatch="////",
                linewidth=0.6,
                zorder=3,
            )
        )
    if "plot" in scene:
        ax.add_patch(
            Polygon(
                scene["plot"]["vertices"],
                fill=False,
                edgecolor="black",
                linewidth=0.6,
                zorder=4,
            )
        )
    draw_canopies(ax, scene, lw=0.3)
    # Auto limits from extent or plot
    if "extent" in scene:
        e = scene["extent"]
        ax.set_xlim(e["min"][0] - 1, e["max"][0] + 1)
        ax.set_ylim(e["min"][1] - 1, e["max"][1] + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("x/m")
    ax.set_ylabel("y/m")
    ax.set_title(f"({label}) {style}（seed {seed}）")
    return dict(
        style=style,
        seed=seed,
        n_targets=len(scene["targets"]),
        n_no_spray=len(scene.get("no_spray_zones") or []),
        n_no_fly=len(scene.get("no_fly_zones") or []),
        n_obstacles=len(scene.get("obstacles") or []),
        generator_version=(scene.get("source") or {}).get("generator_version"),
        source=scene.get("source"),
    )


def main():
    configure_fonts()
    scene, expanded, F, d, cfg = main_scene()

    fig, axes = plt.subplots(2, 2, figsize=(170 * MM, 170 * MM))
    fig.subplots_adjust(
        left=0.07, right=0.98, bottom=0.10, top=0.94, wspace=0.22, hspace=0.28
    )
    panel_a(axes[0, 0], scene, F, d)
    panel_meta = []
    for ax, (style, seed), lab in zip(
        [axes[0, 1], axes[1, 0], axes[1, 1]], RANDOM_PANELS, list("bcd")
    ):
        panel_meta.append(panel_random(ax, style, seed, lab))

    handles = [
        Patch(facecolor="#D9E9C5", edgecolor="#365B35", label="树冠"),
        Patch(
            facecolor="white",
            edgecolor="#802020",
            hatch="////",
            label="园外/贴边禁喷",
        ),
        Patch(
            facecolor="#6BAED6",
            edgecolor="#08519C",
            hatch="\\\\\\",
            label="园内岛状禁喷（示意）",
        ),
        Patch(
            facecolor="#F6B65C",
            alpha=0.4,
            edgecolor="#D68416",
            label=f"上风缓冲 F (d={d:g} m)",
        ),
        Line2D([], [], color="#333333", lw=1.2, label="风来向"),
        Patch(facecolor="#C0C0C0", edgecolor="#555555", label="障碍（随机图）"),
        Patch(
            facecolor="#F0E6FF",
            edgecolor="#6A3D9A",
            hatch="xx",
            label="禁飞区（随机图）",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.005),
        ncol=4,
        frameon=False,
        columnspacing=1.0,
        handlelength=1.8,
    )

    fig.savefig(str(PREFIX) + ".png", dpi=300)
    fig.savefig(str(PREFIX) + ".pdf")
    plt.close(fig)

    commit = git_sha()
    meta = dict(
        figure="A",
        section="§1.2",
        commit=commit,
        planning_ran=False,
        buffer_expand=1.0,
        wind_speed=2.0,
        wind_direction=0.0,
        d_m=d,
        d_tier="U=2 m/s → d=10 m（孔令标 2026，U≤3）",
        panel_a=dict(
            scene="ha_orchard 100x100 seed 0 + _inject_downwind_no_spray + ns-island-demo",
            seed=0,
            style="ha_orchard",
            island_demo=ISLAND,
            island_note="示意注入：主实验默认仅有园外禁喷；为展示园内岛状不外扩而加入 ns-island-demo",
            n_targets=len(scene["targets"]),
            zones=[
                dict(
                    id=z["id"],
                    exterior=_zone_is_exterior_sensitive(z, scene["plot"], d),
                    vertices=z["footprint"]["vertices"],
                )
                for z in scene["no_spray_zones"]
            ],
            F=[
                dict(
                    id=f["id"],
                    swept=f["swept"],
                    vertices=f["vertices"],
                )
                for f in F
            ],
            x_F=max(v[0] for f in F if f["swept"] for v in f["vertices"]),
            x_Z_exterior=max(
                v[0]
                for z in scene["no_spray_zones"]
                if _zone_is_exterior_sensitive(z, scene["plot"], d)
                for v in z["footprint"]["vertices"]
            ),
        ),
        panels_bcd=panel_meta,
        outputs={
            "png": str(PREFIX) + ".png",
            "pdf": str(PREFIX) + ".pdf",
            "caption": str(PREFIX) + ".caption.md",
            "json": str(PREFIX) + ".json",
        },
    )
    PREFIX.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    caption = f"""图A 场景构建示意（主实验与随机地图）。(a) 主实验果园俯视图：ha_orchard，seed 0，buffer_expand=1，风速档 U=2 m/s → 有效缓冲 d=10 m（孔令标 2026 查表）；红色斜线为园外/贴边禁喷区，橙色为沿风来向外扩的上风缓冲带 F，蓝色斜线为园内岛状禁喷示意区（ns-island-demo，仅作图注入，外扩前后几何不变）。箭头指向风来向（wind_direction=0，来自 +x）。(b) jitter_rows，seed 1；(c) clusters_gaps，seed 2；(d) random_obstacles_zones，seed 0。本图仅由场景数据重绘，未运行任何规划。

Fig. A Scene-construction panel (main experiment and random maps). (a) Top view of the main-experiment orchard: ha_orchard, seed 0, buffer_expand=1, wind-speed tier U=2 m/s → effective buffer d=10 m (Kong et al., 2026 lookup). Red hatch: exterior/edge-adjacent no-spray zone; orange: upwind buffer strip F; blue hatch: in-orchard island no-spray demo (ns-island-demo, figure-only injection; geometry unchanged after expansion). Arrow points to the wind-from direction (wind_direction=0, from +x). (b) jitter_rows, seed 1; (c) clusters_gaps, seed 2; (d) random_obstacles_zones, seed 0. Re-rendered from scene data only; no planning was run.

数据与脚本 / Data & script: a_trial_heading.scene0(0); planning.drift.resolve_effective_buffer + expand_sensitive_inward; a_trial_eval.buffer_set; scene.random_map.build; scripts/figA_scene_construction.py; commit {commit}.
"""
    PREFIX.with_suffix(".caption.md").write_text(caption, encoding="utf-8")
    print("Wrote", PREFIX.with_suffix(".png"))
    print("Wrote", PREFIX.with_suffix(".pdf"))
    print("d=", d, "commit=", commit, "planning_ran=False")


if __name__ == "__main__":
    main()
