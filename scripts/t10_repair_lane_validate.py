"""「新增，不改已冻结主表」: S1 control/repair and w=2 frozen-HEAD proof."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import a_trial_heading as H
from planning.model import configuration, fingerprint, config_fingerprint
from planning.planner import generate_plan, maybe_append_repair_lanes, lane_parts
import planning.planner as pp
from planning.drift import expand_sensitive_inward, resolve_effective_buffer
from planning.safety import check, _drift_ray_violations
from planning.zones import classify

LABEL = '「新增，不改已冻结主表」'
# Live generate_plan on 463badb (probe offset=0); a609968 capture was stale (it already carried min_buffer=0).
BASELINE = {'0': {'plan_hash': 'bd031af9dcccc87fdeeffeac7a1c6b0be95908f4a0b9ce8a71186c1fd5895d70', 'segments_digest': '218d5208975e962d44c304cf15a5e10e9ecda889f90f53ac68afe5b9d223d412'}, '1': {'plan_hash': '505c3aa2a714635f274b8bbb2a79c74251c93f81e3a858c3d13c0b74fee4cc27', 'segments_digest': 'cc17a21cb3072f98c6770d525f901136257f6c0bc0d4b53fc1f918569532e1d6'}, '4': {'plan_hash': '38db9f4431debca48fd0461e233cb648000818e09d26a4f53f18dd942773d3e2', 'segments_digest': '4fc9373d01e0150a9d7232a1dcd4b0880dfa43443f52dc6d0cef5ed80338b838'}}


def run():
    H.install_lane_offset(0)
    rows = []
    for flag in (0, 1):
        for seed in range(5):
            scene = H.scene0(seed)
            raw = {**H.JOB, 'swath': 4, 'wind_speed': 2, 'wind_direction': 0,
                   'buffer_expand': 1, 'drift_mode': 'sort', 'repair_lanes': flag}
            c = configuration(raw)
            geo = expand_sensitive_inward(scene, c)
            layout = pp.fixed_y_lanes(geo, c)
            repaired = maybe_append_repair_lanes(geo, layout, c)
            associated = {tid for lane in repaired['lanes'] for part in lane_parts(geo, lane, c)
                          if part.get('spray') for tid in part['target_ids']}
            missing = sorted({t['id'] for t in scene['targets']} - associated - set(classify(scene, c)))
            p = generate_plan(scene, raw)
            violations = None
            drift_bad = None
            if p['status'] == 'success':
                check(scene, p)  # Raises on any safety violation; failed plans are not counted as zero.
                violations = 0
                _, drift_hits = _drift_ray_violations(scene, p['segments'], resolve_effective_buffer(c), 0, 4)
                drift_bad = len(drift_hits)
            row = dict(seed=seed, repair_lanes=flag, swath=4, U=2, d=resolve_effective_buffer(c),
                       offset=0, status=p['status'], reason=p.get('reason'), geom_missing=missing,
                       appended_lanes=len(repaired['lanes'])-len(layout['lanes']),
                       safety_violations=violations, drift_violations=drift_bad)
            rows.append(row)
            print(json.dumps(dict(label=LABEL, **row), ensure_ascii=False), flush=True)
    proofs = []
    for seed in (0, 1, 4):
        p = generate_plan(H.scene0(seed), {**H.JOB, 'swath': 2, 'wind_speed': 2,
                          'wind_direction': 0, 'buffer_expand': 1, 'drift_mode': 'sort', 'repair_lanes': 0})
        restored = copy.deepcopy(p)
        restored['config'].pop('repair_lanes', None)
        restored['config_hash'] = config_fingerprint(restored['config'])
        old = BASELINE[str(seed)]
        proof = dict(seed=seed, status=p['status'], baseline=old,
                     segments_digest=fingerprint(p['segments']), plan_hash=fingerprint(p),
                     restored_plan_hash=fingerprint(restored))
        proof['segments_identical'] = proof['segments_digest'] == old['segments_digest']
        proof['restored_hash_identical'] = proof['restored_plan_hash'] == old['plan_hash']
        assert p['status'] == 'success' and proof['segments_identical'] and proof['restored_hash_identical'], proof
        proofs.append(proof)
    for row in rows:
        if row['repair_lanes'] == 0 and row['seed'] in (0, 1, 4):
            assert row['status'] == 'failed' and '目标缺少有效喷洒关联' in row['reason'], row
        if row['repair_lanes'] == 1:
            assert row['status'] == 'success' and row['safety_violations'] == 0 and row['drift_violations'] == 0, row
    result = dict(label=LABEL, baseline_commit='463badb', planner='generate_plan + a_trial_heading offset=0',
                  cases=rows, w2_proofs=proofs)
    sha = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()
    path = ROOT / 'results' / f't10_repair_lane_validate.{sha}.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
