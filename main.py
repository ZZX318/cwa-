"""Run this file in VS Code; paths are independent of working directory."""

import argparse
import json
from pathlib import Path
from scene import generate, load, save, summary


ROOT = Path(__file__).resolve().parent


def job_config(job, transition_mode):
    """Load job JSON and let the CLI transition mode override the file value."""
    from planning.model import with_transition_mode

    return with_transition_mode(json.loads(job.read_text()) if job else {}, transition_mode)


def main() -> int:
    """Launch UI by default, or run shared scene tools in terminal mode."""
    p = argparse.ArgumentParser(description="果园场景工具 · 第一阶段")
    p.add_argument("--check", action="store_true")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--port", type=int, default=0)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path)
    source.add_argument("--load", type=Path)
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
    p.add_argument("--methods", default="fixed-y,naive,multi,rl")
    p.add_argument("--save-results", type=Path)
    p.add_argument("--transition-experiment", action="store_true")
    p.add_argument("--save-transition-results", type=Path)
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

        return max(run(), plan_checks(), execution_checks(), evaluation_checks(), comparison_checks(), multi_checks(), env_checks(), rl_checks(), plant_checks(), experiment_checks(), wind_checks(), routing_checks(), joint_checks(), coordination_checks(), surrogate_checks(), web_checks(), transition_checks(), transition_experiment_checks())
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
        result=run_experiment(tuple(int(x) for x in a.seeds.split(',')),tuple(x for x in a.methods.split(',') if x), (a.uavs,))
        if a.save_results: save_results(result,a.save_results)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    if a.env_demo:
        from env import MultiUAVEnv
        e=MultiUAVEnv(generate(), {}, a.uavs, 0)
        while e.result()["status"] != "success": e.step(e.random_policy())
        print(json.dumps(e.result(), ensure_ascii=False, indent=2)); return 0
    if a.transition_experiment:
        from transition_experiment import run as run_transition_experiment, save as save_transition_results
        scene = load(a.load) if a.load else generate(json.loads(a.config.read_text()) if a.config else {})
        result = run_transition_experiment(scene, job_config(a.job, None))
        if a.save_transition_results: save_transition_results(result, a.save_transition_results)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    if a.config or a.load or a.save or a.summary or a.plan or a.load_plan or a.execute or a.compare or a.multi:
        try:
            s = (
                load(a.load)
                if a.load
                else generate(json.loads(a.config.read_text()) if a.config else {})
            )
            if a.compare:
                from comparison import run as compare_run, save as save_comparison
                result=compare_run(s, job_config(a.job, a.transition_mode), a.method)
                if a.save_comparison: save_comparison(result,a.save_comparison)
                print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
            if a.multi:
                from multi import run as multi_run
                result=multi_run(s, job_config(a.job, a.transition_mode), a.uavs)
                print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result['status']=='success' else 1
            if a.plan or a.load_plan or a.execute:
                from planning import generate_plan, load_plan, save_plan

                plan = (
                    load_plan(s, a.load_plan)
                    if a.load_plan
                    else generate_plan(
                        s, job_config(a.job, a.transition_mode)
                    )
                )
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
