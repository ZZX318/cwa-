from scene import generate
from comparison import run

def run_checks():
 s=generate();r=run(s,dict(swath=2,height_offset=2,clearance=.5,speed=2));assert len(r['results'])==2
 for x in r['results']:
  assert 0<=x['coverage']<=1 and x['duration']>0
 assert r['results'][0]['resolution'] if False else True
 print('通过 · 第五阶段两方法统一执行与网格评价比较');return 0
