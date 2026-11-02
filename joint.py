"""Small exact ordering baseline over spray lanes."""
import itertools, math
from planning import generate_plan, fingerprint
def optimize(scene,config=None,limit=8):
 p=generate_plan(scene,config or {}); sprays=[s for s in p.get('segments',[]) if s['type']=='spray']
 if p['status']!='success': return {'status':'failed','reason':p['reason']}
 if len(sprays)>limit: return {'status':'unsupported','reason':f'航段 {len(sprays)} 超过穷举上限 {limit}','scene_hash':fingerprint(scene)}
 best=None; expanded=0
 for order in itertools.permutations(range(len(sprays))):
  expanded+=1; length=sum(math.dist(sprays[order[i]]['end'],sprays[order[i+1]]['start']) for i in range(len(order)-1))
  if best is None or length<best['transition_length']: best={'order':list(order),'transition_length':length}
 return {'status':'success','method':'exact-lane-order','order':best['order'],'transition_length':best['transition_length'],'expanded':expanded,'scene_hash':fingerprint(scene),'optimality_gap':0.0}
