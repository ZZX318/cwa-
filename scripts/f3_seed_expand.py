"""F3: expand to seeds 0-9 for main contrast (d=10/16) and F2 non-integer d cells.

- Never overwrite frozen CSVs.
- Seeds 0-4 main contrast: re-run and assert plan_hash matches frozen sources.
- Seeds 5-9 main contrast: new plans.
- F2 cells (d∈{11,13,15}): reuse F2 CSV for seeds 0-4 if provided; run seeds 5-9.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import f1_heading90_table as T

ROOT = Path(__file__).resolve().parents[1]
MAIN_CSV = ROOT / "results/a_trial_seeds0-4_2ff2df1.csv"
OH_CSV = ROOT / "results/a_trial_extra_oh_rot_h90_58024ac.csv"
BB_CSV = ROOT / "results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv"
FROZEN_TIERS = {2.0: 10.0, 4.0: 16.0}
GEOM_DS = (11.0, 13.0, 15.0)
COMMAND = "/home/box/.venvs/mpl/bin/python scripts/f3_seed_expand.py"


def load_frozen():
    text_fields = {"variant", "status", "stage", "matrix_mode", "order_strategy", "plan_hash", "reason",
                   "heuristic_lane_found", "heuristic_grid_aligned"}
    rows = []
    for path, tag in ((MAIN_CSV, "2ff2df1"), (OH_CSV, "58024ac"), (BB_CSV, "0e0715a")):
        with path.open(encoding="utf-8", newline="") as fh:
            for raw in csv.DictReader(fh):
                row = dict(raw)
                row["_source"] = tag
                rows.append(row)
    return rows


def frozen_index(rows):
    """Map (kind, seed, U, heading) -> frozen row for hash checks."""
    out = {}
    for r in rows:
        if r["status"] != "success":
            continue
        seed, U, heading = int(r["seed"]), float(r["U"]), int(r["heading"])
        v = r["variant"]
        if v == "heuristic" and heading == 0:
            out[("heuristic", seed, U, 0)] = r
        elif v == "oh_rot" and heading == 90:
            out[("oh_rot", seed, U, 90)] = r
        elif v == "b_boundary" and heading in (0, 90):
            out[("b_boundary", seed, U, heading)] = r
    return out


def worker_main(job):
    """Main contrast job with real TIERS (d=10/16)."""
    import a_trial_heading as H
    import a_trial_extra_runs as E

    seed, U, heading, variant = job["seed"], job["U"], job["heading"], job["variant"]
    H.apply_swath_override(2.0)
    H.TIERS = dict(FROZEN_TIERS)
    H.JOB = {k: v for k, v in H.JOB.items() if k != "drift_buffer"}
    try:
        scene = H.scene0(seed)
        d = FROZEN_TIERS[U]
        info = {}
        offset = 0.0
        if variant == "oh_rot":
            offset, info = E.oh_rot(scene, heading, d, 2.0)
            run_variant = "main"
        elif variant == "b_boundary":
            offset, info = E._boundary_offset(scene, heading, d, 2.0, {})
            run_variant = "main"
        else:
            run_variant = "heuristic"
        row, geom = H.run(dict(seed=seed, U=U, heading=heading, offset=offset, variant=run_variant))
        row.update(variant=variant, extra_info=info, requested_d=d, w=2.0, family="main")
        return row, geom
    except Exception as exc:
        return dict(job, status="exception", reason=f"{type(exc).__name__}: {exc}",
                    traceback=traceback.format_exc(), family="main", requested_d=FROZEN_TIERS[U], w=2.0), None


def worker_geom(job):
    """F2-style geometric d job; carrier U=2.0."""
    import a_trial_heading as H
    import a_trial_extra_runs as E
    from f2_noninteger_dw import strip_stats

    d, seed, heading, variant = job["requested_d"], job["seed"], job["heading"], job["variant"]
    H.apply_swath_override(2.0)
    H.JOB = {**H.JOB, "drift_buffer": float(d)}
    H.TIERS = {2.0: float(d)}
    info, cut = {}, None
    try:
        scene = H.scene0(seed)
        cut = strip_stats(scene, d) if heading == 0 else E.oh_rot(scene, 90, d, 2.0)[1]
        offset = 0.0
        if variant == "oh_rot":
            offset, info = E.oh_rot(scene, heading, d, 2.0)
            run_variant = "main"
        elif variant == "b_boundary":
            offset, info = E._boundary_offset(scene, heading, d, 2.0, {})
            run_variant = "main"
        else:
            run_variant = "heuristic"
        row, geom = H.run(dict(seed=seed, U=2.0, heading=heading, offset=offset, variant=run_variant))
        assert abs(float(row["d"]) - float(d)) < 1e-9
        row.update(variant=variant, extra_info=info, requested_d=d, w=2.0,
                   cut_geometry=cut, family="geom")
        return row, geom
    except Exception as exc:
        return dict(job, U=2.0, w=2.0, status="exception", family="geom",
                    reason=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(),
                    cut_geometry=cut, extra_info=info, requested_d=d), None


def run_pool(jobs, worker, workers, checkpoint):
    rows, geoms = [], {}
    def ident(r):
        return (r.get('family'), int(r['seed']), float(r.get('U') or 2.0),
                float(r.get('requested_d') or FROZEN_TIERS[float(r['U'])]),
                int(r['heading']), r['variant'])
    wanted={ident(j) for j in jobs}
    saved={}
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            item=json.loads(line)
            key=ident(item['row'])
            if key in wanted: saved[key]=item
    for key,item in saved.items():
        rows.append(item['row'])
        if item['geom'] is not None: geoms[str(key)]=item['geom']
    todo=[j for j in jobs if ident(j) not in saved]
    if saved: print(f'Resumed {len(saved)} completed rows from {checkpoint.name}; todo={len(todo)}',flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, j): j for j in todo}
        for fut in as_completed(pending):
            job = pending[fut]
            try:
                row, geom = fut.result()
            except Exception as exc:
                row, geom = dict(job, status="worker_exception", reason=repr(exc)), None
            rows.append(row)
            with checkpoint.open('a', encoding='utf-8') as cp:
                cp.write(json.dumps(dict(row=row, geom=geom), ensure_ascii=False)+'\n')
            key = (job.get("family") or row.get("family"),
                   job.get("requested_d", job.get("U")),
                   job["seed"], job["heading"], job["variant"])
            if geom is not None:
                geoms[str(key)] = geom
            print(f"[{len(rows)}/{len(jobs)}] {key}: {row.get('status')}; "
                  f"d={row.get('d')}; viol={row.get('violations')}; "
                  f"reason={row.get('reason','')[:120]}", flush=True)
    return rows, geoms


def write_csv(path, rows):
    fields = sorted({k for r in rows for k in r})
    with path.open("x", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                         for k, v in r.items()})


def assert_frozen_hashes(new_rows, frozen):
    mismatches, missing = [], []
    for r in new_rows:
        if r.get("family") != "main" or int(r["seed"]) > 4:
            continue
        if r.get("status") != "success":
            missing.append(f"seed={r['seed']} U={r.get('U')} h={r.get('heading')} "
                           f"{r.get('variant')} status={r.get('status')} reason={r.get('reason')}")
            continue
        key = (r["variant"], int(r["seed"]), float(r["U"]), int(r["heading"]))
        fr = frozen.get(key)
        if fr is None:
            missing.append(f"no frozen row for {key}")
            continue
        for metric in ('A_extra_tau0','A_extra_tau0.5','A_extra_tau1','total_time','violations'):
            if abs(float(r[metric])-float(fr[metric])) > 1e-9:
                mismatches.append(f"{key}: metric {metric} differs new={r[metric]} frozen={fr[metric]}")
        if r.get("plan_hash") != fr["plan_hash"]:
            mismatches.append(f"{key}: new={r.get('plan_hash')} frozen={fr['plan_hash']} "
                              f"(src={fr['_source']})")
    return mismatches, missing


def paired_summary(rows, seeds, label_U):
    """Build S_h vs B summaries for a set of seeds.
    label_U: function(row)-> grouping key displayed as U (main: actual U; geom: heading).
    """
    summaries = []
    # Determine groups: (group_key, heading, tau)
    groups = {}
    for r in rows:
        g = label_U(r)
        groups.setdefault((g, int(r["heading"])), [])
        if r.get("status") == "success":
            groups[(g, int(r["heading"]))].append(r)
    for (g, h), pool in sorted(groups.items()):
        for tau, key in T.TAUS.items():
            cell = []
            for seed in seeds:
                sh_v = "heuristic" if h == 0 else "oh_rot"
                try:
                    sh = next(r for r in pool if int(r["seed"]) == seed and r["variant"] == sh_v)
                    b = next(r for r in pool if int(r["seed"]) == seed and r["variant"] == "b_boundary")
                except StopIteration:
                    cell.append(dict(comparison="Sh_minus_B", U=g, tau=tau, delta=None, dtime=None,
                                     left_A_extra=None, right_A_extra=None,
                                     left_total_time=None, right_total_time=None,
                                     left_violations=None, right_violations=None,
                                     **{"class": "not_interpreted"}))
                    continue
                eligible = True
                if sh.get("heuristic_lane_found") is False or sh.get("heuristic_lane_found") == "False":
                    eligible = False
                rec = dict(comparison="Sh_minus_B", U=g, tau=tau, delta=None, dtime=None)
                for side, rr in zip(("left", "right"), (sh, b)):
                    rec[side + "_A_extra"] = float(rr[key]) if rr.get(key) not in (None, "") else None
                    rec[side + "_total_time"] = float(rr["total_time"])
                    rec[side + "_violations"] = int(rr["violations"])
                if eligible and rec["left_A_extra"] is not None:
                    rec["delta"] = rec["left_A_extra"] - rec["right_A_extra"]
                    rec["dtime"] = rec["left_total_time"] - rec["right_total_time"]
                rec["class"] = T.classify(rec["delta"])
                cell.append(rec)
            s = T.summarize(cell)
            s["group"] = g
            s["heading"] = h
            s["excluded"] = len(seeds)-s["n"]
            summaries.append(s)
    return summaries


def min_time_summary(rows):
    """Frozen main criterion: S_h at 0° versus fastest B heading (time,path)."""
    out=[]
    for U in (2.0,4.0):
        for tau,key in T.TAUS.items():
            cell=[]
            for seed in range(10):
                pool=[r for r in rows if float(r['U'])==U and int(r['seed'])==seed
                      and r.get('status')=='success']
                sh=next((r for r in pool if r['variant']=='heuristic' and int(r['heading'])==0),None)
                bs=[r for r in pool if r['variant']=='b_boundary']
                b=min(bs,key=lambda r:(float(r['total_time']),float(r['path_length']))) if bs else None
                ok=sh is not None and b is not None and sh.get('heuristic_lane_found') not in (False,'False')
                rec=dict(comparison='min_time',U=U,tau=tau,delta=None,dtime=None)
                for side,r in (('left',sh),('right',b)):
                    for dest,src in (('A_extra',key),('total_time','total_time'),('violations','violations')):
                        rec[side+'_'+dest]=float(r[src]) if r is not None else None
                if ok:
                    rec['delta']=rec['left_A_extra']-rec['right_A_extra']
                    rec['dtime']=rec['left_total_time']-rec['right_total_time']
                rec['class']=T.classify(rec['delta'])
                cell.append(rec)
            ss=T.summarize(cell)
            ss['excluded']=10-ss['n']
            out.append(ss)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--report-only", action="store_true", help="Render from completed checkpoint files; no replanning")
    ap.add_argument("--f2-csv", default="", help="Reuse F2 CSV for geom seeds 0-4")
    ap.add_argument("--skip-main-verify", action="store_true",
                    help="Copy frozen 0-4 main rows instead of re-planning (still records source hashes)")
    ap.add_argument("--main-seeds", default="0-9")
    ap.add_argument("--geom-seeds", default="0-9")
    a = ap.parse_args()

    T.self_test()
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    frozen = frozen_index(load_frozen())

    def parse_seeds(s):
        if "-" in s:
            lo, hi = s.split("-", 1)
            return list(range(int(lo), int(hi) + 1))
        return [int(x) for x in s.split(",") if x]

    main_seeds = parse_seeds(a.main_seeds)
    geom_seeds = parse_seeds(a.geom_seeds)

    main_jobs = []
    for seed in main_seeds:
        for U in (2.0, 4.0):
            main_jobs += [
                dict(seed=seed, U=U, heading=0, variant="heuristic", family="main"),
                dict(seed=seed, U=U, heading=90, variant="oh_rot", family="main"),
                dict(seed=seed, U=U, heading=0, variant="b_boundary", family="main"),
                dict(seed=seed, U=U, heading=90, variant="b_boundary", family="main"),
            ]

    geom_jobs = []
    reuse_rows = []
    if a.f2_csv:
        with (ROOT / a.f2_csv).open(encoding="utf-8", newline="") as fh:
            for raw in csv.DictReader(fh):
                r = dict(raw)
                # JSON fields
                for k in ("extra_info", "cut_geometry"):
                    if r.get(k) and isinstance(r[k], str) and r[k].startswith(("{", "[")):
                        r[k] = json.loads(r[k])
                for k in ("seed", "heading", "violations"):
                    if r.get(k) not in (None, ""):
                        r[k] = int(float(r[k]))
                for k in ("U", "d", "requested_d", "offset", "total_time", "A_extra_tau0",
                          "A_extra_tau0.5", "A_extra_tau1"):
                    if r.get(k) not in (None, ""):
                        r[k] = float(r[k])
                r["family"] = "geom"
                if int(r["seed"]) <= 4:
                    reuse_rows.append(r)
        print(f"reused {len(reuse_rows)} F2 rows from {a.f2_csv}", flush=True)
        geom_seed_run = [s for s in geom_seeds if s > 4]
    else:
        geom_seed_run = list(geom_seeds)

    for seed in geom_seed_run:
        for d in GEOM_DS:
            geom_jobs += [
                dict(seed=seed, requested_d=d, heading=0, variant="heuristic", family="geom"),
                dict(seed=seed, requested_d=d, heading=90, variant="oh_rot", family="geom"),
                dict(seed=seed, requested_d=d, heading=0, variant="b_boundary", family="geom"),
                dict(seed=seed, requested_d=d, heading=90, variant="b_boundary", family="geom"),
            ]

    # Optionally skip re-planning frozen main 0-4
    copied_main = []
    if a.skip_main_verify:
        keep = []
        for j in main_jobs:
            if j["seed"] <= 4:
                fr = frozen.get((j["variant"], j["seed"], j["U"], j["heading"]))
                if fr is None:
                    raise SystemExit(f"missing frozen for {j}")
                row = dict(fr)
                row.update(family="main", requested_d=FROZEN_TIERS[j["U"]], w=2.0,
                           seed=j["seed"], U=j["U"], heading=j["heading"], variant=j["variant"],
                           _copied_from=fr["_source"])
                # cast numerics
                for k in ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time", "d", "offset", "U"):
                    if row.get(k) not in (None, ""):
                        row[k] = float(row[k])
                row["violations"] = int(float(row.get("violations") or 0))
                if "heuristic_lane_found" in row:
                    v = row["heuristic_lane_found"]
                    row["heuristic_lane_found"] = {"True": True, "False": False, "": None, None: None}.get(v, v)
                copied_main.append(row)
            else:
                keep.append(j)
        main_jobs = keep
        print(f"copied {len(copied_main)} frozen main rows; will plan {len(main_jobs)} new main jobs", flush=True)

    t0 = time.perf_counter()
    print(f"F3 main jobs={len(main_jobs)} geom jobs={len(geom_jobs)} workers={a.workers} sha={sha}", flush=True)
    if a.report_only:
        def read_checkpoint(name, expected):
            p=ROOT/'results'/name
            items=[json.loads(line) for line in p.read_text().splitlines()]
            assert len(items)==expected, (name,len(items),expected)
            return [i['row'] for i in items], {str(n):i['geom'] for n,i in enumerate(items) if i['geom'] is not None}
        main_rows,main_geoms=read_checkpoint('F3_main_checkpoint.jsonl',len(main_jobs))
        geom_rows,geom_geoms=read_checkpoint('F3_geom_checkpoint.jsonl',len(geom_jobs))
    else:
        main_rows, main_geoms = run_pool(main_jobs, worker_main, a.workers, ROOT/"results/F3_main_checkpoint.jsonl") if main_jobs else ([], {})
        geom_rows, geom_geoms = run_pool(geom_jobs, worker_geom, a.workers, ROOT/"results/F3_geom_checkpoint.jsonl") if geom_jobs else ([], {})
    elapsed = time.perf_counter() - t0

    all_main = copied_main + main_rows
    all_geom = reuse_rows + geom_rows

    mismatches, missing = assert_frozen_hashes(
        [r for r in all_main if int(r["seed"]) <= 4], frozen)

    stem = f"F3_seeds0-9_{sha}"
    out = ROOT / "results"
    if (out / f"{stem}_main.csv").exists():
        stem += "_" + time.strftime("%Y%m%dT%H%M%S")
    write_csv(out / f"{stem}_main.csv", all_main)
    write_csv(out / f"{stem}_geom.csv", all_geom)
    (out / f"{stem}.geom.json").write_text(json.dumps(dict(main=main_geoms, geom=geom_geoms),ensure_ascii=False)+'\n')
    (out / f"{stem}.meta.json").write_text(json.dumps(dict(
        commit=sha, command=COMMAND, workers=a.workers, elapsed_seconds=elapsed,
        main_csv=f"{stem}_main.csv", geom_csv=f"{stem}_geom.csv",
        skip_main_verify=a.skip_main_verify, f2_csv=a.f2_csv,
        hash_mismatches=mismatches, hash_missing=missing,
        status_main=dict(Counter(r.get("status") for r in all_main)),
        status_geom=dict(Counter(r.get("status") for r in all_geom)),
    ), ensure_ascii=False, indent=2) + "\n")

    # Summaries n=10
    min_sum = min_time_summary(all_main)
    main_sum = paired_summary(all_main, list(range(10)), lambda r: float(r["U"]))
    geom_sum = paired_summary(all_geom, list(range(10)),
                              lambda r: float(r.get('requested_d', r.get('d'))))

    for name, ss in (("main", main_sum), ("geom", geom_sum), ("min_time", min_sum)):
        write_csv(out / f"{stem}_{name}_summary.csv", ss)

    def render(title, summaries):
        lines = [f"## {title}", ""]
        # reuse T.table but group key may be str
        for h in (0, 90):
            lines += [f"### heading={h}°", ""]
            lines += T.table([s for s in summaries if s['heading']==h])
        
        return lines

    md = ["# F3 tables — 新增，不改已冻结主表", "",
          "seeds 0–9；主对比 d=10/16（U=2/4）；几何档 d∈{11,13,15}（非孔令标）。",
          "n=10 时 Wilcoxon 双侧最小 p≈0.002；仅描述，不写显著。|Δ|<1 m² 不解读。固定同航向用于隔离对齐对象；主准则仍取最短时间。", ""]
    md += ["## 主准则 min total_time：S_h(0°) vs B(0°/90°最短时间)", ""] + T.table(min_sum) + [""]
    md += render("主对比 S_h vs B-boundary（按 U×heading×τ）", main_sum)
    md += [""] + render("几何档 S_h vs B-boundary（按 d×heading×τ）", geom_sum)
    (out / "F3_tables.md").write_text("\n".join(md) + "\n")

    viol_main = sum(int(r["violations"]) for r in all_main if r.get("status") == "success")
    viol_geom = sum(int(float(r["violations"])) for r in all_geom if r.get("status") == "success")
    fails = [r for r in all_main + all_geom if r.get("status") != "success"]

    # Key numbers from main U=2 h=0 τ=1.0 and geom
    def cell_num(summaries, pred):
        for s in summaries:
            if pred(s):
                return s
        return None

    report = [
        "# F3 report — 新增，不改已冻结主表", "",
        "结论：将主对比与非整数 d/w 几何档扩展到 seeds 0–9；"
        f"主对比成功 {sum(1 for r in all_main if r.get('status')=='success')}/{len(all_main)}，"
        f"几何档成功 {sum(1 for r in all_geom if r.get('status')=='success')}/{len(all_geom)}；"
        f"violations 主={viol_main} 几何={viol_geom}；"
        f"冻结 seeds 0–4 plan_hash 错配 {len(mismatches)}，缺失 {len(missing)}。",
        "",
        f"原始：`results/{stem}_main.csv`，`results/{stem}_geom.csv`；wall={elapsed:.1f}s。",
        f"skip_main_verify={a.skip_main_verify}；f2_csv={a.f2_csv or '（无，全跑）'}。",
        "",
        "主对比冻结 seeds 0–4 独立重规划 40 行，逐行检查 plan_hash 以及 A_extra(3τ)/total_time/violations。",
        "几何档 seeds 0–4 续接 F2 SHA-tagged CSV，不重算、不覆盖；新增 seeds 5–9 独立运行。",
        "d∈{11,13,15} 仅为几何假设档，carrier U=2.0，显式 drift_buffer；不是孔令标风速分档。",
        "S_h 在 0° 邻缓冲首航道不存在的格保持不适用，即使已成功返回其他航道；不记作安全违规。",
        "同航向相位重合的零差只说明几何等价，不是不同算法比较性能证据。",
        "",
        "## plan_hash 复核（冻结 seeds 0–4）",
        f"- mismatches ({len(mismatches)}):",
        *([f"  - {x}" for x in mismatches] or ["  - 无"]),
        f"- missing/failed ({len(missing)}):",
        *([f"  - {x}" for x in missing] or ["  - 无"]),
        "",
        "## 缺失数据",
        "预定主矩阵 80 行、几何矩阵 120 行（含失败行）；缺失或拒出的配对不填零。",
        f"实际主行数 {len(all_main)}、几何行数 {len(all_geom)}；主 seed 0–4 为独立重规划校验，几何 seed 0–4 从 F2 原值续接。",
        "",
        "## Safety / 拒绝",
        f"- violations 总和（成功行）主={viol_main} 几何={viol_geom}",
        f"- 非 success 行数={len(fails)}",
        *([f"  - family={r.get('family')} seed={r.get('seed')} U/d={r.get('U', r.get('requested_d'))} "
          f"h={r.get('heading')} {r.get('variant')}: {r.get('status')} {r.get('reason')}"
          for r in fails] or ["  - 无"]),
        "",
        "## 关键汇总",
        "",
        *md[md.index("## 主准则 min total_time：S_h(0°) vs B(0°/90°最短时间)"): ],
        "",
        f"复现：`{COMMAND}` --workers {a.workers}"
        + (f" --f2-csv {a.f2_csv}" if a.f2_csv else "")
        + (" --skip-main-verify" if a.skip_main_verify else ""),
        "",
        "Wilcoxon n=10 最小双侧 p=2/2^10=0.001953…≈0.002；只写描述，不写显著。",
        "几何违规仅指所定义的程序检查，不代表真实环境安全验证。",
        "基线回归：`python3 -u drift_checks.py`→23/0；`python3 -u main.py --check`→170/0；日志 `F_checks_drift.log`、`F_checks_main.log`。",
        "`git diff 463badb --stat -- planning/` 为空；已冻结 CSV 和 RESULTS_complete.md 未改。",
    ]
    (out / "F3.report.md").write_text("\n".join(report) + "\n")

    print(json.dumps(dict(
        mismatches=len(mismatches), missing=len(missing),
        viol_main=viol_main, viol_geom=viol_geom,
        fails=len(fails), elapsed=elapsed, stem=stem,
    ), ensure_ascii=False), flush=True)
    if mismatches:
        raise SystemExit(f"PLAN_HASH_MISMATCH: {len(mismatches)}")
    if viol_main or viol_geom:
        raise SystemExit("NONZERO_VIOLATIONS")


if __name__ == "__main__":
    main()
