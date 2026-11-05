#!/usr/bin/env python3
"""T5 只读探针：w=4 航道数双峰原因（假设 2w=8 m = 行距）。

数据：results/a_trial_1c_sweep_7e7318e.rows.csv（commit d0d41d3）+ scene0(ha_orchard)。
不改 planning/ 磁盘文件；仅内存内安装 lane offset（同 a_trial_heading.install_lane_offset）。

用法：python3 scripts/probes/t5_w4_lane_bimodality.py
写：results/t5_w4_lane_bimodality.json
"""
from __future__ import annotations

import csv
import inspect
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import a_trial_heading as H  # noqa: E402
import planning.planner as pp  # noqa: E402

W = 4.0
CSV = ROOT / "results/a_trial_1c_sweep_7e7318e.rows.csv"
OUT = ROOT / "results/t5_w4_lane_bimodality.json"
_ORIG = inspect.getsource(pp.fixed_y_lanes)
NEEDLE = '    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in targets)\n'


def row_centers(scene):
    xs = sorted(t["geometry"]["center"][0] for t in scene["targets"])
    clusters, cur = [], [xs[0]]
    for a, b in zip(xs, xs[1:]):
        if b - a > 3.0:
            clusters.append(cur)
            cur = [b]
        else:
            cur.append(b)
    clusters.append(cur)
    return [sum(c) / len(c) for c in clusters]


def lanes_at(scene, offset, w=W):
    assert _ORIG.count(NEEDLE) == 1
    src = _ORIG.replace(NEEDLE, NEEDLE + f"    xmin = xmin - {float(offset)!r}\n")
    ns = {}
    exec(compile(src, "<t5_offset>", "exec"), pp.__dict__, ns)
    lay = ns["fixed_y_lanes"](scene, {**H.JOB, "swath": w, "buffer_expand": 0.0})
    byx = defaultdict(list)
    for lane in lay["lanes"]:
        byx[round(lane["start"][0], 6)].append(len(lane["target_ids"]))
    return dict(
        strip_count=lay["strip_count"],
        n_lanes=len(lay["lanes"]),
        strips={str(x): dict(n_seg=len(v), n_targets=sum(v)) for x, v in sorted(byx.items())},
        seg_per_strip_hist=dict(sorted(Counter(len(v) for v in byx.values()).items())),
        n_full16=sum(1 for v in byx.values() if len(v) == 16),
        n_sparse=sum(1 for v in byx.values() if len(v) < 16),
    )


def main():
    rows = [r for r in csv.DictReader(open(CSV, encoding="utf8")) if float(r["w"]) == W]
    assert rows, "no w=4 rows"
    high, low = [], []
    for r in rows:
        rec = dict(
            scheme=r["scheme"],
            U=float(r["U"]),
            d=float(r["d"]),
            seed=int(r["seed"]),
            offset=float(r["offset"]),
            n_lanes=int(r["n_lanes"]),
            status=r["status"],
        )
        (high if rec["n_lanes"] > 300 else low).append(rec)

    scenes = {}
    geom = []
    for seed in range(5):
        sc = H.scene0(seed)
        scenes[seed] = sc
        p = sc["source"]["parameters"]
        cents = row_centers(sc)
        diffs = [cents[i + 1] - cents[i] for i in range(len(cents) - 1)]
        geom.append(
            dict(
                seed=seed,
                row_spacing_param=p["row_spacing"],
                plant_spacing=p["plant_spacing"],
                n_rows=p["rows"],
                n_clusters=len(cents),
                mean_pitch=sum(diffs) / len(diffs),
                centers=[round(c, 4) for c in cents],
            )
        )
        assert abs(p["row_spacing"] - 8.0) < 1e-12
        assert abs(p["row_spacing"] - 2 * W) < 1e-12

    # representative offsets from CSV modes
    probes = []
    for label, offset in (
        ("low_S1_offset0", 0.0),
        ("high_B_offset1p88", 1.88),
        ("low_Sh_U2_offset3p88", 3.88),
    ):
        info = lanes_at(scenes[0], offset)
        info["label"] = label
        info["offset"] = offset
        probes.append(info)

    # CSV ↔ probe consistency for seed0 known rows
    csv_s0 = {(r["scheme"], float(r["U"])): r for r in rows if int(r["seed"]) == 0}
    consistency = []
    for (sch, U), expect_off_key in (
        (("S1", 2.0), "low_S1_offset0"),
        (("B", 2.0), "high_B_offset1p88"),
        (("S_h", 2.0), "low_Sh_U2_offset3p88"),
        (("S_h", 4.0), "high_B_offset1p88"),  # U=4 S_h offset≈1.88 same phase as B
    ):
        r = csv_s0[(sch, U)]
        pr = next(p for p in probes if p["label"] == expect_off_key)
        consistency.append(
            dict(
                scheme=sch,
                U=U,
                csv_n_lanes=int(r["n_lanes"]),
                csv_offset=float(r["offset"]),
                probe_n_lanes=pr["n_lanes"],
                probe_offset=pr["offset"],
                n_lanes_match=int(r["n_lanes"]) == pr["n_lanes"],
            )
        )
    # S1/B exact; S_h U=2 offset is 3.88 vs CSV 3.88 — should match n_lanes
    assert consistency[0]["n_lanes_match"], consistency[0]
    assert consistency[1]["n_lanes_match"], consistency[1]
    assert consistency[2]["n_lanes_match"], consistency[2]
    assert consistency[3]["n_lanes_match"], consistency[3]

    conclusion_tag = "【已验证】"
    conclusion = (
        f"{conclusion_tag} w=4 航道数双峰（约 206–218 vs 恒为 384）的根因是 "
        f"2w = 8 m = ha_orchard 名义行距 row_spacing：偏移相位决定「每行 1 条满载航带 + 行间稀疏条带」"
        f"还是「每行被 2 条满载航带双覆盖」。"
        f"高峰：offset≈w/2（CSV 1.86–2.15）时 24 条航带均含 16 段 → 24×16=384；"
        f"低峰：offset≈0 或 ≈w（CSV 0 / 3.86–3.90）时仅约 12 条满载（对正树行）+ 行间抖动擦边稀疏段 → ~210。"
        f"fixed_y_lanes 对无冠层相交的条带直接 skip；行间条带因 jitter 常仍有 1–5 段，故 strip_count 并非减半，"
        f"减半的是满载段数。不改代码。"
    )

    evidence = dict(
        source_csv=str(CSV.relative_to(ROOT)),
        source_commit_note="d0d41d3 (1c-sweep delivery; file present at baseline 463badb)",
        hypothesis="2w = 8 m = row_spacing",
        csv_modes=dict(
            high=dict(
                n=len(high),
                n_lanes=sorted({x["n_lanes"] for x in high}),
                offsets_rounded=sorted({round(x["offset"], 3) for x in high}),
                schemes=sorted({x["scheme"] for x in high}),
                rows=high,
            ),
            low=dict(
                n=len(low),
                n_lanes=sorted({x["n_lanes"] for x in low}),
                offsets_rounded=sorted({round(x["offset"], 3) for x in low}),
                schemes=sorted({x["scheme"] for x in low}),
                rows=low,
            ),
        ),
        geometry=geom,
        seed0_offset_probes=[{k: v for k, v in p.items() if k != "strips"} | {"n_strips": len(p["strips"])} for p in probes],
        seed0_probe_strips_detail={p["label"]: p["strips"] for p in probes},
        csv_probe_consistency=consistency,
        mechanism=(
            "Because lane pitch w and row pitch 2w lock, offset mod w selects whether strip centers "
            "sit near tree rows (one full 16-seg strip per row + sparse mid-gap leftovers) or midway "
            "so two adjacent strips each fully cover the same 16-tree row (24×16=384)."
        ),
        conclusion=conclusion,
        conclusion_tag=conclusion_tag,
        planning_untouched=True,
    )
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf8")
    print(conclusion)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
