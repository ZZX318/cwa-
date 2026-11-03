"""Loopback-only UI adapter. All scene decisions live in scene/."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser
from scene import DEFAULT, Scene, generate, summary, decode, encode
from scene.validation import report as validation_report
from typing import Optional

EXECUTIONS = {}

ROOT = Path(__file__).resolve().parent


def random_response(payload: dict) -> dict:
    """Pure ``POST /api/random`` body builder; raises ValueError on bad input."""
    from random_scene import generate_with_report

    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    style = payload.get("style", "regular")
    seed = payload.get("seed", 0)
    if type(seed) is not int:
        raise ValueError("seed 必须是整数")
    params = payload.get("params")
    if params is not None and not isinstance(params, dict):
        raise ValueError("params 必须是 JSON 对象")
    require_reachable = payload.get("require_reachable", False)
    if type(require_reachable) is not bool:
        raise ValueError("require_reachable 必须是布尔值")
    scene, report = generate_with_report(
        style, seed, params, require_reachable=require_reachable
    )
    config = None
    if style == "regular":
        config = {key: value for key, value in report["parameters"].items() if key in DEFAULT}
    return dict(
        scene=scene,
        summary=summary(scene, validated=True, warnings=report.get("warnings", [])),
        serialized=encode(scene),
        report=report,
        config=config,
    )


def validate_response(payload: dict) -> dict:
    """Pure ``POST /api/validate`` body builder; content errors stay HTTP 200."""
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    if "scene" not in payload:
        raise ValueError("缺少 scene")
    if not isinstance(payload["scene"], dict):
        raise ValueError("scene 必须是 JSON 对象")
    mode = payload.get("mode", "full")
    if mode not in ("fast", "full"):
        raise ValueError("mode 必须为 fast 或 full")
    strict = payload.get("strict")
    if strict is None:
        strict = payload.get("strict_launch")
    if strict is not None and not isinstance(strict, bool):
        raise ValueError("strict / strict_launch 必须是布尔值")
    return validation_report(payload["scene"], mode=mode, strict=strict)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, body, mime="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/default":
            self.respond(
                200,
                json.dumps(dict(config=DEFAULT, scene=generate()), ensure_ascii=False),
            )
            return
        if self.path == "/api/initial":
            scene = self.server.initial_scene or generate()
            self.respond(
                200, json.dumps(dict(config=DEFAULT, scene=scene), ensure_ascii=False)
            )
            return
        paths = {
            "/": "index.html",
            "/app.js": "app.js",
            "/style.css": "style.css",
            "/execution.js": "execution.js",
            "/playback.js": "playback.js",
            "/editor.js": "editor.js",
        }
        if self.path not in paths:
            self.respond(404, "{}")
            return
        name = paths[self.path]
        mime = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[
            name.split(".")[-1]
        ]
        self.respond(200, (ROOT / "web" / name).read_bytes(), mime + "; charset=utf-8")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 8000000:
                raise ValueError("请求大小须在 1 至 8000000 字节")
            payload = json.loads(self.rfile.read(n))
            if self.path == "/api/random":
                self.respond(
                    200,
                    json.dumps(random_response(payload), ensure_ascii=False),
                )
                return
            if self.path == "/api/validate":
                self.respond(
                    200,
                    json.dumps(validate_response(payload), ensure_ascii=False),
                )
                return
            if self.path == "/api/execution":
                from execution import build

                result = build(payload["scene"], payload["plan"])
                if len(EXECUTIONS) >= 8:
                    EXECUTIONS.pop(next(iter(EXECUTIONS)))
                EXECUTIONS[result["execution_id"]] = result
                self.respond(200, json.dumps(result, ensure_ascii=False))
                return
            if self.path == "/api/compare":
                from comparison import run as compare_run
                result=compare_run(payload["scene"],payload.get("config",{}),payload.get("method","both"),payload.get("resolution",.5))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/order":
                from planning.order import solve_order
                from planning.planner import fixed_y_lanes
                layout=fixed_y_lanes(payload["scene"],payload.get("config",{}))
                result=solve_order(payload["scene"],payload.get("config",{}),layout["lanes"],strategy=payload.get("strategy","nn+2opt"),objective=payload.get("objective","time"),step_xy=payload.get("step_xy",1.0))
                result.pop("matrix",None)
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/route3d":
                from planning.model import configuration
                from planning.planner import fixed_y_lanes
                from planning.routing3d import route3d
                c=configuration(payload.get("config",{}))
                layout=fixed_y_lanes(payload["scene"],c)
                home=sorted(payload["scene"]["launch_points"],key=lambda p:tuple(p["position"]))[0]["position"]
                start=payload.get("start") or [home[0],home[1],layout["work_height"]]
                goal=payload.get("goal") or payload.get("end") or (layout["lanes"][0]["start"] if layout["lanes"] else None)
                if goal is None: raise ValueError("没有可用的终点")
                result=route3d(payload["scene"],start,goal,c,objective=payload.get("objective","time"),grid={"step_xy":payload.get("step_xy",1.0)})
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/multi":
                from coordination_plan import normalize_algorithm
                if normalize_algorithm(payload.get("algorithm")) == "caw":
                    from multi_caw import run as multi_caw_run
                    result=multi_caw_run(payload["scene"],payload.get("config",{}),payload.get("uavs",2),payload.get("options"))
                else:
                    from multi import run as multi_run
                    result=multi_run(payload["scene"],payload.get("config",{}),payload.get("uavs",2))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/experiment":
                from experiment import run as experiment_run
                result=experiment_run(tuple(payload.get('seeds',[0])),tuple(payload.get('methods',['fixed-y','multi'])),tuple(payload.get('uavs',[1,2])),config=payload.get('config'))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/route":
                from routing import route
                result=route(payload['scene'],payload['start'],payload['goal'],payload.get('step',1.0),payload.get('clearance',.5))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/coordinate":
                from coordination_plan import coordinate
                result=coordinate(payload['scene'],payload.get('config',{}),payload.get('uavs',2),payload.get('min_distance',1.0),payload.get('max_delay',120.0),payload.get('max_attempts',200),include_playback=True,algorithm=payload.get('algorithm','fixed-y'),options=payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/multi-playback":
                from playback import multi_playback
                result=multi_playback(payload['scene'],payload.get('config',{}),payload.get('uavs',2),algorithm=payload.get('algorithm','fixed-y'),options=payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/joint-playback":
                from playback import joint_playback
                result=joint_playback(payload['scene'],payload.get('config',{}),payload.get('order'),payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/joint":
                from joint import optimize
                result=optimize(payload['scene'],payload.get('config',{}),payload.get('limit',8),payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/depot":
                from depot import optimize
                result=optimize(payload['scene'],payload.get('config',{}),payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/sorties":
                from sortie import plan_sorties
                result=plan_sorties(payload['scene'],payload.get('config',{}),payload.get('options'))
                self.respond(200,json.dumps(result,ensure_ascii=False,allow_nan=False)); return
            if self.path == "/api/evaluation":
                from evaluation import build, at
                ev = build(payload["scene"], payload["plan"], payload["timeline"], payload.get("resolution", 0.5))
                result = at(ev, payload["timeline"], payload["time"])
                result["evaluation"] = ev
                self.respond(200, json.dumps(result, ensure_ascii=False))
                return
            if self.path == "/api/state":
                from execution import state_at

                timeline = EXECUTIONS.get(payload["execution_id"])
                if timeline is None:
                    raise ValueError("时间模型已过期，请重新准备回放")
                self.respond(
                    200,
                    json.dumps(state_at(timeline, payload["time"]), ensure_ascii=False),
                )
                return
            if self.path in ("/api/plan", "/api/plan-check"):
                from planning import generate_plan, check

                if self.path == "/api/plan":
                    method = payload.get("method") or payload.get("algorithm")
                    options = payload.get("options")
                    if method:
                        from planner_api import make_planner, normalize_name

                        name = normalize_name(method)
                        if options is None:
                            options = {}
                            if name.startswith("caw"):
                                options = dict(
                                    step_xy=payload.get("step_xy", 1.0),
                                    order_strategy=payload.get("order_strategy", "nn+2opt"),
                                    objective=payload.get("objective", "time"),
                                    max_expansions=payload.get("max_expansions", 200000),
                                    max_grid_nodes=payload.get("max_grid_nodes", 2000000),
                                )
                            elif name == "naive-target-order":
                                options = dict(transition=payload.get("transition", "straight"))
                        result = make_planner(name).plan(
                            payload["scene"], payload["config"], options
                        )
                    else:
                        result = generate_plan(payload["scene"], payload["config"])
                else:
                    result = payload["plan"]
                    check(payload["scene"], result)
                if isinstance(result, dict):
                    from planning import fingerprint as plan_fingerprint

                    result = dict(result)
                    result.setdefault("plan_hash", plan_fingerprint(result))
                self.respond(200, json.dumps(result, ensure_ascii=False))
                return
            if self.path == "/api/generate":
                s = generate(payload)
            elif self.path in ("/api/load", "/api/save"):
                s = decode(json.dumps(payload, allow_nan=False))
            else:
                self.respond(404, "{}")
                return
            self.respond(
                200,
                json.dumps(
                    dict(scene=s, summary=summary(s), serialized=encode(s)),
                    ensure_ascii=False,
                ),
            )
        except (ValueError, TypeError, KeyError, OverflowError) as e:
            self.respond(400, json.dumps(dict(error=str(e)), ensure_ascii=False))

    def log_message(self, *args):
        pass


def serve(
    port: int = 0, open_browser: bool = True, initial_scene: Optional[Scene] = None
) -> None:
    """Open one loopback preview; optionally display an already materialized scene."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.initial_scene = initial_scene
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"场景界面：{url}  （Ctrl+C 停止）", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
