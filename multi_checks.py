from scene import generate
from multi import run
def run_checks():
 r=run(generate(),{},2);assert r['status']=='success' and len(r['uavs'])==2;assert all(x['status']=='success' for x in r['uavs']);print('通过 · 第六阶段多机连续分块基线');return 0
