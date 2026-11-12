"""Competitive recovery, overlapping protection, budget and saved-plan safety."""
import copy
import json
import math
from scene import generate
from planning import check
from wind_buffer import apply_buffer
from wind_buffer_checks import example
from coverage_alternatives import compare_recovery


def source(id,x0,y0,x1,y1):
    return dict(id=id,kind='polygon_prism',footprint=dict(kind='polygon',
        vertices=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]),z_min=0,z_max=8)


def multi_example():
    s=generate(dict(rows=4,trees_per_row=5,row_spacing=4,plant_spacing=3))
    return apply_buffer(s,[source('sensitive-a',9.8,0,10.5,6.5),
                           source('sensitive-b',14,7.5,14.7,16)],1.3,2,math.pi)['scene']


def run():
    base,z=example();s=apply_buffer(base,[z],3.5,2,math.pi)['scene'];snapshot=copy.deepcopy(s)
    c=dict(wind_speed=2,wind_direction=math.pi)
    result=compare_recovery(s,c,.1,60)
    rows={r['strategy']:r for r in result['alternatives']}
    assert s==snapshot
    assert rows['local-border']['extra_miss']<rows['baseline']['extra_miss']
    assert rows['local-border']['duration']<rows['global-phase']['duration']
    assert rows['local-border']['supplemental_count']>0
    assert rows['local-border']['repeated_area']>=0
    assert 'coverage_recovery' not in rows['baseline']['plan']
    assert len({r['restricted_area'] for r in rows.values()})==1
    saved=json.loads(json.dumps(rows['local-border']['plan']))
    check(s,saved)
    bad=copy.deepcopy(saved)
    spray=next(seg for seg in bad['segments'] if seg['spray'])
    # Moving a spray segment cannot bypass the independent final validator.
    spray['start'][0]=spray['end'][0]=23
    try:check(s,bad)
    except ValueError:pass
    else:raise AssertionError('unsafe edited recovery accepted')
    zero=compare_recovery(s,c,.25,0)
    assert all(r['duration']<=zero['alternatives'][0]['duration']+1e-8 for r in zero['alternatives'])
    dense=multi_example();snapshot=copy.deepcopy(dense)
    result=compare_recovery(dense,c,.1,60)
    assert dense==snapshot and len(dense['wind_buffer']['sources'])==2
    for r in result['alternatives']:
        check(dense,r['plan']);assert r['illegal_count']==0 and r['within_budget']
        assert abs(r['restricted_area']-result['alternatives'][0]['restricted_area'])<1e-8
    assert result['alternatives'][2]['repeated_area']>result['alternatives'][0]['repeated_area']
    for budget in (-1,float('nan'),True):
        try:compare_recovery(s,c,.25,budget)
        except ValueError:pass
        else:raise AssertionError('invalid budget accepted')
    all_blocked=copy.deepcopy(base)
    all_blocked['no_spray_zones']=[source('full',-1,-1,26,26)]
    # Region must remain in the generated scene extent.
    all_blocked['no_spray_zones'][0]['footprint']=copy.deepcopy(base['plot'])
    denied=compare_recovery(all_blocked,{},.25,60)
    assert denied['status']=='unavailable' and not denied['alternatives']
    print('通过 · 局部边带竞争对照、保护面积不变、预算为零、多敏感区密植、保存重载与违规拒出')
    return 0

if __name__=='__main__':run()
