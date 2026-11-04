import json, csv, sys, math, time
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from ablation_sort_vs_sort_drift import _inject_downwind_no_spray
from random_scene import generate_with_report
from planning import configuration
from planning.planner import fixed_y_lanes
from planning.drift import drift_cost_buffer, lane_drift_proxy, expand_sensitive_inward
from planning.order import cost_matrix, _order_cost
from planning.planner import fixed_y_lanes
raw = json.load(open("configs/job.ablation.crosswind.json"))
rows = {(int(r["seed"]), r["drift_mode"]): r for r in csv.DictReader(open("results/ablation_sort_vs_sort_drift_54aa1ad.csv"))}
seeds = [int(a) for a in sys.argv[1:]] or [0]
for seed in seeds:
    scene,_ = generate_with_report("ha_orchard", seed, {"plot_width":100.0,"plot_height":100.0})
    scene = _inject_downwind_no_spray(scene)
    out = {}
    for mode in ("sort","sort_drift"):
        c = configuration({**raw, "drift_mode":mode, "buffer_expand":0.0})
        sc = expand_sensitive_inward(scene, c)
        lanes = fixed_y_lanes(sc, c)["lanes"]
        out[mode]=(c, sc, lanes)
    c, sc, lanes = out["sort_drift"]
    b = drift_cost_buffer(c)
    prox = [lane_drift_proxy(l, sc, c, b) for l in lanes]
    heads = {round(math.degrees(math.atan2(l["end"][1]-l["start"][1], l["end"][0]-l["start"][0]))) for l in lanes}
    same_lanes = json.dumps(out["sort"][2], sort_keys=True)==json.dumps(lanes, sort_keys=True)
    # recompute sort-matrix cost of each order (CAW plan uses home at work height; replicate as solve_order default home)
    r_s = rows[(seed,"sort")]; r_d = rows[(seed,"sort_drift")]
    oc_s=float(r_s["order_cost"]); oc_d=float(r_d["order_cost"])
    print(f"seed={seed} n_lanes={len(lanes)} same_lanes={same_lanes} headings={sorted(heads)} buffer={b} "
          f"lanes_hit={sum(p>0 for p in prox)} sum_proxy={sum(prox):.4f} oc_sort={oc_s:.4f} oc_drift={oc_d:.4f} "
          f"oc_drift-sum_proxy={oc_d-sum(prox):.4f} delta={oc_d-oc_s:.4f}")
