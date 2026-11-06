"""图1、图2 重绘到 results/repro_main/（不覆盖入库图），并抽取图注数字。只读场景/CSV/geom，不规划。

图1：scripts/figA_scene_construction.py（模块 PREFIX 改指向输出目录后调用 main()）。
图2：scripts/fig1b_noninteger_buffer_lanes.py（同上）。两脚本本身未改。
需 matplotlib（/workspace/.venv-fig/bin/python）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
from p8_common import ROOT, REFERENCE_PNGS, read_csv, select, sha256  # noqa: E402


def _png_compare(new: Path, ref_rel: str) -> dict:
    import numpy as np
    import matplotlib.image as mpimg
    ref = ROOT / ref_rel
    out = dict(new_png=str(new.relative_to(ROOT)) if new.is_relative_to(ROOT) else str(new), new_sha256=sha256(new),
               ref_png=ref_rel, ref_sha256=REFERENCE_PNGS[ref_rel])
    out["bytes_identical"] = out["new_sha256"] == out["ref_sha256"]
    a, b = mpimg.imread(str(new)), mpimg.imread(str(ref))
    out["shape_new"], out["shape_ref"] = list(a.shape), list(b.shape)
    if a.shape == b.shape:
        diff = np.abs(a.astype(float) - b.astype(float))
        out["pixels_differing"] = int((diff.max(axis=-1) > 0).sum()) if diff.ndim == 3 else int((diff > 0).sum())
        out["max_abs_diff"] = float(diff.max())
    return out


def render_fig1(out_dir: Path) -> dict:
    import figA_scene_construction as F
    F.PREFIX = out_dir / "fig1_scene_construction"
    F.main()
    meta = json.loads(F.PREFIX.with_suffix(".json").read_text(encoding="utf-8"))
    ref = json.loads((ROOT / "results/figA_scene_construction.json").read_text(encoding="utf-8"))
    strip = lambda m: {k: v for k, v in m.items() if k not in ("commit", "outputs")}  # noqa: E731
    # x_F at the d=16 tier (caption: layout unchanged, x_F 9 → 15), same buffer function the figure uses.
    import a_trial_heading as H
    import a_trial_eval as ev
    F16 = ev.buffer_set(H.scene0(0), 16.0, 0.0)
    xF16 = max(v[0] for f in F16 if f["swept"] for v in f["vertices"])
    return dict(meta=meta, meta_equal_reference_except_commit_and_paths=(strip(meta) == strip(ref)),
                x_F_d16=xF16, png=_png_compare(F.PREFIX.with_suffix(".png"), "results/figA_scene_construction.png"))


def render_fig2(out_dir: Path) -> dict:
    import fig1b_noninteger_buffer_lanes as G
    G.PREFIX = out_dir / "fig2_noninteger_buffer_lanes"
    G.main()
    rep = json.loads(Path(str(G.PREFIX) + ".json").read_text(encoding="utf-8"))
    ref = json.loads((ROOT / "results/fig1b_noninteger_buffer_lanes.json").read_text(encoding="utf-8"))
    rows = read_csv("results/F2_noninteger_dw_71278c2.csv")
    csvchk = {}
    for m, var in (("S_h", "heuristic"), ("B-boundary(0°)", "b_boundary")):
        r = select(rows, seed="0", variant=var, d=11.0, U=2.0, heading="0")
        assert len(r) == 1
        r = r[0]
        c = rep["checks"][m]
        csvchk[m] = dict(plan_hash=c["plan_hash"] == r["plan_hash"],
                         A_extra_tau0=c["A_extra_tau0"] == float(r["A_extra_tau0"]),
                         total_time=c["total_time"] == float(r["total_time"]),
                         offset=c["offset"] == float(r["offset"]),
                         first_lane_center=r["heuristic_first_lane_center"], w=float(r["w"]),
                         seed=int(r["seed"]), U=float(r["U"]), heading=float(r["heading"]), d=float(r["d"]))
    return dict(report=rep, checks_equal_reference=(rep["checks"] == ref["checks"]),
                cut_geometry_equal_reference=(rep["cut_geometry"] == ref["cut_geometry"]),
                csv_checks=csvchk,
                png=_png_compare(Path(str(G.PREFIX) + ".png"), "results/fig1b_noninteger_buffer_lanes.png"))
