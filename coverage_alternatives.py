"""Bounded comparison of global phase and local Y-strip repair, fixed protection."""
import math
import copy
from coverage_recovery import recover
from planning import configuration, check, fingerprint
from planning.footprint import rectangle, overlaps_target
from planning.safety import (TOUCH, remaining_y_intervals, nofly_expanded_boxes,
                             obstacle_expanded_boxes)
from scene.geometry import polygon_bounds
from planner_api import make_planner
from execution import build
from evaluation import build as evaluate, at


def measure(scene, plan, resolution):
    check(scene, plan)
    timeline = build(scene, plan)
    ev = evaluate(scene, plan, timeline, resolution)
    m = at(ev, timeline, timeline['duration'])
    if m['illegal']:
        raise ValueError('恢复候选的完整喷幅进入保护区')
    covered = {(ix, iy) for _, ix, iy in m['coverage_cells']}
    missed = {(ix, iy) for _, ix, iy in ev['cells']} - set(map(tuple, ev['excluded_xy'])) - covered
    return dict(duration=timeline['duration'], extra_miss=m['extra_miss_area_m2'],
                restricted_area=m['restricted_canopy_area_m2'],
                sprayable_area=m['sprayable_canopy_area_m2'],
                sprayable_coverage=m['sprayable_coverage'], illegal_count=len(m['illegal']),
                repeated_cells=m['repeated_cells'], repeated_area=m['repeated_sprayable_area_m2'],
                spray_amount=m['total_spray_amount']), missed


def repair_candidates(scene, c, height, missed, resolution):
    """Full-width, fixed-Y border strips; no per-nozzle or heading assumptions."""
    w = c['swath']
    zones = scene['no_spray_zones'] + scene['no_fly_zones']
    bounds = [polygon_bounds(z['footprint']) for z in zones]
    xs = sorted({round(x, 8) for b in bounds for x in
                 (b['min'][0]-w/2-.01, b['max'][0]+w/2+.01)})
    if len(xs) > 32:
        raise ValueError('局部边带候选超过32个，请分区实验')
    boxes = nofly_expanded_boxes(scene,c['clearance']) + obstacle_expanded_boxes(scene,c['clearance'])
    boxes += [([b['min'][0]-w/2-TOUCH,b['min'][1],height],
               [b['max'][0]+w/2+TOUCH,b['max'][1],height]) for b in bounds]
    result=[]
    for x in xs:
        if not scene['extent']['min'][0] <= x <= scene['extent']['max'][0]: continue
        relevant=[((ix+.5)*resolution,(iy+.5)*resolution) for ix,iy in missed
                  if abs((ix+.5)*resolution-x) <= w/2]
        if not relevant: continue
        ymin=min(y for _,y in relevant)-resolution/2
        ymax=max(y for _,y in relevant)+resolution/2
        ymin=max(ymin,scene['extent']['min'][1]); ymax=min(ymax,scene['extent']['max'][1])
        for lo,hi in remaining_y_intervals(x,height,ymin,ymax,boxes):
            points=[(px,py) for px,py in relevant if lo<=py<=hi]
            if not points: continue
            lane=dict(start=[x,lo,height],end=[x,hi,height],type='spray',spray=True,
                      speed=c['speed'],target_ids=[])
            lane['target_ids']=[t['id'] for t in scene['targets']
                                if overlaps_target(rectangle(lane,w),t['geometry'])]
            if lane['target_ids']:
                result.append((len(points)*resolution**2/(hi-lo+w),lane))
    return [lane for _,lane in sorted(result,key=lambda r:(-r[0],r[1]['start'],r[1]['end']))]


def compare_recovery(scene, raw, resolution=.25, time_budget=60):
    if type(time_budget) not in (int,float) or not math.isfinite(time_budget) or time_budget<0:
        raise ValueError('额外时间上限须为有限非负秒数')
    # Shared input validation, bounded phases and conservative all-restricted check.
    phase_result=recover(scene,raw,resolution)
    if phase_result.get('baseline') is None:
        return dict(status='unavailable',message=phase_result['message'],alternatives=[])
    c=configuration(raw); planner=make_planner('caw-a*-3d-wind')
    original_hash=fingerprint(scene)
    base=planner.plan(scene,c)
    if base['status']!='success':
        return dict(status='unavailable',message='当前相位不能执行，无法建立额外时间基准：'+base.get('reason',''),alternatives=[])
    bm,missed=measure(scene,base,resolution)
    limit=bm['duration']+time_budget
    def row(name,plan,metrics,**extra):
        return dict(strategy=name,status='success',plan=plan,**metrics,
                    added_seconds=metrics['duration']-bm['duration'],
                    restored_area=bm['extra_miss']-metrics['extra_miss'],
                    within_budget=metrics['duration']<=limit+1e-8,**extra)
    rows=[row('baseline',base,bm)]
    phase_valid=[r for r in phase_result['candidates'] if r['status']=='success' and r['duration']<=limit+1e-8]
    pr=min(phase_valid,key=lambda r:(round(r['extra_miss'],8),r['duration']))
    pp=planner.plan(scene,dict(c,lane_phase=pr['phase']))
    pm,_=measure(scene,pp,resolution)
    rows.append(row('global-phase',pp,pm,phase=pr['phase']))
    current=base; cm=bm; additions=[]; attempts=[]
    for _ in range(4):
        pool=repair_candidates(scene,c,base['work_height'],missed,resolution)[:4]
        evaluated=[]
        for lane in pool:
            if lane in additions: continue
            plan=planner.plan_with_supplement(scene,c,additions+[lane])
            attempt=dict(start=lane['start'],end=lane['end'],status=plan['status'],reason=plan.get('reason'))
            if plan['status']=='success':
                metrics,remaining=measure(scene,plan,resolution)
                attempt.update(metrics,within_budget=metrics['duration']<=limit+1e-8)
                if attempt['within_budget'] and metrics['extra_miss']<cm['extra_miss']-1e-8:
                    evaluated.append((metrics,remaining,plan,lane))
            attempts.append(attempt)
        if not evaluated: break
        cm,missed,current,lane=min(evaluated,key=lambda r:(round(r[0]['extra_miss'],8),r[0]['duration']))
        additions.append(lane)
        if not missed: break
    current=copy.deepcopy(current)
    current['coverage_recovery']=dict(strategy='local-border',supplemental_count=len(additions),
                                     base_phase=c['lane_phase'],bounded=True)
    check(scene,current)
    rows.append(row('local-border',current,cm,supplemental_count=len(additions)))
    for r in rows:
        if abs(r['restricted_area']-bm['restricted_area'])>1e-8 or abs(r['sprayable_area']-bm['sprayable_area'])>1e-8:
            raise ValueError('恢复对照的保护范围或任务面积不一致')
    assert fingerprint(scene)==original_hash
    valid=[r for r in rows if r['within_budget']]
    best=min(valid,key=lambda r:(round(r['extra_miss'],8),r['duration']))
    frontier=[r['strategy'] for r in valid if not any(
        q['extra_miss']<=r['extra_miss']+1e-8 and q['duration']<=r['duration']+1e-8 and
        (q['extra_miss']<r['extra_miss']-1e-8 or q['duration']<r['duration']-1e-8) for q in valid)]
    return dict(status='success',alternatives=rows,recommended=best['strategy'],frontier=frontier,
                resolution=resolution,time_budget=time_budget,scene_hash=original_hash,
                phase_candidates=phase_result['candidates'],local_attempts=attempts,
                note='同一保护范围、喷幅、作业高度与CAW默认参数。局部边带保持原相位，最多补4段，每轮试前4个候选；有限贪心，非全局最优。重复喷洒和估算喷量单列；网格零值不证明真实零漏喷。')
