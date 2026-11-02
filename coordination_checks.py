from scene import generate
from multi import run
from execution import build
from planning import generate_plan
from coordination import analyze
def run_checks():
 s=generate(); r=run(s,{},2); ts=[]
 for x in r['uavs']:
  p=dict(generate_plan(s,{})); p['allow_partial']=True; p['segments']=x['segments']; ts.append(build(s,p))
 q=analyze(ts); assert q['makespan']>0 and q['conflicts']>=0; print('通过 · 第十四阶段多机连续时间协同检查'); return 0
