# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""One owned run/Ask job in an isolated Python process (no project imports)."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import threading
from datetime import datetime, UTC

# -I omits cwd/PYTHONPATH/user site packages. Only this owner-installed code is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from workbench_files import read_bytes, strict_json, write_json
import safe_io


def main() -> int:
    job = safe_io.lexical_path(sys.argv[1])
    request = strict_json(read_bytes(job / "request.json"))
    lock = threading.RLock()
    stopped = threading.Event()
    finished = threading.Event()
    state = {"schema_version": "arquilo.workbench.worker.v1", "status": "starting", "events": [], "sequence": 0}

    def emit(kind, detail):
        with lock:
            state["sequence"] += 1
            state["events"].append({"sequence": state["sequence"], "kind": kind, "detail": detail})
            state["events"] = state["events"][-100:]
            if kind == "controller_status":
                state["controller"] = detail
            if kind == "progress":
                state["progress"] = detail
            write_json(job / "worker.json", state)

    def cancel_requested():
        return "Operator cancellation" if stopped.is_set() or (job / "cancel.request").exists() else None

    def cancel_run_on_parent_exit():
        # Parent owns a pipe, not a PID. EOF cannot accidentally refer to a reused PID.
        try:
            sys.stdin.buffer.read()
        finally:
            if finished.is_set():
                return
            stopped.set()
            if request["kind"] == "run":
                marker = Path(request["workdir"]) / "process_stop"
                try:
                    safe_io.write_text(marker, "Workbench connection closed; inspect before resuming.\n", exclusive=True)
                except FileExistsError:
                    pass  # Never replace an existing independent stop reason.

    threading.Thread(target=cancel_run_on_parent_exit, daemon=True).start()
    def interrupted(_signum, _frame):
        stopped.set()
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    emit("started", {})
    code = 7
    try:
        if request["kind"] == "ask":
            from ask import ask
            result = ask(**request["arguments"], cancel_requested=cancel_requested,
                         progress=lambda text: emit("progress", {"message": text}))
            write_json(job / "answer.json", result)
            code = 0
            status = "completed"
        elif request["kind"] == "run":
            from workbench_controller import run
            code = run(request["arguments"], revision=request["revision"],
                       pause_requested=lambda: (job / "pause.request").exists(),
                       cancel_requested=cancel_requested, emit=emit)
            status = state.get("controller", {}).get("status", "failed")
            if cancel_requested():
                status = "cancelled"
            elif code != 0 and status == "completed":
                status = "failed"
        else:
            raise ValueError("Unknown job kind")
    except (KeyboardInterrupt, InterruptedError):
        code, status = 130, "cancelled"
    except BaseException as exc:
        code, status = 7, "failed"
        # No raw exception text is exposed to the browser; diagnostics remain local.
        print(f"Worker failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        state["error_type"] = type(exc).__name__
    finished.set()
    state.update(status=status, exit_code=code, finished_at=datetime.now(UTC).isoformat())
    emit("finished", {"status": status, "exit_code": code})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
