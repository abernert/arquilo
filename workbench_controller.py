# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Worker-local adapter for the existing runner; no second task scheduler.

The adapter binds owner-confirmed bytes to PlanAuthority and observes the same
runner's safe task/batch boundaries. It is installed only inside the dedicated
single-run worker and restored on exit; CLI and production defaults are untouched.
"""
from __future__ import annotations

import time
import threading
from pathlib import Path
import safe_io
from functools import partial
import run_todos
from workbench_files import WorkbenchError


def run(argv: list[str], *, revision: str, pause_requested, cancel_requested, emit) -> int:
    original_runner, original_authority = run_todos.TodoRunner, run_todos.PlanAuthority

    class ControlledRunner(original_runner):
        paused = False

        def run(self):
            self._active_stops = {self.process_stop_path: 1}
            self._stops_lock = threading.RLock()
            end = threading.Event()
            def propagate_cancel():
                while not end.wait(0.15):
                    if cancel_requested():
                        with self._stops_lock:
                            for path in self._active_stops:
                                self._cancel_marker(path)
            monitor = threading.Thread(target=propagate_cancel, daemon=True)
            monitor.start()
            try:
                return super().run()
            finally:
                end.set()
                monitor.join()

        @staticmethod
        def _cancel_marker(path):
            try:
                safe_io.write_text(path, "Workbench cancellation; inspect partial work before resuming.\n", exclusive=True)
            except FileExistsError:
                pass

        def _run_autobuild(self, identifier, task_text, **kwargs):
            path = Path(kwargs.get("process_stop_override") or self.process_stop_path)
            with self._stops_lock:
                self._active_stops[path] = self._active_stops.get(path, 0) + 1
                if cancel_requested():
                    self._cancel_marker(path)
            try:
                return super()._run_autobuild(identifier, task_text, **kwargs)
            finally:
                with self._stops_lock:
                    self._active_stops[path] -= 1
                    if not self._active_stops[path]:
                        del self._active_stops[path]

        def _pause_boundary(self):
            if cancel_requested() or self._process_stop_active():
                self.process_stop_detected = True
                self.stop_triggered = True
                self.exit_code = 6
                return True
            if pause_requested():
                self.paused = True
                self.stop_triggered = True
                self.exit_code = 9
                emit("paused", {"boundary": "between_task_trees_or_parallel_batches"})
                return True
            return False

        def _next_todo(self):
            if self._pause_boundary():
                return None
            return super()._next_todo()

        def _wait_directives_allow_execution(self, todo):
            # Same existing WAIT semantics; additionally observe operator controls
            # during a wait rather than sleeping until a long deadline expires.
            if self._pause_boundary():
                return False
            for cfg in todo.wait_directives:
                expressions = [p.strip() for p in str(cfg.get("on", "")).split(",") if p.strip()]
                if not expressions:
                    continue
                timeout = cfg.get("timeout_seconds")
                deadline = time.monotonic() + timeout if isinstance(timeout, int) and timeout >= 0 else None
                while True:
                    if self._pause_boundary():
                        return False
                    checks = [self._wait_condition_is_met(e) for e in expressions]
                    done = any(checks) if str(cfg.get("mode", "all")).lower() == "any" else all(checks)
                    if done:
                        break
                    if deadline is None or time.monotonic() >= deadline:
                        if str(cfg.get("on_timeout", "stop")).lower() != "continue":
                            return False
                        break
                    time.sleep(min(0.2, max(0, deadline - time.monotonic())))
            return not self._pause_boundary()

        def _handle_todo(self, todo):
            emit("task_started", {"task_id": todo.identifier})
            result = super()._handle_todo(todo)
            emit("task_finished", {"task_id": todo.identifier, "completed": result.completed,
                                   "reviewed": todo.identifier in self.reviewed_this_run})
            return result

        def _run_parallel_group(self, seed_todo):
            if self._pause_boundary():
                return True
            emit("batch_started", {"group": seed_todo.config.get("parallel")})
            result = super()._run_parallel_group(seed_todo)
            emit("batch_finished", {"reviewed_task_ids": sorted(self.reviewed_this_run)})
            return result

        def _write_run_log(self, *, run_status):
            if self.paused and run_status not in {"preparing", "running", "failed", "aborted"}:
                run_status = "paused"
            super()._write_run_log(run_status=run_status)
            emit("controller_status", {"status": run_status, "run_directory": str(self.run_dir),
                 "exit_code": self.exit_code, "reviewed_task_ids": sorted(self.reviewed_this_run)})

    if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise WorkbenchError("Missing owner-confirmed plan revision")
    run_todos.PlanAuthority = partial(original_authority, expected_sha256=revision)
    run_todos.TodoRunner = ControlledRunner
    try:
        return run_todos.main(argv)
    finally:
        run_todos.TodoRunner, run_todos.PlanAuthority = original_runner, original_authority
