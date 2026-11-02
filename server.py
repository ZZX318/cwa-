"""Loopback-only UI adapter. All scene decisions live in scene/."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser
from scene import DEFAULT, Scene, generate, summary, decode, encode
from typing import Optional

EXECUTIONS = {}

ROOT = Path(__file__).resolve().parent


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
            if self.path == "/api/multi":
                from multi import run as multi_run
                result=multi_run(payload["scene"],payload.get("config",{}),payload.get("uavs",2))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/experiment":
                from experiment import run as experiment_run
                result=experiment_run(tuple(payload.get('seeds',[0])),tuple(payload.get('methods',['fixed-y','multi'])),tuple(payload.get('uavs',[1,2])))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/route":
                from routing import route
                result=route(payload['scene'],payload['start'],payload['goal'],payload.get('step',1.0),payload.get('clearance',.5))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
            if self.path == "/api/joint":
                from joint import optimize
                result=optimize(payload['scene'],payload.get('config',{}),payload.get('limit',8))
                self.respond(200,json.dumps(result,ensure_ascii=False)); return
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
                    result = generate_plan(payload["scene"], payload["config"])
                else:
                    result = payload["plan"]
                    check(payload["scene"], result)
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
