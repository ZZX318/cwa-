"""Sample geom cells seed2 and seed7 (one cell each) vs existing F3 geom CSV hashes.
Default cell: d=11, heading=0, variant=b_boundary (loss-band sensitive).
"""
from __future__ import annotations
import argparse, csv, json, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_expected(csv_path, seed, d, heading, variant):
    with csv_path.open(encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh):
            if (int(float(r['seed']))==seed and abs(float(r['requested_d'])-d)<1e-9
                    and int(r['heading'])==heading and r['variant']==variant):
                return r
    raise SystemExit(f'missing expected row seed={seed} d={d} h={heading} {variant}')

def one(job):
    import a_trial_heading as H
    import a_trial_extra_runs as E
    from f2_noninteger_dw import strip_stats
    d, seed, heading, variant = job['requested_d'], job['seed'], job['heading'], job['variant']
    H.apply_swath_override(2.0)
    H.JOB = {**H.JOB, 'drift_buffer': float(d)}
    H.TIERS = {2.0: float(d)}
    scene = H.scene0(seed)
    cut = strip_stats(scene, d) if heading == 0 else E.oh_rot(scene, 90, d, 2.0)[1]
    offset, info = 0.0, {}
    if variant == 'oh_rot':
        offset, info = E.oh_rot(scene, heading, d, 2.0)
        run_variant = 'main'
    elif variant == 'b_boundary':
        offset, info = E._boundary_offset(scene, heading, d, 2.0, {})
        run_variant = 'main'
    else:
        run_variant = 'heuristic'
    row, geom = H.run(dict(seed=seed, U=2.0, heading=heading, offset=offset, variant=run_variant))
    row.update(variant=variant, requested_d=d, family='geom', cut_geometry=cut, extra_info=info)
    return row

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--geom-csv', default='results/F3_seeds0-9_a9916cb_geom.csv')
    ap.add_argument('--d', type=float, default=11.0)
    ap.add_argument('--heading', type=int, default=0)
    ap.add_argument('--variant', default='b_boundary')
    ap.add_argument('--seeds', default='2,7')
    ap.add_argument('--out', default='results/F3_geom_sample_postcache.json')
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(',') if x]
    expected = {s: load_expected(ROOT/a.geom_csv, s, a.d, a.heading, a.variant) for s in seeds}
    jobs = [dict(seed=s, requested_d=a.d, heading=a.heading, variant=a.variant) for s in seeds]
    t0 = time.perf_counter()
    try:
        pool = ProcessPoolExecutor(max_workers=min(2, len(jobs)), max_tasks_per_child=1)
    except TypeError:
        pool = ProcessPoolExecutor(max_workers=min(2, len(jobs)))
    results = []
    with pool as ex:
        futs = list(ex.map(one, jobs))
    for job, row, exp in zip(jobs, futs, [expected[j['seed']] for j in jobs]):
        match = row.get('plan_hash') == exp['plan_hash']
        results.append(dict(
            seed=job['seed'], requested_d=a.d, heading=a.heading, variant=a.variant,
            status=row.get('status'), match=match,
            new_hash=row.get('plan_hash'), old_hash=exp['plan_hash'],
            A_extra_tau0=row.get('A_extra_tau0'), old_A_extra_tau0=float(exp['A_extra_tau0']),
            total_time=row.get('total_time'), old_total_time=float(exp['total_time']),
            violations=row.get('violations'),
        ))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    out = dict(elapsed=time.perf_counter()-t0, cell=dict(d=a.d, heading=a.heading, variant=a.variant),
               all_match=all(r['match'] for r in results), results=results)
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False)+'\n')
    print('ALL_MATCH' if out['all_match'] else 'MISMATCH', '->', a.out)
    raise SystemExit(0 if out['all_match'] else 2)

if __name__ == '__main__':
    main()
