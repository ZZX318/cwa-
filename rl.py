"""Minimal reproducible tabular policy baseline; not a research RL result."""
import json, random
from pathlib import Path
from env import MultiUAVEnv
from execution import build
from evaluation import build as eb, at
from planning import fingerprint

def train(scene, config=None, uavs=2, episodes=50, seed=0):
    if episodes < 1: raise ValueError("episodes 必须为正数")
    rng=random.Random(seed); q={}; rewards=[]
    for _ in range(episodes):
        env=MultiUAVEnv(scene,config,uavs,seed); env.reset(seed)
        total=0
        while env.result()['status']!='success':
            key=tuple(env._obs()['remaining_strips']); actions=env.random_policy() if rng.random()<.2 else env.random_policy()
            obs,reward,done,info=env.step(actions); q[str(key)]=actions; total+=reward
        rewards.append(total)
    return {'version':'1.0','algorithm':'tabular-random-policy-baseline','scene_hash':fingerprint(scene),'seed':seed,'episodes':episodes,'uavs':uavs,'q':q,'rewards':rewards}

def evaluate(scene, policy, config=None):
    env=MultiUAVEnv(scene,config,policy['uavs'],policy['seed']); env.reset(policy['seed'])
    while env.result()['status']!='success':
        key=str(tuple(env._obs()['remaining_strips'])); action=policy['q'].get(key,env.random_policy()); env.step(action)
    plan=env.plan; timeline=build(scene,plan); ev=eb(scene,plan,timeline); m=at(ev,timeline,timeline['duration'])
    return {'status':'success','trajectory':env.trajectory,'path_length':sum(s['length'] for s in timeline['segments']),'duration':timeline['duration'],'coverage':m['coverage'],'missed':m['missed_cells'],'repeated':m['repeated_cells'],'violation':bool(m['illegal']),'scene_hash':fingerprint(scene),'plan_hash':fingerprint(plan)}
def save(policy,path): Path(path).write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf8')
def load(path): return json.loads(Path(path).read_text(encoding='utf8'))
