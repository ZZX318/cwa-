from scene import generate
from routing import route
def run():
 s=generate(); a=route(s,[-3,12.5,6.2],[2,12.5,6.2]); assert a['status']=='success' and a['expanded']>0
 s['obstacles']=[{'id':'wall','min':[-4,10,0],'max':[4,15,8]}]; b=route(s,[-3,12.5,6.2],[2,12.5,6.2]); assert b['status'] in ('success','failed'); print('通过 · 第十二阶段净空网格转场基线'); return 0
