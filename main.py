"""Run this file in VS Code; paths are independent of working directory."""

import argparse
import json
from pathlib import Path
from scene import generate, load, save, summary


ROOT = Path(__file__).resolve().parent


def job_config(job, transition_mode):
    """Load job JSON and let the CLI transition mode override the file value."""
    from planning.model import with_transition_mode

    raw = json.loads(job.read_text()) if job else {}
    if not isinstance(raw, dict):
        raise ValueError("作业 JSON 顶层必须是对象")
    return with_transition_mode(raw, transition_mode)


def main() -> int:
    """Launch UI by default, or run shared scene tools in terminal mode."""
    p = argparse.ArgumentParser(description="果园植保无人机仿真 · 统一入口")
    p.add_argument("--check", action="store_true")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--port", type=int, default=0)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path)
    source.add_argument("--load", type=Path)
    source.add_argument(
        "--random-scene",
        action="store_true",
        help="生成可复现随机场景（与 --config/--load 互斥）",
    )
    p.add_argument(
        "--style",
        default="regular",
        choices=(
            "regular",
            "jitter_rows",
            "clusters_gaps",
            "clustered",
            "size_mix",
            "random_obstacles_zones",
        ),
        help="--random-scene 的样式（clustered 是 clusters_gaps 的别名）",
    )
    p.add_argument("--random-params", type=Path, help="随机样式参数 JSON 文件")
    p.add_argument(
        "--require-reachable",
        action="store_true",
        help="随机场景必须通过固定条带规划，否则明确失败",
    )
    p.add_argument("--save", type=Path)
    p.add_argument("--summary", action="store_true")
    p.add_argument(
        "--preview", action="store_true", help="打开配置或已加载场景的交互预览"
    )
    p.add_argument("--plan", action="store_true")
    p.add_argument("--job", type=Path)
    p.add_argument(
        "--transition-mode",
        choices=("fixed", "search"),
        help="覆盖作业 JSON 的 transition_mode；未给出时用配置值，配置也未给出时为 fixed",
    )
    p.add_argument("--save-plan", type=Path)
    p.add_argument("--load-plan", type=Path)
    p.add_argument(
        "--algorithm",
        help="规划器：fixed-y / naive / caw / caw-a*-fixed-order / caw-a*-nn / caw-a*-3d-wind",
    )
    p.add_argument("--objective", default="time", choices=("time", "energy"))
    p.add_argument(
        "--order-strategy", default="nn+2opt", choices=("fixed", "nn", "nn+2opt", "nn_astar")
    )
    p.add_argument("--step-xy", type=float, default=1.0)
    p.add_argument("--joint-transition", choices=("fixed", "search", "caw"))
    p.add_argument("--order", action="store_true")
    p.add_argument("--save-order", type=Path)
    p.add_argument("--route3d", action="store_true")
    p.add_argument("--start", type=float, nargs=3)
    p.add_argument("--end", type=float, nargs=3)
    p.add_argument("--save-route3d", type=Path)
    p.add_argument("--compare", action="store_true")
    p.add_argument("--multi", action="store_true")
    p.add_argument("--uavs", type=int, default=2)
    p.add_argument("--env-demo", action="store_true")
    p.add_argument("--train", action="store_true")
    p.add_argument("--episodes", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--save-policy", type=Path)
    p.add_argument("--evaluate-policy", type=Path)
    p.add_argument("--experiment", action="store_true")
    p.add_argument("--seeds", default="0")
    p.add_argument("--scene-style", help="--experiment 时每个 seed 用该随机样式生成独立场景")
    p.add_argument("--methods", default="fixed-y,naive,multi,rl")
    p.add_argument("--save-results", type=Path)
    p.add_argument("--transition-experiment", action="store_true")
    p.add_argument("--save-transition-results", type=Path)
    p.add_argument("--joint", action="store_true")
    p.add_argument("--save-joint", type=Path)
    p.add_argument("--coordinate", action="store_true")
    p.add_argument("--save-coordination", type=Path)
    p.add_argument("--optimize-depot", action="store_true")
    p.add_argument(
        "--depot-candidates", choices=("launch", "grid"), default="launch"
    )
    p.add_argument("--depot-grid", type=int, default=3)
    p.add_argument("--depot-budget", type=int, default=64)
    p.add_argument(
        "--energy-profile",
        choices=("motion-only", "mission-proxy"),
        default="motion-only",
    )
    p.add_argument("--save-depot", type=Path)
    p.add_argument("--depot-coordinate", action="store_true")
    p.add_argument("--energy-wh-per-eu", type=float)
    p.add_argument("--energy-calibration-id")
    p.add_argument("--sorties", action="store_true")
    p.add_argument("--payload-capacity-kg", type=float)
    p.add_argument("--flow-rate-kg-per-s", type=float)
    p.add_argument("--refill-seconds", type=float, default=0.0)
    p.add_argument("--recharge-seconds", type=float, default=0.0)
    p.add_argument("--save-sorties", type=Path)
    p.add_argument("--min-distance", type=float, default=1.0)
    p.add_argument("--max-delay", type=float, default=120.0)
    p.add_argument("--max-attempts", type=int, default=200)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--method", default="both")
    p.add_argument("--save-comparison", type=Path)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--time", type=float, default=0.0)
    p.add_argument("--step", type=float, default=1.0)
    p.add_argument("--save-execution", type=Path)
    p.add_argument("--load-execution", type=Path)
    p.add_argument("--samples", type=Path)
    a = p.parse_args()
    for field in (
        "config",
        "load",
        "save",
        "job",
        "save_plan",
        "load_plan",
        "save_execution",
        "load_execution",
        "samples",
        "save_policy",
        "evaluate_policy",
        "save_results",
        "save_transition_results",
        "save_depot",
        "save_sorties",
        "save_joint",
        "save_coordination",
        "save_order",
        "save_route3d",
        "random_params",
    ):
        value = getattr(a, field)
        if value is not None and not value.is_absolute():
            setattr(a, field, ROOT / value)
    if a.check:
        from checks import run

        from planning_checks import run as plan_checks
        from evaluation_checks import run as evaluation_checks

        from execution_checks import run as execution_checks
        from comparison_checks import run_checks as comparison_checks
        from multi_checks import run_checks as multi_checks
        from env_checks import run as env_checks
        from rl_checks import run as rl_checks
        from plant_evaluation_checks import run as plant_checks
        from experiment_checks import run_checks as experiment_checks
        from wind_checks import run as wind_checks
        from routing_checks import run as routing_checks
        from joint_checks import run as joint_checks
        from coordination_checks import run_checks as coordination_checks
        from surrogate_checks import run as surrogate_checks
        from web_checks import run as web_checks
        from transition_checks import run as transition_checks
        from transition_experiment_checks import run_checks as transition_experiment_checks
        from joint_transit_checks import run as joint_transit_checks
        from coordination_plan_checks import run as coordination_plan_checks
        from playback_checks import run as playback_checks
        from evaluation_swath_checks import run as evaluation_swath_checks
        from routing3d_checks import run as routing3d_checks
        from wind_planning_checks import run as wind_planning_checks
        from planner_checks import run as planner_checks
        from order_checks import run as order_checks
        from comparison_real_checks import run_checks as comparison_real_checks
        from experiment_semantics_checks import run_checks as experiment_semantics_checks
        from caw_checks import run as caw_checks
        from random_map_checks import run as random_map_checks
        from scene_editor_checks import run as scene_editor_checks
        from depot_checks import run_checks as depot_checks
        from launch_checks import run_checks as launch_checks
        from sortie_checks import run_checks as sortie_checks
        from multi_caw_checks import run as multi_caw_checks
        from regression_cli_checks import run_checks as regression_cli_checks
        from no_spray_cut_checks import run as no_spray_cut_checks
        from zone_metric_checks import run as zone_metric_checks
        from drift_checks import run as drift_checks

        return max(run(), plan_checks(), execution_checks(), evaluation_checks(), comparison_checks(), multi_checks(), env_checks(), rl_checks(), plant_checks(), experiment_checks(), wind_checks(), routing_checks(), joint_checks(), coordination_checks(), surrogate_checks(), web_checks(), transition_checks(), transition_experiment_checks(), joint_transit_checks(), coordination_plan_checks(), playback_checks(), evaluation_swath_checks(), routing3d_checks(), wind_planning_checks(), planner_checks(), order_checks(), comparison_real_checks(), experiment_semantics_checks(), caw_checks(), random_map_checks(), scene_editor_checks(), depot_checks(), launch_checks(), sortie_checks(), multi_caw_checks(), regression_cli_checks(), no_spray_cut_checks(), zone_metric_checks(), drift_checks())
    if a.random_scene:
        try:
            from random_scene import generate_with_report

            params = None
            if a.random_params:
                params = json.loads(a.random_params.read_text(encoding="utf8"))
                if not isinstance(params, dict):
                    raise ValueError("随机参数 JSON 顶层必须是对象")
            scene, report = generate_with_report(
                a.style, a.seed, params, a.require_reachable
            )
            if a.save:
                save(scene, a.save)
            print(
                json.dumps(
                    dict(
                        summary=summary(
                            scene, validated=True, warnings=report.get("warnings", [])
                        ),
                        report=report,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        except (ValueError, OSError) as error:
            print(f"失败：{error}")
            return 1
    if a.train or a.evaluate_policy:
        from rl import train as train_policy, evaluate as evaluate_policy, save as save_policy, load as load_policy
        if a.evaluate_policy:
            policy=load_policy(a.evaluate_policy); result=evaluate_policy(generate(),policy,{})
        else:
            policy=train_policy(generate(),{},a.uavs,a.episodes,a.seed)
            if a.save_policy: save_policy(policy,a.save_policy)
            result=policy
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    if a.experiment:
        from experiment import run as run_experiment, save as save_results
        if a.config or a.load:
            print("失败：实验暂不支持 --config/--load；请使用默认场景")
            return 2
        job = job_config(a.job, a.transition_mode) if a.job else {}
        try:
            seeds = tuple(range(int(a.seeds.split('-')[0]), int(a.seeds.split('-')[1]) + 1)) if '-' in a.seeds else tuple(int(x) for x in a.seeds.split(','))
            params = json.loads(a.random_params.read_text(encoding="utf8")) if a.random_params else None
            result=run_experiment(seeds,tuple(x for x in a.methods.split(',') if x), (a.uavs,), config=job, scene_style=a.scene_style, scene_params=params, require_reachable=a.require_reachable)
        except (ValueError, TypeError, KeyError, OSError) as error:
            print(f"失败：{error}")
            return 2
        if a.save_results: save_results(result,a.save_results)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    if a.env_demo:
        from env import MultiUAVEnv
        e=MultiUAVEnv(generate(), {}, a.uavs, 0)
        while e.result()["status"] != "success": e.step(e.random_policy())
        print(json.dumps(e.result(), ensure_ascii=False, indent=2)); return 0
    if a.transition_experiment:
        from transition_experiment import run as run_transition_experiment, save as save_transition_results
        try:
            scene = load(a.load) if a.load else generate(json.loads(a.config.read_text()) if a.config else {})
            result = run_transition_experiment(scene, job_config(a.job, None))
        except (ValueError, OSError) as e:
            print(f"失败：{e}")
            return 1
        if a.save_transition_results: save_transition_results(result, a.save_transition_results)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if a.config or a.load or a.save or a.summary or a.plan or a.load_plan or a.execute or a.compare or a.multi or a.joint or a.coordinate or a.order or a.route3d or a.optimize_depot or a.sorties:
        try:
            s = (
                load(a.load)
                if a.load
                else generate(json.loads(a.config.read_text()) if a.config else {})
            )
            if a.order:
                from planning.order import solve_order
                from planning.planner import fixed_y_lanes

                try:
                    job = job_config(a.job, a.transition_mode)
                    layout = fixed_y_lanes(s, job)
                    result = solve_order(
                        s,
                        job,
                        layout["lanes"],
                        strategy=a.order_strategy,
                        objective=a.objective,
                        step_xy=a.step_xy,
                    )
                except (ValueError, TypeError) as error:
                    print(f"失败：{error}")
                    return 2
                if a.save_order:
                    a.save_order.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
                        encoding="utf8",
                    )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "success" else 1
            if a.route3d:
                from planning.model import configuration
                from planning.planner import fixed_y_lanes
                from planning.routing3d import route3d

                try:
                    job = job_config(a.job, a.transition_mode)
                    c = configuration(job)
                    layout = fixed_y_lanes(s, c)
                    home = sorted(
                        s["launch_points"], key=lambda p: tuple(p["position"])
                    )[0]["position"]
                    start = a.start or [home[0], home[1], layout["work_height"]]
                    goal = a.end or (
                        layout["lanes"][0]["start"] if layout["lanes"] else None
                    )
                    if goal is None:
                        raise ValueError("场景没有喷洒航段，请用 --start/--end 指定端点")
                    result = route3d(
                        s,
                        start,
                        goal,
                        c,
                        objective=a.objective,
                        grid={"step_xy": a.step_xy},
                    )
                except (ValueError, TypeError) as error:
                    print(f"失败：{error}")
                    return 2
                if a.save_route3d:
                    a.save_route3d.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
                        encoding="utf8",
                    )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "success" else 1
            if a.coordinate:
                from coordination_plan import (
                    coordinate,
                    normalize_algorithm,
                    save as save_coordination,
                )

                try:
                    algorithm = normalize_algorithm(a.algorithm)
                    options = None
                    if algorithm == "caw":
                        from planner_api import normalize_name

                        name = normalize_name(a.algorithm)
                        options = dict(
                            step_xy=a.step_xy,
                            order_strategy=(
                                "nn"
                                if name == "caw-a*-nn"
                                else "fixed"
                                if name == "caw-a*-fixed-order"
                                else a.order_strategy
                            ),
                            objective=a.objective,
                        )
                    result = coordinate(
                        s,
                        job_config(a.job, a.transition_mode),
                        a.uavs,
                        a.min_distance,
                        a.max_delay,
                        a.max_attempts,
                        algorithm=algorithm,
                        options=options,
                    )
                except (ValueError, TypeError) as error:
                    print(f"失败：{error}")
                    return 2
                if a.save_coordination:
                    try:
                        save_coordination(result, a.save_coordination)
                    except OSError as error:
                        print(f"失败：协调结果无法写入 {a.save_coordination}：{error}")
                        return 1
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "success" else 1
            if a.sorties:
                from sortie import plan_sorties, save as save_sorties

                energy_options = {"profile": a.energy_profile}
                if a.energy_wh_per_eu is not None:
                    energy_options["wh_per_eu"] = a.energy_wh_per_eu
                if a.energy_calibration_id is not None:
                    energy_options["calibration_id"] = a.energy_calibration_id
                try:
                    result = plan_sorties(
                        s,
                        job_config(a.job, a.transition_mode),
                        {
                            "payload_capacity_kg": a.payload_capacity_kg,
                            "flow_rate_kg_per_s": a.flow_rate_kg_per_s,
                            "refill_seconds": a.refill_seconds,
                            "recharge_seconds": a.recharge_seconds,
                            "energy": energy_options,
                        },
                    )
                except (ValueError, TypeError) as error:
                    print(f"失败：{error}")
                    return 2
                if a.save_sorties:
                    try:
                        save_sorties(result, a.save_sorties)
                    except OSError as error:
                        print(f"失败：多批次结果无法写入 {a.save_sorties}：{error}")
                        return 1
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "success" else 1
            if a.optimize_depot:
                from depot import optimize as optimize_depot, save as save_depot

                planner = a.algorithm or "fixed-y"
                planner_options = {}
                if planner not in ("fixed-y", "naive"):
                    planner_options = dict(
                        step_xy=a.step_xy,
                        order_strategy=a.order_strategy,
                        objective=a.objective,
                    )
                energy_options = {"profile": a.energy_profile}
                if a.energy_wh_per_eu is not None:
                    energy_options["wh_per_eu"] = a.energy_wh_per_eu
                if a.energy_calibration_id is not None:
                    energy_options["calibration_id"] = a.energy_calibration_id
                options = dict(
                    candidates=a.depot_candidates,
                    grid=a.depot_grid,
                    budget=a.depot_budget,
                    uavs=a.uavs,
                    objective=a.objective,
                    planner=planner,
                    planner_options=planner_options,
                    energy=energy_options,
                    coordinate=a.depot_coordinate,
                    min_distance=a.min_distance,
                )
                try:
                    result = optimize_depot(
                        s, job_config(a.job, a.transition_mode), options
                    )
                except (ValueError, TypeError) as error:
                    print(f"失败：{error}")
                    return 2
                if a.save_depot:
                    try:
                        save_depot(result, a.save_depot)
                    except OSError as error:
                        print(f"失败：起降点结果无法写入 {a.save_depot}：{error}")
                        return 1
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["status"] == "success" else 1
            if a.joint:
                from joint import optimize, save as save_joint

                job = job_config(a.job, a.transition_mode)
                options = dict(
                    transition=a.joint_transition or job.get("transition_mode", "fixed"),
                    step_xy=a.step_xy,
                    objective=a.objective,
                )
                result = optimize(s, job, a.limit, options)
                if a.save_joint:
                    save_joint(result, a.save_joint)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if result["status"] == "success":
                    return 0
                return 2 if result["status"] == "unsupported" else 1
            if a.compare:
                from comparison import run as compare_run, save as save_comparison
                result=compare_run(s, job_config(a.job, a.transition_mode), a.method)
                if a.save_comparison: save_comparison(result,a.save_comparison)
                print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
            if a.multi:
                from planner_api import normalize_name

                try:
                    name = normalize_name(a.algorithm or "fixed-y")
                except ValueError as error:
                    print(f"失败：{error}")
                    return 2
                job = job_config(a.job, a.transition_mode)
                if name.startswith("caw"):
                    from multi_caw import run as multi_caw_run

                    options = dict(
                        step_xy=a.step_xy,
                        order_strategy=(
                            "nn"
                            if name == "caw-a*-nn"
                            else "fixed"
                            if name == "caw-a*-fixed-order"
                            else a.order_strategy
                        ),
                        objective=a.objective,
                    )
                    try:
                        result = multi_caw_run(s, job, a.uavs, options)
                    except (ValueError, TypeError) as error:
                        print(f"失败：{error}")
                        return 2
                elif name == "fixed-y-boustrophedon":
                    from multi import run as multi_run

                    result = multi_run(s, job, a.uavs)
                else:
                    print("失败：--multi 仅支持 --algorithm fixed-y 或 caw")
                    return 2
                print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result['status']=='success' else 1
            if a.plan or a.load_plan or a.execute:
                from planning import generate_plan, load_plan, save_plan

                if a.load_plan:
                    plan = load_plan(s, a.load_plan)
                elif a.algorithm:
                    from planner_api import make_planner

                    if a.objective == "energy" and a.algorithm in ("fixed-y", "naive"):
                        print("失败：能量代理口径未实现（M2）；请使用 time")
                        return 1
                    options = {}
                    if a.algorithm not in ("fixed-y", "naive"):
                        options = dict(
                            step_xy=a.step_xy,
                            order_strategy=a.order_strategy,
                            objective=a.objective,
                        )
                    plan = make_planner(a.algorithm).plan(
                        s, job_config(a.job, a.transition_mode), options
                    )
                else:
                    if a.objective == "energy":
                        print("失败：能量代理口径未实现（M2）；请使用 time")
                        return 1
                    plan = generate_plan(
                        s, job_config(a.job, a.transition_mode)
                    )
                if plan["status"] == "success":
                    from planning import fingerprint as plan_fingerprint

                    plan.setdefault("plan_hash", plan_fingerprint(plan))
                if a.save_plan and plan["status"] == "success":
                    save_plan(s, plan, a.save_plan)
                if a.execute:
                    from execution import (
                        build,
                        state_at,
                        sample,
                        save as save_execution,
                        load as load_execution,
                    )

                    timeline = (
                        load_execution(s, plan, a.load_execution)
                        if a.load_execution
                        else build(s, plan)
                    )
                    if a.save_execution:
                        save_execution(timeline, a.save_execution)
                    if a.samples:
                        a.samples.write_text(
                            json.dumps(
                                sample(timeline, a.step), ensure_ascii=False, indent=2
                            ),
                            encoding="utf8",
                        )
                    print(
                        json.dumps(
                            dict(
                                duration=timeline["duration"],
                                state=state_at(timeline, a.time),
                            ),
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    return 0
                print(json.dumps(plan, ensure_ascii=False, indent=2))
                return 0 if plan["status"] == "success" else 1
            if a.save:
                save(s, a.save)
            print(json.dumps(summary(s), ensure_ascii=False, indent=2))
            if a.preview:
                from server import serve

                serve(a.port, not a.no_browser, s)
            return 0
        except (ValueError, OSError) as e:
            print(f"失败：{e}")
            return 1
    from server import serve

    serve(a.port, not a.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
