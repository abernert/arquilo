# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Shared, standard-library Codex Exec transport.

Only this module starts Codex processes. Each invocation receives its own cwd,
environment snapshot, arguments, logs and cancellation/timeout controls. Import
does not load configuration, providers, AutoBuild or the task scheduler.

Prompts travel as UTF-8 on stdin. Per-call archives retain exact input/output
bytes separately from normalized event logs and the extracted final answer.
The invocation policy fixes the maximum sandbox and independent network grant.
Process-tree lifetime is owned through a per-call operating-system adapter.
"""
from __future__ import annotations
import safe_io
from project_logs import numbered_directory

from dataclasses import dataclass, field
from datetime import datetime
import codecs
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from runtime_contracts import ExecutionResult, ExecutionStatus, Failure, FailureKind
from runtime_failure import execution_error
import codex_policy
from codex_launcher import resolve_launcher
from process_tree import InterruptiblePipe, ProcessTree, ProcessTreeError, REAP_TIMEOUT, finish_cleanup
from runtime_files import atomic_write_text, native_path, safe_component, unique_directory


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportTimeouts:
    post_turn_grace: float = 120.0
    stall: float = 7200.0
    kill_grace: float = 10.0
    total: float | None = None

    def __post_init__(self) -> None:
        for name in ("post_turn_grace", "stall", "kill_grace", "total"):
            value = getattr(self, name)
            if name == "total" and value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")


@dataclass(frozen=True, slots=True, kw_only=True)
class CodexExecRequest:
    prompt: str
    cwd: Path
    env: Mapping[str, str]
    raw_log: Path
    pretty_log: Path
    model: str | None = None
    model_provider: str | None = None
    reasoning_effort: str | None = None
    network_access: bool = False
    output_schema: Path | None = None
    output_last_message: Path | None = None
    launcher: tuple[str, ...] = ("codex",)
    extra_args: tuple[str, ...] = ()
    sandbox: str | None = "workspace-write"
    config_profile: str | None = None
    timeouts: TransportTimeouts = field(default_factory=TransportTimeouts)
    process_stop_path: Path | None = None
    cancel_requested: Callable[[], str | None] | None = None
    phase: str = "execution"
    verbose: bool = False
    console_todo_id: str | None = None
    log_redactor: Callable[[str], str] | None = None
    prompt_display: str = "<prompt>"
    decision_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be non-empty text")
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise ValueError("phase must be non-empty text")
        for name in ("network_access", "verbose", "decision_only"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be bool")
        for name in ("launcher", "extra_args"):
            values = getattr(self, name)
            if isinstance(values, str) or not isinstance(values, (tuple, list)):
                raise ValueError(f"{name} must be an argument sequence, not a shell string")
            if any(not isinstance(value, str) or not value or "\0" in value for value in values):
                raise ValueError(f"{name} contains an invalid argument")
            object.__setattr__(self, name, tuple(values))
        if not self.launcher:
            raise ValueError("launcher must not be empty")
        codex_policy.validate_launcher(self.launcher)
        codex_policy.validate_sandbox(self.sandbox)
        codex_policy.validate_extra_args(self.extra_args)
        codex_policy.validate_config_profile(self.config_profile)
        codex_policy.validate_model_provider(self.model_provider)
        if self.decision_only:
            if self.sandbox != "read-only":
                raise codex_policy.CodexPolicyError("Decide requires the read-only sandbox.")
            codex_policy.decision_arguments(network_access=self.network_access,
                                           config_profile=self.config_profile, extra_args=self.extra_args)
        if self.reasoning_effort is not None and self.reasoning_effort not in (
            "none", "minimal", "low", "medium", "high", "xhigh", "max",
        ):
            raise ValueError("reasoning_effort must be a supported effort value")
        if not isinstance(self.timeouts, TransportTimeouts):
            raise ValueError("timeouts must be TransportTimeouts")
        env = dict(self.env)
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError("env must map strings to strings")
        object.__setattr__(self, "env", MappingProxyType(env))
        cwd = native_path(self.cwd, label="Codex cwd")
        object.__setattr__(self, "cwd", cwd)
        for name in ("raw_log", "pretty_log", "output_schema", "output_last_message", "process_stop_path"):
            value = getattr(self, name)
            if value is not None:
                # These are controller/output paths, not user-selected roots.
                # Resolve no workspace links before the anchored I/O layer sees them.
                from runtime_files import validate_path
                validate_path(value, label=name)
                object.__setattr__(self, name, safe_io.check_path(cwd / Path(value)))
        paths = [self.raw_log, self.pretty_log, self.output_schema, self.output_last_message]
        present = [path for path in paths if path is not None]
        if len(set(present)) != len(present):
            raise ValueError("Log, schema and final response paths must be distinct")


def build_command(request: CodexExecRequest) -> list[str]:
    """Build argv without reading ambient configuration or invoking a shell."""
    codex_policy.validate_launcher(request.launcher)
    extras = codex_policy.validate_extra_args(request.extra_args)
    profile = codex_policy.validate_config_profile(request.config_profile)
    cmd = [*request.launcher, "exec", "--json"]
    if profile is not None:
        cmd += ["--profile", profile]
    if not request.decision_only:
        cmd += ["--cd", str(request.cwd)]
    if request.model:
        cmd += ["--model", request.model]
    if request.model_provider is not None:
        cmd += ["-c", "model_provider=" + json.dumps(request.model_provider)]
    if request.reasoning_effort:
        cmd += ["-c", f"model_reasoning_effort={request.reasoning_effort}"]
    if request.output_schema is not None:
        cmd += ["--output-schema", str(request.output_schema)]
    if request.output_last_message is not None:
        cmd += ["--output-last-message", str(request.output_last_message)]
    cmd += extras
    # Workspace operation does not require a Git checkout, on any platform.
    if "--skip-git-repo-check" not in cmd:
        cmd.append("--skip-git-repo-check")
    if request.decision_only:
        cmd += codex_policy.decision_arguments(network_access=request.network_access,
                                              config_profile=request.config_profile, extra_args=extras)
    else:
        # Existing production/review write and network grants are unchanged.
        cmd += codex_policy.sandbox_arguments(sandbox=request.sandbox, network_access=request.network_access)
    cmd.append("-")
    return cmd


def _start_process(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> subprocess.Popen:
    """The sole Codex process-start boundary, including the version probe."""
    cwd = native_path(cwd, label="Codex cwd")
    launcher = resolve_launcher(command[0], cwd=cwd, env=env)
    argv = [*launcher.argv, *command[1:]]
    tree = ProcessTree()
    proc = None
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=dict(env), shell=False,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, bufsize=0, **tree.popen_options,
        )
        proc.arquilo_process_tree = tree
        proc.arquilo_launcher = launcher.metadata()
        proc.arquilo_argv = argv
        tree.bind(proc)
    except BaseException:
        tree.abort_start(proc)
        raise
    return proc


def probe_version(*, launcher: Sequence[str], cwd: Path, env: Mapping[str, str],
                  timeout: float) -> subprocess.CompletedProcess:
    """Non-model CLI probe through the same launch boundary; no global state."""
    return probe_cli_metadata(probe="version", launcher=launcher, cwd=cwd, env=env, timeout=timeout)


def metadata_probe_arguments(probe: str) -> list[str]:
    """Only side-effect-free help/version commands; no config dumps or overrides."""
    if probe == "version":
        return ["--version"]
    if probe == "help":
        return ["exec", "--help"]
    raise ValueError("Unknown metadata probe; allowed: version, help")


def probe_cli_metadata(*, probe: str, launcher: Sequence[str], cwd: Path,
                       env: Mapping[str, str], timeout: float) -> subprocess.CompletedProcess:
    """Cost-free introspection using the same launcher and owned process tree."""
    codex_policy.validate_launcher(launcher)
    command = [*launcher, *metadata_probe_arguments(probe)]
    proc = _start_process(command, cwd=cwd, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException:
        _terminate_process_group(proc, grace_seconds=0.1, reason=f"{probe}_probe_aborted")
        proc.communicate(timeout=REAP_TIMEOUT)
        raise
    finally:
        cleanup = _terminate_process_group(proc, grace_seconds=0.1, reason=f"{probe}_probe_exit")
        finish_cleanup(proc.arquilo_process_tree.close, cleanup)
        if cleanup.errors:
            raise ProcessTreeError("; ".join(cleanup.errors))
    return subprocess.CompletedProcess(getattr(proc, "arquilo_argv", command), proc.returncode,
                                       stdout.decode("utf-8"), stderr.decode("utf-8"))



def inspect_decision_cli(*, launcher: Sequence[str], cwd: Path, env: Mapping[str, str],
                         model: str | None = None, config_profile: str | None = None,
                         timeout: float = 10,
                         cancel_requested: Callable[[], str | None] | None = None) -> dict:
    """Verify only the flags the upcoming call needs, without loading user config."""
    report = {"status": "FAIL", "flags": {}, "probes": [], "interrupted": False,
              "detail": "Codex Exec capabilities could not be read."}
    record = {"name": "help", "status": "FAIL", "argv": [*launcher, "exec", "--help"]}
    try:
        if cancel_requested is not None and cancel_requested():
            report.update(interrupted=True, detail="Decide cancelled before CLI check.")
            return report
        report["probes"].append(record)
        result = probe_cli_metadata(probe="help", launcher=launcher, cwd=cwd, env=env, timeout=timeout)
        record.update(exit_code=result.returncode, stderr_present=bool(result.stderr))
        if cancel_requested is not None and cancel_requested():
            report.update(interrupted=True, detail="Decide cancelled during CLI check.")
            return report
        if result.returncode != 0:
            return report
        record["status"] = "PASS"
        found = codex_policy.exec_help_flags(result.stdout)
        required = codex_policy.decision_required_flags(model=model, config_profile=config_profile)
        report["flags"] = {flag: flag in found for flag in required}
        missing = [flag for flag, present in report["flags"].items() if not present]
        if missing:
            report["detail"] = "Required Codex Exec flags unavailable: " + ", ".join(missing)
        else:
            report.update(status="PASS", detail="Required Codex Exec flags available; host configuration inherited.")
    except KeyboardInterrupt:
        report.update(interrupted=True, detail="Decide CLI check interrupted.")
    except (OSError, UnicodeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report["detail"] = f"Codex Exec help could not be read ({type(exc).__name__})."
    return report


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_console_todo_id(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _console_prefix(todo_id: Optional[str] = None, *, timestamp: Optional[Callable[[], str]] = None) -> str:
    prefix = f"[{(timestamp or ts)()}]"
    normalized_todo_id = _normalize_console_todo_id(todo_id)
    if normalized_todo_id:
        prefix += f" [{normalized_todo_id}]"
    return prefix


def _inject_console_todo_prefix(line: str, todo_id: Optional[str] = None) -> str:
    normalized_todo_id = _normalize_console_todo_id(todo_id)
    if not normalized_todo_id or not line.startswith("["):
        return line
    end_of_timestamp = line.find("]")
    if end_of_timestamp < 0:
        return line
    remainder = line[end_of_timestamp + 1 :]
    if remainder.startswith(f" [{normalized_todo_id}]"):
        return line
    return f"{line[: end_of_timestamp + 1]} [{normalized_todo_id}]" f"{remainder}"


def _escape_terminal_controls(value: str) -> str:
    """Render untrusted event text without executing terminal controls.

    Preserve line feeds used by the existing console layout. Retained event
    data and diagnostic files remain byte-for-byte separate from this display.
    """
    return "".join(
        character if character == "\n" or unicodedata.category(character) != "Cc"
        else f"\\x{ord(character):02x}" if ord(character) <= 0xFF
        else f"\\u{ord(character):04x}"
        for character in value
    )


def append(path: Path, text: str) -> None:
    with safe_io.open_file(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text)


@dataclass
class CommandExec:
    command: str
    status: str
    exit_code: Optional[int] = None
    aggregated_output: str = ""


@dataclass
class FileChange:
    # Struktur je nach CLI-Version; wir halten es generisch:
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    assistant_messages: List[str] = field(default_factory=list)
    commands: List[CommandExec] = field(default_factory=list)
    file_changes: List[FileChange] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    turn_failed: Optional[Dict[str, Any]] = None
    process_stop_triggered: bool = False
    process_stop_details: Optional[str] = None
    # Additions stay after the existing positional fields for older callers.
    turn_completed: bool = False
    process_exit_code: Optional[int] = None
    stream_errors: List[Dict[str, Any]] = field(default_factory=list)
    execution_error: Optional[Dict[str, Any]] = None
    post_turn_cleanup: bool = False
    capture_dir: Optional[Path] = None
    capture: Dict[str, Any] = field(default_factory=dict)
    cleanup_reason: Optional[str] = None
    stream_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    _stdout_event_count: int = field(default=0, repr=False)

    @property
    def end_answer(self) -> str:
        return self.assistant_messages[-1].strip() if self.assistant_messages else ""


_RECONNECT = re.compile(
    r"Reconnecting\.\.\. ([1-9][0-9]*)/([1-9][0-9]*) "
    r"\(stream disconnected before completion: "
    r"websocket closed by server before response\.completed\)"
)


def is_transient_reconnect(event: Any, *, terminal_seen: bool) -> bool:
    """Only the verified pre-terminal WebSocket notice, never a generic error."""
    if terminal_seen or not isinstance(event, dict) or set(event) != {"type", "message"}:
        return False
    if event["type"] != "error" or not isinstance(event["message"], str):
        return False
    match = _RECONNECT.fullmatch(event["message"].strip())
    if match is None:
        return False
    try:
        attempt, limit = map(int, match.groups())
    except ValueError:
        return False
    return 1 <= attempt <= limit


def observe_stop(trace: RunResult, details: object) -> None:
    """Stop is an independent fact. Keep the first observed reason."""
    from runtime_failure import stop_reason
    if not trace.process_stop_triggered:
        trace.process_stop_details = stop_reason(details)
    trace.process_stop_triggered = True
    trace.process_stop_details = stop_reason(trace.process_stop_details)


def fatal_run_error(trace: RunResult, *, phase: str = "execution") -> Optional[Dict[str, Any]]:
    """One precedence rule for the collector and legacy/custom AutoBuild runners."""
    if isinstance(trace.execution_error, dict):
        return trace.execution_error
    violations = [e for e in trace.stream_errors
                  if isinstance(e, dict) and e.get("type") == "decision_policy_violation"]
    if violations:
        detail, code = violations, "codex_decision_policy_violation"
    elif trace.turn_failed is not None:
        detail, code = trace.turn_failed, "codex_turn_failed"
    elif trace.stream_errors:
        detail, code = trace.stream_errors, "codex_stream_error"
    else:
        return None
    return execution_error(json.dumps(detail, ensure_ascii=False), code=code,
                           phase=phase, process_exit_code=trace.process_exit_code)


def expected_stdin_abort(diagnostic: Dict[str, Any], *, shutdown_started: bool) -> bool:
    """Only an actual pipe break caused by already initiated controller cleanup."""
    return (shutdown_started and diagnostic.get("during_shutdown") is True
            and diagnostic.get("type") == "stdin_write_error"
            and diagnostic.get("source") == "stdin"
            and (diagnostic.get("exception_type") == "BrokenPipeError"
                 or (diagnostic.get("exception_type") == "OSError"
                     and (diagnostic.get("errno") == 32
                          or diagnostic.get("winerror") in (109, 232)))))


class CodexExecutionError(RuntimeError):
    """A failed Codex attempt, including partial output and diagnostic metadata."""
    def __init__(self, result: RunResult, error: Dict[str, Any]):
        self.result = result
        self.error = error
        result.execution_error = error
        super().__init__(error["message"])


def handle_event(
    ev: Dict[str, Any],
    acc: RunResult,
    pretty_log: Path,
    raw_log: Path,
    verbose: bool = False,
    console_todo_id: Optional[str] = None,
    pretty_log_redactor: Optional[Callable[[str], str]] = None,
    raw_log_redactor: Optional[Callable[[str], str]] = None,
    *,
    timestamp: Optional[Callable[[], str]] = None,
    on_log_error: Optional[Callable[[Path, Exception], None]] = None,
) -> None:
    timestamp = timestamp or ts
    acc._stdout_event_count += 1

    def _log(path: Path, line: str) -> None:
        try:
            append(path, line)
        except (OSError, UnicodeError) as exc:
            if on_log_error is None:
                raise
            on_log_error(path, exc)

    if not isinstance(ev, dict):
        acc.stream_errors.append({"type": "protocol_error", "message": "JSONL event is not an object"})
        _log(raw_log, json.dumps(ev, ensure_ascii=False) + "\n")
        return
    t = ev.get("type")
    reconnect = is_transient_reconnect(
        ev, terminal_seen=acc.turn_completed or acc.turn_failed is not None)
    if reconnect:
        acc.stream_diagnostics.append({"kind": "codex_reconnect",
            "event_index": acc._stdout_event_count, "event": dict(ev)})
    elif t == "error":
        acc.stream_errors.append(dict(ev))

    def _console_write(line: str) -> None:
        if pretty_log_redactor is not None:
            line = pretty_log_redactor(line)
        try:
            sys.stdout.write(_escape_terminal_controls(
                _inject_console_todo_prefix(line, console_todo_id)))
        except (OSError, UnicodeError) as exc:
            if on_log_error is None:
                raise
            on_log_error(Path("<console>"), exc)

    def _append_pretty(line: str) -> None:
        if pretty_log_redactor is not None:
            line = pretty_log_redactor(line)
        _log(pretty_log, line)

    def _append_raw(line: str) -> None:
        if raw_log_redactor is not None:
            line = raw_log_redactor(line)
        _log(raw_log, line)

    # Rohlog (JSONL)
    _append_raw(json.dumps(ev, ensure_ascii=False) + "\n")
    if reconnect:
        line = f"[{timestamp()}] [reconnect] {ev['message'].strip()}\n"
        _append_pretty(line)
        _console_write(line)
        return

    if not isinstance(t, str):
        # Some metadata preamble events do not expose a `type`; log them for diagnostics and continue.
        label = "event"
        if not verbose:
            _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {label}\n")
        line = f"[{timestamp()}] [event] {json.dumps(ev, ensure_ascii=False)}\n"
        _append_pretty(line)
        if verbose:
            _console_write(line)
        return

    # Schönlog: minimale, sinnvolle Sicht
    if t.startswith("item."):
        item = ev.get("item", {})
        if not isinstance(item, dict):
            acc.stream_errors.append({"type": "protocol_error", "message": "item is not an object"})
            return
        # Some CLI builds use `item_type`, others use `type`.
        itype = item.get("item_type") or item.get("type") or item.get("kind")
        label = f"{t}/{itype}" if itype else t
        if itype in {"assistant_message", "agent_message"}:
            text = item.get("text")
            if text is None:
                text = item.get("content")

            if isinstance(text, list):
                segments: List[str] = []
                for chunk in text:
                    if isinstance(chunk, dict):
                        maybe_text = chunk.get("text")
                        if isinstance(maybe_text, str) and maybe_text.strip():
                            segments.append(maybe_text.strip())
                    elif isinstance(chunk, str) and chunk.strip():
                        segments.append(chunk.strip())
                if segments:
                    acc.assistant_messages.append("\n".join(segments))
                rendered = "\n".join(segments)
            elif isinstance(text, str):
                cleaned = text.strip()
                if cleaned:
                    acc.assistant_messages.append(cleaned)
                rendered = cleaned
            else:
                rendered = ""

            if not rendered and isinstance(text, (int, float)):
                rendered = str(text)

            label = (
                "assistant_message" if itype == "assistant_message" else "agent_message"
            )
            line = f"[{timestamp()}] [{label}]\n{rendered}\n\n"
            _append_pretty(line)
            # Console output: always include text for agent/assistant messages
            if verbose:
                _console_write(line)
            else:
                # Single-line condensed echo with text
                _console_write(
                    f"{_console_prefix(console_todo_id, timestamp=timestamp)} [{label}] {rendered}\n"
                )
        elif itype == "command_execution":
            # command_execution kann started/updated/completed sein
            cmd = item.get("command", "")
            status = item.get("status")
            agg = item.get("aggregated_output", "")
            exit_code = item.get("exit_code")
            acc.commands.append(CommandExec(cmd, status or "", exit_code, agg or ""))
            # Pretty log: do NOT include command output (per requirement)
            if status == "completed":
                line = f"[{timestamp()}] [exec] {cmd}\nexit={exit_code}\n\n"
            else:
                line = f"[{timestamp()}] [exec] {cmd} ({status})\n"
            _append_pretty(line)
            # Console: condensed status when not verbose; full line when verbose
            if verbose:
                _console_write(line)
            else:
                if status == "completed":
                    _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} [exec] {cmd}\n")
                else:
                    _console_write(
                        f"{_console_prefix(console_todo_id, timestamp=timestamp)} [exec] {cmd} ({status})\n"
                    )
        elif itype == "file_change":
            acc.file_changes.append(FileChange(raw=item))
            line = f"[{timestamp()}] [file_change] {json.dumps(item, ensure_ascii=False)}\n"
            _append_pretty(line)
            if verbose:
                _console_write(line)
            else:
                _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {label}\n")
        else:
            # reasoning, mcp_tool_call, web_search, ...
            # Pretty log remains JSON dump for full context
            line = (
                f"[{timestamp()}] [{itype or 'item'}] {json.dumps(item, ensure_ascii=False)}\n"
            )
            _append_pretty(line)
            if verbose:
                _console_write(line)
            else:
                # Console: for reasoning, also echo the text alongside timestamp
                if (itype or "").lower() == "reasoning":
                    rtext = item.get("text")
                    if isinstance(rtext, list):
                        rtext = " ".join(
                            s.strip()
                            for s in (
                                [
                                    (
                                        c.get("text", "")
                                        if isinstance(c, dict)
                                        else (c or "")
                                    )
                                    for c in rtext
                                ]
                            )
                            if isinstance(s, str) and s.strip()
                        )
                    if not isinstance(rtext, str):
                        rtext = ""
                    _console_write(
                        f"{_console_prefix(console_todo_id, timestamp=timestamp)} [reasoning] {rtext.strip()}\n"
                    )
                else:
                    _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {label}\n")

    elif t == "turn.completed":
        acc.turn_completed = True
        usage = ev.get("usage") or {}
        acc.usage = usage
        if not verbose:
            _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {t}\n")
        line = f"[{timestamp()}] [turn.completed] usage={json.dumps(usage)}\n\n"
        _append_pretty(line)
        if verbose:
            _console_write(line)

    elif t == "turn.failed":
        acc.turn_failed = ev
        if not verbose:
            _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {t}\n")
        line = f"[{timestamp()}] [turn.failed] {json.dumps(ev, ensure_ascii=False)}\n\n"
        _append_pretty(line)
        if verbose:
            _console_write(line)

    elif t in ("thread.started", "turn.started"):
        if not verbose:
            _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {t}\n")
        line = f"[{timestamp()}] [{t}]\n"
        _append_pretty(line)
        if verbose:
            _console_write(line)

    else:
        if not verbose:
            _console_write(f"{_console_prefix(console_todo_id, timestamp=timestamp)} {t}\n")
        line = f"[{timestamp()}] [{t}] {json.dumps(ev, ensure_ascii=False)}\n"
        _append_pretty(line)
        if verbose:
            _console_write(line)


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


class ProcessStopMonitor:
    def __init__(
        self,
        path: Path,
        pretty_log: Path,
        console_todo_id: Optional[str] = None,
        *,
        kill_grace: float = 5.0,
        timestamp: Optional[Callable[[], str]] = None,
    ) -> None:
        self.kill_grace = kill_grace
        self.timestamp = timestamp
        self.path = path
        self.pretty_log = pretty_log
        self.console_todo_id = _normalize_console_todo_id(console_todo_id)
        self.details: Optional[str] = None
        self.triggered = threading.Event()
        self.log_error: Optional[str] = None
        self.cleanup_error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, proc: subprocess.Popen) -> None:
        def _poll() -> None:
            if self.path.exists():
                self._trigger(proc)
                return
            while proc.poll() is None and not self.triggered.is_set():
                if self.path.exists():
                    self._trigger(proc)
                    break
                time.sleep(0.5)

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def _trigger(self, proc: subprocess.Popen) -> None:
        if self.triggered.is_set():
            return
        try:
            details = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            details = ""
        self.details = details or f"process_stop ausgelöst ({self.path})"
        log_line = (
            f"{_console_prefix(self.console_todo_id, timestamp=self.timestamp)} [process_stop] {self.details}\n"
        )
        self.triggered.set()
        try:
            append(self.pretty_log, log_line)
            sys.stderr.write(log_line)
        except (OSError, UnicodeError) as exc:
            self.log_error = f"{type(exc).__name__}: {exc}"
        try:
            cleanup = _terminate_process_group(proc, grace_seconds=self.kill_grace, reason="process_stop")
            if cleanup is not None and cleanup.errors:
                self.cleanup_error = "; ".join(cleanup.errors)
        except OSError as exc:
            self.cleanup_error = str(exc)

    def wait(self) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


_CHUNK_SIZE = 64 * 1024
_INVALID_UTF8 = re.compile("[\udc80-\udcff]")


def _write_bytes(stream: Any, data: bytes, progress: Callable[[int], None]) -> None:
    """Binary pipes/files may write only a prefix, including without an error."""
    view = memoryview(data)
    while view:
        written = stream.write(view[:_CHUNK_SIZE])
        if not isinstance(written, int) or written <= 0 or written > len(view[:_CHUNK_SIZE]):
            raise OSError(f"Invalid short write result: {written!r}")
        progress(written)
        view = view[written:]


def _prepare_capture(request: CodexExecRequest, acc: RunResult) -> bytes:
    role = {"auftrag": "production"}.get(request.phase, request.phase)
    acc.capture_dir = numbered_directory(request.raw_log.parent, role)
    acc.capture = {
        "schema_version": "arquilo.codex.io_capture.v1", "phase": request.phase,
        "cwd": str(request.cwd), "argv": build_command(request),
        "stdin": {"expected_bytes": None, "archived_bytes": 0, "written_bytes": 0, "closed": False},
        "stdout": {"received_bytes": 0, "archived_bytes": 0, "eof": False, "invalid_utf8_bytes": 0},
        "stderr": {"received_bytes": 0, "archived_bytes": 0, "eof": False, "invalid_utf8_bytes": 0},
        "diagnostics": [], "started_at": datetime.now().astimezone().isoformat(),
        "raw_files": {"stdin": "prompt.utf8", "stdout": "stdout.bin", "stderr": "stderr.bin"},
        "normalized_event_log": str(request.raw_log), "pretty_log": str(request.pretty_log),
        "answer_file": "response.txt", "answer_source": "last stdout agent/assistant message (normalized)",
        "cli_answer_file": str(request.output_last_message) if request.output_last_message else None,
    }
    for name in ("stdout.bin", "stderr.bin", "response.txt"):
        safe_io.write_bytes(acc.capture_dir / name, b"", exclusive=True)
    # Strict encoding: an unpaired surrogate must fail before a process starts.
    prompt = request.prompt.encode("utf-8")
    acc.capture["stdin"]["expected_bytes"] = len(prompt)

    def archived(count: int) -> None:
        acc.capture["stdin"]["archived_bytes"] += count

    with safe_io.open_file(acc.capture_dir / "prompt.utf8", "wb", buffering=0) as stream:
        _write_bytes(stream, prompt, archived)
    return prompt



def _cancellation_reason(request: CodexExecRequest) -> str | None:
    reason = request.cancel_requested() if request.cancel_requested is not None else None
    if request.process_stop_path is not None and request.process_stop_path.exists():
        reason = safe_io.read_text(request.process_stop_path).strip() or "process_stop active"
    return reason

def _run(request: CodexExecRequest, acc: RunResult, prompt_bytes: bytes) -> RunResult:
    cwd = request.cwd
    raw_log, pretty_log = request.raw_log, request.pretty_log
    verbose, console_todo_id = request.verbose, request.console_todo_id
    kill_grace = request.timeouts.kill_grace
    cmd = build_command(request)
    safe_command = json.dumps(cmd, ensure_ascii=False)
    header = (f"[{ts()}] ARGV (JSON): {safe_command}\nCWD: {cwd}\nPHASE: {request.phase}\n"
              f"STDIN: {request.prompt_display}\nCAPTURE: {acc.capture_dir}\n\n")
    append(pretty_log, header)
    if verbose:
        sys.stdout.write(_inject_console_todo_prefix(header, console_todo_id))
    cancellation = _cancellation_reason(request)
    if cancellation:
        observe_stop(acc, cancellation)
        append(pretty_log, f"[{ts()}] [cancelled] {cancellation}\n")
        return acc
    try:
        proc = _start_process(cmd, cwd=cwd, env=request.env)
    except OSError as exc:
        raise CodexExecutionError(acc, execution_error(
            f"Cannot execute Codex: {exc}", code="codex_launch_failed", phase=request.phase,
        )) from exc
    try:
        return _collect_process(request, acc, prompt_bytes, proc)
    finally:
        # This also covers exceptions during reader/thread setup, before the
        # collector's event-loop finally block has been reached.
        cleanup = _terminate_process_group(proc, grace_seconds=kill_grace, reason="transport_scope_exit")
        try:
            finish_cleanup(proc.arquilo_process_tree.close, cleanup)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None and not stream.closed:
                    finish_cleanup(stream.close, cleanup)
        except OSError as exc:
            cleanup.errors.append(str(exc))
        acc.capture["process_tree"] = cleanup.metadata()
        acc.process_exit_code = cleanup.parent_exit_after
        if cleanup.interrupted:
            observe_stop(acc, "KeyboardInterrupt")
        if cleanup.errors and acc.execution_error is None:
            acc.execution_error = execution_error(
                "; ".join(cleanup.errors), code="codex_cleanup_failed", process_exit_code=acc.process_exit_code)


def _collect_process(request: CodexExecRequest, acc: RunResult, prompt_bytes: bytes,
                     proc: subprocess.Popen) -> RunResult:
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
                                name=f"autobuild-codex-{source}", daemon=True)
               for source, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    threads.append(threading.Thread(target=_write_stdin, name="autobuild-codex-stdin", daemon=True))
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
        line = line.strip()
        if not line:
            return
        try:
            ev = codex_policy.parse_decision_event(line) if request.decision_only else json.loads(line)
        except ValueError:
            if request.decision_only:
                acc.stream_errors.append({"type": "decision_policy_violation",
                                          "message": "Non-JSON stdout in decision stream"})
            redacted_line = _redact_prompt_for_pretty_log(line)
            log(pretty_log, f"[{ts()}] [WARN] Non-JSON stdout: {redacted_line}\n")
            log(raw_log, redacted_line + "\n")
        else:
            if request.decision_only:
                violation = codex_policy.decision_event_violation(ev)
                if violation is None and terminal_event is not None and ev.get("type") != "error":
                    violation = "Decision event after terminal event: " + str(ev.get("type"))
                if violation:
                    acc._stdout_event_count += 1
                    acc.stream_errors.append({"type": "decision_policy_violation", "message": violation})
                    log(raw_log, json.dumps(ev, ensure_ascii=False) + "\n")
                    log(pretty_log, f"[{ts()}] [decision_policy_violation] {violation}\n")
                    return  # Do not pass malformed/forbidden items to legacy display handlers.
            handle_event(ev, acc, pretty_log, raw_log, verbose,
                         console_todo_id=console_todo_id,
                         pretty_log_redactor=_redact_prompt_for_pretty_log,
                         raw_log_redactor=_redact_prompt_for_pretty_log,
                         on_log_error=log_error)
            event_type = ev.get("type") if isinstance(ev, dict) else None
            if event_type in {"turn.completed", "turn.failed"}:
                terminal_event = str(event_type)
                terminal_event_at = time.monotonic()

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
            if request.decision_only and any(e.get("type") == "decision_policy_violation" for e in acc.stream_errors):
                terminate("decision_policy_violation")
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
                f"[{ts()}] [WARN] Codex emitted {terminal_event} but did not exit "
                f"within {post_turn_grace:g}s; process group was terminated and "
                "the terminal event will be checked against the execution contract.\n"
            ),
        )
        if verbose:
            sys.stderr.write(
                f"[AutoBuild] Codex wurde nach {terminal_event} und "
                f"{post_turn_grace:g}s Nachlauf beendet.\n"
            )

    log(pretty_log, f"[{ts()}] EXIT {rc}\n\n")

    error = fatal_run_error(acc)
    forced_exit = (cleanup.forced_parent_exit and cleanup.parent_exit_before is None
                   and not cleanup.errors)
    if error is None:
        if forced_for_timeout:
            error = execution_error(
                f"Codex exceeded the total timeout of {request.timeouts.total:g}s.",
                code="codex_timeout", process_exit_code=rc)
        elif forced_for_stall:
            error = execution_error(
                f"Codex stalled for {stall_timeout:g}s before successful turn completion. "
                "Partial edits may exist; inspect them before retrying.",
                code="codex_stalled", process_exit_code=rc)
        elif acc.process_stop_triggered:
            # A later sentinel cannot hide a naturally failed process. Only
            # our evidenced kill (or natural exit 0) is expected on cancellation.
            if rc != 0 and not forced_exit:
                error = execution_error(
                    f"Codex exited with code {rc}; not an expected controller termination.",
                    code="codex_process_failed", process_exit_code=rc)
        elif not acc.turn_completed:
            error = execution_error(
                f"Codex exited with code {rc} without turn.completed.",
                code="codex_missing_completion", process_exit_code=rc)
        elif rc != 0 and not (forced_after_terminal and forced_exit):
            error = execution_error(
                f"Codex emitted turn.completed but exited with code {rc}.",
                code="codex_process_failed", process_exit_code=rc)
        elif not acc.end_answer:
            error = execution_error(
                "Codex completed the turn without a final assistant message.",
                code="codex_missing_answer", process_exit_code=rc)
    if error is not None:
        log(pretty_log, f"[{ts()}] [execution_error] {json.dumps(error, ensure_ascii=False)}\n")
        raise CodexExecutionError(acc, error)
    return acc


@dataclass(frozen=True, slots=True)
class TransportResult:
    """Validated status plus the retained command/file/usage trace for old callers."""

    execution: ExecutionResult
    trace: RunResult


def execute(request: CodexExecRequest) -> TransportResult:
    """Execute one request. Technical failures never become semantic decisions."""
    build_command(request)  # Validate before even creating a per-call archive.
    trace = RunResult()
    try:
        prompt_bytes = _prepare_capture(request, trace)
        cancellation = _cancellation_reason(request)
        if cancellation:
            observe_stop(trace, cancellation)
        elif request.decision_only:
            compatibility = inspect_decision_cli(
                launcher=request.launcher, cwd=request.cwd, env=request.env,
                model=request.model, config_profile=request.config_profile,
                cancel_requested=lambda: _cancellation_reason(request),
            )
            trace.capture["decision_cli_compatibility"] = compatibility
            trace.capture["configuration_policy"] = "inherit-trusted-host"
            if compatibility["interrupted"]:
                observe_stop(trace, _cancellation_reason(request) or "Decide CLI check cancelled")
            elif compatibility["status"] != "PASS":
                raise CodexExecutionError(trace, execution_error(
                    compatibility["detail"] + " No model call was started.",
                    code="codex_decision_cli_failed", phase=request.phase))
        if not trace.process_stop_triggered:
            trace = _run(request, trace, prompt_bytes)
    except CodexExecutionError as exc:
        trace = exc.result
    except (OSError, UnicodeError) as exc:
        trace.execution_error = execution_error(
            f"Cannot execute or log Codex: {exc}", code="codex_io_failed", phase=request.phase,
            process_exit_code=trace.process_exit_code,
        )
    except Exception as exc:
        # For example Thread.start() raises RuntimeError on resource exhaustion.
        # Request validation stays outside this boundary; runtime failures keep
        # their partial capture and must never skip the structured result.
        trace.execution_error = execution_error(
            f"Codex transport failed: {type(exc).__name__}: {exc}",
            code="codex_transport_failed", phase=request.phase,
            process_exit_code=trace.process_exit_code,
        )
    except KeyboardInterrupt:
        observe_stop(trace, "KeyboardInterrupt")

    if trace.execution_error is not None:
        trace.execution_error = {**trace.execution_error, "phase": request.phase}

    def archive_error(exc: Exception) -> None:
        diagnostic = {"type": "log_error", "source": "capture",
                      "message": f"{type(exc).__name__}: {exc}"}
        trace.stream_errors.append(diagnostic)
        if trace.execution_error is None:
            trace.execution_error = execution_error(
                f"Cannot archive Codex result: {exc}", code="codex_io_failed", phase=request.phase,
                process_exit_code=trace.process_exit_code,
            )

    if trace.capture_dir is not None:
        try:
            atomic_write_text(trace.capture_dir / "response.txt", trace.end_answer)
        except (OSError, UnicodeError) as exc:
            archive_error(exc)
        capture = trace.capture
        if capture:
            for source in ("stdout", "stderr"):
                stats = capture[source]
                stats["complete"] = (stats["eof"] and stats["received_bytes"] == stats["archived_bytes"]
                                     and not any(e["source"] == source and e["type"] in {"log_error", "read_error"}
                                                 for e in capture["diagnostics"]))
            stdin = capture["stdin"]
            stdin["complete"] = (stdin["closed"] and
                                 stdin["expected_bytes"] == stdin["written_bytes"] == stdin["archived_bytes"])
            capture.update({
                "finished_at": datetime.now().astimezone().isoformat(),
                "process_exit_code": trace.process_exit_code, "completion_seen": trace.turn_completed,
                "post_turn_cleanup": trace.post_turn_cleanup, "cleanup_reason": trace.cleanup_reason,
                "cancellation_reason": trace.process_stop_details,
                "process_stop_triggered": trace.process_stop_triggered,
                "stream_diagnostics": trace.stream_diagnostics,
                "status": "failed" if trace.execution_error else "cancelled" if trace.process_stop_triggered else "succeeded",
                "error": trace.execution_error, "stream_errors": trace.stream_errors,
            })
            try:
                atomic_write_text(trace.capture_dir / "capture.json",
                                  json.dumps(capture, ensure_ascii=True, indent=2) + "\n")
            except (OSError, UnicodeError) as exc:
                archive_error(exc)
                capture["status"] = "failed"
                capture["error"] = trace.execution_error
    error = trace.execution_error
    if error is not None:
        error = trace.execution_error = {**error, "phase": request.phase}
        execution = ExecutionResult(
            status=ExecutionStatus.FAILED, answer=trace.end_answer,
            process_exit_code=trace.process_exit_code, completion_seen=trace.turn_completed,
            failure=Failure(kind=FailureKind.EXECUTION, code=error["code"],
                            message=error["message"], phase=request.phase),
        )
    elif trace.process_stop_triggered:
        execution = ExecutionResult(
            status=ExecutionStatus.CANCELLED, answer=trace.end_answer,
            process_exit_code=trace.process_exit_code, completion_seen=trace.turn_completed,
            cancellation_reason=trace.process_stop_details or "Cancelled",
        )
    else:
        execution = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED, answer=trace.end_answer,
            process_exit_code=trace.process_exit_code, completion_seen=trace.turn_completed,
            cleanup_reason=trace.cleanup_reason,
        )
    return TransportResult(execution, trace)
