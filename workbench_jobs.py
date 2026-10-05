# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Bounded subprocess supervision; manifests, not terminal prose, carry status."""
from __future__ import annotations

import codecs
from datetime import datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from process_tree import ProcessTree
import safe_io
from workbench_files import WorkbenchError, read_bytes, strict_json, write_json

TERMINAL = {"completed", "failed", "cancelled", "paused", "stopped", "incomplete", "aborted", "interrupted"}
LOG_LIMIT = 8 * 1024 * 1024
TAIL_LIMIT = 24000


class Jobs:
    def __init__(self, root: Path):
        self.root = root
        safe_io.mkdir(root)
        self.lock = threading.RLock()
        self.active = {}
        self.latest = {}
        self.closed = False
        # Restored records are display-only. Never kill/adopt a process by stored PID.
        for directory in sorted(root.iterdir()):
            if not re.fullmatch(r"[a-f0-9]{32}", directory.name):
                continue
            saved = self._read(directory / "job.json")
            if saved:
                if saved.get("status") not in TERMINAL:
                    saved.update(status="interrupted", warning="Supervisor restarted; inspect controller state before continuing.")
                    write_json(directory / "job.json", saved)
                if saved.get("started_at", "") >= self.latest.get(saved["kind"], {}).get("started_at", ""):
                    self.latest[saved["kind"]] = saved

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            value = strict_json(read_bytes(path, 2 * 1024 * 1024))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict):
            raise WorkbenchError("Invalid private job record")
        return value

    def busy(self, kind="run"):
        with self.lock:
            return kind in self.active

    def replay(self, request_id, kind, payload):
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise WorkbenchError("Invalid request ID")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        path = self.root / request_id
        saved = self._read(path / "job.json")
        if saved:
            if saved.get("fingerprint") != fingerprint or saved.get("kind") != kind:
                raise WorkbenchError("Request ID was already used for different input", code="conflict", status=409)
            return saved
        return None

    def start(self, request_id: str, kind: str, payload: dict):
        with self.lock:
            old = self.replay(request_id, kind, payload)
            if old:
                return old
            if self.closed or kind in self.active:
                raise WorkbenchError("A job of this kind is still active", code="busy", status=409)
            directory = self.root / request_id
            with safe_io.directory(self.root) as (base, fd):
                os.mkdir(base / request_id if fd is None else request_id, 0o700, dir_fd=fd)
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
            state = {"id": request_id, "kind": kind, "fingerprint": fingerprint,
                     "started_at": datetime.now(UTC).isoformat(), "status": "starting", "output": ""}
            write_json(directory / "request.json", payload)
            write_json(directory / "job.json", state)
            tree = ProcessTree()
            proc = None
            try:
                command = [sys.executable, "-I", "-X", "utf8", "-u", "-B", str(Path(__file__).with_name("workbench_worker.py")), str(directory)]
                proc = subprocess.Popen(command, cwd=str(directory), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, **tree.popen_options)
                tree.bind(proc)
            except BaseException:
                tree.abort_start(proc)
                state.update(status="failed", error_type="worker_start_failed")
                write_json(directory / "job.json", state)
                raise
            record = {"process": proc, "tree": tree, "directory": directory, "state": state, "request": payload}
            self.active[kind] = record
            self.latest[kind] = state
            thread = threading.Thread(target=self._collect, args=(kind, record), daemon=True)
            record["thread"] = thread
            thread.start()
            return dict(state)

    def _collect(self, kind, record):
        proc, directory, state = record["process"], record["directory"], record["state"]
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        total = 0
        try:
            with safe_io.open_file(directory / "console.log", "xb") as log:
                while True:
                    chunk = proc.stdout.read1(4096)
                    if not chunk:
                        break
                    keep = max(0, LOG_LIMIT - total)
                    log.write(chunk[:keep])
                    log.flush()
                    total += len(chunk)
                    with self.lock:
                        state["output"] = (state["output"] + decoder.decode(chunk))[-TAIL_LIMIT:]
                        state["output_truncated"] = total > LOG_LIMIT
            code = proc.wait()
            worker = self._read(directory / "worker.json")
            with self.lock:
                state.update(exit_code=code, finished_at=datetime.now(UTC).isoformat())
                status = worker.get("status")
                # No success from partial output, a missing manifest, or merely exit zero.
                state["status"] = status if status in TERMINAL else "failed"
                if code != 0 and state["status"] == "completed":
                    state["status"] = "failed"
                state["worker"] = worker
                if kind == "ask" and state["status"] == "completed":
                    state["answer"] = self._read(directory / "answer.json")
        except BaseException as exc:
            with self.lock:
                state.update(status="failed", error_type=type(exc).__name__)
        finally:
            if proc.poll() is None:
                # Request cooperative shutdown first. Native transport owns Codex cleanup.
                if proc.stdin:
                    proc.stdin.close()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    state["warning"] = "Worker cleanup incomplete; inspect host processes and controller state."
                    # Do not report idle or permit a new job while this worker is alive.
                    while proc.poll() is None:
                        time.sleep(0.2)
            cleanup = record["tree"].terminate(reason="workbench_worker_exit", grace_seconds=0.2)
            record["tree"].close()
            if cleanup.errors:
                state.update(status="failed", error_type="process_cleanup_failed")
            for stream in (proc.stdin, proc.stdout):
                if stream and not stream.closed:
                    stream.close()
            with self.lock:
                write_json(directory / "job.json", state)
                self.active.pop(kind, None)

    def control(self, kind, job_id, action):
        with self.lock:
            record = self.active.get(kind)
            if record is None or record["state"]["id"] != job_id:
                raise WorkbenchError("This job is no longer active; refresh its status", code="stale_job", status=409)
            if action not in {"pause", "cancel"} or action == "pause" and kind != "run":
                raise WorkbenchError("Invalid job control")
            directory = record["directory"]
            marker = directory / (action + ".request")
            try:
                safe_io.write_text(marker, action + "\n", exclusive=True)
            except FileExistsError:
                pass
            if kind == "run" and action == "cancel":
                stop = Path(record["request"]["workdir"]) / "process_stop"
                try:
                    safe_io.write_text(stop, f"Workbench cancellation of job {job_id}. Inspect partial work before resuming.\n", exclusive=True)
                except FileExistsError:
                    pass
                record["state"]["stop_marker"] = "process_stop retained; inspect and deliberately remove before resuming"
            # Remain active until the worker and output collector really finish.
            record["state"]["status"] = "cancelling" if action == "cancel" else "pausing"
            return self.snapshot(kind)

    def snapshot(self, kind):
        with self.lock:
            state = dict(self.latest.get(kind, {"status": "idle"}))
            record = self.active.get(kind)
            if record:
                worker = self._read(record["directory"] / "worker.json")
                state["worker"] = worker
                if state["status"] not in {"pausing", "cancelling"}:
                    state["status"] = "running" if worker else "starting"
            state["active"] = record is not None
            return state

    def shutdown(self):
        with self.lock:
            self.closed = True
            records = list(self.active.items())
        for kind, record in records:
            try:
                self.control(kind, record["state"]["id"], "cancel")
            except WorkbenchError:
                pass
        # Cooperatively wait, preserving the lifetime lock. A forced OS kill cannot
        # be made safe by stale-PID recovery; the next startup marks records interrupted.
        for _kind, record in records:
            record["thread"].join()
