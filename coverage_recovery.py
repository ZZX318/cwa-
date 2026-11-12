"""Bounded CAW phase alternatives under exactly the same exclusion geometry."""
import math
from scene import validate_scene
from scene.geometry import polygon_bounds
from planning import configuration
from planner_api import make_planner
from execution import build
from evaluation import build as evaluate, at
from wind_buffer import check_buffer_wind


def recover(scene, raw, resolution=.25):
    validate_scene(scene)
    c = configuration(raw)
    check_buffer_wind(scene,c)
    if type(resolution) not in (float,int) or not math.isfinite(resolution) or resolution < .05 or resolution > 1:
        raise ValueError("恢复方案评价网格须在 0.05 至 1 m")
    if len(scene["targets"]) > 200:
        raise ValueError("当前候选方案支持最多 200 个目标，请先缩小实验场景")
    if not scene["targets"]:
        raise ValueError("没有喷洒目标")
    xmin=min(t["geometry"]["center"][0]-t["geometry"]["radius"] for t in scene["targets"])
    w=c["swath"]
    phases=[c["lane_phase"],0.0]
    # Test actual restricted frontiers first, then a small uniform sensitivity set.
    for zone in scene["no_spray_zones"]+scene["no_fly_zones"]:
        b=polygon_bounds(zone["footprint"])
        for x in (b["min"][0]-.01,b["max"][0]+.01):
            phases.append((x-xmin)%w)
    phases += [w*k/4 for k in range(1,4)]
    unique=[]
    for phase in phases:
        if all(abs(phase-p)>1e-6 for p in unique): unique.append(phase)
    if len(unique)>16:
        raise ValueError("区域边界过多，候选相位超过 16 个，请分区域实验")
    bounds=[polygon_bounds(z["footprint"]) for z in scene["no_spray_zones"]+scene["no_fly_zones"]]
    points=set()
    for t in scene["targets"]:
        g=t["geometry"];x,y=g["center"];r=g["radius"]
        for ix in range(math.floor((x-r)/resolution),math.ceil((x+r)/resolution)):
            for iy in range(math.floor((y-r)/resolution),math.ceil((y+r)/resolution)):
                px,py=(ix+.5)*resolution,(iy+.5)*resolution
                if math.hypot(px-x,py-y)<=r: points.add((px,py))
    if points and all(any(b["min"][0]<=x<=b["max"][0] and b["min"][1]<=y<=b["max"][1] for b in bounds) for x,y in points):
        return dict(improved=False,baseline=None,recommended=None,candidates=[],resolution=resolution,
            message="当前网格下全部树冠都处于禁喷范围，没有合法喷洒面积。保留受限任务，建议等待风况变化后重新评估缓冲，或另行评估人工定点施药；当前保护范围内不能直接补喷。")
    rows=[]
    for phase in unique:
        config=dict(c,lane_phase=phase)
        plan=make_planner("caw-a*-3d-wind").plan(scene,config)
        row=dict(phase=phase,status=plan["status"],reason=plan.get("reason"))
        if plan["status"]=="success":
            timeline=build(scene,plan)
            m=at(evaluate(scene,plan,timeline,resolution),timeline,timeline["duration"])
            if m["illegal"]: raise ValueError("候选执行存在禁喷足迹侵入")
            row.update(duration=timeline["duration"],restricted_area=m["restricted_canopy_area_m2"],
                sprayable_area=m["sprayable_canopy_area_m2"],extra_miss=m["extra_miss_area_m2"],
                sprayable_coverage=m["sprayable_coverage"],illegal_count=len(m["illegal"]))
        rows.append(row)
    baseline=rows[0]
    valid=[r for r in rows if r["status"]=="success"]
    if not valid:
        return dict(improved=False,baseline=baseline,recommended=None,candidates=rows,
            message="所有候选均不可执行，请先处理障碍可达性或起降点；不能通过缩小保护范围强行喷洒。")
    best=min(valid,key=lambda r:(round(r["extra_miss"],8),r["duration"]))
    improved=baseline["status"]!="success" or best["extra_miss"] < baseline["extra_miss"]-1e-8
    if best["sprayable_area"]==0:
        message="所有树冠都处于禁喷约束内，当前条件下没有合法喷洒面积。保留任务记录，建议调整作业时段或采用另行评估的人工定点施药；不能直接越界补喷。"
    elif improved:
        before="不可执行" if baseline["status"]!="success" else f'{baseline["extra_miss"]:.2f} m² / {baseline["duration"]:.2f} s'
        message=f'候选平移 {best["phase"]:.3f} m：原方案 {before}，新方案区外漏喷 {best["extra_miss"]:.2f} m² / {best["duration"]:.2f} s。受限树冠 {best["restricted_area"]:.2f} m² 仍关喷。已应用平移并重新生成 CAW 航线。'
    else:
        message=f'受限树冠 {best["restricted_area"]:.2f} m² 必须关喷；本次相位候选未进一步减少区外漏喷（{best["extra_miss"]:.2f} m²）。可使用“比较整体平移与局部边带”继续评估；自动改航向与人工定点路线尚未实现。'
    return dict(improved=improved,baseline=baseline,recommended=best,candidates=rows,
        resolution=resolution,method="bounded-phase-candidates",message=message,
        note="同一保护几何；优先减少区外漏喷，再比较时间。网格采样，非连续零漏喷证明，非全局最优。")
