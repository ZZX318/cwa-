"""plan_hash parity: run generate_plan live in this tree; print JSON per seed.
Run in both trees (HEAD and 463badb worktree) and compare. 「新增，不改已冻结主表」"""
import json, sys
from pathlib import Path
ROOT = Path.cwd(); sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import a_trial_heading as H
from planning.model import fingerprint
from planning.planner import generate_plan
out = []
for scheme, off_fn in (("S1", lambda s: 0.0), ("S_h", None)):
    for seed in range(5):
        scene = H.scene0(seed)
        if off_fn is None:
            o, _, _ = H.heuristic_offset(scene, 10.0, 0, 2.0)
        else:
            o = 0.0
        H.install_lane_offset(o)
        raw = {**H.JOB, "swath": 2, "wind_speed": 2, "wind_direction": 0}
        p = generate_plan(scene, raw)
        out.append(dict(scheme=scheme, seed=seed, offset=round(o, 6), status=p["status"],
                        plan_hash=fingerprint(p), segments_digest=fingerprint(p["segments"])))
print(json.dumps(out))
