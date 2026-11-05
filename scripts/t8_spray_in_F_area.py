"""T8 no_wind_awareness: exact spray-footprint ∩ F area (m²). 「新增，不改已冻结主表」
Footprint = union of τ=0 spray rectangles (segment ± swath/2). Exact area via
planning.zones._clip_polygon_to_rect (Sutherland–Hodgman, same clip used by the
safety positive-overlap test) + _shoelace_area, summed over (rect, F polygon).
Overlapping spray rects are first merged into an exact interior-disjoint union
(x-strip sweep); F polygons are asserted pairwise disjoint (checked on the 0.05 m raster), so the sum equals the union area.
Raster |P ∩ F| at 0.05 m (a_trial_eval.Raster, same as A_CFP) is reported as cross-check.
"""
import csv, json, math, statistics, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from a_trial_eval import buffer_set, Raster
from planning import configuration, generate_plan
from planning.zones import _clip_polygon_to_rect, _shoelace_area
from random_scene import generate_with_report
from wind_baseline_T8 import JOB, CONDITIONS, NEW_CONDITION

def rects_of(segments, half):
    out = []
    for s in segments:
        if not s.get("spray"):
            continue
        (ax, ay), (bx, by) = s["start"][:2], s["end"][:2]
        if abs(ax - bx) > 1e-9 and abs(ay - by) > 1e-9:
            raise AssertionError("non axis-aligned spray segment")
        if abs(ax - bx) <= 1e-9:
            out.append(((ax - half, min(ay, by)), (ax + half, max(ay, by))))
        else:
            out.append(((min(ax, bx), ay - half), (max(ax, bx), ay + half)))
    return out

def disjoint_union(rs):
    """Exact union of axis-aligned rects as interior-disjoint rects (x-strip sweep)."""
    xs = sorted({r[0][0] for r in rs} | {r[1][0] for r in rs})
    out = []
    for x0, x1 in zip(xs, xs[1:]):
        if x1 - x0 <= 1e-12:
            continue
        iv = sorted((r[0][1], r[1][1]) for r in rs if r[0][0] <= x0 + 1e-12 and r[1][0] >= x1 - 1e-12)
        cur = None
        for a, b in iv:
            if cur and a <= cur[1]:
                cur[1] = max(cur[1], b)
            else:
                if cur: out.append(((x0, cur[0]), (x1, cur[1])))
                cur = [a, b]
        if cur: out.append(((x0, cur[0]), (x1, cur[1])))
    return out

def run(seed):
    scene, _ = generate_with_report("ha_orchard", seed, dict(plot_width=100.0, plot_height=100.0))
    scene = _inject_downwind_no_spray(scene)
    raw = {**JOB, **CONDITIONS[NEW_CONDITION], "drift_mode": "sort"}
    c = configuration(raw)
    plan = generate_plan(scene, raw)
    assert plan["status"] == "success"
    half = c["swath"] / 2.0
    F = buffer_set(scene, 10.0, c["wind_direction"])
    rs = rects_of(plan["segments"], half)
    disj = disjoint_union(rs)
    exact = math.fsum(_shoelace_area(_clip_polygon_to_rect(f["vertices"], *r0, *r1))
                      for (r0, r1) in disj for f in F)
    R = Raster(scene, 0.05)
    masks = [R.polys([f["vertices"]]) for f in F]
    for i in range(len(masks)):
        for j in range(i + 1, len(masks)):
            assert not (masks[i] & masks[j]).any(), "F polygons overlap"
    Fm = R.polys([f["vertices"] for f in F])
    P = R.rects([((r0[0] + half, r0[1]), (r0[0] + half, r1[1])) if abs((r1[0]-r0[0]) - 2*half) < 1e-9
                 else ((r0[0], r0[1] + half), (r1[0], r0[1] + half)) for r0, r1 in rs], half)
    raster = float((P & Fm).sum() * R.cell)
    return dict(seed=seed, condition=NEW_CONDITION, eval_d=10.0, A_spray_in_F_exact_m2=exact,
                A_spray_in_F_raster005_m2=raster, n_spray_rects=len(rs), n_union_rects=len(disj), n_F=len(F))

def main():
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    with ProcessPoolExecutor(4) as ex:
        rows = sorted(ex.map(run, range(30)), key=lambda r: r["seed"])
    pre = ROOT / "results" / f"T8_no_wind_spray_in_F_area_{sha}"
    with pre.with_suffix(".csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    summ = {}
    for k in ("A_spray_in_F_exact_m2", "A_spray_in_F_raster005_m2"):
        v = [r[k] for r in rows]
        summ[k] = dict(n=len(v), mean=statistics.fmean(v), sd=statistics.stdev(v), min=min(v), max=max(v))
    summ["max_abs_exact_minus_raster"] = max(abs(r["A_spray_in_F_exact_m2"] - r["A_spray_in_F_raster005_m2"]) for r in rows)
    summ["base_commit"] = sha
    pre.with_suffix(".summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))

if __name__ == "__main__":
    main()
