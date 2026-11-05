"""Fresh-process audit: recompute F3 frozen seed0-4 main contrast hashes.

Compares against a_trial_seeds0-4_2ff2df1.csv / oh_rot / b_boundary frozen CSVs.
Does NOT overwrite any frozen file. Exits 1 on any mismatch.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from f3_seed_expand import FROZEN_TIERS, frozen_index, load_frozen, worker_main


def jobs_from_frozen(frozen):
    jobs = []
    for (kind, seed, U, heading), fr in sorted(frozen.items()):
        jobs.append(
            dict(
                seed=seed,
                U=U,
                heading=heading,
                variant=kind,
                family="main",
                _frozen_hash=fr["plan_hash"],
                _source=fr.get("_source"),
            )
        )
    return jobs


def _one(job):
    from planning.routing3d import clear_cache

    clear_cache()
    payload = {k: job[k] for k in ("seed", "U", "heading", "variant", "family")}
    t0 = time.perf_counter()
    row, _ = worker_main(payload)
    return dict(
        key=(job["variant"], job["seed"], job["U"], job["heading"]),
        frozen=job["_frozen_hash"],
        source=job.get("_source"),
        new=row.get("plan_hash"),
        status=row.get("status"),
        solve=row.get("solve_seconds"),
        wall=round(time.perf_counter() - t0, 3),
        metrics={
            m: row.get(m)
            for m in (
                "A_extra_tau0",
                "A_extra_tau0.5",
                "A_extra_tau1",
                "total_time",
                "violations",
            )
        },
    )


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "results/F3_frozen_hash_audit.json")
    a = ap.parse_args()

    frozen = frozen_index(load_frozen())
    jobs = jobs_from_frozen(frozen)
    print(f"auditing {len(jobs)} frozen keys with workers={a.workers}", flush=True)
    results = []
    # maxtasksperchild=1 so each job is a fresh interpreter (anti cache pollution)
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=None) as pool:
        # ProcessPoolExecutor doesn't expose maxtasksperchild until 3.11 via max_tasks?
        # Use initializer clear only; each worker process persists. Safer: submit with
        # clear_cache inside _one (done). For true fresh process use max_tasks_per_child.
        try:
            pool2 = ProcessPoolExecutor(max_workers=a.workers, max_tasks_per_child=1)
        except TypeError:
            pool2 = ProcessPoolExecutor(max_workers=a.workers)
        with pool2 as ex:
            futs = {ex.submit(_one, j): j for j in jobs}
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                results.append(r)
                ok = r["new"] == r["frozen"] and r["status"] == "success"
                print(
                    f"[{i}/{len(jobs)}] {r['key']}: {'OK' if ok else 'MISMATCH'} "
                    f"solve={r['solve']}",
                    flush=True,
                )

    mismatches = [r for r in results if r["new"] != r["frozen"] or r["status"] != "success"]
    out = dict(
        n=len(results),
        mismatches=len(mismatches),
        mismatch_rows=mismatches,
        all_ok=not mismatches,
        results=results,
    )
    a.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(n=out["n"], mismatches=out["mismatches"], all_ok=out["all_ok"]), indent=2))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
