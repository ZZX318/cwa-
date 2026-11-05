"""CAW full plan_hash parity: S_h (variant=heuristic), U=2, heading 0, seeds 0-4, live
a_trial_heading.run (make_planner('caw')) on this HEAD vs frozen results/a_trial_seeds0-4_2ff2df1.csv.
「新增，不改已冻结主表」"""
import csv, json, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import a_trial_heading as H
FROZEN = ROOT / "results/a_trial_seeds0-4_2ff2df1.csv"
def one(seed):
    row, _ = H.run(dict(seed=seed, U=2, heading=0, offset=0.0, variant="heuristic"))
    return row
if __name__ == "__main__":
    frozen = {int(r["seed"]): r for r in csv.DictReader(FROZEN.open())
              if r["variant"] == "heuristic" and float(r["U"]) == 2 and int(r["heading"]) == 0}
    with ProcessPoolExecutor(5) as ex:
        rows = list(ex.map(one, range(5)))
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    out = []
    for r in rows:
        f = frozen[r["seed"]]
        out.append(dict(seed=r["seed"], status=r["status"], frozen_plan_hash=f["plan_hash"], head_plan_hash=r.get("plan_hash"),
                        equal=f["plan_hash"] == r.get("plan_hash"),
                        A_extra_tau0_frozen=f["A_extra_tau0"], A_extra_tau0_head=r.get("A_extra_tau0"),
                        total_time_frozen=f["total_time"], total_time_head=r.get("total_time")))
    Path(ROOT / f"results/caw_plan_hash_parity_{sha}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
