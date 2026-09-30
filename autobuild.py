#!/usr/bin/env python3
# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
# -*- coding: utf-8 -*-
"""
autobuild.py — Runner für Codex CLI (JSONL-Streaming, non-interactive)
- Startet `codex exec --json` im gewünschten Workspace
- Liest JSONL-Events zuverlässig von stdout
- Schreibt Roh- und schönes Log
- Extrahiert finale assistant_message als Endantwort
- Sammelt ausgeführte Kommandos & File-Änderungen
- Optional Auto-Continue über erkannte "Next steps"

Erfordert: Codex CLI im PATH, Login bereits erfolgt.
"""

from __future__ import annotations
import safe_io
from controller_state import state_directory

ARQUILO_DIRECT_REPAIR_REVIEW_CONTRACT_VERSION = 1

import argparse
from runtime_config import (
    CODEX_REASONING_EFFORT_CHOICES,
    resolve_model as _resolve_codex_model,
    resolve_reasoning_effort as _resolve_codex_reasoning_effort,
)
from review_contract import (
    DEFAULT_CONTRACT_REVIEW_POLICY_RULES, build_review_prompt, build_fix_prompt,
    parse_review_classification, review_classification_passes,
    review_requires_runner_handling, build_review_context_reference,
)
import codex_transport
from runtime_config import environment_value, transport_timeout_values
import codex_policy
from codex_transport import (
    ts,
    _normalize_console_todo_id,
    _console_prefix,
    _inject_console_todo_prefix,
    append,
    CommandExec,
    FileChange,
    RunResult,
    CodexExecutionError,
    _terminate_process_group,
)
from runtime_failure import execution_error, failure_exit_code, EXIT_INCOMPLETE
from autobuild_contract import (AutoBuildOptions, AutoBuildContext, call_payload, decode_call,
                                core_status, validate_result, strict_object, AutoBuildResultError)
from decision_request import (
    DecisionInputError, TaskSnapshot, completion_request, read_input_text, snapshot_todo,
)
from decision_exec import DecisionCall, DecisionExecSettings
from runtime_contracts import DecisionResult as ValidatedDecisionResult, ExecutionStatus
import json
import os
import posixpath
from runtime_files import atomic_write_text, native_path, read_utf8, unique_directory
import re
import shlex
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
)
from uuid import uuid4
from execution_budget import CallBudget, BudgetExhausted, DEFAULT_MAX_CALLS
from removed_features import reject_removed_options, check_removed_environment, SERVICE_MIGRATION
from todo_ids import extract_todo_id
from runtime_profile import (
    ARQUILO_CODEX_MODEL_ENV,
    ARQUILO_CODEX_REASONING_EFFORT_ENV,
    RuntimeProfileError,
    load_runtime_profile,
)


try:
    from decide import run_decision as run_semantic_decision
except ImportError as exc:  # Report when a semantic choice is actually required.
    run_semantic_decision = None
    _DECISION_IMPORT_ERROR = str(exc)
else:
    _DECISION_IMPORT_ERROR = None

CODEX_MODEL_ENV = ARQUILO_CODEX_MODEL_ENV
CODEX_REASONING_EFFORT_ENV = ARQUILO_CODEX_REASONING_EFFORT_ENV

CODEX_INVOCATION_OVERRIDE_CONTRACT_VERSION = 1
SUMMARY_SCHEMA_VERSION = "mpa.autobuild.summary.v1"
ARQUILO_AUTOBUILD_LIFECYCLE_CONTRACT_VERSION = 1
AUTOBUILD_REVIEW_CONTRACT_VERSION = 4
AUTOBUILD_FINAL_FAILURE_CONTRACT_VERSION = 1
AUTOBUILD_PARENT_REVIEW_CONTRACT_VERSION = 1
AUTOBUILD_REVIEW_POLICY_CONTRACT_VERSION = 1


def _prompt_redaction_placeholder(prompt: str) -> str:
    return "<prompt redacted>"


_PROMPT_SENSITIVE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:+={}\-@]{6,}")
_PROMPT_SECRET_MARKER_RE = re.compile(
    r"(secret|token|pass(word|wd)?|api[_-]?key|private|credential|bearer|sk-)",
    re.IGNORECASE,
)


def _redacted_codex_exec_command(command: Sequence[str], prompt: str) -> str:
    redacted = list(command)
    if redacted and redacted[-1] == prompt:
        redacted[-1] = _prompt_redaction_placeholder(prompt)
    return shlex.join(redacted)


def _json_string_payload(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _prompt_sensitive_fragments(prompt: str) -> List[str]:
    fragments: List[str] = []
    seen: set[str] = set()

    def add(fragment: str) -> None:
        if fragment and fragment not in seen:
            seen.add(fragment)
            fragments.append(fragment)

    for match in _PROMPT_SENSITIVE_TOKEN_RE.finditer(prompt):
        token = match.group(0).strip(".,;:!?()[]{}<>\"'")
        if not token:
            continue
        has_secret_marker = bool(_PROMPT_SECRET_MARKER_RE.search(token))
        looks_high_entropy = (
            len(token) >= 24
            and not token.isalpha()
            and any(ch.isdigit() for ch in token)
        )
        if not has_secret_marker and not looks_high_entropy:
            continue
        add(token)
        add(_json_string_payload(token))

    fragments.sort(key=len, reverse=True)
    return fragments


def _redact_prompt_text(text: str, prompt: str) -> str:
    if not prompt:
        return text
    redacted = text
    placeholder = _prompt_redaction_placeholder(prompt)
    for prompt_variant in {prompt, _json_string_payload(prompt)}:
        if prompt_variant:
            redacted = redacted.replace(prompt_variant, placeholder)
    for fragment in _prompt_sensitive_fragments(prompt):
        redacted = redacted.replace(fragment, "<prompt fragment redacted>")
    return redacted


def _codex_reasoning_config_value(reasoning_effort: str) -> str:
    return f"model_reasoning_effort={reasoning_effort}"


class RequiredDecisionError(RuntimeError):
    """A required semantic decision failed; no semantic option is available."""

    def __init__(self, code: str, message: str, call: Optional[DecisionCall] = None):
        self.code, self.call = code, call
        super().__init__(message)


class ProcessStopActiveError(RuntimeError):
    """Raised when a process_stop-Sentinel blockiert den Lauf."""


def _decision_model() -> Optional[str]:
    return environment_value("ARQUILO_DECISION_MODEL")


def _decision_system_prompt() -> str:
    return environment_value("ARQUILO_DECISION_SYSTEM_PROMPT") or _DEFAULT_DECISION_SYSTEM_PROMPT


# ------------------ Utility / Logging ------------------


def _expected_todo_result_filename(todo_identifier: Optional[str]) -> Optional[str]:
    """Return the deterministic `todo_result_<base>.md` filename for one todo."""

    todo_id = extract_todo_id(todo_identifier)
    if not isinstance(todo_id, str):
        return None
    base_segment = todo_id.split(".", 1)[0].strip()
    if not base_segment:
        return None
    return f"todo_result_{base_segment}.md"


def write_text(path: Path, text: str) -> None:
    atomic_write_text(path, text)


def _terminal_beep(count: int) -> None:
    """Emit a terminal bell without failing the run if the write is blocked."""
    try:
        sys.stdout.write("\a" * count)
        sys.stdout.flush()
    except Exception:
        return


# ------------------ Data structures ------------------


@dataclass
class AutoBuildSummary:
    last_answer: str
    completed: bool
    auftrag_runs: int
    review_runs: int
    workspace: Path
    pretty_log: Path
    raw_log: Path
    readonly_result_path: Optional[Path]
    run_history: List[RunResult] = field(default_factory=list)
    review_history: List[RunResult] = field(default_factory=list)
    summary_json_path: Optional[Path] = None
    process_stop_triggered: bool = False
    process_stop_details: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    review_findings: Optional[str] = None
    review_classification: Optional[Dict[str, Any]] = None
    execution_error: Optional[Dict[str, Any]] = None
    review_required: bool = True
    call_budget: Optional[Dict[str, Any]] = None
    budget_exhausted: Optional[Dict[str, Any]] = None


def run_result_error(result: RunResult, phase: str) -> Optional[Dict[str, Any]]:
    """Also honour error signals from custom runners / test doubles."""
    if isinstance(result.execution_error, dict):
        return {**result.execution_error, "phase": phase}
    if result.turn_failed or result.stream_errors:
        return execution_error(
            json.dumps(result.turn_failed or result.stream_errors, ensure_ascii=False),
            code="codex_turn_failed", phase=phase,
            process_exit_code=result.process_exit_code,
        )
    return None


def summary_exit_code(summary: AutoBuildSummary) -> int:
    if isinstance(summary.execution_error, dict):
        return failure_exit_code(summary.execution_error)
    if summary.process_stop_triggered:
        return 6
    return 0 if summary.completed is True else EXIT_INCOMPLETE


@dataclass
class DecisionResult:
    is_finished: bool
    selected_option: str
    explanation: str
    source: str
    fallback_used: bool
    error: Optional[str] = None
    archive: Optional[Dict[str, Any]] = None

    @property
    def decision_text(self) -> str:
        return f"{self.selected_option}\n{self.explanation}".strip()


class SummaryCommand(TypedDict):
    source: str
    run_index: int
    command: str
    status: str
    exit_code: Optional[int]
    aggregated_output: str


class SummaryFileChange(TypedDict, total=False):
    source: str
    run_index: int
    path: Optional[str]
    action: Optional[str]
    raw: Dict[str, Any]


class SummaryDocument(TypedDict, total=False):
    schema_version: str
    generated_at: str
    completed: bool
    last_answer: str
    workspace: str
    pretty_log: str
    raw_log: str
    auftrag_runs: int
    review_runs: int
    commands: List[SummaryCommand]
    file_changes: List[SummaryFileChange]
    readonly_result_path: Optional[str]
    process_stop_triggered: bool
    process_stop_details: Optional[str]
    model: str
    reasoning_effort: str
    decision: Dict[str, Any]
    review_findings: Optional[str]
    review_classification: Dict[str, Any]
    execution_error: Optional[Dict[str, Any]]
    exit_code: int
    status: str
    review_required: bool


def _normalize_command_entry(
    cmd: CommandExec, source: str, run_index: int
) -> SummaryCommand:
    entry: SummaryCommand = {
        "source": source,
        "run_index": run_index,
        "command": (cmd.command or "").strip(),
        "status": (cmd.status or "").strip(),
        "exit_code": cmd.exit_code,
        "aggregated_output": (cmd.aggregated_output or "").strip(),
    }
    return entry


def _first_string(value: Any) -> Optional[str]:
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    return candidate
    return None


def _extract_file_change_path(raw: Dict[str, Any]) -> Optional[str]:
    path_candidates = [
        raw.get("path"),
        raw.get("file"),
        raw.get("filepath"),
        raw.get("target"),
        raw.get("destination"),
        raw.get("destination_path"),
        raw.get("dest_path"),
        raw.get("dest"),
        raw.get("source_path"),
        raw.get("old_path"),
        raw.get("new_path"),
    ]

    for key in ("paths", "files", "targets", "destinations"):
        candidate = _first_string(raw.get(key))
        if candidate:
            path_candidates.append(candidate)

    metadata = raw.get("metadata")
    if isinstance(metadata, dict):
        path_candidates.append(metadata.get("path"))
        for key in ("paths", "files", "targets"):
            candidate = _first_string(metadata.get(key))
            if candidate:
                path_candidates.append(candidate)

    details = raw.get("details")
    if isinstance(details, dict):
        path_candidates.append(details.get("path"))
        candidate = _first_string(details.get("paths"))
        if candidate:
            path_candidates.append(candidate)

    for candidate in path_candidates:
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return None


def _extract_file_change_action(raw: Dict[str, Any]) -> Optional[str]:
    for key in ("action", "type", "change_type", "operation"):
        candidate = raw.get(key)
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return None


def _workspace_prefixes(workspace: Optional[Path]) -> List[str]:
    if workspace is None:
        return []
    prefixes: List[str] = []
    seen: set[str] = set()
    candidates = [workspace.expanduser()]
    try:
        resolved = candidates[0].resolve()
        candidates.append(resolved)
    except OSError:
        pass
    for candidate in candidates:
        posix = candidate.as_posix().rstrip("/") or "/"
        if posix not in seen:
            prefixes.append(posix)
            seen.add(posix)
    prefixes.sort(key=len, reverse=True)
    return prefixes


def _looks_like_absolute_path(path: str) -> bool:
    if not path:
        return False
    if path.startswith("/") or path.startswith("\\\\"):
        return True
    if len(path) >= 3 and path[1] == ":":
        return True
    return False


def _normalize_file_change_path_value(
    raw_path: str, workspace_prefixes: Sequence[str]
) -> Optional[str]:
    # Logical summary labels only. Filesystem access uses native pathlib paths;
    # the untouched event remains in SummaryFileChange.raw and raw archives.
    if not isinstance(raw_path, str):
        return None

    candidate = raw_path.strip()
    if not candidate:
        return None

    candidate = os.path.expanduser(candidate)
    candidate = candidate.replace("\\", "/")
    normalized = posixpath.normpath(candidate)

    if workspace_prefixes and _looks_like_absolute_path(normalized):
        for prefix in workspace_prefixes:
            workspace_norm = posixpath.normpath(prefix)
            workspace_prefix = workspace_norm.rstrip("/") + "/"
            if normalized == workspace_norm:
                return "."
            if normalized.startswith(workspace_prefix):
                rel_path = normalized[len(workspace_prefix) :]
                return rel_path or "."

    return normalized


def _normalize_file_change_entry(
    change: FileChange,
    source: str,
    run_index: int,
    workspace_prefixes: Sequence[str],
) -> SummaryFileChange:
    entry: SummaryFileChange = {
        "source": source,
        "run_index": run_index,
        "raw": change.raw,
    }
    path = _extract_file_change_path(change.raw)
    if path is not None:
        normalized = _normalize_file_change_path_value(path, workspace_prefixes)
        if normalized is not None:
            entry["path"] = normalized
    action = _extract_file_change_action(change.raw)
    if action is not None:
        entry["action"] = action
    return entry


def _collect_run_artifacts(
    runs: Sequence[RunResult],
    source: str,
    workspace_prefixes: Sequence[str],
) -> Tuple[List[SummaryCommand], List[SummaryFileChange]]:
    commands: List[SummaryCommand] = []
    file_changes: List[SummaryFileChange] = []
    for index, run in enumerate(runs, 1):
        for cmd in run.commands:
            commands.append(_normalize_command_entry(cmd, source, index))
        for change in run.file_changes:
            file_changes.append(
                _normalize_file_change_entry(change, source, index, workspace_prefixes)
            )
    return commands, file_changes


def _deduplicate_and_sort_file_changes(
    entries: List[SummaryFileChange],
) -> List[SummaryFileChange]:
    unique: Dict[str, SummaryFileChange] = {}
    without_path: List[SummaryFileChange] = []
    for entry in entries:
        path = entry.get("path")
        if path:
            key = path.casefold()
            if key not in unique:
                unique[key] = entry
        else:
            without_path.append(entry)

    ordered = [unique[key] for key in sorted(unique.keys())]
    ordered.extend(without_path)
    return ordered


def build_summary_document(summary: AutoBuildSummary) -> SummaryDocument:
    """Create a JSON serialisable payload that fulfils the MVP summary schema."""

    commands: List[SummaryCommand] = []
    file_changes: List[SummaryFileChange] = []

    workspace_prefixes = _workspace_prefixes(summary.workspace)

    for origin, runs in (
        ("auftrag", summary.run_history),
        ("review", summary.review_history),
    ):
        run_cmds, run_changes = _collect_run_artifacts(runs, origin, workspace_prefixes)
        commands.extend(run_cmds)
        file_changes.extend(run_changes)
    file_changes = _deduplicate_and_sort_file_changes(file_changes)

    readonly_path = (
        str(summary.readonly_result_path)
        if summary.readonly_result_path is not None
        else None
    )

    payload: SummaryDocument = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "completed": bool(summary.completed),
        "last_answer": summary.last_answer,
        "auftrag_runs": summary.auftrag_runs,
        "review_runs": summary.review_runs,
        "workspace": str(summary.workspace),
        "pretty_log": str(summary.pretty_log),
        "raw_log": str(summary.raw_log),
        "commands": commands,
        "file_changes": file_changes,
    }
    payload["execution_error"] = summary.execution_error
    payload["exit_code"] = summary_exit_code(summary)
    payload["status"] = core_status(payload["exit_code"])
    payload["review_required"] = summary.review_required
    payload["call_budget"] = summary.call_budget
    payload["budget_exhausted"] = summary.budget_exhausted
    if summary.execution_error or summary.process_stop_triggered:
        payload["completed"] = False
    payload["execution_attempts"] = [
        {"phase": phase, "index": index, "turn_completed": run.turn_completed,
         "turn_failed": run.turn_failed, "process_exit_code": run.process_exit_code,
         "execution_error": run.execution_error, "post_turn_cleanup": run.post_turn_cleanup}
        for phase, history in (("task", summary.run_history), ("review", summary.review_history))
        for index, run in enumerate(history, start=1)
    ]
    payload["readonly_result_path"] = readonly_path
    payload["process_stop_triggered"] = bool(summary.process_stop_triggered)
    payload["process_stop_details"] = summary.process_stop_details
    payload["review_findings"] = summary.review_findings
    payload["review_contract_version"] = AUTOBUILD_REVIEW_CONTRACT_VERSION
    payload["final_failure_contract_version"] = AUTOBUILD_FINAL_FAILURE_CONTRACT_VERSION
    payload["parent_review_contract_version"] = AUTOBUILD_PARENT_REVIEW_CONTRACT_VERSION
    if isinstance(summary.review_classification, dict):
        payload["review_classification"] = dict(summary.review_classification)
    if summary.model:
        payload["model"] = summary.model
    if summary.reasoning_effort:
        payload["reasoning_effort"] = summary.reasoning_effort

    if summary.decision is not None:
        payload["decision"] = dict(summary.decision)
    return payload


def write_summary_json(summary: AutoBuildSummary, output_path: Path) -> Path:
    """Persist a structured summary document to disk."""

    document = build_summary_document(summary)
    atomic_write_text(output_path, json.dumps(document, indent=2, ensure_ascii=False))
    return output_path


# ------------------ Workspace setup ------------------


def setup_workspace(
    workdir: Optional[Path], single_file: Optional[Path]
) -> Tuple[Path, Optional[Path]]:
    if single_file:
        single_file = native_path(single_file, label="single_file")
        if not single_file.exists():
            raise FileNotFoundError(f"--file nicht gefunden: {single_file}")
        base = Path.cwd() / "codex_jobs"
        safe_io.mkdir(base)
        ws = unique_directory(base, prefix=datetime.now().strftime("job_%Y%m%d_%H%M%S"))
        target = ws / single_file.name
        safe_io.write_bytes(target, safe_io.read_bytes(single_file))
        return ws, target
    else:
        assert workdir is not None, "--workdir nötig wenn --file fehlt"
        workdir = native_path(workdir, label="workdir")
        safe_io.mkdir(workdir)
        return workdir, None


# ------------------ JSON line handling ------------------


def handle_event(
    ev: Dict[str, Any],
    acc: RunResult,
    pretty_log: Path,
    raw_log: Path,
    verbose: bool = False,
    console_todo_id: Optional[str] = None,
    pretty_log_redactor: Optional[Callable[[str], str]] = None,
    raw_log_redactor: Optional[Callable[[str], str]] = None,
) -> None:
    """Retain the public logging seam while sharing the event parser."""
    codex_transport.handle_event(
        ev, acc, pretty_log, raw_log, verbose, console_todo_id,
        pretty_log_redactor, raw_log_redactor, timestamp=ts,
    )


class ProcessStopMonitor(codex_transport.ProcessStopMonitor):
    """Compatibility name retaining AutoBuild's injectable timestamp function."""

    def __init__(self, path: Path, pretty_log: Path, console_todo_id: Optional[str] = None) -> None:
        super().__init__(path, pretty_log, console_todo_id, timestamp=lambda: ts())


# ------------------ Run codex exec --json ------------------


def run_codex_exec_json(
    prompt: str,
    cwd: Path,
    *,
    sandbox: Optional[str],
    output_last_message_path: Optional[Path],
    raw_log: Path,
    pretty_log: Path,
    extra_args: List[str],
    verbose: bool = False,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    process_stop_path: Optional[Path] = None,
    console_todo_id: Optional[str] = None,
    network_access: bool = False,
    output_schema_path: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeouts: Optional[codex_transport.TransportTimeouts] = None,
    cancel_requested: Optional[Callable[[], Optional[str]]] = None,
    phase: str = "execution",
    config_profile: Optional[str] = None,
) -> RunResult:
    """Compatibility adapter; process state belongs to codex_transport.execute."""
    request = codex_transport.CodexExecRequest(
        prompt=prompt, cwd=cwd, sandbox=sandbox,
        output_last_message=output_last_message_path, output_schema=output_schema_path,
        raw_log=raw_log, pretty_log=pretty_log, extra_args=tuple(extra_args),
        verbose=verbose, model=model, reasoning_effort=reasoning_effort,
        network_access=network_access, env=dict(os.environ) if env is None else env,
        config_profile=config_profile,
        process_stop_path=process_stop_path, cancel_requested=cancel_requested,
        console_todo_id=console_todo_id, phase=phase,
        timeouts=timeouts if timeouts is not None else codex_transport.TransportTimeouts(
            **transport_timeout_values(environ=env),
        ),
        log_redactor=lambda value: _redact_prompt_text(value, prompt),
        prompt_display=_prompt_redaction_placeholder(prompt),
    )
    result = codex_transport.execute(request)
    if result.trace.execution_error is not None:
        raise CodexExecutionError(result.trace, result.trace.execution_error)
    return result.trace


# ------------------ Next steps parsing (aus Endantwort) ------------------

NEXT_STEPS_RE = re.compile(
    r"(?:^|\n)\s*(?:Nächste Schritte|Next steps)\s*:?\s*\n(.+)",
    re.IGNORECASE | re.DOTALL,
)


def parse_next_steps(text: str) -> List[str]:
    m = NEXT_STEPS_RE.search(text)
    if not m:
        return []
    tail = m.group(1)
    steps = []
    for ln in tail.splitlines():
        s = ln.strip(" -*•\t")
        if not s:
            continue
        # heuristischer Abbruch bei neuer Überschrift
        if re.match(r"^[A-ZÄÖÜ].{0,40}:$", s):
            break
        steps.append(s)
    return steps[:10]


def _runtime_profile_review_policy_rules(
    task_text: str,
) -> Optional[Tuple[str, ...]]:
    """Resolve additive review rules for direct/worker AutoBuild invocations.

    run_todos passes the selected rules explicitly.  Standalone and worker
    AutoBuild executions instead consume the same neutral runtime-profile
    environment contract, keeping adapter behavior consistent across both
    public entry paths without teaching AutoBuild about any domain.
    """

    try:
        profile = load_runtime_profile()
    except RuntimeProfileError as exc:
        raise ValueError(str(exc)) from exc
    if not profile.is_active_for_text(task_text):
        return None
    return profile.autobuild_review_rules or None


def _build_global_review_prompt(
    *,
    original_task: str,
    latest_answer: str,
    review_policy_rules: Optional[Sequence[str]] = None,
    contract_path: Optional[Path] = None,
    contract_text: Optional[str] = None,
) -> str:
    return build_review_prompt(
        original_task,
        latest_answer,
        review_policy_rules=review_policy_rules,
    ) + (
        build_review_context_reference(str(contract_path), contract_text=contract_text)
        if contract_path is not None else ""
    )


_DEFAULT_DECISION_SYSTEM_PROMPT = (
    "You are a contract-bound evaluator. Select INCOMPLETE only when the reviewer "
    "identifies at least one unresolved blocking issue against an explicit requirement "
    "or acceptance criterion. Non-blocking observations, optional improvements, risks, "
    "and theoretical refinements do not prevent COMPLETE."
)


def _decision_archive_payload(call: DecisionCall) -> Dict[str, Any]:
    """Link the summary to all retained attempts, including technical failures."""
    request = call.request
    return {
        "directory": str(call.directory) if call.directory is not None else None,
        "identity": ({name: getattr(request, name) for name in
                      ("run_id", "task_id", "phase", "attempt_id")} if request is not None else None),
        "result": asdict(call.result),
        "attempts": [{
            "directory": str(row.directory) if row.directory is not None else None,
            "workdir": str(row.attempt.cwd) if row.attempt is not None else None,
            "archive_complete": row.archive_complete,
            "archive_error": row.archive_error,
            "result": asdict(row.result),
        } for row in call.attempts],
    }


def evaluate_completion_decision(
    original_task: str,
    latest_answer: str,
    review_findings: str,
    *,
    task_snapshot: Optional[TaskSnapshot] = None,
    run_id: Optional[str] = None,
    task_id: str = "standalone",
    phase: str = "completion",
    attempt_id: str = "1",
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    settings: Optional[DecisionExecSettings] = None,
    pretty_log: Optional[Path] = None,
) -> DecisionResult:
    """Deterministic structured reviews; explicit evidence for semantic choices.

    Direct callers without a snapshot declare original_task to be concrete
    inline task text. Runner calls must supply their captured ToDo snapshot.
    Input and execution errors propagate; they never become semantic choices.
    """

    classification = parse_review_classification(review_findings)
    if classification.get("valid") is False:
        return DecisionResult(False, "INCOMPLETE", classification["short_summary"],
                              "invalid_review", False, error="invalid_review")
    snapshot = task_snapshot if task_snapshot is not None else TaskSnapshot(
        task_text=original_task, preamble="", reference_prompt=original_task,
        attempt_prompt=original_task, source="inline")
    if not isinstance(snapshot, TaskSnapshot):
        raise DecisionInputError("decision_missing_input", "task_snapshot", "Concrete task evidence is required")
    if type(latest_answer) is not str or not latest_answer.strip():
        raise DecisionInputError("decision_missing_input", "latest_answer", "The production answer is required")
    if classification.get("source_format") in {"structured", "json_legacy"}:
        blocking = classification.get("blocking_issues")
        blocking_count = len(blocking) if isinstance(blocking, list) else 0
        return DecisionResult(
            is_finished=blocking_count == 0,
            selected_option="COMPLETE" if blocking_count == 0 else "INCOMPLETE",
            explanation=(
                "Deterministic review-contract decision: no blocking issues remain."
                if blocking_count == 0
                else f"Deterministic review-contract decision: {blocking_count} blocking issue(s) remain."
            ),
            source="review_contract",
            fallback_used=False,
        )

    request = completion_request(
        snapshot,
        latest_answer=latest_answer, review_findings=review_findings,
        run_id=run_id if run_id is not None else f"standalone-{uuid4().hex}",
        task_id=task_id, phase=phase, attempt_id=attempt_id,
        model=model if model is not None else _decision_model(),
        reasoning_effort=reasoning_effort, system_prompt=_decision_system_prompt())
    if pretty_log is not None:
        append(pretty_log, f"[{ts()}] [decision_input] {json.dumps(request.to_dict(), ensure_ascii=False)}\n")
    if run_semantic_decision is None:
        raise RequiredDecisionError("decision_unavailable",
            f"Required Codex decision helper is unavailable: {_DECISION_IMPORT_ERROR or 'missing callable'}")
    try:
        call = run_semantic_decision(request, settings=settings)
    except DecisionInputError:
        raise
    except KeyboardInterrupt as exc:
        raise RequiredDecisionError("decision_cancelled", "KeyboardInterrupt in required decision") from exc
    except Exception as exc:
        raise RequiredDecisionError("decision_execution_failed", f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(call, DecisionCall) or not isinstance(call.result, ValidatedDecisionResult):
        raise RequiredDecisionError("decision_invalid_result", "Decision helper did not return DecisionCall")
    if not call.result.valid:
        execution = call.result.execution
        failure = call.result.failure or (execution.failure if execution is not None else None)
        code = failure.code if failure is not None else "decision_cancelled"
        message = failure.message if failure is not None else (
            execution.cancellation_reason if execution is not None else "No execution result")
        raise RequiredDecisionError(code, message, call)
    try:
        selected_option = request.selected_option(call.result)
    except DecisionInputError as exc:
        raise RequiredDecisionError("decision_invalid_result", str(exc), call) from exc

    return DecisionResult(
        is_finished=selected_option == "COMPLETE",
        selected_option=selected_option,
        explanation=call.result.explanation,
        source="codex_exec",
        fallback_used=False,
        archive=_decision_archive_payload(call),
    )


def start(
    task: Optional[str] = None,
    *,
    task_file: Optional[Union[str, Path]] = None,
    workdir: Optional[Union[str, Path]] = None,
    file: Optional[Union[str, Path]] = None,
    options: Optional[AutoBuildOptions] = None,
    context: Optional[AutoBuildContext] = None,
    decision_settings: Optional[DecisionExecSettings] = None,
    **removed_options: Any,
) -> AutoBuildSummary:
    """Run one task with mandatory review and bounded, review-directed continuation.

    Core options/context replace flat feature flags. Removed parameters are
    accepted only for migration errors, before any workspace or model access.
    """
    try:
        reject_removed_options(removed_options, source="autobuild.start")
    except ValueError as exc:
        raise TypeError(str(exc)) from exc
    check_removed_environment()
    options = options if options is not None else AutoBuildOptions()
    context = context if context is not None else AutoBuildContext()
    if not isinstance(options, AutoBuildOptions) or not isinstance(context, AutoBuildContext):
        raise ValueError("AutoBuild benötigt AutoBuildOptions und AutoBuildContext.")
    # Revalidate at the execution boundary, including objects changed after
    # construction; reject before reading task files or setting up a workspace.
    options.__post_init__()
    sandbox, network_access = options.sandbox, options.network_access
    config_profile = options.config_profile
    base_extra_args = list(options.extra_arg)
    model, reasoning_effort = options.model, options.reasoning_effort
    logfile, rawlog, summary_json = options.logfile, options.rawlog, options.summary_json
    process_stop_path = options.process_stop_path
    max_steps, auto_continue = options.max_steps, options.auto_continue
    print_end_answer, verbose = options.print_end_answer, options.verbose
    todo_identifier, decision_todo_file = context.todo_identifier, context.decision_todo_file
    decision_run_id, decision_attempt_id = context.decision_run_id, context.decision_attempt_id
    decision_phase, review_policy_rules = context.decision_phase, context.review_policy_rules
    if (task is None) == (task_file is None):
        raise ValueError(
            "Entweder 'task' oder 'task_file' angeben (genau eines erforderlich)."
        )
    if (workdir is None) == (file is None):
        raise ValueError(
            "Entweder 'workdir' oder 'file' angeben (genau eines erforderlich)."
        )
    model = _resolve_codex_model(model)
    reasoning_effort = _resolve_codex_reasoning_effort(reasoning_effort)
    if task is None:
        task_path = native_path(task_file, label="task_file")  # type: ignore[arg-type]
        task_text = read_utf8(task_path).strip()
    else:
        task_text = task.strip()
    if not task_text:
        raise ValueError("Auftragstext darf nicht leer sein.")
    if review_policy_rules is None:
        review_policy_rules = _runtime_profile_review_policy_rules(task_text)

    workdir_path = native_path(workdir, label="workdir") if workdir else None
    single_file = native_path(file, label="file") if file else None

    workspace, _ = setup_workspace(workdir_path, single_file)
    process_stop_full: Optional[Path] = None
    if process_stop_path is not None:
        candidate = safe_io.check_path(workspace / Path(process_stop_path))
        if candidate.exists():
            raise ProcessStopActiveError(
                f"process_stop aktiv unter {candidate}. Lösche die Datei, bevor AutoBuild startet."
            )
        process_stop_full = candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_logs = (unique_directory(workspace / ".codex_runs", prefix=f"run_{stamp}")
                    if logfile is None or rawlog is None else None)
    pretty_log = (
        safe_io.lexical_path(logfile)
        if logfile is not None
        else default_logs / "run.log"
    )
    raw_log = (
        safe_io.lexical_path(rawlog)
        if rawlog is not None
        else default_logs / "run.jsonl"
    )
    summary_json_path = (
        safe_io.lexical_path(summary_json) if summary_json is not None else None
    )

    sys.stdout.write(
        f"[AutoBuild] Logs werden in {pretty_log} und {raw_log} geschrieben.\n"
    )
    if verbose:
        sys.stdout.flush()
    budget_directory = (safe_io.lexical_path(context.budget_directory)
                        if context.budget_directory is not None else unique_directory(
                            state_directory(workspace, workspace / "standalone"), prefix="call_budget"))
    if budget_directory.is_relative_to(workspace):
        raise ValueError("Call budgets must be outside the model-writable workspace")
    call_budget = CallBudget(
        budget_directory,
        options.max_calls, context.budget_root_id or todo_identifier or "standalone",
    )

    def budget_phase(stage: str) -> str:
        return f"{decision_phase}:{stage}"

    def one_run(
        prompt: str,
        sandbox_override: Optional[str] = None,
        *,
        stage: str = "auftrag",
    ) -> RunResult:
        effective_sandbox = (
            sandbox_override if sandbox_override is not None else sandbox
        )
        extra_args = list(base_extra_args)
        try:
            claim = call_budget.consume(todo_identifier or "standalone", budget_phase(stage))
            append(pretty_log, f"[{ts()}] [call_budget] {json.dumps(claim, ensure_ascii=False)}\n")
            return run_codex_exec_json(
                prompt=prompt,
                cwd=workspace,
                sandbox=effective_sandbox,
                output_last_message_path=None,
                raw_log=raw_log,
                pretty_log=pretty_log,
                extra_args=extra_args,
                verbose=verbose,
                model=model,
                reasoning_effort=reasoning_effort,
                process_stop_path=process_stop_full,
                console_todo_id=todo_identifier,
                phase=stage,
                network_access=network_access,
                config_profile=config_profile,
            )
        except CodexExecutionError as exc:
            error = {**exc.error, "phase": stage}
            if stage == "review" and error.get("code") == "codex_missing_answer":
                error = execution_error(error["message"], code="invalid_review", phase=stage,
                                        process_exit_code=error.get("process_exit_code"))
            exc.result.execution_error = error
            return exc.result
        except OSError as exc:
            return RunResult(execution_error=execution_error(
                f"Cannot execute Codex: {exc}", code="codex_launch_failed", phase=stage,
            ))

    readonly_mode = sandbox == "read-only"
    readonly_result_path = None
    readonly_written = False
    if readonly_mode:
        readonly_result_path = pretty_log.parent / f"readonly_result_{stamp}.txt"

    original_task = task_text
    active_decision_run_id = decision_run_id if decision_run_id is not None else f"autobuild-{uuid4().hex}"
    current_prompt = original_task
    auftrag_runs = 0
    review_runs = 0
    max_iterations = max(1, max_steps)
    completed = False
    last_answer = ""
    auftrag_history: List[RunResult] = []
    review_history: List[RunResult] = []
    process_stop_triggered = False
    process_stop_details: Optional[str] = None
    decision_payload: Optional[Dict[str, Any]] = None
    runtime_error: Optional[Dict[str, Any]] = None
    budget_exhausted: Optional[Dict[str, Any]] = None
    latest_review_findings: Optional[str] = None
    latest_review_classification: Optional[Dict[str, Any]] = None
    review_contract_text: Optional[str] = None
    review_contract_path = pretty_log.parent / f"review_contract_{uuid4().hex}.json"

    def _record_decision_payload(decision: DecisionResult) -> None:
        nonlocal decision_payload
        decision_payload = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "selected_option": decision.selected_option,
            "explanation": decision.explanation,
            "source": decision.source,
            "fallback_used": decision.fallback_used,
            "error": decision.error,
        }
        if decision.archive is not None:
            decision_payload["archive"] = decision.archive


    attempt_runs = 0
    while attempt_runs < max_iterations:
        attempt_runs += 1
        decision_payload = None  # A previous choice cannot describe a failed new attempt.
        stage_name = "auftrag" if attempt_runs == 1 else "fix"
        # Capture before this production attempt can edit the shared ToDo file.
        # This changes only Decide evidence, never the production/reference prompt.
        try:
            if decision_todo_file is not None:
                try:
                    snapshot_path = native_path(decision_todo_file, base=workspace, label="decision_todo_file")
                except (TypeError, ValueError, OSError) as exc:
                    raise DecisionInputError("decision_input_unreadable", "decision_todo_file", str(exc)) from exc
                snapshot_id = extract_todo_id(todo_identifier or "")
                if snapshot_id is None:
                    raise DecisionInputError("decision_missing_input", "task_id", "ToDo snapshot requires its exact ID")
                decision_snapshot = snapshot_todo(
                    read_input_text(snapshot_path), task_id=snapshot_id,
                    reference_prompt=original_task, attempt_prompt=current_prompt, source=str(snapshot_path))
            else:
                if context.task_source == "todo":
                    raise DecisionInputError("decision_missing_input", "decision_todo_file", "Runner must supply the concrete ToDo source")
                decision_snapshot = TaskSnapshot(task_text=original_task, preamble="",
                    reference_prompt=original_task, attempt_prompt=current_prompt, source="inline")
            snapshot_payload = {
                "run_id": active_decision_run_id, "task_id": todo_identifier or "standalone",
                "phase": decision_phase, "attempt_id": f"{decision_attempt_id}.{attempt_runs}",
                "task_text": decision_snapshot.task_text, "preamble": decision_snapshot.preamble,
                "reference_prompt": decision_snapshot.reference_prompt,
                "attempt_prompt": decision_snapshot.attempt_prompt, "source": decision_snapshot.source,
            }
            append(pretty_log, f"[{ts()}] [decision_task_snapshot] {json.dumps(snapshot_payload, ensure_ascii=False)}\n")
            if review_contract_text is None:
                # Pin the first task contract through local correction attempts.
                # Decide retains its separate per-attempt evidence contract.
                review_contract_text = json.dumps({
                    "schema_version": "arquilo.review_contract.v1",
                    "original_request": original_task,
                    "task_text": decision_snapshot.task_text,
                    "source": decision_snapshot.source,
                }, ensure_ascii=False, indent=2) + "\n"
        except DecisionInputError as exc:
            runtime_error = execution_error(str(exc), code=exc.code, phase="decide_input")
            runtime_error["input_error"] = exc.to_dict()
            break

        try:
            result = one_run(current_prompt, stage=stage_name)
        except BudgetExhausted as exc:
            budget_exhausted = exc.details
            break
        auftrag_runs += 1
        auftrag_history.append(result)
        runtime_error = run_result_error(result, stage_name)
        if runtime_error:
            last_answer = runtime_error["message"]
            completed = False
            break
        last_answer = result.end_answer

        if result.process_stop_triggered:
            process_stop_triggered = True
            process_stop_details = result.process_stop_details
            note = (
                result.process_stop_details
                or "process_stop-Datei signalisiert manuellen Eingriff."
            )
            append(
                pretty_log,
                f"[{ts()}] [process_stop] Lauf wird beendet: {note}\n",
            )
            completed = False
            last_answer = note
            break

        if readonly_mode and readonly_result_path:
            write_text(readonly_result_path, last_answer)
            if not readonly_written:
                sys.stdout.write(
                    f"[AutoBuild] Read-only result saved to {readonly_result_path}.\n"
                )
                readonly_written = True

        try:
            # Restore from controller memory after production, before the
            # read-only reviewer sees the file. Never reread an edited ToDo.
            write_text(review_contract_path, review_contract_text)
        except (OSError, UnicodeError) as exc:
            runtime_error = execution_error(
                f"Cannot archive original review contract: {exc}",
                code="review_context_failed", phase="review",
            )
            completed = False
            break
        review_prompt = _build_global_review_prompt(
            original_task=original_task,
            latest_answer=last_answer,
            review_policy_rules=review_policy_rules,
            contract_path=review_contract_path,
            contract_text=review_contract_text,
        )
        print("Last answer:", last_answer)
        try:
            review_result = one_run(
                review_prompt,
                sandbox_override="read-only",
                stage="review",
            )
        except BudgetExhausted as exc:
            budget_exhausted = exc.details
            break
        review_runs += 1
        review_history.append(review_result)
        runtime_error = run_result_error(review_result, "review")
        if runtime_error:
            completed = False
            break
        if review_result.process_stop_triggered:
            process_stop_triggered = True
            process_stop_details = review_result.process_stop_details
            note = (
                review_result.process_stop_details
                or "process_stop-Datei signalisiert manuellen Eingriff während der Review."
            )
            append(
                pretty_log,
                f"[{ts()}] [process_stop] Review abgebrochen: {note}\n",
            )
            completed = False
            last_answer = note
            break

        review_findings = review_result.end_answer
        latest_review_findings = review_findings
        latest_review_classification = parse_review_classification(review_findings)
        if latest_review_classification.get("valid") is False:
            runtime_error = execution_error(
                latest_review_classification["short_summary"], code="invalid_review", phase="review",
            )
            completed = False
            break
        print("Review findings:", review_findings)
        try:
            settings = decision_settings
            if latest_review_classification.get("source_format") == "text_legacy":
                if settings is None:
                    settings = DecisionExecSettings(
                        project_root=workspace, trusted_codex_home=Path.home() / ".codex",
                        env=dict(os.environ), log_root=workspace / ".codex_runs",
                        process_stop_path=process_stop_full,
                    )
                elif not isinstance(settings, DecisionExecSettings) or settings.project_root != workspace:
                    raise DecisionInputError("decision_invalid_input", "decision_settings",
                                             "Decision settings must belong to the active workspace")
                elif process_stop_full is not None:
                    settings = replace(settings, process_stop_path=process_stop_full)
                settings = replace(settings, call_budget=call_budget)
            decision = evaluate_completion_decision(
                original_task=original_task, latest_answer=last_answer, review_findings=review_findings,
                task_snapshot=decision_snapshot, run_id=active_decision_run_id,
                task_id=extract_todo_id(todo_identifier or "") or "standalone",
                phase=decision_phase, attempt_id=f"{decision_attempt_id}.{attempt_runs}",
                model=_decision_model() or model, reasoning_effort=reasoning_effort,
                settings=settings, pretty_log=pretty_log,
            )
        except DecisionInputError as exc:
            runtime_error = execution_error(str(exc), code=exc.code, phase="decide_input")
            runtime_error["input_error"] = exc.to_dict()
            completed = False
            break
        except RequiredDecisionError as exc:
            completed = False
            call = exc.call
            execution = call.result.execution if call is not None else None
            decision_payload = {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "selected_option": None, "explanation": None, "source": "codex_exec",
                "fallback_used": False, "error": str(exc), "error_code": exc.code,
                "archive": _decision_archive_payload(call) if call is not None else None,
            }
            if exc.code == "call_budget_exhausted":
                budget_exhausted = {**call_budget.snapshot(),
                    "blocked_task_id": todo_identifier or "standalone", "blocked_phase": budget_phase("decide")}
            elif exc.code == "decision_cancelled" and (
                    execution is None or execution.status is ExecutionStatus.CANCELLED):
                process_stop_triggered = True
                process_stop_details = str(exc)
            else:
                runtime_error = execution_error(str(exc), code=exc.code, phase="decide",
                    process_exit_code=execution.process_exit_code if execution is not None else None)
            append(pretty_log, f"[{ts()}] [decision_error] {json.dumps(decision_payload, ensure_ascii=False)}\n")
            break
        _record_decision_payload(decision)
        if decision.is_finished:
            completed = True
            break

        print(
            "Is Finished, Decision text:", decision.is_finished, decision.decision_text
        )

        if review_requires_runner_handling(latest_review_classification):
            append(
                pretty_log,
                (
                    f"[{ts()}] [review] Blocker requires runner handling; "
                    "skipping another local AutoBuild fix loop.\n"
                ),
            )
            break

        current_prompt = build_fix_prompt(
            original_task, review_findings, decision.decision_text
        ) + build_review_context_reference(
            str(review_contract_path), contract_text=review_contract_text
        )

        if auto_continue:
            append(
                pretty_log,
                f"[{ts()}] [auto-continue] Weitere Iteration ausgelöst.\n",
            )

    if not completed and runtime_error is None and auftrag_runs >= max_iterations:
        max_msg_pretty = f"[{ts()}] MAX ITERATIONS REACHED ({max_iterations}).\n"
        max_msg_console = (
            f"{_console_prefix(todo_identifier)} MAX ITERATIONS REACHED "
            f"({max_iterations}).\n"
        )
        append(pretty_log, max_msg_pretty)
        sys.stderr.write(f"[AutoBuild] {max_msg_console}")

    if print_end_answer:
        sys.stdout.write("\n==================== ENDANTWORT ====================\n\n")
        sys.stdout.write(last_answer + "\n")

    summary_text = (
        f"[AutoBuild] Aufträge: {auftrag_runs}, Prüfungen: {review_runs}. "
        f"Logs: {pretty_log} | {raw_log}\n"
    )
    if summary_json_path is not None:
        summary_text = (
            summary_text.rstrip("\n") + f" | summary_json: {summary_json_path}\n"
        )
    if process_stop_triggered:
        summary_text = summary_text.rstrip("\n") + " | process_stop ausgelöst\n"
    if verbose:
        sys.stdout.write(summary_text)
    else:
        sys.stderr.write(summary_text)

    summary_obj = AutoBuildSummary(
        last_answer=last_answer,
        completed=completed,
        auftrag_runs=auftrag_runs,
        review_runs=review_runs,
        workspace=workspace,
        pretty_log=pretty_log,
        raw_log=raw_log,
        readonly_result_path=readonly_result_path,
        run_history=auftrag_history,
        review_history=review_history,
    )
    summary_obj.execution_error = runtime_error
    summary_obj.call_budget = call_budget.snapshot()
    summary_obj.budget_exhausted = budget_exhausted
    summary_obj.review_required = True
    if runtime_error is not None:
        summary_obj.completed = False
        append(pretty_log, f"[{ts()}] [execution_error] {json.dumps(runtime_error, ensure_ascii=False)}\n")
    summary_obj.process_stop_triggered = process_stop_triggered
    summary_obj.process_stop_details = process_stop_details
    summary_obj.model = model
    summary_obj.reasoning_effort = reasoning_effort
    summary_obj.decision = decision_payload
    summary_obj.review_findings = latest_review_findings
    summary_obj.review_classification = latest_review_classification

    if summary_json_path is not None:
        written_path = write_summary_json(summary_obj, summary_json_path)
        summary_obj.summary_json_path = written_path
        append(
            pretty_log,
            f"[{ts()}] [info] summary.json geschrieben: {written_path}\n",
        )

    return summary_obj


# ------------------ CLI ------------------


class RemovedAutoBuildArgument(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.error(f"{option_string} wurde aus AutoBuild entfernt. "
                     "AutoBuild führt einen Auftrag mit Pflichtreview aus; "
                     "Wiederholungen ganzer Aufträge steuert ausschließlich run_todos.")


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument("--task", help="Auftragstext direkt.")
    task.add_argument("--task-file", help="UTF-8-Datei mit Auftrag.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--workdir", help="Gemeinsamer Projektworkspace.")
    target.add_argument("--file", help="Einzeldatei in einem isolierten Workspace.")
    parser.add_argument("--sandbox", choices=["workspace-write", "read-only"], default="workspace-write")
    parser.add_argument("--network-access", action="store_true")
    parser.add_argument("--codex-profile", dest="config_profile")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=CODEX_REASONING_EFFORT_CHOICES)
    parser.add_argument("--extra-arg", action="append", default=[])
    for name in ("logfile", "rawlog", "summary-json", "process-stop", "todo-identifier",
                 "decision-todo-file", "decision-run-id"):
        parser.add_argument("--" + name)
    parser.add_argument("--decision-attempt-id", default="1", help=argparse.SUPPRESS)
    parser.add_argument("--decision-phase", default="completion", help=argparse.SUPPRESS)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help="Gemeinsame Obergrenze aller Modellaufrufe, einschließlich Review und Decide.")
    for name in ("auto-continue", "print-end-answer", "verbose"):
        parser.add_argument("--" + name, action="store_true")
    from removed_features import add_removed_arguments
    add_removed_arguments(parser)


def _cli_call(args) -> dict:
    options = {name: getattr(args, name) for name in AutoBuildOptions.__dataclass_fields__
               if name != "process_stop_path"}
    options["process_stop_path"] = args.process_stop
    context = {name: getattr(args, name) for name in AutoBuildContext.__dataclass_fields__
               if name not in ("review_policy_rules", "task_source", "budget_directory", "budget_root_id")}
    context["task_source"] = "todo" if args.decision_todo_file else "inline"
    return dict(task=args.task, task_file=args.task_file, workdir=args.workdir, file=args.file,
                options=AutoBuildOptions(**options),
                context=AutoBuildContext(**context))


def failure_summary(exc: BaseException, *, workdir, options: AutoBuildOptions) -> AutoBuildSummary:
    """Preserve a structured terminal result even when Python/argument setup fails."""
    code = (6 if isinstance(exc, (ProcessStopActiveError, KeyboardInterrupt)) else
            7 if isinstance(exc, AutoBuildResultError) else
            2 if isinstance(exc, ValueError) else 3)
    message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    error = None
    if code != 6:
        error = execution_error(message, code=("invalid_autobuild_summary" if code == 7 else
                                      "autobuild_configuration" if code == 2 else "autobuild_runner_error"),
                                phase="autobuild")
        error["exit_code"] = code
    workspace = Path(workdir or ".").resolve()
    summary = AutoBuildSummary(last_answer="", completed=False, auftrag_runs=0, review_runs=0,
        workspace=workspace, pretty_log=Path(options.logfile or workspace / ".codex_runs/run.log"),
        raw_log=Path(options.rawlog or workspace / ".codex_runs/run.jsonl"), readonly_result_path=None,
        execution_error=error, process_stop_triggered=code == 6, process_stop_details=message if code == 6 else None,
        summary_json_path=Path(options.summary_json) if options.summary_json else None)
    if summary.summary_json_path is not None:
        write_summary_json(summary, summary.summary_json_path)
    return summary


def __getattr__(name: str):
    # Diagnostics only: no dynamic exports or lazy service imports remain.
    # ImportError preserves the explanation for `from autobuild import ...` too.
    if name in {"queue_main", "QueuedJob", "QueueState", "QueueWorker", "TelemetryMetrics"}:
        raise ImportError(f"autobuild.{name} ist entfernt. {SERVICE_MIGRATION}")
    raise AttributeError(name)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Thin CLI: parse one call, invoke start once, return its shared result code."""
    try:
        try:
            check_removed_environment()
        except ValueError as exc:
            sys.stderr.write(f"Fehler: {exc}\n")
            return 2
        args_list = list(argv) if argv is not None else sys.argv[1:]
        if args_list and args_list[0] == "queue":
            sys.stderr.write(f"Fehler: {SERVICE_MIGRATION}\n")
            return 2
        parser = argparse.ArgumentParser(description="AutoBuild: ein Auftrag mit Pflichtreview über Codex Exec.")
        if args_list[:1] == ["--request-json"]:
            from removed_features import add_removed_arguments
            add_removed_arguments(parser)
            parser.add_argument("--request-json", required=True)
            args = parser.parse_args(args_list)
            try:
                call = decode_call(json.loads(read_utf8(Path(args.request_json)), object_pairs_hook=strict_object))
            except (OSError, ValueError) as exc:
                sys.stderr.write(f"Fehler: {exc}\n")
                return 2
        else:
            add_run_arguments(parser)
            parser.add_argument("--max-retries", action=RemovedAutoBuildArgument, help=argparse.SUPPRESS)
            args = parser.parse_args(args_list)
            try:
                call = _cli_call(args)
            except ValueError as exc:
                sys.stderr.write(f"Fehler: {exc}\n")
                return 2
        try:
            summary = start(**call)
            validate_result(build_summary_document(summary))
        except (Exception, KeyboardInterrupt) as exc:
            summary = failure_summary(exc, workdir=call.get("workdir"), options=call["options"])
        payload = validate_result(build_summary_document(summary))
        code = payload["exit_code"]
        if code:
            detail = (summary.execution_error or {}).get("message") or summary.process_stop_details or "Job nicht abgeschlossen"
            sys.stderr.write(f"Fehler: {detail}\n")
        return code
    finally:
        _terminal_beep(1)


if __name__ == "__main__":
    sys.exit(main())
