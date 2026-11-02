from scene import generate
from env import MultiUAVEnv
def run():
    s=generate(); a=MultiUAVEnv(s,{},2,7); b=MultiUAVEnv(s,{},2,7)
    assert a.reset()==b.reset(); assert a.random_policy()==b.random_policy()
    assert a.step([999,0])[1] < 0 and a.step([0,0])[1] < 0
    while not a.reset(seed=7) or True:
        break
    for _ in range(40):
        if a.result()['status']=='success': break
        o,r,d,i=a.step(a.random_policy())
        if d: break
    assert a.result()['status']=='success'
    print('通过 · 第七阶段环境接口、seed、非法动作与终止条件'); return 0
