"""Deterministic multi-UAV contiguous strip partition baseline."""
from planning import generate_plan, check
from execution import build
from evaluation import build as eb,at

def run(scene,config,uavs=2):
 if type(uavs) is not int or not 1<=uavs<=32: raise ValueError('无人机数量需为 1..32')
 base=generate_plan(scene,config)
 if base['status']!='success': return {'status':'failed','reason':base['reason'],'uavs':[]}
 sprays=[(i,s) for i,s in enumerate(base['segments']) if s['type']=='spray']
 chunks=[sprays[i*len(sprays)//uavs:(i+1)*len(sprays)//uavs] for i in range(uavs)]
 out=[]
 for i,chunk in enumerate(chunks):
  if not chunk: out.append({'uav':i+1,'status':'success','segments':[],'duration':0});continue
  ids={tid for _,s in chunk for tid in s['target_ids']}
  first,last=chunk[0][0],chunk[-1][0]
  selected=base['segments'][first:last+1]
  home=sorted(scene['launch_points'], key=lambda p: tuple(p['position']))[0]['position']
  p=dict(base);p['allow_partial']=True;p['segments']=[]
  height=base['work_height']; cur=list(home)
  def add(end,kind,targets=None):
   nonlocal cur
   if cur != end:
    p['segments'].append({'start':cur[:],'end':list(end),'type':kind,'spray':kind=='spray','speed':base['config']['speed'],'target_ids':sorted(targets or [])})
   cur=list(end)
  add([home[0],home[1],height],'takeoff')
  for s in selected:
   add(s['start'],'transit')
   add(s['end'],s['type'],s.get('target_ids',[]))
  add([home[0],home[1],height],'transit'); add(home,'landing')
  p['status']='success';p['method']='multi-contiguous-uav';p['assigned_target_ids']=sorted(ids)
  try: check(scene,p);t=build(scene,p);e=eb(scene,p,t);m=at(e,t,t['duration']);out.append({'uav':i+1,'status':'success','segments':p['segments'],'duration':t['duration'],'path_length':sum(s['length'] for s in t['segments']),'coverage':m['coverage'],'missed':m['missed_cells'],'repeated':m['repeated_cells'],'target_ids':sorted(ids)})
  except Exception as ex: out.append({'uav':i+1,'status':'failed','reason':str(ex)})
 return {'status':'success','uavs':out,'uav_count':uavs}
