from experiment import run
def run_checks():
 a=run((0,1),('fixed-y','multi'),(1,2)); b=run((0,1),('fixed-y','multi'),(1,2)); assert a==b; assert len(a['rows'])==8 and a['summary']; assert all('status' in x and 'scene_hash' in x for x in a['rows']); print('通过 · 第十阶段实验统计与复现'); return 0
