"""Regression: zones.classify 'unreachable' fallback is gated on repair_lanes=1.
OFF (default) must stay fail-closed; ON labels the target. 「新增，不改已冻结主表」
Run: python3 tests/test_unreachable_gate.py"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import planning.zones as Z
from planning import configuration, generate_plan
from scene.generator import generate  # noqa: E402

def main():
    scene = generate(dict(rows=2, trees_per_row=3))
    scene["no_spray_zones"] = []
    scene["no_fly_zones"] = []
    victim = scene["targets"][0]["id"]
    orig = Z._spray_candidates
    def patched(geo, c, t, nf):  # force the "no legal candidate, no zone overlap" branch
        return [] if t["id"] == victim else orig(geo, c, t, nf)
    Z._spray_candidates = patched
    try:
        off = Z.classify(scene, configuration({}))
        on = Z.classify(scene, configuration({"repair_lanes": 1}))
    finally:
        Z._spray_candidates = orig
    assert victim not in off, off            # default: not exempted -> stays a required target
    assert on[victim]["reason"] == "unreachable" and on[victim]["zone_ids"] == [], on
    assert set(on) - {victim} == set(off), (on, off)
    # Default plan on this scene is unaffected by the gate (no zones -> success, nothing exempt).
    p = generate_plan(scene, {})
    assert p["status"] == "success", p.get("reason")
    print("PASS test_unreachable_gate: OFF not exempted (fail-closed), ON reason=unreachable")

if __name__ == "__main__":
    main()
