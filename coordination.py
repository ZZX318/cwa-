"""Continuous-time pairwise coordination diagnostics for multi-UAV timelines."""
import math
def analyze(timelines,min_distance=1.0):
 if min_distance<=0: raise ValueError('最小机间距必须为正')
 conflicts=0; wait=0.0
 for i,a in enumerate(timelines):
  for b in timelines[i+1:]:
   for sa in a['segments']:
    for sb in b['segments']:
     lo=max(sa['t_start'],sb['t_start']); hi=min(sa['t_end'],sb['t_end'])
     if hi<=lo: continue
     fa=(lo-sa['t_start'])/sa['duration']; fb=(lo-sb['t_start'])/sb['duration']
     pa=[x+(y-x)*fa for x,y in zip(sa['start'],sa['end'])]; pb=[x+(y-x)*fb for x,y in zip(sb['start'],sb['end'])]
     if math.dist(pa,pb)<min_distance: conflicts+=1; wait+=hi-lo
 return {'status':'success','conflicts':conflicts,'waiting_seconds':wait,'makespan':max((x['duration'] for x in timelines),default=0.0),'total_time':sum(x['duration'] for x in timelines)}
