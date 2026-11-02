"""Small reproducible experiment runner; statistics are descriptive only."""
import json, math, statistics
from pathlib import Path
from scene import generate
from planning import generate_plan
from execution import build
from evaluation import build as eb, at
from multi import run as multi_run
from rl import train, evaluate as rl_eval
from planning import fingerprint

def one(scene, config, method, seed, uavs):
    try:
        if method=='multi':
            r=multi_run(scene,config,uavs)
            if r['status']!='success': return {'status':'failed','reason':r.get('reason','multi failed')}
            vals=[x for x in r['uavs'] if x['status']=='success']
            return {'status':'success','coverage':statistics.mean(x['coverage'] for x in vals),'missed_target_rate':None,'repeated_target_rate':None,'spray_seconds':sum(x.get('duration',0) for x in vals),'total_time':max(x.get('duration',0) for x in vals),'path_length':sum(x.get('path_length',0) for x in vals),'amount':0.0,'violation':False}
        if method=='rl': return rl_eval(scene,train(scene,config,uavs,5,seed),config)
        p=generate_plan(scene,config); p['method']=method; t=build(scene,p); e=eb(scene,p,t); m=at(e,t,t['duration'])
        return {'status':'success','coverage':m['coverage'],'missed_target_rate':len(m['missed_targets'])/len(m['target_stats']),'repeated_target_rate':len(m['repeated_targets'])/len(m['target_stats']),'spray_seconds':m['spray_seconds'],'total_time':t['duration'],'path_length':sum(x['length'] for x in t['segments']),'amount':m['total_spray_amount'],'violation':bool(m['illegal'])}
    except Exception as ex: return {'status':'failed','reason':str(ex)}
def run(seeds=(0,), methods=('fixed-y','naive','multi','rl'), uavs=(1,), config=None):
    rows=[]
    for seed in seeds:
      for n in uavs:
       s=generate(config or {}); sh=fingerprint(s)
       for method in methods:
        r=one(s,{},method,seed,n); r.update(seed=seed,uavs=n,method=method,scene_hash=sh,config_hash=fingerprint({'config':{}})); rows.append(r)
    groups={}
    for r in rows:
      if r['status']!='success': continue
      k=(r['method'],r['uavs']); groups.setdefault(k,[]).append(r)
    summary=[]
    for (m,n),rs in groups.items():
      summary.append({'method':m,'uavs':n,'runs':len(rs),'coverage_mean':statistics.mean(x['coverage'] for x in rs),'coverage_std':statistics.pstdev([x['coverage'] for x in rs]),'time_mean':statistics.mean(x['total_time'] for x in rs)})
    return {'version':'1.0','rows':rows,'summary':summary}
def save(result,path): Path(path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
def load(path): return json.loads(Path(path).read_text(encoding='utf8'))
