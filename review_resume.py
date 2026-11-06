# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Opt-in, evidence-checked review continuation without production replay.

CLI: arquilo tasklist resume-review [--check-only] --todo ID --capture-dir PATH --
     tasklist run --workdir WORK --todo-file TASKS --start ID --stop ID
     --max-steps 1 --max-retries 1 --breakdown-policy off

Only one thoroughly validated, fully captured Codex production success can
be substituted once for the otherwise repeatable production call. The normal
mandatory read-only review and controller acceptance gates are never bypassed.
Use the same --state-dir, workspace, working task file, prompt catalog and
resource settings as the original run. --check-only verifies the archive and
its binding without model calls or writes; it does not mark the task DONE.
The normal runner still checks the current plan and exact regenerated prompt.
Archived workspace files are untrusted; operator confirmation is required.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import stat
from typing import Any

import codex_transport as transport
import safe_io
from controller_state import state_directory_path, PlanIntegrityError

# Keep one universal retry classifier in codex_transport.
is_transient_retry_notice = transport.is_transient_reconnect

class RecoveryRefused(RuntimeError):
    """Preflight or validation failed; production must never run as a fallback."""


@dataclass(frozen=True)
class RecoveryEvidence:
    capture_dir: Path
    task_id: str
    workdir: Path
    prompt: str
    answer: str
    notices: tuple[tuple[int, dict], ...]
    sha256: dict[str, str]


def _checked_path(path: Path) -> Path:
    try:
        # Check the spelling before resolving it: resolving first would hide
        # user-controlled links. Native aliases (notably Windows 8.3 names)
        # must then use the same canonical spelling as the workspace/state.
        checked = safe_io.check_path(path, missing_ok=False)
        canonical = checked.resolve(strict=True)
        return safe_io.check_path(canonical, missing_ok=False)
    except (OSError, ValueError) as exc:
        raise RecoveryRefused("Required archive/binding path is missing, linked or unsafe.") from exc


def _regular_file(path: Path, max_bytes: int) -> bytes:
    # No-follow, single-link reads also protect external controller captures.
    # Do not resolve user-selected symlinks before this check.
    try:
        with safe_io.open_file(path, "rb") as stream:
            if os.fstat(stream.fileno()).st_size > max_bytes:
                raise RecoveryRefused("Required archive file is larger than the safety limit.")
            data = stream.read(max_bytes + 1)
    except (OSError, ValueError) as exc:
        raise RecoveryRefused("Required archive file is missing, linked or unsafe.") from exc
    if len(data) > max_bytes:
        raise RecoveryRefused("Archived source exceeded the strict read-size limit.")
    return data


def _safe_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RecoveryRefused("Archived structured evidence is malformed.") from exc


def _final_text(event: dict) -> str | None:
    if event.get("type") not in ("item.completed", "item.updated", "item.started"):
        return None
    item = event.get("item", {})
    if not isinstance(item, dict) or (item.get("item_type") or item.get("type") or item.get("kind")) not in (
            "assistant_message", "agent_message"):
        return None
    value = item.get("text", item.get("content"))
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = []
        for piece in value:
            text = piece.get("text") if isinstance(piece, dict) else piece
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts) or None
    return None


def _record_path(record: dict, name: str) -> Path:
    value = record.get(name)
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RecoveryRefused("Archive metadata has no absolute " + name + ".")
    return _checked_path(Path(value))


def _verify_capture_location(capture: Path, workspace: Path, task_id: str, *,
                             todo_file: Path | None, state_root: Path | None) -> None:
    if (capture.parent.name != "task-" + task_id
            or not re.fullmatch(r"[0-9]{3}-production", capture.name)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z(?:-\d{4})?",
                                capture.parent.parent.name)):
        raise RecoveryRefused("Capture is not the selected task's production attempt.")
    run_dir = capture.parent.parent
    if run_dir.parent == workspace / ".codex_runs" / "run_todos":
        return  # Historical workspace layout; all byte/contract checks still apply.
    if todo_file is None:
        raise RecoveryRefused("External captures require the original --todo-file and --state-dir.")
    todo = _checked_path(todo_file.expanduser())
    if not todo.is_relative_to(workspace):
        raise RecoveryRefused("Use the original working task file inside --workdir, not an external template.")
    # Compute, never allocate, the existing workspace+task key. Preserve all
    # plan journals and budgets; no copied capture can authorize a fresh key.
    try:
        state = state_directory_path(workspace, todo, state_root)
    except (OSError, ValueError, PlanIntegrityError) as exc:
        raise RecoveryRefused("Selected controller-state binding is unavailable or inconsistent.") from exc
    _checked_path(state)
    info = state.parent.stat()
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise RecoveryRefused("Controller state root must be owned by this user with mode 0700.")
    identity = _safe_json(_regular_file(state / "identity.json", 65536))
    if (not isinstance(identity, dict) or identity.get("schema_version") != "arquilo.state_identity.v1"
            or identity.get("state_key") != state.name
            or _record_path(identity, "workspace") != workspace
            or _record_path(identity, "todo") != todo):
        raise RecoveryRefused("Controller identity does not bind this workspace and working task file.")
    allowed = [state / "runs"]
    if run_dir.parent not in allowed:
        # Optional named project logs are an indexed view of the SAME state.
        registry = _safe_json(_regular_file(state.parent / "projects.json", 8 << 20))
        plans = registry.get("plans") if isinstance(registry, dict) else None
        project = plans.get(state.name) if isinstance(plans, dict) else None
        if (not isinstance(registry, dict) or registry.get("schema_version") != "arquilo.projects.v1"
                or not isinstance(project, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", project)):
            raise RecoveryRefused("Capture is not in this plan's registered controller logs.")
        directory = state.parent / project
        record = _safe_json(_regular_file(directory / "project.json", 8 << 20))
        bindings = record.get("plans") if isinstance(record, dict) else None
        binding = bindings.get(state.name) if isinstance(bindings, dict) else None
        if (not isinstance(record, dict) or record.get("schema_version") != "arquilo.project.v1"
                or record.get("project_id") != project
                or _record_path(record, "workspace") != workspace
                or not isinstance(binding, dict)
                or _record_path(binding, "controller_state") != state
                or _record_path(binding, "todo_file") != todo):
            raise RecoveryRefused("Named project log binding does not match this plan.")
        allowed.append(directory / "runs")
    if run_dir.parent not in allowed:
        raise RecoveryRefused("Capture is outside this plan's registered controller logs.")
    run = _safe_json(_regular_file(run_dir / "run.json", 8 << 20))
    if (not isinstance(run, dict) or run.get("schema_version") != "arquilo.run_log.v2"
            or _record_path(run, "run_directory") != run_dir
            or _record_path(run, "workspace") != workspace
            or _record_path(run, "todo_file") != todo
            or _record_path(run, "controller_state") != state
            or run.get("status") != "failed" or not isinstance(run.get("finished_at"), str)
            or not run["finished_at"]
            or not isinstance(run.get("tasks"), list)
            or not any(_record_path({"path": path}, "path") == capture.parent / "task_log.json"
                       for path in run["tasks"])
            or run.get("process_stop_triggered", False) is not False):
        raise RecoveryRefused("Original external run is not closed and bound to the selected plan.")


def load_verified_recovery(capture_dir: Path, workdir: Path, task_id: str, *,
                           todo_file: Path | None = None,
                           state_root: Path | None = None) -> RecoveryEvidence:
    """Read the exact closed capture; never mutate archives, plans or budgets.

    Historical workspace captures are untrusted. Current external captures
    must match the selected controller state and its run/project metadata.
    Both require explicit opt-in and a fresh independent review before DONE.
    """
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", task_id):
        raise RecoveryRefused("Invalid task ID.")
    workspace = workdir.expanduser().resolve(strict=True)
    if ".." in capture_dir.parts:
        raise RecoveryRefused("Capture path must not contain parent traversal.")
    capture = _checked_path(capture_dir.expanduser())
    _verify_capture_location(capture, workspace, task_id,
                             todo_file=todo_file, state_root=state_root)
    original = capture.parent
    names = {"capture": capture / "capture.json", "stdout": capture / "stdout.bin",
             "stderr": capture / "stderr.bin",
             "response": capture / "response.txt", "prompt": original / "prompt.md",
             "request": capture / "prompt.utf8", "contract": original / "original_contract.json",
             "summary": original / "autobuild_summary.json"}
    limits = {"capture": 8 << 20, "stdout": 512 << 20, "stderr": 512 << 20, "response": 32 << 20,
              "prompt": 8 << 20, "request": 24 << 20, "contract": 12 << 20, "summary": 16 << 20}
    raw = {name: _regular_file(path, limits[name]) for name, path in names.items()}
    info = _safe_json(raw["capture"])
    contract = _safe_json(raw["contract"])
    summary = _safe_json(raw["summary"])
    if not isinstance(info, dict) or not isinstance(contract, dict) or not isinstance(summary, dict):
        raise RecoveryRefused("Capture metadata or task contract is not an object.")
    if todo_file is not None and _record_path(contract, "source") != _checked_path(todo_file.expanduser()):
        raise RecoveryRefused("Original contract belongs to another working task file.")
    if info.get("schema_version") != "arquilo.codex.io_capture.v1":
        raise RecoveryRefused("Unsupported capture schema.")
    if (info.get("completion_seen") is not True or type(info.get("process_exit_code")) is not int
            or info["process_exit_code"] != 0 or info.get("process_stop_triggered") is not False):
        raise RecoveryRefused("Archived execution did not end normally with turn.completed and exit 0.")
    if info.get("status") != "failed" or not isinstance(info.get("error"), dict) or info["error"].get("code") != "codex_stream_error":
        raise RecoveryRefused("Archived result is not the known spurious-stream-error scenario.")
    if info.get("phase") != "auftrag" or Path(info.get("cwd", "/")).resolve() != workspace:
        raise RecoveryRefused("Archived production phase/workspace does not match.")
    if (summary.get("auftrag_runs") != 1 or summary.get("review_runs") != 0 or
            not isinstance(summary.get("execution_error"), dict) or
            summary["execution_error"].get("code") != "codex_stream_error" or
            summary.get("completed") is not False or
            summary.get("process_stop_triggered", False) is not False):
        raise RecoveryRefused("Original AutoBuild summary does not confirm a pre-review false failure.")
    terminal = summary.get("terminal_attempt")
    if (not isinstance(terminal, dict) or terminal.get("phase") != "task" or
            terminal.get("index") != 1 or
            Path(terminal.get("capture_directory") or "/").resolve() != capture):
        raise RecoveryRefused("Original AutoBuild summary references another execution attempt.")
    if terminal.get("process_stop_triggered", False) is not False or terminal.get("turn_failed") is not None:
        raise RecoveryRefused("Original terminal attempt records a real failure or stop.")
    for channel in ("stdout", "stderr", "stdin"):
        if not isinstance(info.get(channel), dict) or info[channel].get("complete") is not True:
            raise RecoveryRefused("Archived Codex input/output was not completely captured.")
    stdin = info["stdin"]
    if any(type(stdin.get(field)) is not int or stdin[field] != len(raw["request"])
           for field in ("expected_bytes", "archived_bytes", "written_bytes")):
        raise RecoveryRefused("The recorded production input stream is not complete.")
    for channel in ("stdout", "stderr"):
        if any(type(info[channel].get(field)) is not int or info[channel][field] != len(raw[channel])
               for field in ("archived_bytes", "received_bytes")):
            raise RecoveryRefused("The recorded production " + channel + " stream is not complete.")
    try:
        prompt = raw["request"].decode("utf-8")
        original_prompt = raw["prompt"].decode("utf-8")
        answer = raw["response"].decode("utf-8").strip()
    except UnicodeError as exc:
        raise RecoveryRefused("Archived prompt/answer are not UTF-8.") from exc
    if not prompt.strip() or not answer or contract.get("original_request") != prompt or original_prompt != prompt:
        raise RecoveryRefused("Original task contract, prompt and answer are inconsistent.")
    notice_events = []
    last_answer = None
    completion = 0
    index = 0
    for line in raw["stdout"].splitlines():
        if len(line) > (16 << 20):
            raise RecoveryRefused("An archived event exceeds the safe per-event size.")
        if not line.strip():
            continue
        index += 1
        event = _safe_json(line)
        if not isinstance(event, dict):
            raise RecoveryRefused("Archived event is not a JSON object.")
        if event.get("type") == "turn.failed":
            raise RecoveryRefused("A real turn.failed occurred; cannot resume review.")
        if event.get("type") == "turn.completed":
            completion += 1
        elif completion and event.get("type") in ("thread.started", "turn.started", "item.started", "item.updated", "item.completed"):
            raise RecoveryRefused("Archive contains new production activity after the terminal event.")
        if event.get("type") == "error":
            if not transport.is_transient_reconnect(event, terminal_seen=completion > 0):
                raise RecoveryRefused("Unknown or post-terminal stream error; cannot resume review.")
            notice_events.append((index, event))
        text = _final_text(event)
        if text:
            last_answer = text
    if completion != 1 or not last_answer or last_answer != answer:
        raise RecoveryRefused("Final assistant message/turn.completed and archived response do not match.")
    archived_errors = info.get("stream_errors")
    diagnostics = info.get("stream_diagnostics")
    if diagnostics is None:
        diagnostics = []
    if not isinstance(archived_errors, list) or not archived_errors or not isinstance(diagnostics, list):
        raise RecoveryRefused("Archive does not record a recoverable stream-error-only failure.")
    observed = dict(notice_events)
    diagnosed: set[int] = set()
    last_index = 0
    for entry in diagnostics:
        if (not isinstance(entry, dict) or set(entry) != {"kind", "event_index", "event"}
                or entry.get("kind") != "codex_reconnect"
                or type(entry.get("event_index")) is not int
                or entry["event_index"] <= last_index
                or entry["event_index"] not in observed
                or entry["event"] != observed[entry["event_index"]]):
            raise RecoveryRefused("Unknown, duplicated or mismatched archive diagnostics.")
        last_index = entry["event_index"]
        diagnosed.add(last_index)
    # The old collector split error events into two lists. Reconcile that
    # partition in wire order, including repeated identical waiting notices.
    remaining = [event for index, event in notice_events if index not in diagnosed]
    if archived_errors != remaining:
        raise RecoveryRefused("Archived errors/diagnostics do not exactly cover the observed retry notices.")
    digests = {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}
    return RecoveryEvidence(capture, task_id, workspace, prompt, answer, tuple(notice_events), digests)


def _value(argv: list[str], name: str) -> str:
    if argv.count(name) != 1:
        raise RecoveryRefused("Review recovery requires exactly one " + name + ".")
    if any(token.startswith(name + "=") for token in argv):
        raise RecoveryRefused("Use one unambiguous separated value for " + name + ".")
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise RecoveryRefused("Value missing for " + name + ".")
    return argv[i + 1]


def _validate_recovery_argv(argv: list[str], todo: str) -> Path:
    for i, token in enumerate(argv):
        if token == "--backend" and (i+1 >= len(argv) or argv[i+1] != "codex"):
            raise RecoveryRefused("Legacy reconnect review recovery supports Codex archives only; Claude Code is not started or replaced.")
        if token.startswith("--backend=") and token != "--backend=codex":
            raise RecoveryRefused("Legacy reconnect review recovery supports Codex archives only.")
    if argv[:2] != ["tasklist", "run"]:
        raise RecoveryRefused("Use 'tasklist run' for a native controller review.")
    if (_value(argv, "--start") != todo or _value(argv, "--stop") != todo
            or _value(argv, "--max-steps") != "1" or _value(argv, "--max-retries") != "1"
            or _value(argv, "--breakdown-policy") != "off"):
        raise RecoveryRefused("Recovery must be bounded to one task and one review without automatic fixes/breakdown.")
    for banned in ("--dry-run", "--allow-todo-modifications", "--git", "--git-push",
                   "--accept-plan-changes", "--todo-template"):
        if any(token == banned or token.startswith(banned + "=") for token in argv):
            raise RecoveryRefused("Recovery refuses plan/git/dry-run changes or plan adoption.")
    work = Path(_value(argv, "--workdir")).expanduser().resolve(strict=True)
    if not Path(_value(argv, "--todo-file")).expanduser().is_file():
        raise RecoveryRefused("Selected working task list is unavailable.")
    return work


def install_review_injection(evidence: RecoveryEvidence, autobuild_module) -> dict:
    """Inject the archived *result*, never an old request; one exact prompt only."""
    prior = autobuild_module.run_codex_exec_json
    state = {"used": False, "review_seen": False}

    def call(*args, **kwargs):
        phase = kwargs.get("phase")
        task = kwargs.get("console_todo_id")
        if not state["used"]:
            if (phase != "auftrag" or task != evidence.task_id
                    or Path(kwargs.get("cwd", "/")).resolve() != evidence.workdir
                    or kwargs.get("prompt") != evidence.prompt):
                raise RecoveryRefused("First attempted model call differs from the archived production task; refusing any model call.")
            state["used"] = True
            # A legacy call-budget reservation can be accounted for by AutoBuild,
            # but NO new Codex production process/request is made.
            print(f"[recovery] Reused verified completed production of ToDo {evidence.task_id}; reviewer runs normally.", flush=True)
            return transport.RunResult(
                assistant_messages=[evidence.answer], turn_completed=True,
                process_exit_code=0, capture_dir=evidence.capture_dir,
                stream_diagnostics=[{"kind": "codex_reconnect", "event_index":i, "event":dict(ev)}
                                    for i, ev in evidence.notices],
            )
        if (phase != "review" or task != evidence.task_id or state["review_seen"]
                or kwargs.get("sandbox") != "read-only"
                or Path(kwargs.get("cwd", "/")).resolve() != evidence.workdir):
            raise RecoveryRefused("Only one independent read-only review of this task is permitted.")
        state["review_seen"] = True
        return prior(*args, **kwargs)

    autobuild_module.run_codex_exec_json = call
    return state


@contextmanager
def _review_only_guards(evidence: RecoveryEvidence, state: dict):
    """Refuse preflight/Decide/parallel-worker escapes from the injected call."""
    import run_todos
    previous_execute = transport.execute
    previous_worker = run_todos.TodoRunner._autobuild_python_attempt

    def execute(request):
        if (not state["used"] or not state["review_seen"] or request.phase != "review"
                or request.console_todo_id != evidence.task_id or request.sandbox != "read-only"
                or request.cwd.resolve() != evidence.workdir):
            raise RecoveryRefused("Review recovery forbids any other model execution.")
        return previous_execute(request)

    def worker(*args, **kwargs):
        raise RecoveryRefused("Parallel-worker recovery is unsupported; no worker or production was started.")

    transport.execute = execute
    run_todos.TodoRunner._autobuild_python_attempt = worker
    try:
        yield
    finally:
        transport.execute = previous_execute
        run_todos.TodoRunner._autobuild_python_attempt = previous_worker


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = None
    if args[:1] != ["resume-review"]:
        print("Use: arquilo tasklist resume-review --help", file=sys.stderr)
        return 2
    if args[1:] in (["-h"], ["--help"]):
        print(__doc__ or "Resume review from a completed archived production.")
        return 0
    if args[:1] == ["resume-review"]:
        if "--" not in args:
            print("Recovery requires '--' before the original tasklist run arguments.", file=sys.stderr)
            return 2
        sep = args.index("--")
        ap = argparse.ArgumentParser(description="One explicit production-to-review continuation", allow_abbrev=False)
        ap.add_argument("--check-only", action="store_true")
        ap.add_argument("--todo", required=True)
        ap.add_argument("--capture-dir", type=Path, required=True)
        opt = ap.parse_args(args[1:sep])
        args = args[sep + 1:]
        try:
            work = _validate_recovery_argv(args, opt.todo)
            state_options = [token for token in args if token == "--state-dir" or token.startswith("--state-dir=")]
            state_root = Path(_value(args, "--state-dir")).expanduser() if state_options else None
            evidence = load_verified_recovery(opt.capture_dir, work, opt.todo,
                todo_file=Path(_value(args, "--todo-file")), state_root=state_root)
        except (RecoveryRefused, OSError, ValueError) as exc:
            print("[recovery] Refused BEFORE model calls: " + str(exc), file=sys.stderr)
            return 125
        print("[recovery] Verified archived input bytes, original task contract, terminal success, final answer and transient-only diagnostics.", flush=True)
        print("[recovery] Original files unchanged; independent read-only review is still mandatory.", flush=True)
        print(f"[recovery] Verified {len(evidence.notices)} recovered reconnect notices; no production replay.", flush=True)
        if opt.check_only:
            print("[recovery] Check-only: no writes or model calls; current plan/prompt gates still apply at review start.", flush=True)
            return 0
        # No workspace-write capability probe in a review-only invocation. The
        # review transport still performs its normal launcher/protocol checks.
        if "--skip-backend-preflight" not in args:
            args.append("--skip-backend-preflight")
    import autobuild  # import after validation
    import arquilo
    previous_call = autobuild.run_codex_exec_json
    state = install_review_injection(evidence, autobuild) if evidence else None
    try:
        with _review_only_guards(evidence, state):
            result = int(arquilo.main(args))
    except RecoveryRefused as exc:
        print("[recovery] Refused: " + str(exc), file=sys.stderr)
        return 125
    finally:
        autobuild.run_codex_exec_json = previous_call
    if state is not None and (not state["used"] or not state["review_seen"]):
        print("[recovery] Review did not start. Inspect fresh run logs; no DONE should be inferred.", file=sys.stderr)
        return result if result != 0 else 125
    return result


if __name__ == "__main__":
    raise SystemExit(main())
