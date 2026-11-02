from scene import generate
from rl import train,evaluate,save,load
from pathlib import Path
from tempfile import gettempdir
def run():
 s=generate(); a=train(s,{},2,2,3); b=train(s,{},2,2,3); assert a==b
 p=Path(gettempdir())/'orchard.policy.json'; save(a,p); assert load(p)==a
 r=evaluate(s,a,{}); assert r['scene_hash']==a['scene_hash'] and r['status']=='success' and not r['violation']
 print('通过 · 第八阶段最小策略训练、保存加载与统一评价'); return 0
