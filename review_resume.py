# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Opt-in, evidence-checked review continuation without production replay.

CLI: arquilo tasklist resume-review --todo ID --capture-dir PATH --
     tasklist run --workdir WORK --todo-file TASKS --start ID --stop ID
     --max-steps 1 --max-retries 1 --breakdown-policy off

Only one thoroughly validated, fully captured Codex production success can
be substituted once for the otherwise repeatable production call. The normal
mandatory read-only review and controller acceptance gates are never bypassed.
Archived workspace files are untrusted; operator confirmation is required.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import codex_transport as transport

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


def _regular_file(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise RecoveryRefused("Required archive file missing, linked or larger than safety limit.")
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)
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


def load_verified_recovery(capture_dir: Path, workdir: Path, task_id: str) -> RecoveryEvidence:
    """Read only the *exact* original closed capture, without modifying it.

    Captures reside in model-writeable log space, not an immutable trusted source.
    Therefore recovery is explicit operator opt-in AND retains the mandatory
    independent review before DONE. No automatic replay, no completion inference
    solely from the workspace summary.
    """
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", task_id):
        raise RecoveryRefused("Invalid task ID.")
    workspace = workdir.expanduser().resolve(strict=True)
    if any(p.is_symlink() for p in (capture_dir, *capture_dir.parents)):
        raise RecoveryRefused("Capture location contains a symlink.")
    capture = capture_dir.expanduser().resolve(strict=True)
    logs = workspace / ".codex_runs" / "run_todos"
    try:
        relative = capture.relative_to(logs)
    except ValueError as exc:
        raise RecoveryRefused("Capture is outside this workspace's historical run logs.") from exc
    # Expected .../run_todos/<UTC run>/task-2/001-production.
    if len(relative.parts) != 3 or relative.parts[1] != "task-" + task_id or not re.fullmatch(
            r"[0-9]{3}-production", relative.parts[2]):
        raise RecoveryRefused("Capture is not the selected task's production attempt.")
    original = capture.parent
    names = {"capture": capture / "capture.json", "stdout": capture / "stdout.bin",
             "response": capture / "response.txt", "prompt": original / "prompt.md",
             "request": capture / "prompt.utf8", "contract": original / "original_contract.json",
             "summary": original / "autobuild_summary.json"}
    limits = {"capture": 8 << 20, "stdout": 512 << 20, "response": 32 << 20,
              "prompt": 8 << 20, "request": 24 << 20, "contract": 12 << 20, "summary": 16 << 20}
    raw = {name: _regular_file(path, limits[name]) for name, path in names.items()}
    info = _safe_json(raw["capture"])
    contract = _safe_json(raw["contract"])
    summary = _safe_json(raw["summary"])
    if not isinstance(info, dict) or not isinstance(contract, dict) or not isinstance(summary, dict):
        raise RecoveryRefused("Capture metadata or task contract is not an object.")
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
            summary.get("completed") is not False):
        raise RecoveryRefused("Original AutoBuild summary does not confirm a pre-review false failure.")
    terminal = summary.get("terminal_attempt")
    if (not isinstance(terminal, dict) or terminal.get("phase") != "task" or
            terminal.get("index") != 1 or
            Path(terminal.get("capture_directory") or "/").resolve() != capture):
        raise RecoveryRefused("Original AutoBuild summary references another execution attempt.")
    for channel in ("stdout", "stderr", "stdin"):
        if not isinstance(info.get(channel), dict) or info[channel].get("complete") is not True:
            raise RecoveryRefused("Archived Codex input/output was not completely captured.")
    stdin = info["stdin"]
    if any(type(stdin.get(field)) is not int or stdin[field] != len(raw["request"])
           for field in ("expected_bytes", "archived_bytes", "written_bytes")):
        raise RecoveryRefused("The recorded production input stream is not complete.")
    if (info["stdout"].get("archived_bytes") != len(raw["stdout"])
            or info["stdout"].get("received_bytes") != len(raw["stdout"])):
        raise RecoveryRefused("The recorded production output stream is not complete.")
    try:
        prompt = raw["request"].decode("utf-8")
        original_prompt = raw["prompt"].decode("utf-8")
        answer = raw["response"].decode("utf-8").strip()
    except UnicodeError as exc:
        raise RecoveryRefused("Archived prompt/answer are not UTF-8.") from exc
    if not prompt.strip() or not answer or contract.get("original_request") != prompt or original_prompt != prompt:
        raise RecoveryRefused("Original task contract, prompt and answer are inconsistent.")
    notice_events = []
    stream_errors = []
    last_answer = None
    completion = 0
    for index, line in enumerate(raw["stdout"].splitlines(), 1):
        if len(line) > (16 << 20):
            raise RecoveryRefused("An archived event exceeds the safe per-event size.")
        if not line.strip():
            continue
        event = _safe_json(line)
        if not isinstance(event, dict):
            raise RecoveryRefused("Archived event is not a JSON object.")
        if event.get("type") == "turn.failed":
            raise RecoveryRefused("A real turn.failed occurred; cannot resume review.")
        if event.get("type") == "turn.completed":
            completion += 1
        elif completion and event.get("type") in ("turn.started", "item.started", "item.updated"):
            raise RecoveryRefused("Archive contains new production activity after the terminal event.")
        if event.get("type") == "error":
            if not transport.is_transient_reconnect(event, terminal_seen=completion > 0):
                raise RecoveryRefused("Unknown or post-terminal stream error; cannot resume review.")
            notice_events.append((index, event))
            stream_errors.append(event)
        text = _final_text(event)
        if text:
            last_answer = text
    if completion != 1 or not last_answer or last_answer != answer:
        raise RecoveryRefused("Final assistant message/turn.completed and archived response do not match.")
    archived_errors = info.get("stream_errors")
    if (not isinstance(archived_errors, list) or not archived_errors
            or archived_errors != stream_errors):
        raise RecoveryRefused("Original archive does not contain exactly the observed retry notices.")
    if info.get("stream_diagnostics") not in (None, []):
        # Cannot assume unrelated diagnostics are harmless or complete.
        raise RecoveryRefused("Additional archive diagnostics require manual investigation.")
    digests = {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}
    return RecoveryEvidence(capture, task_id, workspace, prompt, answer, tuple(notice_events), digests)


def _value(argv: list[str], name: str) -> str:
    if argv.count(name) != 1:
        raise RecoveryRefused("Review recovery requires exactly one " + name + ".")
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise RecoveryRefused("Value missing for " + name + ".")
    return argv[i + 1]


def _validate_recovery_argv(argv: list[str], todo: str) -> Path:
    if argv[:2] != ["tasklist", "run"]:
        raise RecoveryRefused("Use 'tasklist run' for a native controller review.")
    if (_value(argv, "--start") != todo or _value(argv, "--stop") != todo
            or _value(argv, "--max-steps") != "1" or _value(argv, "--max-retries") != "1"
            or _value(argv, "--breakdown-policy") != "off"):
        raise RecoveryRefused("Recovery must be bounded to one task and one review without automatic fixes/breakdown.")
    for banned in ("--dry-run", "--allow-todo-modifications", "--git", "--git-push",
                   "--accept-plan-changes", "--todo-template"):
        if banned in argv:
            raise RecoveryRefused("Recovery refuses plan/git/dry-run changes or plan adoption.")
    work = Path(_value(argv, "--workdir")).expanduser().resolve(strict=True)
    if not Path(_value(argv, "--todo-file")).is_file():
        # May legitimately be workdir-relative; resolve against current process directory.
        if not (Path.cwd() / _value(argv, "--todo-file")).is_file():
            raise RecoveryRefused("Selected task list is unavailable.")
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
        if phase == "auftrag" and task == evidence.task_id:
            raise RecoveryRefused("A second production attempt is prohibited in review recovery.")
        if phase == "review" and task == evidence.task_id:
            state["review_seen"] = True
        return prior(*args, **kwargs)

    autobuild_module.run_codex_exec_json = call
    return state


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
        ap = argparse.ArgumentParser(description="One explicit production-to-review continuation")
        ap.add_argument("--todo", required=True)
        ap.add_argument("--capture-dir", type=Path, required=True)
        opt = ap.parse_args(args[1:sep])
        args = args[sep + 1:]
        try:
            work = _validate_recovery_argv(args, opt.todo)
            evidence = load_verified_recovery(opt.capture_dir, work, opt.todo)
        except (RecoveryRefused, OSError, ValueError) as exc:
            print("[recovery] Refused BEFORE model calls: " + str(exc), file=sys.stderr)
            return 125
        print("[recovery] Verified archived input bytes, original task contract, terminal success, final answer and transient-only diagnostics.", flush=True)
        print("[recovery] Original files unchanged; independent read-only review is still mandatory.", flush=True)
    import autobuild  # import after validation
    import arquilo
    previous_call = autobuild.run_codex_exec_json
    state = install_review_injection(evidence, autobuild) if evidence else None
    try:
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
