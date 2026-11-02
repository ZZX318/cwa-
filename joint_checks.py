from scene import generate
from joint import optimize
def run():
 r=optimize(generate(),{},4); assert r['status']=='unsupported'
 s=generate({'rows':1,'trees_per_row':2}); q=optimize(s,{},8); assert q['status'] in ('success','unsupported'); print('通过 · 第十三阶段小规模联合顺序基准'); return 0
