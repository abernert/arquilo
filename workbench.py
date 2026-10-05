# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Loopback-only, token-authenticated Workbench with validated owner actions."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from controller_state import default_state_root
from runtime_config import resolve_model, resolve_reasoning_effort
import safe_io
from workbench_files import WorkbenchError, MAX_TEXT_BYTES, lease, strict_json, workspace_path
from workbench_jobs import Jobs
from workbench_plan import PlanService, generated_plan
from ask import build_prompt
from workbench_assets import HTML, JS, CSS


def fields(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        raise WorkbenchError("Missing or unknown request fields")


class Application:
    def __init__(self, plan: PlanService):
        self.plan = plan
        self.jobs = Jobs(plan.private / "jobs")
        self.lock = threading.RLock()
        self.sequence = 0

    def state(self):
        with self.lock:
            self.sequence += 1
            return {"schema_version": "arquilo.workbench.v2", "sequence": self.sequence,
                    "plan": self.plan.view(), "run": self.jobs.snapshot("run"),
                    "ask": self.jobs.snapshot("ask")}

    def action(self, path, body):
        with self.lock:
            if path in {"/api/plan/preview", "/api/plan/save"}:
                fields(body, ("text", "revision"), ("text", "revision"))
                if self.jobs.busy():
                    raise WorkbenchError("Plan editing is locked while a run is active", code="busy", status=409)
                if not isinstance(body["text"], str) or not isinstance(body["revision"], str):
                    raise WorkbenchError("Text and revision must be strings")
                fn = self.plan.save if path.endswith("save") else self.plan.preview
                return fn(body["text"], body["revision"])
            if path == "/api/plan/generate":
                fields(body, ("ideas", "base", "revision"), ("ideas", "base", "revision"))
                if self.jobs.busy():
                    raise WorkbenchError("A run is active", code="busy", status=409)
                if not isinstance(body["base"], str) or self.plan.view()["revision"] != body["revision"]:
                    raise WorkbenchError("Reload the changed plan before generating", code="conflict", status=409)
                text = generated_plan(body["ideas"], body["base"])
                return self.plan.preview(text, body["revision"])
            if path == "/api/run/start":
                fields(body, ("request_id", "revision", "allow_provider", "adopt_plan", "max_calls", "model", "reasoning_effort"),
                       ("request_id", "revision", "allow_provider", "adopt_plan", "max_calls"))
                if body["allow_provider"] is not True or type(body["adopt_plan"]) is not bool:
                    raise WorkbenchError("Explicit provider/configuration consent is required", status=403)
                limit = body["max_calls"]
                if type(limit) is not int or limit < 0:
                    raise WorkbenchError("Call limit must be an integer >= 0 (0 means unlimited)")
                model, effort = resolve_model(body.get("model")), resolve_reasoning_effort(body.get("reasoning_effort"))
                args = ["--workdir", str(self.plan.workspace), "--todo-file", str(self.plan.todo),
                        "--state-dir", str(self.plan.state_root), "--process-stop-policy", "controller-only",
                        "--max-calls", str(limit)]
                if body["adopt_plan"]:
                    args += ["--accept-plan-changes"]
                if model:
                    args += ["--model", model]
                if effort:
                    args += ["--reasoning-effort", effort]
                payload = {"kind": "run", "workdir": str(self.plan.workspace), "revision": body["revision"], "arguments": args}
                # Network retries with the same ID must not re-run work or fail just
                # because the first run already advanced the saved task status.
                old = self.jobs.replay(body["request_id"], "run", payload)
                if old:
                    return old
                current = self.plan.view()
                if current["revision"] != body["revision"]:
                    raise WorkbenchError("Plan changed before start", code="conflict", status=409)
                if not current["exists"] or not current["tasks"]:
                    raise WorkbenchError("Save a nonempty validated plan first", status=422)
                if self.plan.validate(current["text"]):
                    raise WorkbenchError("Fix plan validation errors before running", status=422)
                if current["needs_owner_adoption"] and not body["adopt_plan"]:
                    raise WorkbenchError("Review the owner edits and explicitly confirm adoption", code="adoption_required", status=409)
                if (self.plan.workspace / "process_stop").exists():
                    raise WorkbenchError("An existing process_stop blocks this run; inspect it before resuming", code="stop_active", status=409)
                with lease(self.plan.state / "controller.lock"):
                    pass  # Observe external CLI ownership; worker acquires the same lock and checks revision again.
                return self.jobs.start(body["request_id"], "run", payload)
            if path in {"/api/run/pause", "/api/run/cancel", "/api/ask/cancel"}:
                fields(body, ("id",), ("id",))
                _, _, kind, action = path.split("/")
                return self.jobs.control(kind, body["id"], action)
            if path == "/api/ask/start":
                fields(body, ("request_id", "question", "depth", "allow_provider", "files"),
                       ("request_id", "question", "depth", "allow_provider"))
                build_prompt(body["question"], body["depth"])
                if body["allow_provider"] is not True:
                    raise WorkbenchError("Explicit provider/configuration consent is required", status=403)
                files = body.get("files")
                if files is not None and (not isinstance(files, list) or len(files) > 12 or not all(isinstance(f, str) for f in files)):
                    raise WorkbenchError("Select at most 12 relative file paths")
                kwargs = {"workdir": str(self.plan.workspace), "question": body["question"],
                          "depth": body["depth"], "allow_provider": True, "files": files,
                          "log_root": str(self.plan.private / "ask-archives")}
                return self.jobs.start(body["request_id"], "ask", {"kind": "ask", "arguments": kwargs})
            raise WorkbenchError("Unknown action", status=404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, app: Application, port=8765):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.authority = f"127.0.0.1:{self.server_port}"

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass  # No token, prompt or URL logging to a shared terminal.

    def reply(self, status, data, content_type="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def check(self, api=False, mutation=False):
        if self.headers.get_all("Host") != [self.server.authority]:
            raise WorkbenchError("Invalid Host", status=403)
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1:
            raise WorkbenchError("Ambiguous Origin", status=403)
        origin = origins[0] if origins else None
        if (origin is not None and origin != self.server.origin) or (mutation and origin != self.server.origin):
            raise WorkbenchError("Invalid Origin", status=403)
        if self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            raise WorkbenchError("Cross-origin requests are refused", status=403)
        if api:
            auth = self.headers.get_all("Authorization") or []
            expected = "Bearer " + self.server.token
            if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), expected.encode()):
                raise WorkbenchError("Authentication required", status=403)
        url = urlsplit(self.path)
        if url.scheme or url.netloc or url.query or url.fragment:
            raise WorkbenchError("Only exact local paths are accepted")
        return url.path

    def do_GET(self):
        try:
            path = self.check(api=self.path.startswith("/api/"))
            if path == "/api/state":
                self.reply(200, self.server.app.state())
            elif path in {"/", "/app.js", "/style.css"}:
                data, kind = {"/": (HTML, "text/html"), "/app.js": (JS, "text/javascript"),
                              "/style.css": (CSS, "text/css")}[path]
                self.reply(200, data.encode(), kind + "; charset=utf-8")
            else:
                self.reply(404, {"error": "Not found"})
        except WorkbenchError as exc:
            self.reply(exc.status, {"error": str(exc), "code": exc.code})
        except (ValueError, OSError, UnicodeError):
            self.reply(400, {"error": "Unable to read private state safely"})

    def do_POST(self):
        try:
            path = self.check(api=True, mutation=True)
            lengths = self.headers.get_all("Content-Length") or []
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
                raise WorkbenchError("One Content-Length is required")
            length = int(lengths[0])
            if length < 2 or length > MAX_TEXT_BYTES:
                raise WorkbenchError("Request body is too large or empty", status=413)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise WorkbenchError("Expected application/json", status=415)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise WorkbenchError("Incomplete body")
            body = strict_json(raw.decode("utf-8"))
            self.reply(200, self.server.app.action(path, body))
        except WorkbenchError as exc:
            self.reply(exc.status, {"error": str(exc), "code": exc.code})
        except (ValueError, OSError, UnicodeError, TypeError):
            self.reply(400, {"error": "Invalid request or unsafe filesystem state; no action accepted"})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the protected local ARQUILO Workbench")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--todo-file", default="tasks.md")
    parser.add_argument("--state-dir")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    work = workspace_path(args.workdir)
    todo = Path(args.todo_file).expanduser()
    todo = todo if todo.is_absolute() else work / todo
    root = safe_io.lexical_path(Path(args.state_dir).expanduser() if args.state_dir else default_state_root())
    plan = PlanService(work, todo, root)
    with lease(plan.private / "service.lock"):
        app = Application(plan)
        server = Server(app, args.port)
        print(f"ARQUILO Workbench: {server.origin}/#token={server.token}", flush=True)
        print("Loopback only. URL fragment is a local secret. Ctrl-C cancels owned jobs and stops the server.", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.jobs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
