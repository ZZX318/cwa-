"""1c：默认 w=2 不变性抽检（seed 0、3 × U=2/4 × S1/S_h/B-boundary 0°，与 2ff2df1 / 0e0715a 行逐项比对 plan_hash 与指标）。"""
import sys, csv, json; sys.path[:0]=['.','scripts']
from concurrent.futures import ProcessPoolExecutor
import a_trial_extra_runs as X, a_trial_heading as H
assert "A_TRIAL_SWATH" not in __import__('os').environ and H.JOB["swath"]==2 and isinstance(H.JOB["swath"],int)
jobs=[dict(seed=s,U=U,heading=0,variant="sweep0",kind=k) for s in (0,3) for U in (2.0,4.0) for k in ("s1","heuristic","b_boundary")]
ref={}
for r in csv.DictReader(open('results/a_trial_seeds0-4_2ff2df1.csv')):
    if r['heading']=='0' and (r['variant']=='heuristic' or (r['variant']=='main' and float(r['offset'])==0)):
        ref[('s1' if r['variant']=='main' else 'heuristic',int(r['seed']),float(r['U']))]=r
for r in csv.DictReader(open('results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv')):
    if r['variant']=='b_boundary' and r['heading']=='0': ref[('b_boundary',int(r['seed']),float(r['U']))]=r
with ProcessPoolExecutor(6) as ex:
    for j,(row,g) in zip(jobs, ex.map(X._sweep0_run, jobs)):
        R=ref[(j['kind'],j['seed'],j['U'])]
        keys=("plan_hash","A_extra_tau0","A_extra_tau0.5","A_extra_tau1","total_time","path_length","cut_segments","violations")
        same={k: str(row[k])==R[k] for k in keys}
        print(j['kind'],j['seed'],j['U'],row['plan_hash'],all(same.values()), {k:(row[k],R[k]) for k,v in same.items() if not v})
