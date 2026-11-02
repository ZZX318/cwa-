"""Small planner protocol and adapters used by future learning agents."""
from planning import generate_plan

class Planner:
    name = "planner"
    def plan(self, scene, config=None):
        raise NotImplementedError

class FixedYPlanner(Planner):
    name = "fixed-y-boustrophedon"
    def plan(self, scene, config=None):
        p = generate_plan(scene, config or {}); p["method"] = self.name; return p

class NaivePlanner(FixedYPlanner):
    name = "naive-target-order"

class MultiBlockPlanner(FixedYPlanner):
    name = "multi-contiguous-uav"

PLANNERS = {x.name: x for x in (FixedYPlanner, NaivePlanner, MultiBlockPlanner)}
def make_planner(name):
    try: return PLANNERS[name]()
    except KeyError: raise ValueError(f"未知规划器: {name}")
