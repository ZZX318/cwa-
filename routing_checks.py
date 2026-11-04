from scene import generate
from routing import route

def run():
    s = generate()
    a = route(s, [-3, 12.5, 6.2], [2, 12.5, 6.2])
    assert a["status"] == "success" and a["expanded"] > 0
    clear_len = a["length"]
    s["obstacles"] = [{"id": "wall", "min": [-4, 10, 0], "max": [4, 15, 8]}]
    b = route(s, [-3, 12.5, 6.2], [2, 12.5, 6.2])
    assert b["status"] == "failed" or (
        b["status"] == "success" and b["length"] > clear_len + 1e-6
    ), b
    # 禁飞区也必须挡住直线转场
    s2 = generate()
    s2["no_fly_zones"] = [
        dict(
            id="nf-wall",
            kind="polygon_prism",
            footprint=dict(
                kind="polygon",
                vertices=[[-1, 10], [1, 10], [1, 15], [-1, 15]],
            ),
            z_min=0,
            z_max=10,
        )
    ]
    c = route(s2, [-3, 12.5, 6.2], [2, 12.5, 6.2], clearance=0.5)
    assert c["status"] == "failed" or (
        c["status"] == "success" and c["length"] > clear_len + 1e-6
    ), c
    print("通过 · 第十二阶段净空网格转场基线")
    return 0
