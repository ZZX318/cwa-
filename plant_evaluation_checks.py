from scene import generate
from planning import generate_plan
from execution import build
from evaluation import build as eb, at
def run():
    s=generate(); p=generate_plan(s,{})
    assert p['status']=='success' and p['config']['target_type']
    assert generate_plan(s,{'flow_rate':0})['status']=='failed'
    t=build(s,p); e=eb(s,p,t); m=at(e,t,t['duration'])
    assert len(m['target_stats'])==len(s['targets'])
    assert m['total_spray_amount']==m['spray_seconds']*p['config']['flow_rate']
    assert isinstance(m['missed_targets'],list) and isinstance(m['repeated_targets'],list)
    assert any(x['spray'] for x in t['segments']) and any(not x['spray'] for x in t['segments'])
    assert m['spray_seconds'] < t['duration']
    print('通过 · 第九阶段植保目标级评价'); return 0
