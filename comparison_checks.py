from scene import generate
from comparison import run

def run_checks():
    s = generate()
    r = run(s, dict(swath=2, height_offset=2, clearance=.5, speed=2))
    assert len(r["results"]) == 2
    methods = []
    for x in r["results"]:
        assert x["status"] == "success", x
        assert 0 <= x["coverage"] <= 1 and x["duration"] > 0
        assert x["safety"] == "pass"
        assert x["scene_hash"] == r["results"][0]["scene_hash"]
        methods.append(x["method"])
    assert len(set(methods)) == 2, methods
    # 两方法在同一场景上都必须给出有限时长，且至少有一个达到满覆盖
    assert max(x["coverage"] for x in r["results"]) == 1.0
    print("通过 · 第五阶段两方法统一执行与网格评价比较")
    return 0
