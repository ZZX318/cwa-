"""Deterministic, non-training multi-UAV environment interface."""
import random
from planner_api import FixedYPlanner

class MultiUAVEnv:
    def __init__(self, scene, config=None, uavs=2, seed=0):
        if type(uavs) is not int or not 1 <= uavs <= 32: raise ValueError("无人机数量需为 1..32")
        self.scene, self.config, self.uavs = scene, config or {}, uavs
        self.plan = FixedYPlanner().plan(scene, self.config)
        if self.plan["status"] != "success": raise ValueError(self.plan["reason"])
        self.lanes = [s for s in self.plan["segments"] if s["type"] == "spray"]
        self.seed(seed); self.reset()
    def seed(self, value):
        if type(value) is not int: raise ValueError("seed 必须为整数")
        self._seed, self.rng = value, random.Random(value); return value
    def _obs(self):
        return {"uav_positions": [list(self.home) for _ in range(self.uavs)], "remaining_strips": [i for i in range(len(self.lanes)) if i not in self.done], "obstacles": self.scene["obstacles"], "no_spray_zones": self.scene["no_spray_zones"], "time": self.time, "coverage": 0.0}
    def reset(self, seed=None):
        if seed is not None: self.seed(seed)
        self.home = sorted(self.scene["launch_points"], key=lambda p: tuple(p["position"]))[0]["position"]
        self.done, self.time, self.trajectory = set(), 0.0, []
        return self._obs()
    def step(self, action):
        if type(action) not in (list, tuple) or len(action) != self.uavs: return self._illegal("动作必须是每架无人机一个作业带索引")
        if self.done == set(range(len(self.lanes))): return self._illegal("环境已终止")
        chosen = [int(x) if isinstance(x, int) else -1 for x in action]
        active=[x for x in chosen if x != -1]
        if any(x < 0 or x >= len(self.lanes) or x in self.done for x in active) or len(set(active)) != len(active): return self._illegal("作业带越界、重复或已完成")
        self.done.update(active); self.time += 1.0; self.trajectory.append(chosen)
        terminated = len(self.done) == len(self.lanes)
        return self._obs(), (10.0 if terminated else 1.0), terminated, {"action": chosen}
    def _illegal(self, reason): return self._obs(), -5.0, False, {"illegal": True, "reason": reason}
    def random_policy(self):
        remaining = [i for i in range(len(self.lanes)) if i not in self.done]
        picked=self.rng.sample(remaining, min(self.uavs, len(remaining))) if remaining else []
        return picked + [-1] * (self.uavs-len(picked))
    def result(self):
        return {"status": "success" if len(self.done) == len(self.lanes) else "incomplete", "trajectory": self.trajectory, "strips": len(self.lanes), "time": self.time, "plan": self.plan}
