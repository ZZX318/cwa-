"""Explainable clearance-aware grid routing baseline for transition segments."""
import heapq, math
from planning import fingerprint

def _blocked(scene,p,clearance):
    x,y,z=p
    for o in scene['obstacles']:
        if o['min'][0]-clearance<=x<=o['max'][0]+clearance and o['min'][1]-clearance<=y<=o['max'][1]+clearance and o['min'][2]-clearance<=z<=o['max'][2]+clearance:return True
    return False
def route(scene,start,goal,step=1.0,clearance=.5):
    if step<=0: raise ValueError('step 必须为正数')
    z=max(start[2],goal[2]); lo,hi=scene['extent']['min'],scene['extent']['max']
    def key(p): return (round(p[0]/step),round(p[1]/step))
    s,g=key(start),key(goal); openq=[(0,s)]; came={}; cost={s:0}; nodes=0
    while openq:
        _,u=heapq.heappop(openq); nodes+=1
        if u==g:
            path=[]
            while u in came: path.append([u[0]*step,u[1]*step,z]);u=came[u]
            path.append([start[0],start[1],z]);path.reverse();path[-1]=[goal[0],goal[1],z]
            return {'status':'success','path':path,'length':sum(math.dist(a,b) for a,b in zip(path,path[1:])),'expanded':nodes,'scene_hash':fingerprint(scene)}
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            v=(u[0]+dx,u[1]+dy); p=[v[0]*step,v[1]*step,z]
            if not(lo[0]<=p[0]<=hi[0] and lo[1]<=p[1]<=hi[1]) or _blocked(scene,p,clearance): continue
            ng=cost[u]+step
            if ng<cost.get(v,1e99): cost[v]=ng;came[v]=u;heapq.heappush(openq,(ng+math.hypot(v[0]-g[0],v[1]-g[1])*step,v))
    return {'status':'failed','reason':'离散搜索未找到满足净空的路径','expanded':nodes,'scene_hash':fingerprint(scene)}
