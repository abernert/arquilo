# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Owned subprocess I/O for native backend adapters (no model/provider defaults).

The legacy Codex collector remains unchanged for compatibility. This collector
has a native-event protocol per invocation, not global monkeypatches. A native
result never replaces a successful process exit; all I/O evidence is retained.
"""
from __future__ import annotations
import codecs
from datetime import datetime
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional
import safe_io
from agent_types import RunResult
from runtime_failure import execution_error
from process_tree import InterruptiblePipe, ProcessTree, ProcessTreeError, REAP_TIMEOUT, finish_cleanup

_CHUNK_SIZE = 64 * 1024
_INVALID_UTF8 = re.compile("[\udc80-\udcff]")

class AgentProcessError(RuntimeError):
    def __init__(self, result, error):
        self.result, self.error = result, error
        result.execution_error = error
        super().__init__(error["message"])

def fatal_run_error(trace):
    if trace.execution_error:
        return trace.execution_error
    if trace.stream_errors or trace.turn_failed is not None:
        return execution_error(json.dumps(trace.stream_errors or trace.turn_failed, ensure_ascii=True),
                               code="agent_protocol_error", process_exit_code=trace.process_exit_code)
    return None

def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def append(path: Path, text: str) -> None:
    with safe_io.open_file(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)

def observe_stop(trace: RunResult, details: object) -> None:
    """Stop is an independent fact. Keep the first observed reason."""
    from runtime_failure import stop_reason
    if not trace.process_stop_triggered:
        trace.process_stop_details = stop_reason(details)
    trace.process_stop_triggered = True
    trace.process_stop_details = stop_reason(trace.process_stop_details)

def expected_stdin_abort(diagnostic: Dict[str, Any], *, shutdown_started: bool) -> bool:
    """Only an actual pipe break caused by already initiated controller cleanup."""
    return (shutdown_started and diagnostic.get("during_shutdown") is True
            and diagnostic.get("type") == "stdin_write_error"
            and diagnostic.get("source") == "stdin"
            and (diagnostic.get("exception_type") == "BrokenPipeError"
                 or (diagnostic.get("exception_type") == "OSError"
                     and (diagnostic.get("errno") == 32
                          or diagnostic.get("winerror") in (109, 232)))))

def _write_bytes(stream: Any, data: bytes, progress: Callable[[int], None]) -> None:
    """Binary pipes/files may write only a prefix, including without an error."""
    view = memoryview(data)
    while view:
        written = stream.write(view[:_CHUNK_SIZE])
        if not isinstance(written, int) or written <= 0 or written > len(view[:_CHUNK_SIZE]):
            raise OSError(f"Invalid short write result: {written!r}")
        progress(written)
        view = view[written:]

def _terminate_process_group(
    proc: subprocess.Popen,
    *,
    grace_seconds: float = 10.0,
    reason: str = "requested_termination",
):
    """Compatibility name; real launches always have a process-tree owner."""
    tree = getattr(proc, "arquilo_process_tree", None)
    if isinstance(tree, ProcessTree):
        return tree.terminate(reason=reason, grace_seconds=grace_seconds)
    # Older callers use lightweight process doubles without an OS pid. Never
    # use this single-process path for a real unowned Windows/POSIX process.
    if not isinstance(getattr(proc, "pid", None), int):
        if proc.poll() is None:
            proc.terminate()
        return None
    raise ProcessTreeError("Process has no ARQUILO process-tree owner")

def _collect_process(request, acc: RunResult, prompt_bytes: bytes,
                     proc: subprocess.Popen, *, protocol) -> RunResult:
    raw_log, pretty_log = request.raw_log, request.pretty_log
    verbose, console_todo_id = request.verbose, request.console_todo_id
    post_turn_grace, stall_timeout = request.timeouts.post_turn_grace, request.timeouts.stall
    kill_grace = request.timeouts.kill_grace
    _redact_prompt_for_pretty_log = request.log_redactor or (lambda value: value)
    acc.capture["launcher"] = getattr(proc, "arquilo_launcher", None)
    acc.capture["resolved_argv"] = getattr(proc, "arquilo_argv", None)
    stream_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
    shutdown_requested = threading.Event()
    io_stop = threading.Event()
    proc.arquilo_process_tree.prepare_pipes()

    def _io_error(kind: str, source: str, exc: Exception) -> None:
        stream_queue.put(("io_error", {"type": kind, "source": source,
                                      "message": f"{type(exc).__name__}: {exc}",
                                      "during_shutdown": shutdown_requested.is_set(),
                                      "exception_type": type(exc).__name__,
                                      "errno": getattr(exc, "errno", None),
                                      "winerror": getattr(exc, "winerror", None)}))

    def _read_stream(source: str, stream: Any) -> None:
        stats = acc.capture[source]
        archive = None
        archive_context = None

        def archived(count: int) -> None:
            stats["archived_bytes"] += count

        try:
            try:
                archive_context = safe_io.open_file(acc.capture_dir / f"{source}.bin", "ab", buffering=0)
                archive = archive_context.__enter__()
            except OSError as exc:
                _io_error("log_error", source, exc)
            while True:
                chunk = InterruptiblePipe(stream, io_stop).read(_CHUNK_SIZE)
                if not chunk:
                    stats["eof"] = True
                    break
                stats["received_bytes"] += len(chunk)
                if archive is not None:
                    try:
                        _write_bytes(archive, chunk, archived)
                    except OSError as exc:
                        _io_error("log_error", source, exc)
                        try:
                            archive.close()
                        except OSError as close_exc:
                            _io_error("log_error", source, close_exc)
                        archive = None
                stream_queue.put((source, chunk))
        except Exception as exc:
            _io_error("read_error", source, exc)
        finally:
            if archive is not None:
                try:
                    archive.close()
                except OSError as exc:
                    _io_error("log_error", source, exc)
            if archive_context is not None:
                archive_context.__exit__(None, None, None)
            stream_queue.put((source + "_eof", None))

    def _write_stdin() -> None:
        stats = acc.capture["stdin"]

        def written(count: int) -> None:
            stats["written_bytes"] += count
            stream_queue.put(("stdin_progress", count))

        try:
            _write_bytes(InterruptiblePipe(proc.stdin, io_stop), prompt_bytes, written)
        except Exception as exc:
            _io_error("stdin_write_error", "stdin", exc)
        finally:
            try:
                proc.stdin.close()
                stats["closed"] = True
            except (OSError, ValueError) as exc:
                _io_error("stdin_write_error", "stdin", exc)
            stream_queue.put(("stdin_done", None))

    threads = [threading.Thread(target=_read_stream, args=(source, stream),
                                name=f"arquilo-agent-{source}", daemon=True)
               for source, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    threads.append(threading.Thread(target=_write_stdin, name="arquilo-agent-stdin", daemon=True))
    stdout_eof = False
    stderr_eof = False
    stdin_done = False
    terminal_event: Optional[str] = None
    terminal_event_at: Optional[float] = None
    started_at = last_activity = time.monotonic()
    parent_exit_at = None
    shutdown_at = None
    cleanup = None
    forced_after_terminal = False
    forced_for_stall = False
    forced_for_timeout = False

    decoders = {source: codecs.getincrementaldecoder("utf-8")("surrogateescape")
                for source in ("stdout", "stderr")}
    offsets = {"stdout": 0, "stderr": 0}
    stdout_pending = ""
    broken_logs: set[Path] = set()

    def log_error(path: Path, exc: Exception) -> None:
        if path not in broken_logs:
            broken_logs.add(path)
            acc.stream_errors.append({"type": "log_error", "source": str(path),
                                      "message": f"{type(exc).__name__}: {exc}"})

    def log(path: Path, value: str) -> None:
        if path not in broken_logs:
            try:
                append(path, value)
            except (OSError, UnicodeError) as exc:
                log_error(path, exc)

    def stdout_line(line: str) -> None:
        nonlocal terminal_event, terminal_event_at
        if not line.strip():
            return
        try:
            terminal = protocol.accept(line, acc)
            log(raw_log, line + "\n")
            # Progress contains only controlled metadata, never raw prompt/output.
            if terminal:
                terminal_event = "result"
                terminal_event_at = time.monotonic()
        except (ValueError, TypeError, KeyError) as exc:
            acc.stream_errors.append({"type": "protocol_error", "message": str(exc)})
            log(raw_log, line + "\n")
            log(pretty_log, "[protocol_error] " + str(exc) + "\n")

    def decode(source: str, chunk: bytes, *, final: bool = False) -> None:
        nonlocal stdout_pending
        decoder = decoders[source]
        start = offsets[source] - len(decoder.getstate()[0])
        offsets[source] += len(chunk)
        value = decoder.decode(chunk, final=final)
        invalid = _INVALID_UTF8.search(value)
        if invalid is not None:
            stats = acc.capture[source]
            if not stats["invalid_utf8_bytes"]:
                offset = start + len(value[:invalid.start()].encode("utf-8"))
                acc.stream_errors.append({"type": "decode_error", "source": source,
                                          "byte_offset": offset,
                                          "message": f"Invalid UTF-8 in {source} at byte {offset}; raw bytes retained."})
            stats["invalid_utf8_bytes"] += len(_INVALID_UTF8.findall(value))
            value = _INVALID_UTF8.sub("\ufffd", value)
        if source == "stdout":
            stdout_pending += value
            if len(stdout_pending) > 8 * 1024 * 1024:
                raise ValueError("Agent output line exceeds 8 MiB")
            lines = stdout_pending.split("\n")
            stdout_pending = lines.pop()
            for line in lines:
                stdout_line(line)
            if final and stdout_pending:
                stdout_line(stdout_pending)
                stdout_pending = ""
        elif value:
            log(pretty_log, f"[{ts()}] [stderr]\n{_redact_prompt_for_pretty_log(value)}\n")

    def terminate(reason: str) -> None:
        nonlocal shutdown_at, cleanup
        shutdown_requested.set()
        if shutdown_at is None:
            shutdown_at = time.monotonic()
            cleanup = _terminate_process_group(proc, grace_seconds=kill_grace, reason=reason)

    def read_cancellation() -> str | None:
        if request.process_stop_path is not None and request.process_stop_path.exists():
            return safe_io.read_text(request.process_stop_path).strip() or "process_stop active"
        return request.cancel_requested() if request.cancel_requested is not None else None

    def record_io_error(payload: Dict[str, Any]) -> None:
        # The main queue and its final drain must apply exactly the same rule.
        acc.capture["diagnostics"].append(payload)
        if not expected_stdin_abort(payload, shutdown_started=shutdown_requested.is_set()):
            acc.stream_errors.append(payload)
            terminate("stream_error")

    try:
        for thread in threads:
            thread.start()
        while True:
            try:
                channel, payload = stream_queue.get(timeout=0.25)
            except queue.Empty:
                channel, payload = "", None

            if channel:
                last_activity = time.monotonic()

            if channel in decoders:
                decode(channel, payload)
            elif channel == "io_error":
                record_io_error(payload)
            elif channel == "stdin_done":
                stdin_done = True
            elif channel == "stdout_eof":
                decode("stdout", b"", final=True)
                stdout_eof = True
            elif channel == "stderr_eof":
                decode("stderr", b"", final=True)
                stderr_eof = True

            now = time.monotonic()
            try:
                cancellation = read_cancellation()
            except KeyboardInterrupt:
                cancellation = "KeyboardInterrupt"
            if cancellation:
                first_stop = not acc.process_stop_triggered
                observe_stop(acc, cancellation)
                if first_stop:
                    log(pretty_log, f"[{ts()}] [cancelled] {acc.process_stop_details}\n")
                if shutdown_at is None:
                    terminate("cancelled: " + acc.process_stop_details)
            if broken_logs:
                terminate("log_error")
            if acc.stream_errors:
                terminate("protocol_or_io_error")
            if request.timeouts.total is not None and now - started_at >= request.timeouts.total and shutdown_at is None:
                forced_for_timeout = True
                terminate("total_timeout")
            if (
                terminal_event_at is not None
                and shutdown_at is None
                and now - terminal_event_at >= post_turn_grace
            ):
                forced_after_terminal = True
                terminate("post_turn_grace_expired")

            if (
                terminal_event_at is None
                and stall_timeout > 0
                and shutdown_at is None
                and now - last_activity >= stall_timeout
            ):
                forced_for_stall = True
                terminate("stall_timeout")

            if proc.poll() is not None and parent_exit_at is None:
                parent_exit_at = now
            if parent_exit_at is not None and shutdown_at is None and now - parent_exit_at >= post_turn_grace:
                forced_after_terminal = acc.turn_completed
                terminate("parent_exit_pipe_cleanup")
            if shutdown_at is not None and now - shutdown_at >= kill_grace + REAP_TIMEOUT + 2.0:
                acc.stream_errors.append({"type": "io_cleanup_error", "source": "pipes",
                                          "message": "Pipes did not reach EOF after process-tree termination."})
                break

            if (
                proc.poll() is not None
                and stdout_eof
                and stderr_eof
                and stdin_done
                and stream_queue.empty()
            ):
                break

    except KeyboardInterrupt:
        observe_stop(acc, "KeyboardInterrupt")
        terminate("cancelled: KeyboardInterrupt")
    except BaseException:
        terminate("collector_exception")
        raise
    finally:
        # Even successful exit/closed pipes can leave background writers alive.
        terminate("parent_exit_cleanup")
        acc.process_exit_code = cleanup.parent_exit_after
        join_deadline = time.monotonic() + REAP_TIMEOUT
        for thread in threads:
            if thread.ident is not None:
                finish_cleanup(lambda: thread.join(timeout=max(0, join_deadline - time.monotonic())), cleanup)
        if any(thread.is_alive() for thread in threads):
            io_stop.set()
            cancel_deadline = time.monotonic() + REAP_TIMEOUT
            while any(thread.is_alive() for thread in threads) and time.monotonic() < cancel_deadline:
                for thread in threads:
                    try:
                        finish_cleanup(lambda: proc.arquilo_process_tree.cancel_io(thread), cleanup)
                    except OSError as exc:
                        acc.stream_errors.append({"type": "io_cleanup_error", "source": thread.name,
                                                  "message": str(exc)})
                    if thread.ident is not None:
                        finish_cleanup(lambda: thread.join(timeout=.02), cleanup)
        for thread in threads:
            if thread.is_alive():
                acc.stream_errors.append({"type": "io_cleanup_error", "source": thread.name,
                                          "message": "I/O worker did not stop; capture may be incomplete."})
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                finish_cleanup(stream.close, cleanup)
        if cleanup.interrupted:
            observe_stop(acc, "KeyboardInterrupt")
    rc = acc.process_exit_code
    if cleanup.errors:
        acc.stream_errors.append({"type": "process_tree_error", "source": cleanup.strategy,
                                  "message": "; ".join(cleanup.errors)})
    acc.capture["process_tree"] = cleanup.metadata()
    if cleanup.actions:
        log(pretty_log, f"[{ts()}] [process_tree_cleanup] {json.dumps(cleanup.metadata())}\n")

    # Ctrl+C can interrupt queue consumption; readers still archived every byte.
    # Drain diagnostics and pending data after cleanup, including terminal tails.
    while not stream_queue.empty():
        channel, payload = stream_queue.get_nowait()
        if channel in decoders:
            decode(channel, payload)
        elif channel in {"stdout_eof", "stderr_eof"}:
            decode(channel.removesuffix("_eof"), b"", final=True)
        elif channel == "io_error":
            record_io_error(payload)

    if not acc.process_stop_triggered and not (forced_for_timeout or forced_for_stall):
        if acc.capture["stdin"]["written_bytes"] != len(prompt_bytes) or not acc.capture["stdin"]["closed"]:
            acc.stream_errors.append({"type": "stdin_write_error", "source": "stdin",
                                      "message": "Prompt transfer did not complete; see capture byte counts."})

    acc.process_exit_code = rc
    acc.post_turn_cleanup = acc.turn_completed and bool(cleanup.actions) and not (
        acc.process_stop_triggered or forced_for_timeout or forced_for_stall)
    if acc.post_turn_cleanup:
        acc.cleanup_reason = f"{cleanup.reason}: {cleanup.strategy} ({', '.join(cleanup.actions)})"
    if forced_after_terminal:
        log(
            pretty_log,
            (
                f"[{ts()}] [WARN] Agent emitted {terminal_event} but did not exit "
                f"within {post_turn_grace:g}s; process group was terminated and "
                "the terminal event will be checked against the execution contract.\n"
            ),
        )
        if verbose:
            sys.stderr.write(
                f"[AutoBuild] Agent wurde nach {terminal_event} und "
                f"{post_turn_grace:g}s Nachlauf beendet.\n"
            )

    log(pretty_log, f"[{ts()}] EXIT {rc}\n\n")

    error = fatal_run_error(acc)
    forced_exit = (cleanup.forced_parent_exit and cleanup.parent_exit_before is None
                   and not cleanup.errors)
    if error is None:
        if forced_for_timeout:
            error = execution_error(
                f"Agent exceeded the total timeout of {request.timeouts.total:g}s.",
                code="agent_timeout", process_exit_code=rc)
        elif forced_for_stall:
            error = execution_error(
                f"Agent stalled for {stall_timeout:g}s before successful turn completion. "
                "Partial edits may exist; inspect them before retrying.",
                code="agent_stalled", process_exit_code=rc)
        elif acc.process_stop_triggered:
            # A later sentinel cannot hide a naturally failed process. Only
            # our evidenced kill (or natural exit 0) is expected on cancellation.
            if rc != 0 and not forced_exit:
                error = execution_error(
                    f"Agent exited with code {rc}; not an expected controller termination.",
                    code="agent_process_failed", process_exit_code=rc)
        elif not acc.turn_completed:
            error = execution_error(
                f"Agent exited with code {rc} without turn.completed.",
                code="agent_missing_completion", process_exit_code=rc)
        elif rc != 0 or forced_after_terminal:
            error = execution_error(
                f"Agent emitted turn.completed but exited with code {rc}.",
                code="agent_process_failed", process_exit_code=rc)
        elif not acc.end_answer:
            error = execution_error(
                "Agent completed the turn without a final assistant message.",
                code="agent_missing_answer", process_exit_code=rc)
    if error is not None:
        log(pretty_log, f"[{ts()}] [execution_error] {json.dumps(error, ensure_ascii=False)}\n")
        raise AgentProcessError(acc, error)
    return acc
