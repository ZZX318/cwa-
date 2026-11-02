from scene import generate
from planning import generate_plan
from execution import build
from evaluation import build as eb, at
import copy


def run():
    s = generate()
    p = generate_plan(s)
    t = build(s, p)
    e = eb(s, p, t, 0.5)
    z = at(e, t, 0)
    assert z["covered_cells"] == 0
    m = at(e, t, t["segments"][0]["t_end"])
    assert m["covered_cells"] == 0
    end = at(e, t, t["duration"])
    assert end["coverage"] > 0 and end["missed_cells"] >= 0
    bad = copy.deepcopy(t)
    bad["plan_hash"] = "x"
    try:
        eb(s, p, bad)
    except ValueError:
        pass
    else:
        raise AssertionError("指纹未拒绝")
    print("通过 · 第四阶段基础覆盖评价：零覆盖、执行累计、终点指标与指纹拒绝")
    return 0
