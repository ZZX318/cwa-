"""最小复现：w=4、d=10(U=2)、0°、S1(偏移 0) 下 safety 报「目标缺少有效喷洒关联」的原因。

只读探针，不改 planning/。对每个 seed：
1) 照 a_trial_heading.run 的配置调用 caw 规划器，记录 status/reason；
2) 列出 safety 报缺失的目标：圆心/半径、它所在的 fixed-y 条带、该条带被禁喷切割后的各段、
   哪个 spray 段关联了它（应为无）；
3) 对同一目标跑 zones.classify 的两类候选（候选 1 = 树心短带；候选 2 = fixed-y 条带切段），
   说明 classify 为何不把它排除。
用法：python scripts/s1_w4_reject_probe.py [--seeds 0,1,2,3,4] [--swath 4] [--U 2]
"""
from __future__ import annotations
import sys, json, argparse, math, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", default="0,1,2,3,4")
ap.add_argument("--swath", type=float, default=4.0)
ap.add_argument("--U", type=float, default=2.0)
ap.add_argument("--offset", type=float, default=0.0)
ap.add_argument("--plan", action="store_true", help="同时跑完整 caw 规划并与 safety 报的缺失名单逐一比对（慢，每 seed 1–3 min）")
ap.add_argument("--csv", default="", help="可选：sweep CSV，从中取该 seed 的 S1 失败 reason 做比对")
ap.add_argument("--brief", action="store_true", help="只打印每 seed 摘要")
args = ap.parse_args()

import a_trial_heading as H
H.apply_swath_override(args.swath)
H.install_lane_offset(args.offset)
import planning.planner as pp
from planning import configuration
from planning.drift import expand_sensitive_inward, resolve_effective_buffer
from planning.footprint import overlaps_target, rectangle
from planning import zones as Z
from planner_api import make_planner

out = []
for seed in [int(s) for s in args.seeds.split(",")]:
    scene = H.scene0(seed)
    raw = {**H.JOB, "drift_mode": "sort", "wind_speed": args.U, "wind_direction": 0.0, "buffer_expand": 1.0}
    c = configuration(raw)
    d = resolve_effective_buffer(c)
    geo = expand_sensitive_inward(scene, c)
    lay = pp.fixed_y_lanes(geo, c)
    rec = dict(seed=seed, swath=c["swath"], d=d, offset=args.offset)
    if args.plan:
        plan = make_planner("caw").plan(scene, raw, options=H.OPTIONS)
        rec.update(status=plan.get("status"), stage=plan.get("stage"), reason=plan.get("reason"))
        missing = sorted(set(re.findall(r"'([^']+)'", plan.get("reason") or "")))
    elif args.csv:
        import csv as _csv
        rows = [r for r in _csv.DictReader(open(ROOT / args.csv, encoding="utf8"))
                if r["variant"] == "s1" and int(r["seed"]) == seed and float(r["U"]) == args.U]
        rec.update(status=rows[0]["status"], stage=rows[0]["stage"], reason=rows[0]["reason"], reason_source=args.csv)
        missing = sorted(set(re.findall(r"'([^']+)'", rows[0]["reason"] or "")))
    else:
        missing = []
    # 与规划同口径的关联：遍历所有 lane → lane_parts → spray 段的 target_ids
    assoc = {}
    for li, lane in enumerate(lay["lanes"]):
        for part in pp.lane_parts(geo, lane, c):
            if part["type"] == "spray":
                for tid in part["target_ids"]:
                    assoc.setdefault(tid, []).append(li)
    truth = Z.classify(scene, c)
    ids = [t["id"] for t in scene["targets"]]
    geom_missing = sorted(t for t in ids if t not in assoc and t not in truth)
    rec["geom_missing"] = geom_missing
    rec["safety_missing"] = missing
    rec["geom_missing_equals_safety_missing"] = geom_missing == missing if rec.get("status") is not None else None
    xmin = min(t["geometry"]["center"][0] - t["geometry"]["radius"] for t in geo["targets"])
    rec["lane_anchor_xmin"] = round(xmin - args.offset, 6)
    # 与禁喷区正面积相交而整段变 transit 的条带（被切的条带）
    cut = sorted({round(l["start"][0], 6) for l in lay["lanes"]
                  if not any(p["type"] == "spray" for p in pp.lane_parts(geo, l, c))})
    rec["fully_cut_lane_x"] = [[x, [round(x - c["swath"] / 2, 6), round(x + c["swath"] / 2, 6)]] for x in cut]
    nsz = [dict(id=z["id"], xy=[[round(v, 4) for v in p] for p in z["footprint"]["vertices"]]) for z in geo.get("no_spray_zones", [])]
    rec["no_spray_zones_expanded"] = nsz
    tg = {t["id"]: t for t in geo["targets"]}
    det = []
    for tid in geom_missing[:3] + geom_missing[-1:]:
        g = tg[tid]["geometry"]
        cx, cy = g["center"]; r = g["radius"]
        lanes_with = [(li, lane) for li, lane in enumerate(lay["lanes"]) if tid in lane["target_ids"]]
        L = []
        for li, lane in lanes_with:
            x = lane["start"][0]
            parts = pp.lane_parts(geo, lane, c)
            L.append(dict(lane=li, x=round(x, 6), x_band=[round(x - c["swath"] / 2, 6), round(x + c["swath"] / 2, 6)],
                          lane_y=[round(lane["start"][1], 4), round(lane["end"][1], 4)],
                          parts=[dict(type=p["type"], y=[round(p["start"][1], 4), round(p["end"][1], 4)],
                                      covers_tree=overlaps_target(rectangle(p, c["swath"]), g),
                                      tid_in_part=tid in p["target_ids"]) for p in parts]))
        # classify 候选
        anf = Z.active_no_fly(geo, c, Z.work_height(geo, c))
        cands = Z._spray_candidates(geo, c, tg[tid], anf)
        det.append(dict(target=tid, center=[round(cx, 4), round(cy, 4)], radius=round(r, 4),
                        crown_x=[round(cx - r, 4), round(cx + r, 4)], lanes=L,
                        classify_candidates=[dict(x=round(p["start"][0], 4), y=[round(p["start"][1], 4), round(p["end"][1], 4)])
                                             for p in cands],
                        classify_entry=truth.get(tid)))
    rec["detail"] = det
    # 对全部缺失目标：classify 判其可喷所依据的候选是否全部来自「树心短带」（候选 1），
    # 而 fixed-y 布局中覆盖它的条带全部被禁喷切成 transit（候选 2 为空）
    anf = Z.active_no_fly(geo, c, Z.work_height(geo, c))
    lane_xs = {round(l["start"][0], 9) for l in lay["lanes"]}
    chk = []
    for tid in geom_missing:
        g = tg[tid]["geometry"]
        cands = Z._spray_candidates(geo, c, tg[tid], anf)
        chk.append(dict(target=tid, cx=round(g["center"][0], 4), crown_xmax=round(g["center"][0] + g["radius"], 4),
                        tree_centred_band=[round(g["center"][0] - c["swath"] / 2, 4), round(g["center"][0] + c["swath"] / 2, 4)],
                        n_cand=len(cands),
                        all_cands_tree_centred=all(abs(p["start"][0] - g["center"][0]) < 1e-9 for p in cands),
                        any_cand_on_fixed_lane=any(round(p["start"][0], 9) in lane_xs for p in cands)))
    rec["missing_classify_basis"] = chk
    rec["all_missing_eligible_only_via_tree_centred_candidate"] = all(
        x["n_cand"] > 0 and x["all_cands_tree_centred"] and not x["any_cand_on_fixed_lane"] for x in chk)
    out.append(rec)
    print("SUMMARY", json.dumps(dict(w=c["swath"], U=args.U, d=d, seed=seed, offset=args.offset, status=rec.get("status"),
                          lane_anchor_xmin=rec["lane_anchor_xmin"], fully_cut_lane_x=rec["fully_cut_lane_x"],
                          n_geom_missing=len(geom_missing), same_as_safety=rec["geom_missing_equals_safety_missing"],
                          only_tree_centred=rec["all_missing_eligible_only_via_tree_centred_candidate"]),
                     ensure_ascii=False))
if not args.brief:
    print(json.dumps(out, ensure_ascii=False, indent=1))
