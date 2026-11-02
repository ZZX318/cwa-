from scene import generate
from planning import generate_plan
from execution import build
def run():
 s=generate(); p0=generate_plan(s,{}); t0=build(s,p0); p1=generate_plan(s,{'wind_speed':1,'wind_direction':0}); t1=build(s,p1); assert t1['duration']!=t0['duration']; assert generate_plan(s,{'wind_speed':-1})['status']=='failed'; print('通过 · 第十一阶段风场方向代价与无风兼容'); return 0
