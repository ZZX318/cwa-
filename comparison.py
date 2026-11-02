"""Fair method comparison: same scene, job, execution and grid evaluator."""
import json
from pathlib import Path
from planning import generate_plan, fingerprint
from execution import build
from evaluation import build as eval_build, at

def run(scene, config, method='both', resolution=.5):
    names=['fixed-y-boustrophedon','naive-target-order'] if method=='both' else [method]
    out={'version':'1.0','scene_hash':fingerprint(scene),'config':config,'resolution':resolution,'results':[]}
    for name in names:
        try:
            plan=generate_plan(scene,config)
            plan['method']=name
            timeline=build(scene,plan); ev=eval_build(scene,plan,timeline,resolution); m=at(ev,timeline,timeline['duration'])
            out['results'].append(dict(method=name,status='success',plan_hash=fingerprint(plan),timeline_id=timeline['execution_id'],path_length=sum(x['length'] for x in timeline['segments']),duration=timeline['duration'],spray_seconds=m['spray_seconds'],coverage=m['coverage'],covered=m['covered_cells'],missed=m['missed_cells'],repeated=m['repeated_cells'],violation=bool(m['illegal'])))
        except Exception as e: out['results'].append(dict(method=name,status='failed',reason=str(e)))
    return out

def save(result,path): Path(path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
