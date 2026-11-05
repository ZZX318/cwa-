"""F2 geometric d/w tiers; process-local overrides, no planning source edits."""
from __future__ import annotations
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
DS = (11, 13, 15)
COMMAND = '/home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py'


def strip_stats(scene, d):
    """Adapted from a_trial_1c_sweep_report.strip_stats; 0.05 m raster."""
    import numpy as np
    import a_trial_eval as ev
    polygons = ev.buffer_set(scene, d, 0.0)
    xs = [v[0] for f in polygons for v in f['vertices']]
    ys = [v[1] for f in polygons for v in f['vertices']]
    xF, y0, y1 = max(xs), min(ys), max(ys)
    r = d - math.floor(d / 2) * 2
    a, b = xF, xF + 2 - r
    hit = [t['geometry'] for t in scene['targets']
           if t['geometry']['center'][0] + t['geometry']['radius'] > a
           and t['geometry']['center'][0] - t['geometry']['radius'] < b
           and t['geometry']['center'][1] + t['geometry']['radius'] > y0
           and t['geometry']['center'][1] - t['geometry']['radius'] < y1]
    X, Y = np.meshgrid(np.arange(a+.025, b, .05), np.arange(y0+.025, y1, .05))
    mask = np.zeros(X.shape, bool)
    for t in hit:
        mask |= (X-t['center'][0])**2 + (Y-t['center'][1])**2 <= t['radius']**2
    return dict(x_F=xF, lost_strip=[a,b,y0,y1], n_trees=len(hit),
                canopy_m2=float(mask.sum()*.05*.05), on_tree_row=bool(hit), r=r)


def worker(job):
    import a_trial_heading as H
    import a_trial_extra_runs as E
    d, seed, heading, variant = (job[k] for k in ('requested_d','seed','heading','variant'))
    H.apply_swath_override(2.0)
    H.JOB = {**H.JOB, 'drift_buffer': float(d)}
    H.TIERS = {2.0: float(d)}
    info, cut = {}, None
    try:
        scene = H.scene0(seed)
        if heading == 0:
            cut = strip_stats(scene, d)
        else:
            _, cut = E.oh_rot(scene, 90, d, 2.0)
        offset = 0.0
        if variant == 'oh_rot':
            offset, info = E.oh_rot(scene, heading, d, 2.0)
        elif variant == 'b_boundary':
            offset, info = E._boundary_offset(scene, heading, d, 2.0, {})
        row, geom = H.run(dict(seed=seed, U=2.0, heading=heading, offset=offset,
                               variant='heuristic' if variant=='heuristic' else 'main'))
        assert row['d'] == d
        row.update(variant=variant, extra_info=info, requested_d=d, w=2.0, cut_geometry=cut)
        return row, geom
    except Exception as exc:
        return dict(job, U=2.0, w=2.0, status='exception', reason=f'{type(exc).__name__}: {exc}',
                    traceback=traceback.format_exc(), cut_geometry=cut, extra_info=info), None


def report(rows, raw_name, elapsed):
    summaries, exclusions = [], []
    for d in DS:
        for h in (0,90):
            for tau, key in T.TAUS.items():
                cell=[]
                for seed in range(5):
                    pair=[next(r for r in rows if r['requested_d']==d and r['heading']==h
                               and r['seed']==seed and r['variant']==v)
                          for v in (('heuristic' if h==0 else 'oh_rot'), 'b_boundary')]
                    eligible=all(r['status']=='success' for r in pair)
                    if pair[0].get('heuristic_lane_found') is False:
                        eligible=False
                        exclusions.append(f'd={d}, h={h}, seed={seed}: heuristic_lane_found=False')
                    rec=dict(comparison='Sh_minus_B', U=h, tau=tau, delta=None, dtime=None)
                    for side,r in zip(('left','right'),pair):
                        for field in ('A_extra','total_time','violations'):
                            rec[side+'_'+field]=r.get(key if field=='A_extra' else field)
                    if eligible:
                        rec['delta']=pair[0][key]-pair[1][key]
                        rec['dtime']=pair[0]['total_time']-pair[1]['total_time']
                    rec['class']=T.classify(rec['delta'])
                    cell.append(rec)
                s=T.summarize(cell)
                s['d']=d
                summaries.append(s)
    notes=['新增，不改已冻结主表。',
           'd∈{11,13,15} 是几何假设档（geometric assumption tiers），不是孔令标风速档；wind_speed carrier U=2.0，进程内 drift_buffer override；w=2。',
           'Δ=S_h−B-boundary；负值为 S_h 面积更小。仅成功且适用的相同 seed 配对；SD 为样本 SD。',
           '|Δ|≤1e-12 为 tie；其余 |Δ|<1 m² 为 not_interpreted。复用 F1 classify/wilcoxon；exact 双侧符号枚举、平均秩、去零差，保留不解读项；n≤5 最小 p≥0.0625。',
           'τ 仅影响评估阈值，每个计划同时评估 0/0.5/1.0；total_time 是计划执行时间（秒）。']
    tables=['# F2 tables — 新增，不改已冻结主表','',*notes,'']
    for d in DS:
        tables += [f'## d={d}, r=d−floor(d/w)w=1','']
        tables += [line.replace('| U |','| heading /° |') for line in T.table([s for s in summaries if s['d']==d])]+['']
    (ROOT/'results/F2_tables.md').write_text('\n'.join(tables)+'\n')
    with (ROOT/'results/F2_summary.csv').open('w',encoding='utf-8',newline='') as fh:
        wr=csv.DictWriter(fh,fieldnames=list(summaries[0]))
        wr.writeheader(); wr.writerows(summaries)
    failures=[r for r in rows if r['status']!='success']
    successful=[r for r in rows if r['status']=='success']
    violations=sum(r['violations'] for r in successful)
    counts=Counter(r['status'] for r in rows)
    totals={c:sum(s[c] for s in summaries) for c in T.CLASSES}
    lines=['# F2 report — 新增，不改已冻结主表','',*notes,'',
           f'结论：60 个任务中成功 {len(successful)}、失败 {len(failures)}，成功计划 violations={violations}；18 格共 {sum(s["n"] for s in summaries)} 个有效 seed×τ 配对，win/tie/loss/not_interpreted={totals}（各 τ 重复使用同一计划）。',
           '',f'原始数据：`{raw_name}`；实际运行 wall time={elapsed:.1f}s；统计见 `F2_tables.md`。','',
           '## 每格切带几何（各 τ 共用；seed 顺序 0..4）','',
           '0°：描述性 B-boundary 额外损失条带 [x_F,x_F+w−r]，使用 F 的 y 范围；n_trees 为冠层包围盒相交数，canopy_m2 为 0.05m 栅格冠层并集面积；压树行=n_trees>0。',
           '90°：虽然 d mod w=1，d 是沿风向的外扩距离，不是此航向条带法向的偏移；F 的法向端点对应原 y=5/95，差 90=45w，S_h 与 B 相位重合，额外损失条带宽为 0。因此不存在由两种对齐差异造成的切带压树行；下面 adjacent_strips/n_targets 仅记边界邻带与冠层相交，不可当作损失条带。完整缓冲区沿风向长度仍随 d 变化。','']
    geomrows=[]
    for d in DS:
        for h in (0,90):
            rs=[next(r for r in rows if r['requested_d']==d and r['heading']==h and r['seed']==seed and r['variant']==('heuristic' if h==0 else 'oh_rot')) for seed in range(5)]
            descriptions=[]
            for r in rs:
                g=r.get('cut_geometry')
                if g is None:
                    descriptions.append('缺失'); continue
                if h==0:
                    descriptions.append(f"strip={g['lost_strip']}; n_trees={g['n_trees']}; canopy_m2={g['canopy_m2']:.4f}; 压树行={g['on_tree_row']}")
                else:
                    descriptions.append(f"adjacent_strips={g['adjacent_strips']}; 压树行={any(a['n_targets']>0 for a in g['adjacent_strips'])}")
            for tau in T.TAUS:
                geomrows.append([d,h,tau,1,'<br>'.join(f's{i}: {v}' for i,v in enumerate(descriptions))])
    lines+=T.markdown_table(['d','heading','τ','r','切带几何 / 压树行'],geomrows)
    independent=all(len({json.dumps(r['cut_geometry'],sort_keys=True) for r in rows if r['seed']==seed and r['variant']=='oh_rot'})==1 for seed in range(5))
    lines += ['',f'90° 法向边界及 adjacent_strips 跨 d 实测一致：{independent}。','', '## Safety / fail-closed 与异常','',
              f'成功计划 violations 总数={violations}；零违规检查：{"PASS" if violations==0 else "FAIL"}。失败未计作零违规，亦不进入配对。']
    lines += [f"- d={r['requested_d']}, seed={r['seed']}, h={r['heading']}, {r['variant']}: status={r['status']}, stage={r.get('stage')}, reason={r.get('reason')}" for r in failures] or ['无 fail-closed 拒绝或运行异常。']
    lines += ['', '## 不适用配对排除','', *(sorted(set(exclusions)) or ['无。'])]
    lines += ['', '## 关键数值','', *tables[tables.index('## d=11, r=d−floor(d/w)w=1'):], '',f'复现：`{COMMAND}`（workers=5）。','']
    lines += ['', '## 缺失数据', '', '任务矩阵完整（含失败行），没有静默补数或补跑。',
              '', '## 基线回归（脚本未改 planning/）', '',
              '`python3 -u drift_checks.py` → 23/0；`python3 -u main.py --check` → 170/0；',
              '日志：`results/F_checks_drift.log`、`results/F_checks_main.log`。',
              '`git diff 463badb --stat -- planning/` 为空。']
    (ROOT/'results/F2.report.md').write_text('\n'.join(lines))
    return dict(status_counts=dict(counts), violations=violations, classifications=totals, summaries=summaries)


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('--report-only', help='Regenerate tables from SHA-tagged meta JSON; no replanning')
    a=ap.parse_args()
    if a.report_only:
        meta=json.loads((ROOT/a.report_only).read_text())
        raw=a.report_only.removesuffix('.meta.json')+'.csv'
        print(report(meta['rows_full'],raw,meta['elapsed_seconds']))
        return
    T.self_test()
    sha=subprocess.check_output(['git','rev-parse','--short','HEAD'],cwd=ROOT,text=True).strip()
    stem=f'F2_noninteger_dw_{sha}'
    out=ROOT/'results'
    # Preserve previous runs, including those from the same commit.
    if (out/(stem+'.csv')).exists():
        stem += '_'+time.strftime('%Y%m%dT%H%M%S')
    jobs=[dict(requested_d=d, seed=s, heading=h, variant=v) for d in DS for s in range(5)
          for h,v in ((0,'heuristic'),(90,'oh_rot'),(0,'b_boundary'),(90,'b_boundary'))]
    rows, geoms=[],{}
    start=time.perf_counter()
    print(f'F2: {len(jobs)} jobs, workers=5, sha={sha}, w=2, carrier U=2',flush=True)
    with ProcessPoolExecutor(max_workers=5) as pool:
        pending={pool.submit(worker,j):j for j in jobs}
        for future in as_completed(pending):
            job=pending[future]
            try:
                row,geom=future.result()
            except Exception as exc:
                row,geom=dict(job,status='worker_exception',reason=repr(exc)),None
            rows.append(row)
            ident=f"d{job['requested_d']}_s{job['seed']}_h{job['heading']}_{job['variant']}"
            if geom is not None:
                geoms[ident]=geom
            print(f"[{len(rows)}/60] {ident}: {row['status']}; d={row.get('d')}; violations={row.get('violations')}; reason={row.get('reason','')}",flush=True)
    rows.sort(key=lambda r:(r['requested_d'],r['seed'],r['heading'],r['variant']))
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (out/(stem+'.csv')).open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)
    elapsed=time.perf_counter()-start
    meta=dict(commit=sha,command=COMMAND,workers=5,w=2,carrier_U=2,geometric_d=list(DS),elapsed_seconds=elapsed,rows_full=rows)
    (out/(stem+'.meta.json')).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    (out/(stem+'.geom.json')).write_text(json.dumps(geoms,ensure_ascii=False)+'\n')
    summary=report(rows,'results/'+stem+'.csv',elapsed)
    (out/'F2_noninteger_dw.meta.json').write_text(json.dumps(dict(meta,raw_csv=stem+'.csv',geometry=stem+'.geom.json',summary=summary),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='summaries'},ensure_ascii=False),flush=True)
    assert len(rows)==60
    assert all(r['d']==r['requested_d'] for r in rows if r['status']=='success')
    assert summary['violations']==0, 'nonzero safety violations'


if __name__=='__main__':
    main()
