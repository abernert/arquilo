#!/usr/bin/env python3
# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

RUN_TODOS_INPUT_READY_CONTRACT_VERSION = 1
ARQUILO_DIRECT_REPAIR_RUNNER_CONTRACT_VERSION = 1
ARQUILO_CAPABILITIES_SCHEMA_VERSION = "arquilo.capabilities.v1"

import argparse
import safe_io
from controller_state import PlanAuthority, PlanIntegrityError, state_directory, default_state_root
from reviewed_git import ReviewedGit, ReviewedGitError
from runtime_config import (
    environment_value,
    CODEX_REASONING_EFFORT_CHOICES,
    resolve_model as _resolve_codex_model,
    resolve_reasoning_effort as _resolve_codex_reasoning_effort,
)
import codex_policy
import codex_transport
from runtime_logging import TaskLogRecord, LogWriteError, copy_log_files, write_log_json, write_log_text
from removed_features import (reject_removed_options, add_removed_arguments,
                              check_removed_environment, reject_bridge_wait_conditions,
                              migration_for, BRIDGE_MIGRATION, IACT_MIGRATION, SERVICE_MIGRATION)
from todo_syntax import (TASK_PATTERN, OPEN_TASK_PATTERN, task_headers, canonical_status,
                         effective_syntax, normalize_syntax, render_command, directive_tokens,
                         visible_lines, SYNTAX_PATTERN)
from todo_context import augment_with_preamble, normalize_mode, TODO_PREAMBLE_CONTRACT_VERSION
from runtime_files import (PathValidationError, atomic_write_text, native_path, read_utf8,
                           safe_component, unique_directory, validate_path)
from runtime_failure import execution_error, failure_exit_code, EXIT_INCOMPLETE
import concurrent.futures
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
from execution_budget import CallBudget, DEFAULT_MAX_CALLS, positive_limit
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from types import SimpleNamespace
from autobuild_contract import (AutoBuildOptions, AutoBuildContext, call_payload,
                                validate_result, strict_object)

from autobuild import (
    AUTOBUILD_FINAL_FAILURE_CONTRACT_VERSION,
    AUTOBUILD_REVIEW_POLICY_CONTRACT_VERSION,
    ProcessStopActiveError,
    start as autobuild_start,
    build_summary_document as autobuild_summary_document,
    failure_summary as autobuild_failure_summary,
)
from review_contract import (parse_review_classification, review_classification_passes,
                             build_review_context_reference,
                             review_instructions)
from decision_request import read_input_text, snapshot_todo

from todo_lint import lint_todo_file
from todo_ids import extract_todo_id
from runtime_profile import (
    ARQUILO_CODEX_MODEL_ENV,
    ARQUILO_CODEX_REASONING_EFFORT_ENV,
    ARQUILO_RUNTIME_PROFILE_CONTRACT_VERSION,
    ARQUILO_RUNTIME_PROFILE_PREFLIGHT_CONTRACT_VERSION,
    ARQUILO_RUNTIME_PROFILE_PROTECTED_BLOCKS_CONTRACT_VERSION,
    ARQUILO_RUNTIME_PROFILE_PROMPT_POLICY_CONTRACT_VERSION,
    ARQUILO_RUNTIME_VERSION,
    RuntimeProfile,
    RuntimeProfileError,
    empty_runtime_profile,
    load_runtime_profile,
    run_runtime_profile_preflight,
)

RUN_CONFIG_SCHEMA_VERSION = "arquilo.run_config.v1"
CODEX_MODEL_ENV = ARQUILO_CODEX_MODEL_ENV
CODEX_REASONING_EFFORT_ENV = ARQUILO_CODEX_REASONING_EFFORT_ENV

CODEX_INVOCATION_OVERRIDE_CONTRACT_VERSION = 1
ARQUILO_RUNTIME_PROFILE_RUNNER_CONTRACT_VERSION = 1
RUN_TODOS_BREAKDOWN_CONTRACT_VERSION = 3
RUN_TODOS_FINAL_FAILURE_CONTRACT_VERSION = 1
RUN_TODOS_PARENT_REVIEW_CONTRACT_VERSION = 1
RUN_TODOS_PROCESS_STOP_POLICY_CONTRACT_VERSION = 1
RUN_TODOS_EXIT_OK = 0
RUN_TODOS_EXIT_ERROR = 3
RUN_TODOS_EXIT_PROCESS_STOP = 6
BREAKDOWN_POLICIES: Tuple[str, ...] = ("minimal", "legacy", "off")
BREAKDOWN_BLOCKING_TYPES: Set[str] = {
    "local_fix",
    "decomposition_needed",
    "missing_input",
    "scope_conflict",
    "technical_failure",
    "blocked_external",
}

_DEFAULT_CONTROLLER_ONLY_INSTRUCTION = (
    "Wenn Du Entscheidungen vom Nutzer brauchst oder Fragen hast, "
    "dokumentiere sie in `{question_path}` inklusive Datum/Zeit. "
    "Schreibe in diesem Auftrag niemals selbst eine `process_stop`-Datei. "
    "Erzeuge auch bei einem qualifizierten oder fehleranzeigenden Status alle "
    "verlangten strukturierten Outputs und schließe den Auftrag regulär ab. "
    "Ausschließlich der aufrufende Controller entscheidet nach Validierung über "
    "Korrektur, qualifizierte Fortsetzung oder einen technischen "
    "`{process_stop_path}`."
)

_DEFAULT_TASK_CONTRACT_INSTRUCTION = (
    "Wenn der Auftrag eine Prüf- und Reparaturbefugnis enthält, dokumentiere "
    "festgestellte Fehler getrennt und korrigiere sie im selben Auftrag innerhalb "
    "des freigegebenen Reparaturscopes. Fehler oder Widersprüche in bereitgestellten "
    "Eingaben sowie mehrere nach dem Auftrag vertretbare Interpretationen sind "
    "Analyseergebnisse, keine automatisch zu erzwingenden Nutzerentscheidungen. "
    "Ein separates Reparatur-ToDo ist nur für neue Recherche, Spezialzuständigkeit "
    "oder nicht lokal begrenzbare Großreparaturen vorgesehen."
)

_DEFAULT_PARENT_REVIEW_TERMINAL_RULE = (
    "Eine im ursprünglichen Auftrag ausdrücklich zulässige offene Frage, "
    "qualifizierte Aussage oder Halt-Markierung ist kein Mangel."
)


def validate_removed_directives(text: str) -> None:
    """Reject retired CFG and Bridge WAIT inputs before preflight, also in edited plans."""
    for _number, line in visible_lines(text):
        match = re.fullmatch(r"\*\*\*\s*(WAIT|CFG)\s+(.+?)\*\*\*", line.strip(), re.IGNORECASE)
        if match:
            command = match.group(1).upper()
            try:
                tokens = directive_tokens(match.group(2))
            except ValueError:
                if command == "WAIT":
                    raise
                # Keep general CFG grammar errors at the existing lint gate.
                continue
            for token in tokens:
                key, _, value = token.partition("=")
                if command == "CFG":
                    if migration_for(key) in (BRIDGE_MIGRATION, IACT_MIGRATION, SERVICE_MIGRATION):
                        raise ValueError(f"CFG: {key} ist entfernt. {migration_for(key)}")
                elif key.lower() == "on":
                    reject_bridge_wait_conditions(value)


def arquilo_capabilities_payload() -> Dict[str, Any]:
    return {
        "schema_version": ARQUILO_CAPABILITIES_SCHEMA_VERSION,
        "runtime_version": ARQUILO_RUNTIME_VERSION,
        "retained_core_options": ["CFG parallel", "runtime_profile", "--git"],
        "features": {
            "run_todos.breakdown": RUN_TODOS_BREAKDOWN_CONTRACT_VERSION,
            "run_todos.final_failure": RUN_TODOS_FINAL_FAILURE_CONTRACT_VERSION,
            "run_todos.parent_review": RUN_TODOS_PARENT_REVIEW_CONTRACT_VERSION,
            "run_todos.process_stop_policy": RUN_TODOS_PROCESS_STOP_POLICY_CONTRACT_VERSION,
            "run_todos.direct_repair": ARQUILO_DIRECT_REPAIR_RUNNER_CONTRACT_VERSION,
            "run_todos.preamble": TODO_PREAMBLE_CONTRACT_VERSION,
            "runtime_profile": ARQUILO_RUNTIME_PROFILE_CONTRACT_VERSION,
            "runtime_profile.preflight": ARQUILO_RUNTIME_PROFILE_PREFLIGHT_CONTRACT_VERSION,
            "runtime_profile.protected_blocks": ARQUILO_RUNTIME_PROFILE_PROTECTED_BLOCKS_CONTRACT_VERSION,
            "runtime_profile.prompt_policy": ARQUILO_RUNTIME_PROFILE_PROMPT_POLICY_CONTRACT_VERSION,
            "autobuild.final_failure": AUTOBUILD_FINAL_FAILURE_CONTRACT_VERSION,
            "autobuild.review_policy": AUTOBUILD_REVIEW_POLICY_CONTRACT_VERSION,
        },
    }


def _normalize_breakdown_policy(raw: Any, *, default: str = "minimal") -> str:
    candidate = str(raw or "").strip().lower()
    aliases = {
        "none": "off",
        "disabled": "off",
        "false": "off",
        "structured": "minimal",
    }
    candidate = aliases.get(candidate, candidate)
    if candidate in BREAKDOWN_POLICIES:
        return candidate
    return default


def _normalize_breakdown_max_children(raw: Any, *, default: int = 4) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(1, default)
    return min(12, max(1, value))


def _normalize_breakdown_max_rounds(raw: Any, *, default: int = 2) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(1, default)
    return min(8, max(1, value))


def _todo_line_map(text: str) -> Dict[str, Tuple[str, str]]:
    return {m.group(1): (canonical_status(m.group(2)), m.group(3).strip())
            for _, m in task_headers(text)}


def _todo_line_positions(text: str) -> Dict[str, int]:
    return {m.group(1): index for index, m in task_headers(text)}


def _direct_child_ids(parent_id: str, identifiers: Sequence[str]) -> List[str]:
    parent_parts = parent_id.split(".")
    children: List[str] = []
    for identifier in identifiers:
        parts = identifier.split(".")
        if len(parts) != len(parent_parts) + 1:
            continue
        if parts[:-1] != parent_parts:
            continue
        if not parts[-1].isdigit():
            continue
        children.append(identifier)
    return sorted(children, key=lambda item: int(item.rsplit(".", 1)[-1]))


def _extract_marked_block(text: str, marker_name: str) -> Optional[str]:
    start_pattern = re.compile(
        rf"<!--\s*{re.escape(marker_name)}(?:\s+v\d+)?\s+START\s*-->"
    )
    start_match = start_pattern.search(text)
    if start_match is None:
        return None
    end_pattern = re.compile(
        rf"<!--\s*{re.escape(marker_name)}(?:\s+v\d+)?\s+END\s*-->"
    )
    end_match = end_pattern.search(text, start_match.end())
    if end_match is None:
        return None
    return text[start_match.start() : end_match.end()]


def _normalize_boolish(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "yes", "ja", "1", "on"}:
            return True
        if normalized in {"false", "no", "nein", "0", "off", "", "null", "none"}:
            return False
    if isinstance(raw, (int, float)):
        return bool(raw)
    return False


def _normalize_review_classification_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return parse_review_classification(json.dumps(raw, ensure_ascii=False))
    return parse_review_classification(raw if isinstance(raw, str) else "")


def _breakdown_action(classification: Mapping[str, Any]) -> str:
    issues_raw = classification.get("blocking_issues")
    issues = [item for item in issues_raw if isinstance(item, Mapping)] if isinstance(issues_raw, list) else []
    if not issues:
        return "complete" if review_classification_passes(dict(classification)) else "stop"
    types = {
        str(item.get("type") or "local_fix").strip().lower()
        for item in issues
    }
    if types & {"missing_input", "scope_conflict", "technical_failure", "blocked_external"}:
        return "blocked"
    if bool(classification.get("breakdown_recommended")) or "decomposition_needed" in types:
        return "decompose"
    return "single_repair"


def _format_blocking_issues_for_breakdown(classification: Mapping[str, Any]) -> str:
    issues_raw = classification.get("blocking_issues")
    issues = [item for item in issues_raw if isinstance(item, Mapping)] if isinstance(issues_raw, list) else []
    lines: List[str] = []
    for index, issue in enumerate(issues, start=1):
        issue_id = str(issue.get("id") or f"ISSUE-{index}").strip()
        issue_type = str(issue.get("type") or "local_fix").strip()
        summary = str(issue.get("summary") or "Blocking issue.").strip()
        requirement = str(issue.get("requirement") or "").strip()
        criterion = str(issue.get("acceptance_criterion") or "").strip()
        suggestion = str(issue.get("fix_suggestion") or "").strip()
        refs_raw = issue.get("references")
        refs = [str(item).strip() for item in refs_raw if str(item).strip()] if isinstance(refs_raw, list) else []
        lines.append(f"{index}. [{issue_id}] ({issue_type}) {summary}")
        if requirement:
            lines.append(f"   Verletzte Anforderung: {requirement}")
        if criterion:
            lines.append(f"   Abnahmekriterium: {criterion}")
        if refs:
            lines.append("   Referenzen: " + ", ".join(refs))
        if suggestion:
            lines.append(f"   Korrekturhinweis: {suggestion}")
    return "\n".join(lines) if lines else "Keine blockierenden Issues angegeben."


def _codex_reasoning_config_value(reasoning_effort: str) -> str:
    return f"model_reasoning_effort={reasoning_effort}"


class GitIntegrationError(RuntimeError):
    """Raised when git-integrated workflows encounter unrecoverable errors."""


class CodexPreflightError(RuntimeError):
    """Raised when Codex workspace-write preflight validation fails."""


_CODEX_WORKSPACE_WRITE_PREFLIGHT_TIMEOUT_SECONDS = 60
_CODEX_WORKSPACE_WRITE_PREFLIGHT_PROMPT = (
    "Preflight only. Do not modify files. Reply exactly: ok"
)


def _redacted_codex_preflight_command(command: Sequence[str]) -> str:
    if command and command[-1] == _CODEX_WORKSPACE_WRITE_PREFLIGHT_PROMPT:
        command = [*command[:-1], "<preflight prompt>"]
    return shlex.join(command)


def _tail_text(text: str, *, max_chars: int = 2400) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return "... " + stripped[-max_chars:]


def _codex_missing_message(detail: Optional[str] = None) -> str:
    lines = [
        "Codex-Preflight fuer --sandbox workspace-write fehlgeschlagen:",
        "Der Befehl 'codex' wurde nicht gefunden oder konnte nicht gestartet werden.",
        "Installiere die Codex CLI, pruefe PATH/NVM-Shell-Initialisierung und fuehre danach erneut aus.",
    ]
    if detail:
        lines.append(f"Detail: {detail}")
    lines.append(
        "ARQUILO lockert die Sandbox bei Fehlern nicht. Prüfe die Codex-Sandboxinstallation."
    )
    return "\n".join(lines)


def _codex_workspace_write_known_hints(output: str, *, platform_name: str) -> List[str]:
    normalized = output.lower()
    hints: List[str] = []
    is_windows = platform_name.lower().startswith("win")
    is_linux = platform_name.lower().startswith("linux")

    windows_tokens = (
        "windows",
        "win32",
        "job object",
        "native sandbox",
        "sandbox is not supported",
    )
    if is_windows or any(token in normalized for token in windows_tokens):
        hints.append(
            "Windows/native Sandbox: Nutze eine Codex-Version mit eingerichteter Windows-workspace-write-Sandbox. Zugriffsprobleme werden gemeldet; es gibt keinen automatischen Start mit erweiterten Rechten. WSL2 ist eine getrennte Linux-Umgebung."
        )

    linux_specific_tokens = (
        "apparmor",
        "landlock",
        "user namespace",
        "userns",
        "unprivileged_userns",
    )
    linux_generic_tokens = (
        "clone3",
        "unshare",
        "operation not permitted",
        "permission denied",
        "seccomp",
    )
    linux_specific_match = any(token in normalized for token in linux_specific_tokens)
    linux_generic_match = any(token in normalized for token in linux_generic_tokens)
    if linux_specific_match or (is_linux and linux_generic_match):
        prefix = (
            "Linux/AppArmor/User-Namespace/Landlock"
            if linux_specific_match or is_linux
            else "Sandbox/User-Namespace/Landlock"
        )
        hints.append(
            f"{prefix}: pruefe, ob unprivilegierte User-Namespaces und Landlock erlaubt sind. Auf Ubuntu/Fedora ist insbesondere 'sysctl kernel.apparmor_restrict_unprivileged_userns' bzw. die AppArmor-/UserNS-Policy relevant."
        )

    nvm_tokens = (
        "bubblewrap",
        "bwrap",
        ".nvm",
        "nvm",
        "node not found",
        "node: not found",
        "npm",
    )
    if any(token in normalized for token in nvm_tokens):
        hints.append(
            "NVM/Bubblewrap-Pfadproblem: Codex/Node liegt vermutlich in einem Pfad, den die Sandbox nicht sieht. Installiere Codex/Node in einen stabilen Systempfad oder mounte den benoetigten Pfad ueber Codex --add-dir bzw. die Codex-Konfiguration."
        )

    auth_tokens = (
        "not logged in",
        "authentication",
        "api key",
        "openai_api_key",
        "unauthorized",
    )
    if any(token in normalized for token in auth_tokens):
        hints.append(
            "Codex-Authentisierung: pruefe die Codex-Anmeldung und die vom CLI gemeldete Providerkonfiguration. ARQUILO benoetigt keinen eigenen API-Key."
        )

    if "unexpected argument" in normalized and "--skip-git-repo-check" in normalized:
        hints.append(
            "Codex CLI-Version: diese Codex-Version kennt --skip-git-repo-check nicht. Aktualisiere Codex oder pruefe die lokale CLI-Hilfe."
        )

    return hints


def _format_codex_preflight_process_failure(
    *,
    command: Sequence[str],
    cwd: Path,
    process: subprocess.CompletedProcess[str],
) -> str:
    combined_output = "\n".join(
        part
        for part in (
            str(process.stdout or "").strip(),
            str(process.stderr or "").strip(),
        )
        if part
    )
    hints = _codex_workspace_write_known_hints(
        combined_output,
        platform_name=platform.system(),
    )
    lines = [
        "Codex-Preflight fuer --sandbox workspace-write fehlgeschlagen.",
        "Der eigentliche AutoBuild-ToDo-Lauf wurde nicht gestartet.",
        f"Command: {_redacted_codex_preflight_command(command)}",
        f"CWD: {cwd}",
        f"Exit-Code: {process.returncode}",
    ]
    if hints:
        lines.append("Diagnosehinweise:")
        lines.extend(f"- {hint}" for hint in hints)
    else:
        lines.append(
            "Hinweis: Pruefe Codex-Installation, Login/API-Key und lokale Sandbox-Unterstuetzung. Nutze --skip-codex-preflight nur bewusst, wenn du diesen Check extern verifiziert hast."
        )
    if combined_output:
        lines.append("Codex-Ausgabe:")
        lines.append(_tail_text(combined_output))
    lines.append(
        "ARQUILO lockert die Sandbox bei Fehlern nicht. Prüfe die Codex-Sandboxinstallation."
    )
    return "\n".join(lines)


def _format_codex_preflight_version_failure(
    process: subprocess.CompletedProcess[str],
) -> str:
    output = "\n".join(
        part
        for part in (
            str(process.stdout or "").strip(),
            str(process.stderr or "").strip(),
        )
        if part
    )
    lines = [
        "Codex-Preflight fuer --sandbox workspace-write fehlgeschlagen:",
        "'codex --version' konnte nicht erfolgreich ausgefuehrt werden.",
        f"Exit-Code: {process.returncode}",
    ]
    if output:
        lines.append("Codex-Ausgabe:")
        lines.append(_tail_text(output))
    return "\n".join(lines)


def run_codex_workspace_write_preflight(
    *,
    dry_run: bool,
    recorder: Optional["DryRunRecorder"] = None,
    timeout_seconds: int = _CODEX_WORKSPACE_WRITE_PREFLIGHT_TIMEOUT_SECONDS,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> None:
    version_command = ["codex", "--version"]
    resolved_model = _resolve_codex_model(model)
    resolved_reasoning_effort = _resolve_codex_reasoning_effort(reasoning_effort)
    exec_command = codex_transport.build_command(codex_transport.CodexExecRequest(
        prompt=_CODEX_WORKSPACE_WRITE_PREFLIGHT_PROMPT, cwd=Path.cwd(), env=dict(os.environ),
        raw_log=Path("preflight.jsonl"), pretty_log=Path("preflight.log"),
        model=resolved_model, reasoning_effort=resolved_reasoning_effort,
        extra_args=("--skip-git-repo-check",), phase="preflight",
    ))
    if dry_run:
        command_preview = "\n".join(
            [
                shlex.join(version_command),
                _redacted_codex_preflight_command(exec_command),
            ]
        )
        if recorder is not None:
            recorder.record(
                "Codex workspace-write preflight",
                command_preview,
                note=(
                    "Dry-run: wuerde pruefen, ob 'codex' verfuegbar ist und "
                    "ob 'codex exec --sandbox workspace-write' in einem "
                    "temporaeren Workspace starten kann."
                ),
            )
        print(
            "[dry-run] Codex-Preflight: wuerde codex --version und "
            "codex exec --sandbox workspace-write in einem temporaeren Workspace pruefen."
        )
        return

    try:
        version_process = codex_transport.probe_version(
            launcher=("codex",), cwd=Path.cwd(), env=dict(os.environ),
            timeout=timeout_seconds,
        )
    except OSError as exc:
        raise CodexPreflightError(_codex_missing_message(str(exc))) from exc
    except subprocess.TimeoutExpired as exc:
        raise CodexPreflightError(
            "Codex-Preflight fuer --sandbox workspace-write fehlgeschlagen: "
            f"'codex --version' lief laenger als {timeout_seconds}s. "
            "Pruefe Codex-Installation und PATH."
        ) from exc
    if version_process.returncode != 0:
        raise CodexPreflightError(
            _format_codex_preflight_version_failure(version_process)
        )

    with tempfile.TemporaryDirectory(prefix="arquilo-codex-preflight-") as tmpdir:
        temp_workspace = Path(tmpdir).resolve()
        try:
            request = codex_transport.CodexExecRequest(
                prompt=_CODEX_WORKSPACE_WRITE_PREFLIGHT_PROMPT,
                cwd=temp_workspace, env=dict(os.environ),
                raw_log=temp_workspace / "preflight.jsonl",
                pretty_log=temp_workspace / "preflight.log",
                model=resolved_model, reasoning_effort=resolved_reasoning_effort,
                network_access=False, extra_args=("--skip-git-repo-check",),
                phase="preflight",
                timeouts=codex_transport.TransportTimeouts(total=timeout_seconds),
            )
            result = codex_transport.execute(request)
        except FileNotFoundError as exc:
            raise CodexPreflightError(_codex_missing_message(str(exc))) from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexPreflightError(
                "Codex-Preflight fuer --sandbox workspace-write fehlgeschlagen: "
                f"'codex exec --sandbox workspace-write' lief laenger als {timeout_seconds}s. "
                "Pruefe Codex-Login, Modellzugriff und Sandbox-Initialisierung."
            ) from exc
        if not result.execution.succeeded:
            try:
                details = request.pretty_log.read_text(encoding="utf-8")
            except OSError as exc:
                details = f"Preflight-Log nicht lesbar: {exc}"
            if result.execution.failure is not None:
                details += "\n" + result.execution.failure.message
            elif result.execution.cancellation_reason:
                details += "\n" + result.execution.cancellation_reason
            process = subprocess.CompletedProcess(
                codex_transport.build_command(request),
                result.execution.process_exit_code if result.execution.process_exit_code is not None
                else int(result.execution.exit_code),
                "", details,
            )
            raise CodexPreflightError(
                _format_codex_preflight_process_failure(
                    command=codex_transport.build_command(request),
                    cwd=temp_workspace,
                    process=process,
                )
            )
    print("[ok]   Codex-Preflight fuer --sandbox workspace-write erfolgreich.")


def _beep(count: int) -> None:
    """Emit a terminal bell a given number of times without raising."""
    try:
        sys.stdout.write("\a" * count)
        sys.stdout.flush()
    except Exception:
        return


def _format_timestamp(value: Optional[datetime] = None) -> str:
    if value is None:
        value = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class TodoItem:
    identifier: str
    title: str
    depth: int
    line_index: Optional[int] = None
    preceding_line: Optional[str] = None
    directives: List[str] = field(default_factory=list)
    config: Dict[str, str] = field(default_factory=dict)
    wait_directives: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskOutcome:
    completed: bool
    message: str
    process_stop_triggered: bool = False
    abort: bool = False
    session_stamp: Optional[str] = None
    attempt: Optional[int] = None
    pretty_log: Optional[Path] = None
    raw_log: Optional[Path] = None
    summary_json: Optional[Path] = None
    summary_json_attempts: List[Path] = field(default_factory=list)
    log_dir: Optional[Path] = None
    task_log_id: Optional[str] = None
    input_files: List[Path] = field(default_factory=list)
    output_files: List[Path] = field(default_factory=list)
    review_findings: Optional[str] = None
    review_classification: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    execution_error: Optional[Dict[str, Any]] = None
    call_budget: Optional[Dict[str, Any]] = None
    budget_exhausted: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.abort or self.process_stop_triggered or self.execution_error or self.budget_exhausted:
            self.completed = False


@dataclass
class ParentReviewOutcome:
    passed: bool
    classification: Dict[str, Any]
    message: str
    task_outcome: TaskOutcome


@dataclass
class TodoExecutionContext:
    workdir: Path
    todo_file: Path
    result_file: Path
    questions_file: Path
    process_stop_path: Path
    policy_file: Path
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    agent: Optional[str] = None
    parallel_group: Optional[str] = None
    extra_args: List[str] = field(default_factory=list)
    target_result_file: Optional[Path] = None
    result_seed_content: Optional[str] = None
    questions_seed_content: Optional[str] = None
    todo_identifier: Optional[str] = None
    network_access: bool = False


class DryRunRecorder:
    def __init__(self, target: Optional[Path]) -> None:
        self.target = target
        if self.target is not None:
            safe_io.write_text(self.target, "# run_todos.py dry-run\n\n", exclusive=True)

    def record(self, heading: str, command: str, note: Optional[str] = None) -> None:
        if self.target is None:
            return
        block = [f"## {heading}\n", "```\n", f"{command}\n", "```\n"]
        if note:
            block.append(f"\n{note.strip()}\n")
        block.append("\n")
        with safe_io.open_file(self.target, "a", encoding="utf-8") as handle:
            handle.writelines(block)


class TodoRunner:
    TODO_PATTERN = OPEN_TASK_PATTERN
    STOP_SENTINEL = "***STOP***"
    DIRECTIVE_PATTERN = re.compile(r"^\*\*\*(.+?)\*\*\*$")
    CFG_ALLOWED_KEYS = {
        "workspace",
        "agent",
        "model",
        "parallel",
        "web_search",
        "websearch",
        "network_access",
        "result_file",
        "completion_anchor",
        "breakdown",
        "breakdown_max_children",
        "breakdown_max_rounds",
    }
    WAIT_ALLOWED_KEYS = {"on", "mode", "timeout", "on_timeout"}

    def __init__(
        self,
        todo_file: Path,
        workdir: Path,
        max_depth: int,
        max_retries: int,
        start_id: Optional[str],
        stop_id: Optional[str],
        dry_run: bool,
        dry_run_recorder: DryRunRecorder,
        simulated_incomplete: Set[str],
        max_steps: int,
        sandbox: Optional[str],
        run_id: Optional[str],
        git_enabled: bool = False,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        *removed_positional_options: Any,
        git_paths: Sequence[str] = (),
        git_push: bool = False,
        state_dir: Optional[Path] = None,
        accept_plan_changes: bool = False,
        breakdown_policy: str = "minimal",
        breakdown_max_children: int = 4,
        breakdown_max_rounds: int = 2,
        process_stop_policy: str = "model",
        runtime_profile: Optional[RuntimeProfile] = None,
        todo_syntax: str = "auto",
        network_access: bool = False,
        todo_preamble: str = "auto",
        max_calls: int = DEFAULT_MAX_CALLS,
        **removed_options: Any,
    ) -> None:
        if removed_positional_options:
            raise ValueError(
                "TodoRunner: iact_enabled (Positionsargument 16) ist entfernt; "
                "bridge_enabled (Positionsargument 17) ist entfernt. "
                "Nachfolgende Optionen als Schlüsselwortargumente übergeben. "
                + IACT_MIGRATION + " " + BRIDGE_MIGRATION
            )
        reject_removed_options(removed_options, source="TodoRunner")
        check_removed_environment()
        codex_policy.validate_start_policy(sandbox=sandbox, network_access=network_access)
        self.network_access = network_access
        self.run_started_at = datetime.now(UTC)
        self.todo_syntax = normalize_syntax(todo_syntax)
        self.todo_preamble = normalize_mode(todo_preamble)
        self.todo_source_file = native_path(todo_file, label="todo_file")
        self.todo_file = self.todo_source_file
        self.workdir = native_path(workdir, label="workdir")
        if self.todo_file.is_file():
            validate_removed_directives(read_utf8(self.todo_file))
        self.repo_root = Path(__file__).resolve().parent
        self.workspace_equals_repo = self.workdir == self.repo_root
        self.todo_in_workspace = self._path_within(self.todo_source_file, self.workdir)
        self.todo_relative: Optional[Path]
        try:
            self.todo_relative = self.todo_source_file.relative_to(self.repo_root)
        except ValueError:
            self.todo_relative = None
        if self.workspace_equals_repo or self.todo_in_workspace:
            self.workspace_todo_dir = self.todo_source_file.parent
            self.todo_workspace_file = self.todo_source_file
        else:
            if self.todo_relative is not None:
                relative_parent = self.todo_relative.parent
            else:
                relative_parent = Path("documents") / "todos"
            self.workspace_todo_dir = self.workdir / relative_parent
            self.todo_workspace_file = (
                self.workspace_todo_dir / self.todo_source_file.name
            )
        self.questions_file = self.workspace_todo_dir / "todo_fragen.md"
        self.policy_workspace_file = self.workdir / "config" / "policy.md"
        self.process_stop_path = self.workdir / "process_stop"
        self.max_depth = max_depth
        self.max_retries = max(1, max_retries)
        self.start_id = start_id
        self.stop_id = stop_id
        self.dry_run = dry_run
        self.recorder = dry_run_recorder
        self.simulated_incomplete = simulated_incomplete
        self.max_steps = max_steps
        self.max_calls = positive_limit(max_calls)
        self.call_budgets: Dict[str, CallBudget] = {}
        self.call_budget_lock = threading.Lock()
        self.breakdown_policy = _normalize_breakdown_policy(breakdown_policy)
        self.breakdown_max_children = _normalize_breakdown_max_children(breakdown_max_children)
        self.breakdown_max_rounds = _normalize_breakdown_max_rounds(breakdown_max_rounds)
        normalized_process_stop_policy = str(process_stop_policy or "model").strip().lower().replace("_", "-")
        if normalized_process_stop_policy not in {"model", "controller-only"}:
            raise ValueError("process_stop_policy must be 'model' or 'controller-only'")
        self.process_stop_policy = normalized_process_stop_policy
        self.runtime_profile = runtime_profile or empty_runtime_profile()
        self.runtime_profile_active = self.runtime_profile.is_active_for_file(self.todo_file)
        self.runtime_profile_scope_active = self.runtime_profile.scope_is_active_for_file(
            self.todo_file
        )
        self.sandbox = sandbox
        self.git_enabled = git_enabled
        self.model = _resolve_codex_model(model)
        self.reasoning_effort = _resolve_codex_reasoning_effort(reasoning_effort)
        self.git_repo_root: Optional[Path] = None
        self.run_id = self._resolve_run_id(run_id)
        # Reject stale/hostile workspace links even though control records now
        # live outside every model-writable workspace.
        safe_io.check_path(self.workdir / ".codex_runs")
        self.state_dir = (state_directory(self.workdir, self.todo_workspace_file, state_dir)
                          if not self.dry_run else safe_io.lexical_path(state_dir or default_state_root()) / "dry-run")
        self.runs_dir = (self.state_dir / "runs" if self.state_dir else
                         self.workdir / ".codex_runs" / "run_todos")
        self.git_selection = None
        if git_push and not git_enabled:
            raise ValueError("--git-push requires --git")
        if self.git_enabled:
            self.git_repo_root = self._assert_git_repository()
            if not self.dry_run:
                self.git_selection = ReviewedGit(self.workdir, git_paths, self.state_dir, push=git_push)
        self.run_dir = (self.runs_dir / safe_component(self.run_id) if self.dry_run
                        else unique_directory(self.runs_dir, prefix=self.run_id))
        self.autobuild_runs_dir = self.run_dir
        self.python_version = platform.python_version()
        self.run_config_path = self.run_dir / "run_config.json"
        self.run_config_payload: Optional[Dict[str, Any]] = None
        self.task_log_records: Dict[str, TaskLogRecord] = {}
        if not self.dry_run:
            self._prepare_workspace_documents()
            self._ensure_support_documents()
            self._read_policy_text()
        self.plan_authority = PlanAuthority(self.todo_file, None if self.dry_run else self.state_dir,
                                            accept_changes=accept_plan_changes)
        self.run_config_payload = self._build_run_config_payload()
        if not self.dry_run:
            self._write_run_config()
        self.attempted: Set[str] = set()
        self.completed: Set[str] = set()
        self.incomplete: Set[str] = set()
        self.failed: Set[str] = set()
        # Backward-compatible alias: historical code and diagnostics use
        # ``processed`` for every attempted ToDo. Completion is tracked
        # separately and is the only state that can unlock a parent review.
        self.processed = self.attempted
        self.start_reached = start_id is None
        self.pending_reviews: Dict[str, Tuple[Path, str]] = {}
        self.review_seen_children: Dict[str, bool] = {}
        self.breakdown_rounds: Dict[str, int] = {}
        self.parent_review_attempts: Dict[str, int] = {}
        try:
            initial_status_map = {
                identifier: status
                for identifier, (status, _title) in _todo_line_map(
                    read_utf8(self.todo_file)
                ).items()
            }
        except OSError:
            initial_status_map = {}
        for name, requested in (("--start", start_id), ("--stop", stop_id)):
            if requested and requested not in initial_status_map:
                raise ValueError(f"{name}: unbekannte ToDo-ID {requested}.")
        if start_id and stop_id:
            ids = list(initial_status_map)
            if ids.index(start_id) > ids.index(stop_id):
                raise ValueError("--start muss vor oder gleich --stop liegen.")
        self.completed.update(
            identifier
            for identifier, status in initial_status_map.items()
            if status == "DONE"
        )
        self.skip_before_ids: Set[str] = set()
        self.aborted = False
        self.stop_triggered = False
        self.stop_marker_triggered = False
        self.process_stop_detected = False
        self.process_stop_details: Optional[str] = None
        self.exit_code = RUN_TODOS_EXIT_OK
        self.terminal_execution_error: Optional[Dict[str, Any]] = None
        self._workspace_sync_lock = threading.Lock()
        self.completed_parallel_groups: Set[str] = set()
        self.completed_agents: Set[str] = set()


    @staticmethod
    def _clean_optional_text(value: Any) -> Optional[str]:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


    def _ensure_runtime_tracking_state(self) -> None:
        if not hasattr(self, "attempted"):
            self.attempted = set()
        if not hasattr(self, "completed"):
            self.completed = set()
        if not hasattr(self, "incomplete"):
            self.incomplete = set()
        if not hasattr(self, "failed"):
            self.failed = set()
        if not hasattr(self, "processed"):
            self.processed = self.attempted
        if not hasattr(self, "breakdown_rounds"):
            self.breakdown_rounds = {}
        if not hasattr(self, "parent_review_attempts"):
            self.parent_review_attempts = {}
        if not hasattr(self, "breakdown_max_rounds"):
            self.breakdown_max_rounds = 2
        if not hasattr(self, "exit_code"):
            self.exit_code = RUN_TODOS_EXIT_OK
        if not hasattr(self, "process_stop_detected"):
            self.process_stop_detected = False
        if not hasattr(self, "process_stop_details"):
            self.process_stop_details = None
        if not hasattr(self, "stop_triggered"):
            self.stop_triggered = False
        if not hasattr(self, "dry_run"):
            self.dry_run = False

    def close(self) -> None:
        authority = getattr(self, "plan_authority", None)
        if authority is not None:
            authority.close()

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        atomic_write_text(path, text)

    def _append_process_stop_details(self, details: str) -> None:
        text = str(details or "").strip()
        if not text or self.dry_run:
            return
        safe_io.mkdir(self.process_stop_path.parent)
        existing = self._read_text_file_if_exists(self.process_stop_path) or ""
        if text in existing:
            return
        merged = existing
        if merged and not merged.endswith("\n"):
            merged += "\n"
        if merged:
            merged += "\n---\n"
        merged += text
        self._atomic_write_text(self.process_stop_path, merged + "\n")

    def _todo_status_map(self) -> Dict[str, str]:
        try:
            text = read_utf8(self.todo_file)
        except OSError:
            return {}
        return {identifier: status for identifier, (status, _title) in _todo_line_map(text).items()}

    def _direct_child_statuses(self, parent_id: str) -> Dict[str, str]:
        status_map = self._todo_status_map()
        child_ids = _direct_child_ids(parent_id, list(status_map))
        return {child_id: status_map[child_id] for child_id in child_ids}

    def _write_final_failure_process_stop(
        self,
        *,
        todo_id: str,
        reason_code: str,
        phase: str,
        message: str,
        classification: Optional[Mapping[str, Any]] = None,
        parent_id: Optional[str] = None,
        result_file: Optional[Path] = None,
        task_outcome: Optional[TaskOutcome] = None,
    ) -> TaskOutcome:
        """Write a deterministic technical process_stop for a terminal ToDo failure.

        Fachliche Unsicherheit, die der Stage-Vertrag als Caveat, Frage oder
        HOLD zulässt, ist kein terminaler Fehler. Diese Funktion wird erst
        aufgerufen, wenn der verbindliche Auftragsvertrag nach dem verfügbaren
        Reparatur-/Breakdownbudget weiterhin nicht erfüllt ist.
        """

        self._ensure_runtime_tracking_state()
        normalized = _normalize_review_classification_payload(
            dict(classification) if isinstance(classification, Mapping) else {}
        )
        blocking_issues = normalized.get("blocking_issues")
        if not isinstance(blocking_issues, list):
            blocking_issues = []
        if not blocking_issues:
            blocking_issues = [
                {
                    "id": "FINAL-TODO-FAILURE",
                    "type": "technical_failure",
                    "summary": str(message).strip() or "ToDo final unvollständig.",
                    "requirement": "Der ToDo-Vertrag muss vollständig erfüllt sein.",
                    "acceptance_criterion": "Der Auftrag ist abgeschlossen und alle Pflichtoutputs sind gültig.",
                    "references": [],
                    "fix_suggestion": "Prüfe ToDo, Inputs, Outputs und die letzten AutoBuild-/Review-Logs.",
                }
            ]
            normalized["blocking_issues"] = blocking_issues
            normalized["verdict"] = "FAIL"
        now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(todo_id))
        diagnostic_dir = self.workdir / "var" / "process_stops"
        diagnostic_path = diagnostic_dir / f"{stamp}_{safe_id}.json"
        child_statuses = self._direct_child_statuses(parent_id or todo_id)
        payload: Dict[str, Any] = {
            "schema_version": "run_todos.process_stop.v1",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "reason_type": "final_todo_failure",
            "reason_code": str(reason_code),
            "phase": str(phase),
            "todo_id": str(todo_id),
            "parent_id": str(parent_id) if parent_id else None,
            "todo_file": str(self.todo_file),
            "result_file": str(result_file) if result_file is not None else None,
            "message": str(message).strip(),
            "breakdown_rounds_used": int(self.breakdown_rounds.get(parent_id or todo_id, 0)),
            "breakdown_max_rounds": int(self.breakdown_max_rounds),
            "child_statuses": child_statuses,
            "blocking_issues": blocking_issues,
            "review_classification": normalized,
            "review_findings": (task_outcome.review_findings if task_outcome else None),
            "call_budget": (task_outcome.call_budget if task_outcome else None),
            "budget_exhausted": (task_outcome.budget_exhausted if task_outcome else None),
            "logs": {
                "pretty": str(task_outcome.pretty_log) if task_outcome and task_outcome.pretty_log else None,
                "raw": str(task_outcome.raw_log) if task_outcome and task_outcome.raw_log else None,
                "summary_json": str(task_outcome.summary_json) if task_outcome and task_outcome.summary_json else None,
            },
            "user_question_required": False,
        }
        if not self.dry_run:
            safe_io.mkdir(diagnostic_dir)
            self._atomic_write_text(
                diagnostic_path,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )

        issue_lines: List[str] = []
        for index, issue in enumerate(blocking_issues, start=1):
            if not isinstance(issue, Mapping):
                continue
            summary = str(issue.get("summary") or "Blockierender Mangel").strip()
            requirement = str(issue.get("requirement") or "").strip()
            criterion = str(issue.get("acceptance_criterion") or "").strip()
            issue_lines.append(f"{index}. {summary}")
            if requirement:
                issue_lines.append(f"   - Verletzte Anforderung: {requirement}")
            if criterion:
                issue_lines.append(f"   - Abnahmekriterium: {criterion}")
        if not issue_lines:
            issue_lines.append("1. Der Auftrag blieb nach den vorgesehenen Reparatur- und Breakdown-Runden unvollständig.")

        child_lines = [
            f"- `{child_id}`: `{status}`"
            for child_id, status in sorted(child_statuses.items())
        ] or ["- keine direkten Kinder dokumentiert"]
        diagnostic_display = self._path_for_prompt(diagnostic_path)
        stop_text = (
            "# Technischer Prozessstopp: ToDo final nicht abgeschlossen\n\n"
            f"Zeitpunkt: {now.isoformat().replace('+00:00', 'Z')}\n"
            f"Grundcode: `{reason_code}`\n"
            f"Phase: `{phase}`\n\n"
            f"Der Auftrag `{todo_id}` konnte nach den vorgesehenen Produktions-, "
            "Korrektur- und Breakdown-Runden nicht vertragsgemäß abgeschlossen werden. "
            "Der Lauf wird beendet, damit keine unzuverlässigen Upstream-Artefakte weiterverarbeitet werden.\n\n"
            "## Verbleibende blockierende Mängel\n\n"
            + "\n".join(issue_lines)
            + "\n\n## Kinderstatus\n\n"
            + "\n".join(child_lines)
            + "\n\n## Diagnose\n\n"
            f"- Maschinenlesbarer Bericht: `{diagnostic_display}`\n"
            f"- ToDo-Datei: `{self._path_for_prompt(self.todo_file)}`\n"
            + (f"- Ergebnisdatei: `{self._path_for_prompt(result_file)}`\n" if result_file else "")
            + "\n## Fortsetzung\n\n"
            "Prüfe und korrigiere den genannten Auftrags- oder Inputfehler bewusst. "
            "Entferne `process_stop` erst danach und starte den Lauf erneut. "
            "Dieser technische Stopp setzt keine unbeantwortete Nutzerfrage voraus; "
            "`todo_fragen.md` ist nur maßgeblich, wenn dort ausdrücklich eine Frage dokumentiert ist.\n"
        )
        if not self.dry_run:
            if self.process_stop_path.exists():
                self._append_process_stop_details(stop_text)
            else:
                self._atomic_write_text(self.process_stop_path, stop_text)

        self.process_stop_detected = True
        self.process_stop_details = stop_text.strip()
        self.stop_triggered = True
        self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
        self.failed.add(str(todo_id))
        self.incomplete.discard(str(todo_id))
        base = task_outcome or TaskOutcome(completed=False, message=message)
        return replace(
            base,
            completed=False,
            message=stop_text.strip(),
            process_stop_triggered=True,
            abort=True,
            review_classification=normalized,
        )


    def run(self) -> None:
        print(f"[info] Run-ID: {self.run_id}")
        print(f"[info] Laufprotokolle: {self.run_dir}")
        run_status = "completed"
        try:
            if self._process_stop_active():
                details = (
                    self._read_process_stop_details()
                    or "process_stop blockiert diesen Lauf."
                )
                self.process_stop_detected = True
                self.process_stop_details = details
                self.stop_triggered = True
                self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                print(
                    f"[fatal] process_stop erkannt ({self._path_for_prompt(self.process_stop_path)}) – "
                    f"Lauf startet nicht. {details}"
                )
                return
            while True:
                # Validate the live plan before WAIT/STOP or a no-work return,
                # not only after these directives have already been interpreted.
                self.plan_authority.check()
                self._lint_todo_before_autobuild(todo_file=self.todo_file, workdir=self.workdir)
                if self.process_stop_detected or self.stop_triggered:
                    break
                todo = self._next_todo()
                if todo is None:
                    break
                if self._stop_marker_before(todo):
                    print(
                        f"[info] STOP-Marke vor ToDo {todo.identifier} erkannt – Ablauf wird beendet."
                    )
                    self.stop_marker_triggered = True
                    self.stop_triggered = True
                    break
                parallel_group = todo.config.get("parallel")
                if parallel_group:
                    should_stop = self._run_parallel_group(seed_todo=todo)
                    if should_stop:
                        break
                    continue
                if not self._wait_directives_allow_execution(todo):
                    self.stop_triggered = True
                    self.exit_code = EXIT_INCOMPLETE
                    break
                print(f"[run] ToDo {todo.identifier} – {todo.title}")
                outcome = self._handle_todo(todo)
                self.attempted.add(todo.identifier)
                if outcome.completed:
                    self.completed.add(todo.identifier)
                    self.incomplete.discard(todo.identifier)
                    self.failed.discard(todo.identifier)
                else:
                    self.incomplete.add(todo.identifier)

                if outcome.completed:
                    print(f"[ok]   ToDo {todo.identifier} abgeschlossen.")
                else:
                    print(f"[warn] ToDo {todo.identifier} blieb unvollständig.")
                if outcome.execution_error:
                    self._stop_for_execution_error(todo.identifier, outcome)
                    break
                if outcome.process_stop_triggered:
                    details = (
                        outcome.message.strip()
                        or self._read_process_stop_details()
                        or "process_stop ausgelöst."
                    )
                    process_stop_display = self._path_for_prompt(self.process_stop_path)
                    print(
                        f"[fatal] process_stop erkannt ({process_stop_display}) – Lauf endet. {details}"
                    )
                    self.process_stop_detected = True
                    self.process_stop_details = details
                    self.stop_triggered = True
                    self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                    self.failed.add(todo.identifier)
                    self.incomplete.discard(todo.identifier)
                    break
                if outcome.abort:
                    outcome = self._write_final_failure_process_stop(
                        todo_id=todo.identifier,
                        reason_code="unclassified_terminal_abort",
                        phase="todo_execution",
                        message=(
                            outcome.message.strip()
                            or "Unvollständiger Auftrag ohne zulässige Fortsetzung."
                        ),
                        classification=outcome.review_classification,
                        task_outcome=outcome,
                    )
                    print(
                        "[fatal] ToDo-Lauf wird beendet: " + outcome.message
                    )
                    break
                self._maybe_run_pending_reviews(trigger_parent=todo.identifier)
                if self.process_stop_detected or self.stop_triggered:
                    break
                if self.stop_id and todo.identifier == self.stop_id:
                    print(
                        f"[info] Stop-Marke {self.stop_id} erreicht – Ablauf endet nach diesem ToDo."
                    )
                    self.stop_triggered = True
                    break
            if not self.aborted and not self.stop_triggered:
                self._maybe_run_pending_reviews(force=True)
            if self.process_stop_detected:
                self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
            if self.terminal_execution_error:
                self.exit_code = failure_exit_code(self.terminal_execution_error)
            elif self.exit_code == 0 and (self.incomplete or self.failed or self.pending_reviews):
                self.exit_code = EXIT_INCOMPLETE
            if self.exit_code == 0 and not self.stop_triggered and not self.dry_run:
                def number(value):
                    return tuple(int(part) for part in value.split("."))
                outstanding = [item.identifier for item in self._parse_todo_file()
                    if (not self.start_id or number(item.identifier) >= number(self.start_id))
                    and (not self.stop_id or number(item.identifier) <= number(self.stop_id))]
                if outstanding:
                    print("[warn] Ausgewählte Aufgaben bleiben offen: " + ", ".join(outstanding))
                    self.exit_code = EXIT_INCOMPLETE
        except Exception as exc:
            run_status = "failed"
            if self.exit_code == 0:
                self.exit_code = 2 if isinstance(exc, ValueError) else RUN_TODOS_EXIT_ERROR
            if self.terminal_execution_error is None:
                # Keep diagnostics formerly carried by the optional event export
                # in the ordinary run log, without changing exception/exit semantics.
                self.terminal_execution_error = {
                    **execution_error(str(exc), code="runner_failed", phase="runner"),
                    "error_type": type(exc).__name__, "exit_code": self.exit_code,
                }
            raise
        finally:
            if run_status != "failed":
                if self.aborted:
                    run_status = "aborted"
                elif self.stop_triggered or self.process_stop_detected:
                    run_status = "stopped"
                elif self.exit_code != 0:
                    run_status = "incomplete"
            try:
                self._write_run_log(run_status=run_status)
            finally:
                self.close()
    def _sanitize_identifier(self, identifier: str) -> str:
        return safe_component(identifier, fallback="todo")

    def _resolve_run_id(self, provided: Optional[str]) -> str:
        base = (
            provided.strip()
            if provided
            else datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        )
        sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
        sanitized = sanitized.strip("._-")
        if sanitized:
            return safe_component(sanitized, fallback="run")
        fallback = datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
        return fallback

    def _derive_todo_id_from_identifier(self, identifier: str) -> str:
        derived = extract_todo_id(identifier)
        if derived is not None:
            return derived
        fallback = self._sanitize_identifier(identifier)
        return fallback or "todo"

    def _prepare_task_log(self, identifier: str, session_stamp: str,
                          workspace: Path, todo_file: Path, result_file: Optional[Path] = None
                          ) -> Tuple[str, TaskLogRecord, Path]:
        todo_id = self._derive_todo_id_from_identifier(identifier)
        parent = self.run_dir / "todo" / self._sanitize_identifier(todo_id)
        log_dir = (parent / safe_component(session_stamp) if self.dry_run
                   else unique_directory(parent, prefix=session_stamp))
        record = TaskLogRecord(identifier, todo_id, log_dir, workspace)
        self.task_log_records[str(log_dir)] = record
        record.input_sources = [todo_file, todo_file.parent / "todo_fragen.md",
                                workspace / "config" / "policy.md"]
        record.input_sources.extend(sorted(todo_file.parent.glob("todo_result_*.md")))
        if result_file is not None:
            record.input_sources.append(result_file)
        record.payload = {"schema_version": "arquilo.task_log.v1", "run_id": self.run_id,
                          "identifier": identifier, "status": "preparing", "completed": False}
        if not self.dry_run:
            write_log_json(log_dir / "task_log.json", record.payload)
        if not self.dry_run:
            record.inputs = copy_log_files(log_dir, "inputs", record.input_sources, workspace=workspace)
        return todo_id, record, log_dir

    def _attempt_log_paths(self, log_dir: Path, attempt: int, *,
                           ensure_directories: bool) -> Tuple[Path, Path, Path]:
        attempt_dir = log_dir / "autobuild" / f"attempt_{attempt}"
        if ensure_directories:
            safe_io.mkdir(attempt_dir)
        return (attempt_dir / "autobuild_pretty.log", attempt_dir / "autobuild_raw.jsonl",
                attempt_dir / "autobuild_summary.json")

    def _attach_log_metadata(self, outcome: TaskOutcome, *, todo_id: str,
                             log_record: TaskLogRecord, session_stamp: str,
                             log_dir: Path) -> TaskOutcome:
        outcome.task_log_id = todo_id
        outcome.log_dir = log_dir
        return outcome

    def _record_task_io(self, outcome: TaskOutcome, *, log_record: TaskLogRecord) -> None:
        if self.dry_run:
            return
        paths = list(log_record.input_sources)
        # Results can be created dynamically or redirected by CFG result_file.
        for folder in {p.parent for p in log_record.input_sources if p.name == "todo_fragen.md"}:
            paths.extend(sorted(folder.glob("todo_result_*.md")))
        paths.extend(self._collect_changed_files_from_summaries(outcome.summary_json_attempts))
        paths.extend(p for p in (outcome.pretty_log, outcome.raw_log, outcome.summary_json) if p)
        paths.extend(outcome.summary_json_attempts)
        outcome.input_files = [Path(row["path"]) for row in log_record.inputs if "path" in row]
        outcome.output_files = list(dict.fromkeys(paths))
        log_record.outputs = copy_log_files(log_record.log_dir, "outputs", paths,
                                           workspace=log_record.workspace)
        log_record.payload = {
            "schema_version": "arquilo.task_log.v1", "run_id": self.run_id,
            "identifier": log_record.identifier, "todo_id": log_record.todo_id,
            "workspace": str(log_record.workspace), "completed": outcome.completed,
            "status": "failed" if outcome.execution_error else "completed" if outcome.completed else "incomplete",
            "message": outcome.message, "execution_error": outcome.execution_error,
            "process_stop_triggered": outcome.process_stop_triggered,
            "call_budget": outcome.call_budget, "budget_exhausted": outcome.budget_exhausted,
            "inputs": log_record.inputs, "outputs": log_record.outputs,
            "summaries": [str(p) for p in outcome.summary_json_attempts],
            "review_classification": outcome.review_classification,
            "decision": outcome.decision, "aborted": bool(outcome.abort),
        }
        write_log_json(log_record.log_dir / "task_log.json", log_record.payload)

    def _finalize_post_todo_log(self, outcome: TaskOutcome) -> None:
        if self.dry_run or outcome.log_dir is None:
            return
        record = self.task_log_records[str(outcome.log_dir)]
        record.payload["final_stage"] = "before_controller_status_update"
        try:
            record.payload["final"] = copy_log_files(record.log_dir, "final", outcome.output_files,
                                                     workspace=record.workspace)
            write_log_json(record.log_dir / "task_log.json", record.payload)
        except LogWriteError as exc:
            record.payload.update(status="log_failed", completed=False, log_error=str(exc))
            write_log_json(record.log_dir / "task_log.json", record.payload)
            raise

    def _write_run_log(self, *, run_status: str) -> None:
        if self.dry_run:
            return
        write_log_json(self.run_dir / "run_log.json", {
            "schema_version": "arquilo.run_log.v1", "run_id": self.run_id,
            "status": run_status, "exit_code": self.exit_code,
            "completed": sorted(self.completed), "incomplete": sorted(self.incomplete),
            "failed": sorted(self.failed), "execution_error": self.terminal_execution_error,
            "tasks": [str(r.log_dir / "task_log.json") for r in self.task_log_records.values()],
            "call_budgets": {key: budget.snapshot() for key, budget in self.call_budgets.items()},
        })

    def _prepare_workspace_documents(self) -> None:
        if self.workspace_equals_repo or self.todo_in_workspace:
            safe_io.mkdir(self.workspace_todo_dir)
            self.todo_workspace_file = self.todo_source_file
            self.todo_file = self.todo_source_file
            return
        safe_io.mkdir(self.workspace_todo_dir)
        workspace_todo = self.todo_workspace_file
        safe_io.mkdir(workspace_todo.parent)
        if not workspace_todo.exists():
            safe_io.write_bytes(workspace_todo, safe_io.read_bytes(self.todo_source_file))
        self.todo_file = workspace_todo
        self._copy_existing_results_to_workspace()

    def _copy_existing_results_to_workspace(self) -> None:
        source_dir = self.todo_source_file.parent
        if not source_dir.exists():
            return
        for candidate in sorted(source_dir.glob("todo_result_*.md")):
            destination = self.workspace_todo_dir / candidate.name
            if destination.exists():
                continue
            safe_io.mkdir(destination.parent)
            safe_io.write_bytes(destination, safe_io.read_bytes(candidate))
        source_questions = source_dir / "todo_fragen.md"
        if source_questions.is_file():
            target_questions = self.workspace_todo_dir / source_questions.name
            if not target_questions.exists():
                safe_io.write_bytes(target_questions, safe_io.read_bytes(source_questions))

    def _ensure_support_documents(self) -> None:
        self._ensure_questions_file()
        self._ensure_policy_file()

    def _ensure_questions_file(self) -> None:
        target = self.questions_file
        safe_io.mkdir(target.parent)
        if target.exists():
            return
        template = (
            "# ToDo Fragen & Antworten\n\n"
            "Nutze dieses Dokument als Logbuch für Rückfragen an den Auftraggeber "
            "und dokumentiere Antworten direkt unterhalb der jeweiligen Frage.\n"
        )
        try:
            safe_io.write_text(target, template, exclusive=True)
        except OSError:
            pass

    def _ensure_policy_file(self) -> None:
        target = self.policy_workspace_file
        safe_io.check_path(target)
        if target.exists():
            self._read_policy_text(target)
            return
        repo_policy = self.repo_root / "config" / "policy.md"
        content = read_utf8(repo_policy) if repo_policy.exists() else ""
        safe_io.write_text(target, content, exclusive=True)

    def _result_file_for_todo(self, todo_id: str) -> Path:
        base_segment = todo_id.split(".")[0].strip()
        if not base_segment:
            base_segment = "todo"
        filename = f"todo_result_{base_segment}.md"
        return self.todo_file.parent / filename

    def _result_file_for_todo_context(
        self,
        todo: TodoItem,
        cfg: Mapping[str, str],
    ) -> Path:
        raw_filename = cfg.get("result_file") or cfg.get("completion_anchor")
        if raw_filename is None or not raw_filename.strip():
            return self._result_file_for_todo(todo.identifier)
        filename = raw_filename.strip()
        candidate = Path(filename)
        if (
            candidate.is_absolute()
            or candidate.name != filename
            or not re.fullmatch(r"todo_result_\d+(?:_[A-Za-z0-9_.-]+)?\.md", filename)
        ):
            raise RuntimeError(
                f"ToDo {todo.identifier}: CFG result_file muss ein lokaler "
                "todo_result_*.md-Dateiname sein."
            )
        return self.todo_file.parent / filename

    def _relative_to_workspace(self, path: Path) -> Path:
        try:
            return path.relative_to(self.workdir)
        except ValueError:
            return path

    def _read_policy_text(self, policy_file: Optional[Path] = None) -> str:
        target = policy_file or self.policy_workspace_file
        try:
            return read_utf8(target).strip()
        except FileNotFoundError:
            if self.dry_run:
                return ""  # dry-run never creates the optional empty default
            raise RuntimeError(f"Expected policy is missing: {target}")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Cannot read required policy {target}: {exc}") from exc

    def _augment_task_prompt(
        self,
        base_prompt: str,
        *,
        workspace: Optional[Path] = None,
        questions_file: Optional[Path] = None,
        process_stop_path: Optional[Path] = None,
        policy_file: Optional[Path] = None,
        agent: Optional[str] = None,
    ) -> str:
        prompt_workspace = workspace or self.workdir
        questions_path = questions_file or self.questions_file
        process_stop_target = process_stop_path or self.process_stop_path
        policy_target = policy_file or self.policy_workspace_file
        question_path = self._path_for_prompt(
            questions_path, workspace=prompt_workspace
        )
        process_stop_display = self._path_for_prompt(
            process_stop_target, workspace=prompt_workspace
        )
        if self.process_stop_policy == "controller-only":
            controller_template = (
                self.runtime_profile.controller_only_instruction
                if self.runtime_profile_active
                and self.runtime_profile.controller_only_instruction
                else _DEFAULT_CONTROLLER_ONLY_INSTRUCTION
            )
            stop_instruction = self.runtime_profile.format_prompt(
                controller_template,
                question_path=question_path,
                process_stop_path=process_stop_display,
            ) or ""
        else:
            stop_instruction = (
                "Wenn Du Entscheidungen vom Nutzer brauchst oder Fragen hast, "
                f"dokumentiere sie in `{question_path}` inklusive Datum/Zeit. "
                "Antworten werden dort ebenfalls eingetragen. "
                "Falls Du ohne bestimmte Antworten nicht weitermachen kannst, "
                f"notiere bei den entsprechenden Fragen, dass Antworten benötigt werden, "
                f"und schreibe anschließend `{process_stop_display}` in den Workspace. "
                "Diese Datei muss erklären, welche Fragen eine Fortsetzung blockieren."
            )
        instructions = [
            base_prompt.strip(),
            stop_instruction,
            (
                self.runtime_profile.task_contract_instruction
                if self.runtime_profile_active
                and self.runtime_profile.task_contract_instruction
                else _DEFAULT_TASK_CONTRACT_INSTRUCTION
            ),
            (
                'Ändere den Status eines ToDos nie von "Auftrag" auf "DONE". '
                "Das ist ausschließlich einer separaten Kontrollinstanz vorbehalten. "
                'Ebenfalls ändere nie einen Status von "DONE" zurück auf "Auftrag". '
                'Falls Du feststellst, dass es eine solche Statusänderung gegeben hat, '
                'gehe davon aus, dass das die Kontrollinstanz gewesen ist.'
            ),
        ]
        if self._task_command() == "***Task***":
            instructions.append(
                "Neue ToDo-Überschriften verwenden '<id>. ***Task***: <Text>'. "
                "Erledigte Einträge heißen ***DONE***, entfallene ***OBSOLETE***. "
                "OBSOLETE bedeutet nicht erfolgreich erledigt. Bestehende Auftragsinhalte bleiben editierbar."
            )
        if agent:
            instructions.append(
                f"Nutze für diesen Auftrag den Agenten `{agent}` und orientiere Dich an dessen Spezialisierung."
            )
        task_text = "\n\n".join(entry for entry in instructions if entry.strip())
        policy_text = self._read_policy_text(policy_target)
        if policy_text:
            policy_path = self._path_for_prompt(
                policy_target, workspace=prompt_workspace
            )
            if self.process_stop_policy == "controller-only":
                policy_tail = (
                    "Wenn ein Auftrag selbst oder aufgrund weiterer Informationen diese Policy verletzt, "
                    "dokumentiere die Verletzung vollständig in den verlangten strukturierten Outputs; "
                    "schreibe keine process_stop-Datei. Der Controller behandelt den Status."
                )
            else:
                policy_tail = (
                    "Wenn ein Auftrag selbst oder aufgrund weiterer Informationen diese Policy verletzt, "
                    f"schreibe `{process_stop_display}` mit einer Erläuterung der Policy-Verletzung "
                    "und verweise auf den entsprechenden Abschnitt."
                )
            policy_block = (
                f"Folgende Policy aus `{policy_path}` gilt verbindlich:\n{policy_text}\n\n"
                + policy_tail
            )
            task_text = "\n\n".join([task_text, policy_block]).rstrip()
        return task_text

    def _process_stop_active(self) -> bool:
        return self.process_stop_path.exists()

    def _read_process_stop_details(
        self, target: Optional[Path] = None
    ) -> Optional[str]:
        path = target or self.process_stop_path
        if not path.exists():
            return None
        try:
            return read_utf8(path).strip()
        except OSError:
            return None


        # Kein Guard gesetzt und keine Ergebnisse vorhanden – erster Lauf, kein Anker nötig.


    def _assert_git_repository(self) -> Path:
        try:
            status = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise GitIntegrationError(
                f"--git erfordert ein initialisiertes Repository unter {self.workdir}: {exc.stderr.strip()}"
            ) from exc
        if status.stdout.strip().lower() != "true":
            raise GitIntegrationError(
                f"--git erfordert ein initialisiertes Repository unter {self.workdir}."
            )
        try:
            toplevel = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise GitIntegrationError(
                f"Konnte Git-Wurzelverzeichnis nicht bestimmen: {exc.stderr.strip()}"
            ) from exc
        repo_root = Path(toplevel.stdout.strip()).resolve()
        workdir_resolved = self.workdir.resolve()
        git_indicator = workdir_resolved / ".git"
        workspace_has_git_metadata = git_indicator.exists()
        if repo_root != workdir_resolved and not workspace_has_git_metadata:
            raise GitIntegrationError(
                "--git erfordert, dass der Workspace selbst die Git-Wurzel ist oder eine eigene .git-Struktur enthält. "
                f"Workspace: {workdir_resolved}, Git-Wurzel: {repo_root}"
            )
        if workspace_has_git_metadata and repo_root != workdir_resolved:
            return workdir_resolved
        return repo_root

    def _run_git_command(
        self,
        args: Sequence[str],
        *,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess:
        command = ["git", *args]
        try:
            completed = subprocess.run(
                command,
                cwd=self.workdir,
                text=True,
                capture_output=capture_output,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else ""
            raise GitIntegrationError(
                f"Git-Befehl {' '.join(command)} fehlgeschlagen: {stderr or exc}"
            ) from exc
        return completed

    def _git_status_has_changes(self) -> bool:
        result = self._run_git_command(["status", "--porcelain"], capture_output=True)
        assert result.stdout is not None
        return bool(result.stdout.strip())

    def _compose_git_commit_message(
        self, todo: TodoItem
    ) -> str:
        base = f"[run_todos:{self.run_id}] {todo.identifier} DONE"
        if todo.title:
            base += f" – {todo.title}"
        return base

    def _maybe_git_commit(self, todo: TodoItem, outcome: TaskOutcome) -> None:
        if not self.git_enabled:
            return
        if self.dry_run:
            self.recorder.record(f"{todo.identifier}-git", "# explicit reviewed Git selection; no Git mutation")
            return
        self.plan_authority.check()
        result = self.git_selection.commit(self._compose_git_commit_message(todo))
        if result:
            write_log_json(self.run_dir / ("git_" + todo.identifier.replace(".", "_") + ".json"), result)
            print("[info] Ausgewählte geprüfte Dateien committed; Push=" + str(result["pushed"]))

    def _stop_marker_before(self, todo: TodoItem) -> bool:
        if todo.preceding_line is None:
            return False
        return todo.preceding_line.strip() == self.STOP_SENTINEL

    def _task_command(self) -> str:
        text = read_utf8(self.todo_file)
        return render_command("Auftrag", effective_syntax(text, self.todo_syntax))

    def _mark_todo_as_done(self, todo: TodoItem) -> None:
        self.plan_authority.check()
        if self.dry_run:
            print(
                f"[info] Dry-run: Würde ToDo {todo.identifier} im ToDo-File als DONE markieren."
            )
            return
        text = read_utf8(self.todo_file, preserve_newlines=True, preserve_bom=True)
        lines = text.splitlines(keepends=True)
        changed = False
        headers = dict(task_headers(text))
        for index, match in headers.items():
            if match.group(1) != todo.identifier:
                continue
            status = canonical_status(match.group(2))
            if status == "DONE":
                print(f"[info] ToDo {todo.identifier} ist bereits als DONE markiert; keine Änderung nötig.")
                return
            if status == "OBSOLETE":
                raise RuntimeError(f"ToDo {todo.identifier} wurde während der Bearbeitung OBSOLETE; kein DONE wird geschrieben.")
            syntax = effective_syntax(text, self.todo_syntax)
            if self.todo_syntax == "auto" and not any(
                SYNTAX_PATTERN.fullmatch(line.strip())
                for _, line in visible_lines(text)
            ):
                # Mixed files are permitted; preserve each existing task's style.
                syntax = "marked-en" if match.group(2).startswith("***") else "legacy"
            command = render_command("DONE", syntax)
            # Only replace the command token; preserve title, indentation and spacing.
            raw = lines[index]
            bom = 1 if index == 0 and raw.startswith("\ufeff") else 0
            content = raw[bom:]
            offset = bom + len(content) - len(content.lstrip())
            start_pos = offset + match.start(2)
            end_pos = offset + match.end(2)
            lines[index] = raw[:start_pos] + command + raw[end_pos:]
            changed = True
            break
        if not changed:
            raise RuntimeError(f"ToDo {todo.identifier} kann nicht als DONE markiert werden: Eintrag nicht gefunden.")
        self.plan_authority.replace_approved("".join(lines))
        print(f"[info] ToDo {todo.identifier} wurde im ToDo-File als DONE markiert.")

    @staticmethod
    def _path_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    def _path_for_prompt(self, path: Path, *, workspace: Optional[Path] = None) -> str:
        workspace_root = workspace or self.workdir
        try:
            relative = path.relative_to(workspace_root)
        except ValueError:
            relative = path
        if relative == path:
            return str(path)
        return relative.as_posix()

    def _locate_workspace_result_file(self, result_file: Path) -> Optional[Path]:
        filename = result_file.name
        candidates = [
            self.workspace_todo_dir / filename,
            self.workdir / filename,
            self.workdir / "documents" / "todos" / filename,
        ]
        try:
            globbed = list(self.workdir.rglob(filename))
        except OSError:
            globbed = []
        candidates.extend(globbed)
        unique: List[Path] = []
        seen: Set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            if not resolved.is_file() or resolved.is_relative_to(self.workdir / ".codex_runs"):
                continue
            seen.add(resolved)
            unique.append(resolved)
        if not unique:
            return None
        unique.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
        return unique[0]

    def _resolve_result_file_reference(self, result_file: Path) -> Path:
        if result_file.exists():
            return result_file
        workspace_copy = self._locate_workspace_result_file(result_file)
        if workspace_copy is not None:
            return workspace_copy
        return result_file

    def _collect_existing_paths(
        self,
        label: str,
        candidates: Sequence[Tuple[Path, bool]],
    ) -> List[Path]:
        existing: List[Path] = []
        seen: Set[Path] = set()
        for candidate, warn_missing in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved in seen:
                continue
            if not resolved.is_file():
                if warn_missing:
                    print(f"[warn] {label}: Datei nicht gefunden – {resolved}")
                continue
            existing.append(resolved)
            seen.add(resolved)
        return existing

    def _gather_input_files(self, result_file: Path) -> List[Path]:
        resolved_result = self._resolve_result_file_reference(result_file)
        candidates = [
            (self.todo_file, True),
            (resolved_result, True),
        ]
        if self.questions_file.exists():
            candidates.append((self.questions_file, False))
        return self._collect_existing_paths("inputs", candidates)

    def _resolve_workspace_path(self, workspace: Path, raw_path: str) -> Optional[Path]:
        candidate_text = raw_path.strip()
        if not candidate_text:
            return None
        candidate = Path(candidate_text)
        candidate = candidate.expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return None
        return resolved

    def _resolve_workspace_relative_path(
        self,
        workspace: Path,
        raw_path: str,
        *,
        label: str,
    ) -> Optional[Path]:
        candidate_text = raw_path.strip()
        if not candidate_text:
            return None
        candidate = Path(candidate_text).expanduser()
        if candidate.is_absolute():
            print(
                f"[warn] {label}: Pfad muss workspace-relativ sein – {candidate_text}"
            )
            return None
        try:
            resolved = (workspace / candidate).resolve()
        except OSError:
            return None
        try:
            resolved.relative_to(workspace)
        except ValueError:
            print(
                f"[warn] {label}: Pfad liegt ausserhalb des Workspace – {candidate_text}"
            )
            return None
        return resolved

    def _load_autobuild_summary_payload(
        self, summary_path: Path
    ) -> Optional[Tuple[Dict[str, Any], Path]]:
        summary_file = Path(summary_path)
        if not summary_file.is_file():
            print(f"[warn] outputs: Summary JSON nicht gefunden – {summary_file}")
            return None
        try:
            payload = json.loads(summary_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] outputs: Summary JSON unlesbar – {summary_file}: {exc}")
            return None
        if not isinstance(payload, dict):
            print(
                f"[warn] outputs: Summary JSON hat ungueltiges Format – {summary_file}"
            )
            return None
        workspace = self.workdir.expanduser().resolve()
        workspace_value = payload.get("workspace")
        if isinstance(workspace_value, str) and workspace_value.strip():
            declared_workspace_raw = workspace_value.strip()
            try:
                declared_workspace = Path(declared_workspace_raw).expanduser().resolve()
            except OSError:
                print(
                    "[warn] outputs: Summary workspace ist ungueltig "
                    f"und wird ignoriert – {declared_workspace_raw}"
                )
            else:
                if declared_workspace.is_relative_to(self.workdir):
                    workspace = declared_workspace
                else:
                    print(
                        "[warn] outputs: Summary workspace wird ignoriert "
                        f"(summary={declared_workspace}, runner={workspace})"
                    )
        return payload, workspace

    def _collect_changed_files_from_summary(self, summary_path: Path) -> List[Path]:
        summary_payload = self._load_autobuild_summary_payload(summary_path)
        if summary_payload is None:
            return []
        payload, workspace = summary_payload
        file_changes = payload.get("file_changes", [])
        resolved: List[Path] = []
        if isinstance(file_changes, list):
            for entry in file_changes:
                if not isinstance(entry, dict):
                    continue
                raw_paths = [entry.get("path")]
                raw = entry.get("raw")
                if isinstance(raw, dict) and isinstance(raw.get("changes"), list):
                    raw_paths.extend(change.get("path") for change in raw["changes"]
                                     if isinstance(change, dict))
                for raw_path in raw_paths:
                    if isinstance(raw_path, str):
                        candidate = self._resolve_workspace_path(workspace, raw_path)
                        if candidate is not None and candidate not in resolved:
                            resolved.append(candidate)
        return resolved


    def _collect_changed_files_from_summaries(
        self, summary_paths: Sequence[Path]
    ) -> List[Path]:
        aggregated: List[Path] = []
        seen: Set[Path] = set()
        for summary_path in summary_paths:
            for path in self._collect_changed_files_from_summary(summary_path):
                if path in seen:
                    continue
                aggregated.append(path)
                seen.add(path)
        return aggregated

    def _gather_output_files(
        self,
        result_file: Path,
        summary_paths: Sequence[Path],
    ) -> List[Path]:
        resolved_result = self._resolve_result_file_reference(result_file)
        changed_files = [
            (path, False)
            for path in self._collect_changed_files_from_summaries(summary_paths)
        ]
        candidates = [(resolved_result, True)]
        candidates.extend(changed_files)
        return self._collect_existing_paths("outputs", candidates)


    def _relative_to_run_dir(self, path: Path) -> Path:
        try:
            return path.relative_to(self.run_dir)
        except ValueError:
            return path

    def _todo_task_prompt(self, todo: TodoItem, context: TodoExecutionContext) -> str:
        todo_prompt_path = self._path_for_prompt(
            context.todo_file, workspace=context.workdir
        )
        result_prompt_path = self._path_for_prompt(
            context.result_file, workspace=context.workdir
        )
        base_task = (
            f"Erfülle aus `{todo_prompt_path}` das ToDo Nummer {todo.identifier}. "
            f"Berücksichtige dabei bisherige Ergebnisse in den todo_result-Dateien innerhalb des Workspaces (z. B. `{result_prompt_path}`). "
            f"Dokumentiere das Ergebnis in `{result_prompt_path}`."
        )
        if context.workdir != self.workdir:
            workspace_hint = self._path_for_prompt(context.workdir)
            base_task += (
                f" Nutze für diesen Auftrag den Unterworkspace `{workspace_hint}` "
                "und arbeite nur innerhalb dieses Bereichs."
            )
        return self._augment_task_prompt(
            base_task,
            workspace=context.workdir,
            questions_file=context.questions_file,
            process_stop_path=context.process_stop_path,
            policy_file=context.policy_file,
            agent=context.agent,
        )

    def _execute_todo_autobuild(
        self,
        todo: TodoItem,
        *,
        use_cli_subprocess: bool = False,
        sync_back: bool = True,
    ) -> Tuple[TaskOutcome, TodoExecutionContext, Path]:
        context = self._build_todo_execution_context(todo)
        primary_result_file = context.target_result_file or self._result_file_for_todo(
            todo.identifier
        )
        task_text = self._todo_task_prompt(todo, context)
        outcome = self._run_autobuild(
            todo.identifier,
            task_text,
            workdir_override=context.workdir,
            model_override=context.model,
            reasoning_effort_override=context.reasoning_effort,
            extra_args=context.extra_args,
            network_access_override=context.network_access,
            config_profile=context.agent,
            process_stop_override=context.process_stop_path,
            use_cli_subprocess=use_cli_subprocess,
            todo_file_override=context.todo_file,
            result_file_override=context.result_file,
        )
        if sync_back:
            self._sync_context_back_to_primary_workspace(
                context, target_result_file=primary_result_file
            )
        return outcome, context, primary_result_file

    def _collect_parallel_group_batch(self, seed_todo: TodoItem) -> List[TodoItem]:
        group = seed_todo.config.get("parallel")
        if not group:
            return [seed_todo]
        todos = self._parse_todo_file()
        batch: List[TodoItem] = []
        seed_found = False
        for item in todos:
            if not seed_found:
                if item.identifier != seed_todo.identifier:
                    continue
                seed_found = True
            if item.identifier in self.processed:
                continue
            if item.depth > self.max_depth:
                continue
            if item.config.get("parallel") != group:
                if batch:
                    break
                continue
            if self._stop_marker_before(item):
                break
            batch.append(item)
        return batch or [seed_todo]

    def _run_parallel_group(self, seed_todo: TodoItem) -> bool:
        group = seed_todo.config.get("parallel")
        if not group:
            return False
        batch = self._collect_parallel_group_batch(seed_todo)
        for item in batch:
            if not self._wait_directives_allow_execution(item):
                self.stop_triggered = True
                self.exit_code = EXIT_INCOMPLETE
                return True
        resolved_workspaces: Set[Path] = set()
        for item in batch:
            raw_workspace = item.config.get("workspace")
            if not raw_workspace:
                raise RuntimeError(
                    f"ToDo {item.identifier}: parallele Ausführung erfordert CFG workspace=<unterpfad>."
                )
            resolved_workspace = self._resolve_directive_workspace(raw_workspace)
            if resolved_workspace in resolved_workspaces:
                raise RuntimeError(
                    f"ToDo {item.identifier}: Parallelgruppe '{group}' enthält doppelte Workspace-Zuordnung ({resolved_workspace})."
                )
            resolved_workspaces.add(resolved_workspace)
        outcomes: Dict[str, Tuple[TaskOutcome, TodoExecutionContext, Path]] = {}
        if len(batch) == 1:
            todo = batch[0]
            outcomes[todo.identifier] = self._execute_todo_autobuild(
                todo, use_cli_subprocess=False
            )
        else:
            print(
                f"[info] Starte Parallelgruppe '{group}' mit {len(batch)} ToDos in Unterworkspaces."
            )
            worker_count = min(4, len(batch))
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=worker_count
            ) as pool:
                future_map = {
                    pool.submit(
                        self._execute_todo_autobuild,
                        todo,
                        use_cli_subprocess=True,
                        sync_back=False,
                    ): todo
                    for todo in batch
                }
                for future in concurrent.futures.as_completed(future_map):
                    todo = future_map[future]
                    try:
                        outcomes[todo.identifier] = future.result()
                    except Exception as exc:
                        print(
                            f"[warn] ToDo {todo.identifier}: parallele Ausführung fehlgeschlagen ({exc})."
                        )
                        fallback_context = self._build_todo_execution_context(todo)
                        fallback_result = (
                            fallback_context.target_result_file
                            or self._result_file_for_todo(todo.identifier)
                        )
                        outcomes[todo.identifier] = (
                            TaskOutcome(
                                completed=False,
                                abort=True,
                                execution_error=execution_error(str(exc), code="parallel_execution_failed", phase="autobuild"),
                                message=(
                                    "Paralleler Autobuild-Aufruf fehlgeschlagen: "
                                    f"{type(exc).__name__}: {exc}"
                                ),
                            ),
                            fallback_context,
                            fallback_result,
                        )

        stop_requested = False
        for todo in batch:
            outcome, context, primary_result_file = outcomes[todo.identifier]
            if outcome.abort or outcome.process_stop_triggered or outcome.execution_error:
                outcome.completed = False
            self._sync_context_back_to_primary_workspace(
                context, target_result_file=primary_result_file
            )
            print(f"[run] ToDo {todo.identifier} – {todo.title}")
            self.attempted.add(todo.identifier)
            if outcome.completed:
                print(f"[ok]   ToDo {todo.identifier} abgeschlossen.")
                self._finalize_post_todo_log(outcome)
                self._mark_todo_as_done(todo)
                self.completed.add(todo.identifier)
                self.incomplete.discard(todo.identifier)
                self.failed.discard(todo.identifier)
                self._maybe_git_commit(todo, outcome)
            elif outcome.execution_error:
                self._stop_for_execution_error(todo.identifier, outcome)
                stop_requested = True
            else:
                print(f"[warn] ToDo {todo.identifier} blieb unvollständig.")
                self.incomplete.add(todo.identifier)
                if not outcome.process_stop_triggered:
                    review_text = (
                        (outcome.review_findings or "").strip()
                        or outcome.message.strip()
                        or "Keine Review-Nachricht erhalten."
                    )
                    self._record_review(
                        primary_result_file, review_text, todo.identifier
                    )
                    outcome = self._write_final_failure_process_stop(
                        todo_id=todo.identifier,
                        reason_code="parallel_todo_final_failure",
                        phase="parallel_todo_execution",
                        message=(
                            "Ein paralleler Auftrag blieb nach den vorgesehenen "
                            "AutoBuild-Versuchen unvollständig."
                        ),
                        classification=(
                            outcome.review_classification
                            if isinstance(outcome.review_classification, dict)
                            else review_text
                        ),
                        result_file=primary_result_file,
                        task_outcome=outcome,
                    )
                details = (
                    outcome.message.strip()
                    or self._read_process_stop_details()
                    or "process_stop ausgelöst."
                )
                process_stop_display = self._path_for_prompt(self.process_stop_path)
                print(
                    f"[fatal] process_stop erkannt ({process_stop_display}) – Lauf endet. {details}"
                )
                self.process_stop_detected = True
                self.process_stop_details = details
                self.stop_triggered = True
                self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                self.failed.add(todo.identifier)
                self.incomplete.discard(todo.identifier)
                stop_requested = True
            if context.agent and outcome.completed:
                self.completed_agents.add(context.agent)
            if not stop_requested:
                self._maybe_run_pending_reviews(trigger_parent=todo.identifier)
            if self.stop_id and todo.identifier == self.stop_id:
                print(
                    f"[info] Stop-Marke {self.stop_id} erreicht – Ablauf endet nach diesem ToDo."
                )
                self.stop_triggered = True
                stop_requested = True
        if all(outcomes[item.identifier][0].completed for item in batch):
            self.completed_parallel_groups.add(group)
        if self.terminal_execution_error:
            self.exit_code = failure_exit_code(self.terminal_execution_error)
        return stop_requested

    def _stop_for_execution_error(self, todo_id: str, outcome: TaskOutcome) -> TaskOutcome:
        error = outcome.execution_error
        if not isinstance(error, dict):
            return outcome
        already_recorded = todo_id in self.failed and self.terminal_execution_error == error
        self.terminal_execution_error = dict(error)
        self.exit_code = failure_exit_code(error)
        self.stop_triggered = True
        self.failed.add(todo_id)
        self.incomplete.add(todo_id)
        if not already_recorded:
            print(f"[fatal] ToDo {todo_id}: {error.get('category', 'technical')}: {error.get('message', '')}")
            print("[info] ToDo bleibt offen. Zwischenstände und Logs prüfen, bevor der Lauf erneut gestartet wird.")
        return replace(outcome, completed=False, abort=True)

    def _handle_todo(self, todo: TodoItem) -> TaskOutcome:
        # A validated plan survives a deliberate restart. Resume its children
        # and final acceptance without replaying the parent's production task.
        plan_path = self.state_dir / "breakdowns" / todo.identifier.replace(".", "_") / "breakdown_plan.json"
        if plan_path.is_file() and not todo.config.get("workspace"):
            try:
                plan = json.loads(read_utf8(plan_path))
                if not isinstance(plan, dict) or not isinstance(plan.get("children"), list):
                    raise ValueError("Invalid plan object")
                planned = [row["id"] for row in plan["children"]]
                # Include earlier waves; unexpected partial children from an
                # unsuccessful later breakdown do not authorize execution.
                for earlier in plan_path.parent.glob("round_*.json"):
                    wave = json.loads(read_utf8(earlier))
                    if not isinstance(wave, dict) or wave.get("parent_id") != todo.identifier:
                        raise ValueError("Invalid saved breakdown wave")
                    planned.extend(row["id"] for row in wave["children"])
                if not all(isinstance(child, str) for child in planned):
                    raise ValueError("Invalid child IDs")
                statuses = self._direct_child_statuses(todo.identifier)
                resumable = (plan.get("schema_version") == "run_todos.breakdown.v3"
                             and plan.get("parent_id") == todo.identifier and planned
                             and set(planned) == set(statuses)
                             and all(child in _direct_child_ids(todo.identifier, planned) for child in planned))
            except (OSError, ValueError, KeyError, TypeError):
                resumable = False
            if not resumable:
                return self._stop_for_execution_error(todo.identifier, TaskOutcome(
                    completed=False, message="Gespeicherter Breakdown-Plan ist ungültig oder ein Kind fehlt.",
                    execution_error=execution_error("Gespeicherten Breakdown-Plan und Kinder prüfen; kein automatisches Parent-Replay.",
                                                    code="invalid_breakdown_resume", phase="continuation")))
            resume_context = self._build_todo_execution_context(todo)
            if not self.dry_run:
                task_text = augment_with_preamble(
                    self._todo_task_prompt(todo, resume_context),
                    resume_context.todo_file, mode=self.todo_preamble,
                )
                self._capture_original_contract(
                    todo.identifier, task_text, resume_context.todo_file,
                    self.run_dir / "todo" / self._sanitize_identifier(todo.identifier) / "continuation",
                )
            result_file = resume_context.target_result_file or resume_context.result_file
            self.pending_reviews[todo.identifier] = (result_file, self._path_for_prompt(result_file))
            self.review_seen_children[todo.identifier] = True
            self.breakdown_rounds[todo.identifier] = self._infer_breakdown_round(todo.identifier, fallback=1)
            print(f"[info] Fortsetzung von {todo.identifier}: vorhandene Kinder und Parent-Abnahme, kein Produktions-Replay.")
            return TaskOutcome(completed=False, message="Validierten Breakdown mit bestehenden Kindern fortsetzen.")
        outcome, context, result_file = self._execute_todo_autobuild(todo)
        if outcome.execution_error:
            return self._stop_for_execution_error(todo.identifier, outcome)
        if outcome.abort or outcome.process_stop_triggered:
            return replace(outcome, completed=False)
        if outcome.completed:
            self._finalize_post_todo_log(outcome)
            self._mark_todo_as_done(todo)
            self.completed.add(todo.identifier)
            self.incomplete.discard(todo.identifier)
            self.failed.discard(todo.identifier)
            self._maybe_git_commit(todo, outcome)
            if context.parallel_group:
                self.completed_parallel_groups.add(context.parallel_group)
            if context.agent:
                self.completed_agents.add(context.agent)
            return outcome
        if outcome.process_stop_triggered:
            self.failed.add(todo.identifier)
            self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
            return outcome

        review_text = (
            (outcome.review_findings or "").strip()
            or outcome.message.strip()
            or "Keine Review-Nachricht erhalten."
        )
        self._record_review(result_file, review_text, todo.identifier)
        classification = _normalize_review_classification_payload(
            outcome.review_classification
            if isinstance(outcome.review_classification, dict)
            else review_text
        )

        # A successful review cannot override a failed execution or another gate.
        if review_classification_passes(classification):
            return self._write_final_failure_process_stop(
                todo_id=todo.identifier, reason_code="autobuild_incomplete_despite_review",
                phase="todo_execution", message="AutoBuild blieb trotz positivem Teilreview unvollständig.",
                classification={"verdict": "FAIL", "blocking_issues": [{
                    "id": "AUTOBUILD-INCOMPLETE", "type": "technical_failure",
                    "summary": "Positive review cannot override an incomplete execution or failed gate.",
                }]}, result_file=result_file, task_outcome=outcome,
            )

        if context.parallel_group:
            self.completed_parallel_groups.add(context.parallel_group)
        if context.workdir != self.workdir:
            return self._write_final_failure_process_stop(
                todo_id=todo.identifier,
                reason_code="isolated_todo_final_failure",
                phase="todo_execution",
                message=(
                    "Ein isolierter Unterworkspace-Auftrag blieb nach den vorgesehenen "
                    "AutoBuild-Versuchen unvollständig; ein zentraler Breakdown ist dort "
                    "nicht sicher materialisierbar."
                ),
                classification=classification,
                result_file=result_file,
                task_outcome=outcome,
            )

        if _breakdown_action(classification) == "blocked":
            return self._write_final_failure_process_stop(
                todo_id=todo.identifier, reason_code="non_decomposable_blocker",
                phase="breakdown_triage", message="Der Blocker ist nicht durch fachlichen Breakdown lösbar.",
                classification=classification, result_file=result_file, task_outcome=outcome,
            )

        current_todo_ids = set(
            _todo_line_map(read_utf8(self.todo_file))
        )
        existing_children = _direct_child_ids(todo.identifier, current_todo_ids)
        if existing_children and todo.identifier not in self.pending_reviews:
            result_prompt_path = self._path_for_prompt(result_file)
            self.pending_reviews[todo.identifier] = (result_file, result_prompt_path)
            self.review_seen_children[todo.identifier] = True
            self.breakdown_rounds[todo.identifier] = max(
                self.breakdown_rounds.get(todo.identifier, 0),
                self._infer_breakdown_round(todo.identifier, fallback=1),
            )
            print(
                f"[info] Vorhandene Unter-ToDos für {todo.identifier} werden wiederverwendet: "
                + ", ".join(existing_children)
            )
            return replace(outcome, review_classification=classification)

        effective_policy = _normalize_breakdown_policy(
            todo.config.get("breakdown"), default=self.breakdown_policy
        )
        if effective_policy == "off":
            return self._write_final_failure_process_stop(
                todo_id=todo.identifier,
                reason_code="breakdown_disabled_final_failure",
                phase="todo_execution",
                message=(
                    f"ToDo {todo.identifier} blieb unvollständig; automatischer Breakdown "
                    "ist für diesen Auftrag deaktiviert."
                ),
                classification=classification,
                result_file=result_file,
                task_outcome=outcome,
            )

        if todo.depth >= self.max_depth:
            return self._write_final_failure_process_stop(
                todo_id=todo.identifier,
                reason_code="maximum_breakdown_depth_reached",
                phase="todo_execution",
                message=(
                    f"ToDo {todo.identifier} blieb unvollständig und hat die maximale "
                    f"ToDo-Tiefe {self.max_depth} erreicht."
                ),
                classification=classification,
                result_file=result_file,
                task_outcome=outcome,
            )

        if todo.identifier not in self.pending_reviews:
            rounds_used = max(self.breakdown_rounds.get(todo.identifier, 0),
                              self._infer_breakdown_round(todo.identifier))
            if rounds_used >= self._effective_breakdown_max_rounds(todo):
                return self._write_final_failure_process_stop(
                    todo_id=todo.identifier, reason_code="maximum_breakdown_rounds_reached",
                    phase="breakdown", message="Das Breakdown-Rundenbudget ist bereits erschöpft.",
                    classification=classification, result_file=result_file, task_outcome=outcome,
                )
            if effective_policy == "legacy":
                before_ids = set(
                    _todo_line_map(read_utf8(self.todo_file))
                )
                breakdown_outcome = self._request_legacy_breakdown(todo, result_file)
                if not breakdown_outcome.completed:
                    if breakdown_outcome.execution_error:
                        return self._stop_for_execution_error(todo.identifier, breakdown_outcome)
                    if breakdown_outcome.process_stop_triggered:
                        return breakdown_outcome
                    return self._write_final_failure_process_stop(
                        todo_id=todo.identifier,
                        reason_code="legacy_breakdown_failed",
                        phase="breakdown",
                        message=breakdown_outcome.message or "Der Legacy-Breakdown blieb unvollständig.",
                        classification=breakdown_outcome.review_classification,
                        result_file=result_file,
                        task_outcome=breakdown_outcome,
                    )
                after_ids = set(
                    _todo_line_map(read_utf8(self.todo_file))
                )
                new_children = _direct_child_ids(
                    todo.identifier, sorted(after_ids - before_ids)
                )
                if not new_children:
                    return self._write_final_failure_process_stop(
                        todo_id=todo.identifier,
                        reason_code="legacy_breakdown_produced_no_children",
                        phase="breakdown",
                        message=(
                            "Der Legacy-Breakdown erzeugte keine direkten Unteraufträge; "
                            "der Elternauftrag bleibt final unvollständig."
                        ),
                        classification=classification,
                        result_file=result_file,
                        task_outcome=outcome,
                    )
                self.breakdown_rounds[todo.identifier] = rounds_used + 1
                self._write_breakdown_plan(todo=todo, policy="legacy", max_children=len(new_children),
                    classification=classification, child_ids=new_children,
                    child_lines=_todo_line_map(read_utf8(self.todo_file)), breakdown_outcome=breakdown_outcome,
                    round_number=self.breakdown_rounds[todo.identifier])
            else:
                breakdown_outcome = self._request_minimal_breakdown(
                    todo=todo,
                    result_file=result_file,
                    outcome=replace(
                        outcome, review_classification=classification
                    ),
                )
                if breakdown_outcome is not None:
                    if breakdown_outcome.execution_error:
                        return self._stop_for_execution_error(todo.identifier, breakdown_outcome)
                    if breakdown_outcome.process_stop_triggered:
                        return breakdown_outcome
                    return self._write_final_failure_process_stop(
                        todo_id=todo.identifier,
                        reason_code="breakdown_failed",
                        phase="breakdown",
                        message=(
                            breakdown_outcome.message
                            or "Der minimale Breakdown konnte nicht gültig materialisiert werden."
                        ),
                        classification=classification,
                        result_file=result_file,
                        task_outcome=breakdown_outcome,
                    )
            result_prompt_path = self._path_for_prompt(result_file)
            self.pending_reviews[todo.identifier] = (result_file, result_prompt_path)
            self.review_seen_children[todo.identifier] = False
        return replace(outcome, review_classification=classification)

    def _effective_breakdown_max_rounds(self, todo: TodoItem) -> int:
        raw = todo.config.get("breakdown_max_rounds")
        if raw is None:
            return self.breakdown_max_rounds
        return _normalize_breakdown_max_rounds(
            raw, default=self.breakdown_max_rounds
        )

    def _infer_breakdown_round(self, parent_id: str, *, fallback: int = 0) -> int:
        target_dir = (
            self.state_dir / "breakdowns" / parent_id.replace(".", "_")
        )
        highest = 0
        if target_dir.is_dir():
            for path in target_dir.glob("round_*.json"):
                match = re.fullmatch(r"round_(\d+)\.json", path.name)
                if match:
                    highest = max(highest, int(match.group(1)))
            latest = target_dir / "breakdown_plan.json"
            if latest.is_file():
                try:
                    payload = json.loads(latest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
                try:
                    highest = max(highest, int(payload.get("round") or 0))
                except (TypeError, ValueError):
                    pass
        return max(highest, fallback)

    def _effective_breakdown_max_children(self, todo: TodoItem) -> int:
        raw = todo.config.get("breakdown_max_children")
        if raw is None:
            return self.breakdown_max_children
        return _normalize_breakdown_max_children(raw, default=self.breakdown_max_children)

    def _request_legacy_breakdown(self, todo: TodoItem, result_file: Path) -> TaskOutcome:
        todo_prompt_path = self._path_for_prompt(self.todo_file)
        result_prompt_path = self._path_for_prompt(result_file)
        scope_guard = (
            self.runtime_profile.breakdown_scope_guard
            if self.runtime_profile_scope_active
            else ""
        )
        review_boundary = (
            self.runtime_profile.legacy_review_boundary
            if self.runtime_profile_scope_active
            and self.runtime_profile.legacy_review_boundary
            else "einschließlich des dort stehenden letzten Review-Berichts."
        )
        breakdown_base = (
            f"Brich das ToDo #{todo.identifier} aus `{todo_prompt_path}` in einzelne ToDos herunter "
            f"und ergänze diese Unter-ToDos in `{todo_prompt_path}`. "
            f"Jede neue ToDo-Ueberschrift muss exakt mit '<unternummer> {self._task_command()}: ' beginnen, "
            f"zum Beispiel '3.1 {self._task_command()}: API erweitern'. "
            f"{scope_guard}"
            f"Berücksichtige dabei die bisherigen Ergebnisse in `{result_prompt_path}` "
            f"{review_boundary}"
        )
        breakdown_text = self._augment_task_prompt(breakdown_base)
        print(f"[info] Unter-ToDos für {todo.identifier} werden im Legacy-Modus angefordert.")
        return self._run_autobuild(f"{todo.identifier}-breakdown", breakdown_text)

    def _request_minimal_breakdown(
        self,
        *,
        todo: TodoItem,
        result_file: Path,
        outcome: TaskOutcome,
        round_number: Optional[int] = None,
    ) -> Optional[TaskOutcome]:
        self._ensure_runtime_tracking_state()
        classification_source: Any
        if isinstance(outcome.review_classification, dict):
            classification_source = outcome.review_classification
        else:
            classification_source = outcome.review_findings or outcome.message
        classification = _normalize_review_classification_payload(classification_source)
        action = _breakdown_action(classification)
        if round_number is None:
            round_number = max(
                self.breakdown_rounds.get(todo.identifier, 0),
                self._infer_breakdown_round(todo.identifier),
            ) + 1
        if round_number > self._effective_breakdown_max_rounds(todo):
            return replace(outcome, completed=False, abort=True,
                           message="Das Breakdown-Rundenbudget ist bereits erschöpft.")
        if action == "complete":
            message = (
                "Der strukturierte Review enthält keine blockierenden Issues. "
                "Es wird kein Breakdown erzeugt."
            )
            print(f"[warn] {message}")
            return replace(outcome, message=message, abort=True)
        if action == "blocked":
            issue_types = sorted(
                {
                    str(item.get("type") or "local_fix").strip()
                    for item in classification.get("blocking_issues", [])
                    if isinstance(item, dict)
                }
            )
            message = (
                f"ToDo {todo.identifier} benötigt keinen fachlichen Breakdown, sondern eine "
                f"separate Blockerbehandlung ({', '.join(issue_types)})."
            )
            print(f"[warn] {message}")
            return replace(outcome, message=message, abort=True)

        max_children = 1 if action == "single_repair" else self._effective_breakdown_max_children(todo)
        before_text = read_utf8(self.todo_file, preserve_newlines=True, preserve_bom=True)
        before_lines = _todo_line_map(before_text)
        before_positions = _todo_line_positions(before_text)
        before_ids = set(before_lines)
        todo_prompt_path = self._path_for_prompt(self.todo_file)
        result_prompt_path = self._path_for_prompt(result_file)
        issue_block = _format_blocking_issues_for_breakdown(classification)
        scope_guard = (
            self.runtime_profile.breakdown_scope_guard
            if self.runtime_profile_scope_active
            else ""
        )
        mode_instruction = (
            "Erzeuge genau einen fokussierten Unterauftrag, der die zusammenhängende blockierende Restarbeit korrigiert."
            if max_children == 1
            else (
                f"Erzeuge die kleinste ausreichende Zahl direkt untergeordneter Unteraufträge, höchstens {max_children}. "
                "Zwei oder mehr Unteraufträge sind nur zulässig, wenn die Restarbeiten wirklich unabhängig prüfbar sind."
            )
        )
        breakdown_base = (
            f"Bearbeite ausschließlich die noch offene Restarbeit von ToDo #{todo.identifier} "
            f"in Breakdown-Runde {round_number}. "
            f"aus `{todo_prompt_path}`. Ergänze die erforderlichen direkten Unter-ToDos in dieselbe Datei. "
            f"{mode_instruction} "
            f"Jede neue Überschrift muss exakt mit '<parent>.<nummer> {self._task_command()}: ' beginnen. "
            "Erzeuge keine verschachtelten Enkel-ToDos in diesem Lauf. "
            "Wiederhole keine bereits gültig erledigte Arbeit. Zerlege nicht je Aufzählungspunkt, "
            "Outputdatei, Tabellenabschnitt oder Reviewerbullet. Jeder Unterauftrag muss ein klares Ziel, "
            "ein konkretes Ergebnis und ein überprüfbares Abnahmekriterium enthalten. "
            "Die Summe der Unteraufträge darf Scope, Detailtiefe, Outputs, Rechte oder Abnahmestandard "
            "des Elternauftrags nicht erweitern. "
            f"{scope_guard}"
            f"Maßgeblich sind ausschließlich diese blockierenden Issues:\n{issue_block}\n\n"
            f"Die bisherige Ergebnisdatei `{result_prompt_path}` dient nur als Laufhistorie. "
            "Nicht blockierende Beobachtungen und theoretische Verbesserungen sind nicht in Unteraufträge umzusetzen."
        )
        breakdown_text = self._augment_task_prompt(breakdown_base)
        print(
            f"[info] Minimaler Breakdown für {todo.identifier} wird angefordert "
            f"(max_children={max_children}, action={action})."
        )
        breakdown_run = self._run_autobuild(
            f"{todo.identifier}-breakdown",
            breakdown_text,
        )
        # Partial file edits do not prove that the breakdown or its mandatory
        # review succeeded. Preserve those edits for inspection, but do not
        # validate a plan or schedule children after a failed execution.
        if not breakdown_run.completed:
            return breakdown_run
        after_text = read_utf8(self.todo_file)
        after_lines = _todo_line_map(after_text)
        after_positions = _todo_line_positions(after_text)
        after_ids = set(after_lines)
        new_ids = sorted(after_ids - before_ids)

        validation_errors: List[str] = []
        missing_existing = sorted(before_ids - after_ids)
        if missing_existing:
            validation_errors.append(
                "Bestehende ToDo-IDs wurden entfernt: " + ", ".join(missing_existing)
            )
        changed_existing = sorted(
            identifier
            for identifier in before_ids & after_ids
            if before_lines[identifier] != after_lines[identifier]
        )
        if changed_existing:
            validation_errors.append(
                "Bestehende ToDo-Überschriften wurden verändert: "
                + ", ".join(changed_existing)
            )
        direct_children = _direct_child_ids(todo.identifier, new_ids)
        if set(direct_children) != set(new_ids):
            invalid = sorted(set(new_ids) - set(direct_children))
            validation_errors.append(
                "Neue IDs sind keine direkten Kinder des Eltern-ToDos: "
                + ", ".join(invalid)
            )
        if not direct_children:
            validation_errors.append("Es wurde kein direkter Unterauftrag erzeugt.")
        if len(direct_children) > max_children:
            validation_errors.append(
                f"Es wurden {len(direct_children)} Unteraufträge erzeugt; erlaubt sind höchstens {max_children}."
            )

        parent_position = before_positions.get(todo.identifier)
        next_existing_positions = [
            position
            for identifier, position in before_positions.items()
            if parent_position is not None and position > parent_position
        ]
        next_existing_position_after = (
            min(
                after_positions[identifier]
                for identifier, position in before_positions.items()
                if parent_position is not None
                and position > parent_position
                and identifier in after_positions
            )
            if next_existing_positions
            else None
        )
        if parent_position is not None:
            parent_position_after = after_positions.get(todo.identifier, -1)
            for child_id in direct_children:
                child_position = after_positions.get(child_id, -1)
                if child_position <= parent_position_after:
                    validation_errors.append(
                        f"Unterauftrag {child_id} wurde nicht nach dem Elternauftrag eingefügt."
                    )
                if (
                    next_existing_position_after is not None
                    and child_position >= next_existing_position_after
                ):
                    validation_errors.append(
                        f"Unterauftrag {child_id} wurde außerhalb des Elternblocks eingefügt."
                    )

        protected_markers = (
            self.runtime_profile.protected_markers
            if self.runtime_profile_scope_active
            else ()
        )
        for marker_name in protected_markers:
            before_block = _extract_marked_block(before_text, marker_name)
            after_block = _extract_marked_block(after_text, marker_name)
            if before_block is not None and before_block != after_block:
                validation_errors.append(
                    f"Geschützter Block {marker_name} wurde verändert."
                )

        if validation_errors:
            self._atomic_write_text(self.todo_file, before_text)
            message = (
                "Ungültiger Breakdown wurde verworfen und die ToDo-Datei wiederhergestellt: "
                + " | ".join(validation_errors)
            )
            print(f"[warn] {message}")
            return replace(outcome, message=message, abort=True)

        self._write_breakdown_plan(
            todo=todo,
            policy="minimal",
            max_children=max_children,
            classification=classification,
            child_ids=direct_children,
            child_lines=after_lines,
            breakdown_outcome=breakdown_run,
            round_number=round_number,
        )
        self.breakdown_rounds[todo.identifier] = int(round_number)
        print(
            f"[ok]   Minimaler Breakdown für {todo.identifier}: "
            + ", ".join(direct_children)
        )
        return None

    def _write_breakdown_plan(
        self,
        *,
        todo: TodoItem,
        policy: str,
        max_children: int,
        classification: Mapping[str, Any],
        child_ids: Sequence[str],
        child_lines: Mapping[str, Tuple[str, str]],
        breakdown_outcome: TaskOutcome,
        round_number: int = 1,
    ) -> Path:
        target_dir = self.state_dir / "breakdowns" / todo.identifier.replace(".", "_")
        safe_io.mkdir(target_dir)
        target = target_dir / "breakdown_plan.json"
        round_target = target_dir / f"round_{int(round_number):03d}.json"
        payload = {
            "schema_version": "run_todos.breakdown.v3",
            "round": int(round_number),
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "parent_id": todo.identifier,
            "policy": policy,
            "max_children": max_children,
            "review_classification": dict(classification),
            "children": [
                {
                    "id": child_id,
                    "status": child_lines[child_id][0],
                    "title": child_lines[child_id][1],
                }
                for child_id in child_ids
            ],
            "autobuild_summary_json": (
                str(breakdown_outcome.summary_json)
                if breakdown_outcome.summary_json is not None
                else None
            ),
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._atomic_write_text(round_target, serialized)
        self._atomic_write_text(target, serialized)
        self.plan_authority.accept_children(todo.identifier, max_children)
        return target


    def _lint_todo_before_autobuild(self, *, todo_file: Path, workdir: Path) -> None:
        lint_issues = lint_todo_file(todo_file, workdir=workdir)
        if not lint_issues:
            return
        max_issues = 15
        details = [
            f"- Zeile {issue.line}: {issue.message}"
            for issue in lint_issues[:max_issues]
        ]
        if len(lint_issues) > max_issues:
            details.append(
                f"- ... und {len(lint_issues) - max_issues} weitere Probleme."
            )
        todo_display = self._path_for_prompt(todo_file, workspace=workdir)
        detail_block = "\n".join(details)
        error_type = (codex_policy.CodexPolicyError
                      if any(issue.code == "codex_policy" for issue in lint_issues) else RuntimeError)
        raise error_type(
            "ToDo-Lint fehlgeschlagen vor AutoBuild-Aufruf "
            f"(Datei `{todo_display}`).\n"
            "Bitte korrigiere die ToDo-Liste, bevor der Lauf fortgesetzt wird:\n"
            f"{detail_block}"
        )

    def _autobuild_python_attempt(self, task_text, workdir, options, context):
        """One isolated worker for retained CFG parallel groups; never a TodoRunner."""
        summary_path = Path(options.summary_json)
        request_path = summary_path.with_name(f"call_{uuid.uuid4().hex}.json")
        self._atomic_write_text(request_path, json.dumps(call_payload(
            task=task_text, workdir=workdir, options=options, context=context), ensure_ascii=False, indent=2) + "\n")
        if summary_path.exists():
            summary_path.unlink()
        command = [sys.executable, str(self.repo_root / "autobuild.py"),
                   "--request-json", str(request_path)]
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, shell=False, cwd=workdir,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        # Keep the worker's own streams too; Codex streams stay in its capture archive.
        worker_streams = {}
        for name, value in (("stdout", process.stdout), ("stderr", process.stderr)):
            raw = value.encode("utf-8") if isinstance(value, str) else value
            safe_io.write_bytes(summary_path.parent / f"worker_{name}.log", raw)
            worker_streams[name] = raw.decode("utf-8", errors="replace")
        error_code = "invalid_autobuild_summary"
        payload = {}
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
            validate_result(payload)
            error_code = "autobuild_exit_mismatch"
            validate_result(payload, process_exit_code=process.returncode)
        except (OSError, ValueError) as exc:
            error = execution_error(f"AutoBuild worker: {exc}", code=error_code,
                                    phase="autobuild", process_exit_code=process.returncode)
            payload = dict(payload) if isinstance(payload, dict) else {}
            payload.update(completed=False, execution_error=error, exit_code=7, status="failed",
                           process_stop_triggered=False, review_required=True)
            if not isinstance(payload.get("last_answer"), str):
                payload["last_answer"] = worker_streams["stderr"].strip() or worker_streams["stdout"].strip()
            # Preserve the child file (including malformed/contradictory bytes).
            self._atomic_write_text(summary_path.with_suffix(".boundary_error.json"),
                                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        payload["summary_json_path"] = str(summary_path)
        return SimpleNamespace(**payload)

    def _call_budget_for(self, todo_id: str) -> CallBudget:
        # Descendants, breakdown and parent reviews share their numeric root.
        # Allocate once in the controller before starting concurrent workers.
        root_id = todo_id.split(".", 1)[0]
        with self.call_budget_lock:
            if root_id not in self.call_budgets:
                directory = self.state_dir / "call_budgets" / f"task_{root_id}"
                self.call_budgets[root_id] = CallBudget(directory, self.max_calls, root_id)
            return self.call_budgets[root_id]

    def _capture_original_contract(
        self, todo_id: str, task_text: str, todo_file: Path, log_dir: Path
    ) -> None:
        # Capture before production or resumed children; a new runner uses
        # its current task and effective preamble, never another run's contract.
        if not hasattr(self, "review_contracts"):
            self.review_contracts = {}
        if todo_id not in self.review_contracts:
            snapshot = snapshot_todo(
                read_input_text(todo_file), task_id=todo_id,
                reference_prompt=task_text, attempt_prompt=task_text,
                source=str(todo_file),
            )
            contract_text = json.dumps({
                "schema_version": "arquilo.review_contract.v1",
                "original_request": task_text, "task_text": snapshot.task_text,
                "source": str(todo_file),
            }, ensure_ascii=False, indent=2) + "\n"
            contract_path = log_dir / "original_contract.json"
            write_log_text(contract_path, contract_text)
            self.review_contracts[todo_id] = (contract_path, contract_text)

    def _run_autobuild(self, identifier: str, task_text: str, **kwargs) -> TaskOutcome:
        self.plan_authority.check()
        active_file = kwargs.get("todo_file_override") or self.todo_file
        before = read_utf8(active_file)
        outcome = self._run_autobuild_impl(identifier, task_text, **kwargs)
        if self.dry_run:
            return outcome
        is_breakdown = identifier == self._derive_todo_id_from_identifier(identifier) + "-breakdown"
        try:
            if is_breakdown and outcome.completed:
                if active_file != self.todo_file:
                    raise PlanIntegrityError("Breakdown may only modify the primary plan")
                self.plan_authority.verify_children(self._derive_todo_id_from_identifier(identifier))
            else:
                self.plan_authority.check()
                if read_utf8(active_file) != before:
                    raise PlanIntegrityError("Worker changed its copied task plan")
        except (PlanIntegrityError, safe_io.UnsafePathError, OSError) as exc:
            return replace(outcome, completed=False, abort=True,
                message=str(exc), execution_error=execution_error(str(exc),
                    code="unapproved_plan_mutation", phase="controller_acceptance"))
        return outcome

    def _run_autobuild_impl(
        self,
        identifier: str,
        task_text: str,
        *,
        workdir_override: Optional[Path] = None,
        model_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        extra_args: Optional[Sequence[str]] = None,
        process_stop_override: Optional[Path] = None,
        use_cli_subprocess: bool = False,
        todo_file_override: Optional[Path] = None,
        result_file_override: Optional[Path] = None,
        network_access_override: Optional[bool] = None,
        config_profile: Optional[str] = None,
        sandbox_override: Optional[str] = None,
    ) -> TaskOutcome:
        codex_policy.validate_start_policy(sandbox=self.sandbox, network_access=self.network_access)
        active_network_access = self.network_access
        if network_access_override is not None:
            codex_policy.validate_network_access(network_access_override)
            active_network_access = codex_policy.effective_network_access(
                self.network_access, str(network_access_override).lower())
        else:
            # Breakdown/parent calls inherit the original task's tighter CFG too.
            policy_todo = self._find_open_todo_item(self._derive_todo_id_from_identifier(identifier))
            if policy_todo is not None:
                active_network_access = codex_policy.effective_network_access(
                    self.network_access, policy_todo.config.get("network_access"))
                if config_profile is None:
                    config_profile = policy_todo.config.get("agent")
        codex_policy.validate_config_profile(config_profile)
        codex_policy.validate_extra_args(extra_args)
        active_sandbox = codex_policy.validate_sandbox(
            self.sandbox if sandbox_override is None else sandbox_override)
        active_workdir = safe_io.check_path(workdir_override or self.workdir, missing_ok=False)
        if not active_workdir.is_relative_to(self.workdir):
            raise codex_policy.CodexPolicyError("AutoBuild-Unterworkspace muss innerhalb des Runner-Workspaces liegen.")
        active_todo_file = safe_io.check_path(todo_file_override or self.todo_file, missing_ok=False)
        self._lint_todo_before_autobuild(
            todo_file=active_todo_file,
            workdir=active_workdir,
        )
        # Keep the reference request intact. This one boundary covers tasks,
        # breakdown, parent review and the optional Python worker alike.
        task_text = augment_with_preamble(
            task_text, active_todo_file, mode=self.todo_preamble
        )
        active_model = _resolve_codex_model(
            model_override if model_override is not None else self.model
        )
        active_reasoning_effort = _resolve_codex_reasoning_effort(
            reasoning_effort_override
            if reasoning_effort_override is not None
            else self.reasoning_effort
        )
        active_extra_args = list(extra_args or [])
        active_process_stop = process_stop_override or self.process_stop_path
        session_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        process_stop_blocking = self._process_stop_active()
        if not process_stop_blocking and active_process_stop != self.process_stop_path:
            process_stop_blocking = active_process_stop.exists()
        if process_stop_blocking:
            details = self._read_process_stop_details(active_process_stop)
            message = (
                "process_stop-Datei blockiert weitere AutoBuild-Läufe. "
                "Prüfe den Inhalt der Stopdatei und den dort verlinkten Diagnosebericht. "
                "Beantworte `todo_fragen.md` nur, wenn dort ausdrücklich eine Nutzerfrage "
                "dokumentiert ist; behebe andernfalls den technischen oder fachlichen "
                "Vertragsfehler, bevor Du die Stopdatei entfernst."
            )
            if details:
                message += f"\nHinweis: {details}"
            return TaskOutcome(
                completed=False,
                message=message,
                process_stop_triggered=True,
            )
        todo_id, log_record, log_dir = self._prepare_task_log(
            identifier, session_stamp, active_workdir, active_todo_file,
            result_file=result_file_override or self._result_file_for_todo(todo_id=self._derive_todo_id_from_identifier(identifier)))
        if not self.dry_run:
            write_log_text(log_dir / "prompt.md", task_text)
            self._capture_original_contract(todo_id, task_text, active_todo_file, log_dir)
        preview_log, preview_raw, preview_summary = self._attempt_log_paths(
            log_dir, attempt=1, ensure_directories=False)
        command_preview = (
            f"autobuild.start(task=<Referenzprompt>, workdir={str(active_workdir)!r}, "
            f"options=AutoBuildOptions(sandbox={active_sandbox!r}, network_access={active_network_access!r}, "
            f"model={active_model!r}, reasoning_effort={active_reasoning_effort!r}, "
            f"max_steps={self.max_steps * self.max_retries}, max_calls={self.max_calls}, summary_json={str(preview_summary)!r}), "
            f"context=AutoBuildContext(task_source='todo', todo_identifier={identifier!r}))"
        )
        if self.dry_run:
            marker = (
                "Simulierter Fehlschlag"
                if identifier in self.simulated_incomplete
                else "Simulierter Erfolg"
            )
            note_lines = [
                marker,
                "Vollständiger AutoBuild-Auftrag:\n\n" + task_text,
            ]
            note = "\n".join(note_lines)
            self.recorder.record(identifier, command_preview, note=note)
            completed = identifier not in self.simulated_incomplete
            message = (
                "Dry-run: simuliert incomplete."
                if not completed
                else "Dry-run: simuliert erfolgreich."
            )
            outcome = TaskOutcome(
                completed=completed,
                message=message,
                session_stamp=session_stamp,
                attempt=0,
                pretty_log=preview_log,
                raw_log=preview_raw,
                summary_json=preview_summary,
                summary_json_attempts=[preview_summary],
            )
            outcome = self._attach_log_metadata(
                outcome,
                todo_id=todo_id,
                log_record=log_record,
                session_stamp=session_stamp,
                log_dir=log_dir,
            )
            return outcome


        last_message = ""
        last_pretty: Optional[Path] = None
        last_raw: Optional[Path] = None
        last_summary: Optional[Path] = None
        last_attempt: Optional[int] = None
        summary_paths: List[Path] = []
        last_execution_error: Optional[Dict[str, Any]] = None
        # Historical max_retries now extends this single continuation loop;
        # it must never replay the original request after possible side effects.
        budget = self._call_budget_for(todo_id)
        for attempt in (1,):
            pretty_log, raw_log, summary_json = self._attempt_log_paths(
                log_dir, attempt=attempt, ensure_directories=True
            )
            print(f"[exec] (1/1, Fortsetzungsschritte={self.max_steps * self.max_retries}) {task_text}")
            options = AutoBuildOptions(
                sandbox=active_sandbox, network_access=active_network_access,
                config_profile=config_profile, extra_arg=active_extra_args,
                logfile=pretty_log, rawlog=raw_log, summary_json=summary_json,
                max_steps=self.max_steps * self.max_retries, max_calls=budget.limit,
                model=active_model, reasoning_effort=active_reasoning_effort,
                process_stop_path=active_process_stop,
            )
            context = AutoBuildContext(
                task_source="todo", todo_identifier=identifier, decision_todo_file=active_todo_file,
                decision_run_id=self.run_id, decision_attempt_id=f"{log_dir.name}.{attempt}",
                decision_phase="completion" if identifier == todo_id else identifier,
                review_policy_rules=(self.runtime_profile.autobuild_review_rules
                                     if self.runtime_profile_active else None),
                budget_directory=budget.directory, budget_root_id=budget.root_id,
            )
            try:
                if use_cli_subprocess:
                    summary = self._autobuild_python_attempt(task_text, active_workdir, options, context)
                else:
                    summary = autobuild_start(task=task_text, workdir=active_workdir,
                                              options=options, context=context)
                validate_result(autobuild_summary_document(summary) if not use_cli_subprocess else vars(summary))
            except ProcessStopActiveError as exc:
                message = str(exc).strip() or "process_stop verhindert diesen Lauf."
                outcome = TaskOutcome(
                    completed=False,
                    message=message,
                    process_stop_triggered=True,
                    session_stamp=session_stamp,
                    attempt=attempt,
                    pretty_log=pretty_log,
                    raw_log=raw_log,
                    summary_json=None,
                    summary_json_attempts=list(summary_paths),
                )
                outcome = self._attach_log_metadata(
                    outcome,
                    todo_id=todo_id,
                    log_record=log_record,
                    session_stamp=session_stamp,
                    log_dir=log_dir,
                )
                self._record_task_io(outcome, log_record=log_record)
                return outcome
            except (Exception, KeyboardInterrupt) as exc:
                summary = autobuild_failure_summary(exc, workdir=active_workdir, options=options)
            last_message = summary.last_answer.strip()
            last_pretty = pretty_log
            last_raw = raw_log
            summary_path = Path(summary.summary_json_path or summary_json)
            summary_paths.append(summary_path)
            last_summary = summary_path
            last_attempt = attempt
            error_value = getattr(summary, "execution_error", None)
            if isinstance(error_value, dict):
                last_execution_error = dict(error_value)
                self.terminal_execution_error = dict(error_value)
                break  # never replay the entire task automatically after a technical failure
            if summary.process_stop_triggered:
                break
            if summary.completed is True:
                outcome = TaskOutcome(
                    completed=True,
                    message=last_message,
                    process_stop_triggered=bool(summary.process_stop_triggered),
                    session_stamp=session_stamp,
                    attempt=attempt,
                    pretty_log=pretty_log,
                    raw_log=raw_log,
                    summary_json=last_summary,
                    summary_json_attempts=list(summary_paths),
                    review_findings=getattr(summary, "review_findings", None),
                    review_classification=(dict(summary.review_classification) if isinstance(getattr(summary, "review_classification", None), dict) else None),
                    decision=(dict(summary.decision) if isinstance(getattr(summary, "decision", None), dict) else None),
                    call_budget=getattr(summary, "call_budget", None),
                )
                outcome = self._attach_log_metadata(
                    outcome,
                    todo_id=todo_id,
                    log_record=log_record,
                    session_stamp=session_stamp,
                    log_dir=log_dir,
                )
                self._record_task_io(outcome, log_record=log_record)
                return outcome
        outcome = TaskOutcome(
            completed=False,
            message=last_message,
            execution_error=last_execution_error,
            abort=last_execution_error is not None,
            process_stop_triggered=(
                bool(summary.process_stop_triggered) if summary else False
            ),
            session_stamp=session_stamp,
            attempt=last_attempt,
            pretty_log=last_pretty,
            raw_log=last_raw,
            summary_json=last_summary,
            summary_json_attempts=list(summary_paths),
            review_findings=getattr(summary, "review_findings", None) if summary else None,
            review_classification=(dict(summary.review_classification) if summary and isinstance(getattr(summary, "review_classification", None), dict) else None),
            decision=(dict(summary.decision) if summary and isinstance(getattr(summary, "decision", None), dict) else None),
            call_budget=getattr(summary, "call_budget", None),
            budget_exhausted=getattr(summary, "budget_exhausted", None),
        )
        outcome = self._attach_log_metadata(
            outcome,
            todo_id=todo_id,
            log_record=log_record,
            session_stamp=session_stamp,
            log_dir=log_dir,
        )
        self._record_task_io(outcome, log_record=log_record)
        if outcome.budget_exhausted and not outcome.execution_error and not outcome.process_stop_triggered:
            return self._write_final_failure_process_stop(
                todo_id=todo_id, reason_code="shared_call_budget_exhausted", phase=identifier,
                message="Das gemeinsame Modellaufrufbudget ist erschöpft; die Pflichtabnahme fehlt.",
                classification=outcome.review_classification, task_outcome=outcome,
            )
        return outcome

    def _build_run_config_payload(self) -> Dict[str, Any]:
        started_at = self._format_timestamp(self.run_started_at)
        payload: Dict[str, Any] = {
            "schema_version": RUN_CONFIG_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": started_at,
            "todo_file": str(self.todo_file),
            "todo_file_source": str(self.todo_source_file),
            "workdir": str(self.workdir),
            "controller_state": str(self.state_dir),
            "sandbox": self.sandbox,
            "network_access": self.network_access,
            "dry_run": self.dry_run,
            "limits": {
                "max_depth": self.max_depth,
                "max_retries": self.max_retries,
                "max_steps": self.max_steps,
                "max_calls": self.max_calls,
                "continuation_steps": self.max_steps * self.max_retries,
                "breakdown_policy": self.breakdown_policy,
                "breakdown_max_children": self.breakdown_max_children,
                "breakdown_max_rounds": self.breakdown_max_rounds,
            },
            "start_id": self.start_id,
            "stop_id": self.stop_id,
            "simulated_incomplete": sorted(self.simulated_incomplete),
            "python_version": self.python_version,
            "questions_file": str(self.questions_file),
            "process_stop_path": str(self.process_stop_path),
            "policy_file": str(self.policy_workspace_file),
            "todo_directives": {
                "enabled": True,
                "syntax": "***CFG ...*** / ***WAIT ...*** / ***STOP*** / ***SYNTAX marked-en***",
                "task_command_style": self.todo_syntax,
                "todo_preamble": self.todo_preamble,
            },
        }
        if self.model:
            payload["model"] = self.model
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.git_enabled:
            payload["git"] = {
                "enabled": True,
                "repo_root": str(self.git_repo_root) if self.git_repo_root else None,
            }
        return payload

    def _write_run_config(self) -> None:
        if self.run_config_payload is None:
            raise RuntimeError("run_config payload not initialized")
        write_log_json(self.run_config_path, self.run_config_payload)

    def _format_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        iso_text = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return iso_text

    def _record_review(
        self, result_path: Path, review_text: str, identifier: str
    ) -> None:
        target_display = self._path_for_prompt(result_path)
        print(
            f"[info] Rückmeldung für {identifier} wird in `{target_display}` protokolliert."
        )
        if self.dry_run:
            note = f"Würde Review-Abschnitt aktualisieren mit:\n{review_text}"
            self.recorder.record(
                f"{identifier}-review", f"update {result_path}", note=note
            )
            return
        if not result_path.exists():
            header = f"# ToDo {identifier.split('.')[0]}\n\n"
            self._atomic_write_text(result_path, header)
        content = result_path.read_text(encoding="utf-8")
        heading = "## Letztes Reviewer Feedback"
        new_section = f"{heading}\n\n{review_text.strip()}\n"
        pattern = re.compile(rf"{re.escape(heading)}\n.*?(?=\n## |\Z)", re.DOTALL)
        if pattern.search(content):
            content = pattern.sub(new_section, content)
        else:
            if not content.endswith("\n"):
                content += "\n"
            content += "\n" + new_section
        self._atomic_write_text(result_path, content)

    def _is_directive_line(self, line: str) -> bool:
        return bool(self.DIRECTIVE_PATTERN.match(line.strip()))

    def _collect_directive_lines(
        self, lines: Sequence[str], *, todo_line_index: int,
        visible: Optional[Mapping[int, str]] = None,
    ) -> List[str]:
        if visible is None:
            visible = dict(visible_lines("\n".join(lines)))
        collected: List[str] = []
        cursor = todo_line_index - 1
        while cursor >= 0:
            stripped = visible.get(cursor, "").strip()
            if not stripped:
                break
            if not self._is_directive_line(stripped):
                break
            collected.append(stripped)
            cursor -= 1
        collected.reverse()
        return collected

    def _parse_key_value_tokens(self, tokens: Sequence[str]) -> Dict[str, str]:
        params: Dict[str, str] = {}
        for token in tokens:
            if "=" not in token:
                continue
            key, raw_value = token.split("=", 1)
            key = key.strip().lower()
            value = raw_value.strip()
            if not key:
                continue
            params[key] = value
        return params

    def _parse_duration_seconds(self, raw_value: str) -> Optional[int]:
        value = raw_value.strip().lower()
        if not value:
            return None
        match = re.match(r"^(\d+)([smhd]?)$", value)
        if not match:
            return None
        number = int(match.group(1))
        unit = match.group(2) or "s"
        factor = 1
        if unit == "m":
            factor = 60
        elif unit == "h":
            factor = 3600
        elif unit == "d":
            factor = 86400
        return number * factor

    def _directive_bool_value(self, raw_value: str) -> Optional[bool]:
        value = raw_value.strip().lower()
        truthy = {"1", "true", "yes", "on"}
        falsy = {"0", "false", "no", "off"}
        if value in truthy:
            return True
        if value in falsy:
            return False
        return None

    def _parse_directive_block(
        self, directives: Sequence[str], *, todo_id: str
    ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
        cfg: Dict[str, str] = {}
        waits: List[Dict[str, Any]] = []
        for directive in directives:
            if directive.strip().upper().startswith("***SYNTAX "):
                continue
            match = self.DIRECTIVE_PATTERN.match(directive.strip())
            if not match:
                continue
            body = match.group(1).strip()
            if not body:
                continue
            if directive.strip() == self.STOP_SENTINEL:
                continue
            try:
                tokens = directive_tokens(body)
            except ValueError as exc:
                print(
                    f"[warn] Ungültige Directive vor ToDo {todo_id}: {directive} ({exc})"
                )
                continue
            if not tokens:
                continue
            command = tokens[0].upper()
            params = self._parse_key_value_tokens(tokens[1:])
            if command == "CFG":
                codex_policy.reject_policy_keys(params, source="CFG")
                for key, value in params.items():
                    if key not in self.CFG_ALLOWED_KEYS:
                        print(
                            f"[warn] Unbekannter CFG-Parameter vor ToDo {todo_id}: {key}"
                        )
                        continue
                    normalized_key = "web_search" if key == "websearch" else key
                    cfg[normalized_key] = value
                continue
            if command == "WAIT":
                wait_params: Dict[str, Any] = {}
                for key in self.WAIT_ALLOWED_KEYS:
                    if key in params:
                        wait_params[key] = params[key]
                validate_removed_directives(directive)
                if "on" not in wait_params:
                    print(
                        f"[warn] WAIT-Directive vor ToDo {todo_id} ignoriert (on=... fehlt)."
                    )
                    continue
                mode = str(wait_params.get("mode", "all")).strip().lower()
                if mode not in {"all", "any"}:
                    mode = "all"
                on_timeout = str(wait_params.get("on_timeout", "stop")).strip().lower()
                if on_timeout not in {"stop", "continue"}:
                    on_timeout = "stop"
                timeout_seconds: Optional[int] = None
                if "timeout" in wait_params:
                    timeout_seconds = self._parse_duration_seconds(
                        str(wait_params["timeout"])
                    )
                waits.append(
                    {
                        "on": str(wait_params["on"]).strip(),
                        "mode": mode,
                        "timeout_seconds": timeout_seconds,
                        "on_timeout": on_timeout,
                    }
                )
                continue
            print(
                f"[warn] Unbekannte Directive vor ToDo {todo_id}: {tokens[0]} (ignoriert)."
            )
        return cfg, waits

    def _resolve_directive_workspace(self, raw_value: str) -> Path:
        validate_path(raw_value, label="CFG workspace")
        resolved = safe_io.check_path(self.workdir / Path(raw_value).expanduser())
        try:
            resolved.relative_to(self.workdir)
        except ValueError as exc:
            raise codex_policy.CodexPolicyError(
                f"Directive workspace '{raw_value}' liegt außerhalb des Workspaces: {resolved}"
            ) from exc
        return resolved

    def _copy_file_if_exists(self, source: Path, target: Path) -> None:
        if not source.exists() or not source.is_file():
            return
        try:
            if source.resolve() == target.resolve():
                return
        except OSError:
            pass
        safe_io.mkdir(target.parent)
        safe_io.write_bytes(target, safe_io.read_bytes(source))

    def _read_text_file_if_exists(self, path: Path) -> Optional[str]:
        if not path.exists() or not path.is_file():
            return None
        try:
            return read_utf8(path)
        except OSError:
            return None

    def _merge_text_back_to_primary(
        self,
        *,
        source: Path,
        target: Path,
        base_content: Optional[str],
        label: str,
    ) -> None:
        source_text = self._read_text_file_if_exists(source)
        if source_text is None:
            return
        try:
            if source.resolve() == target.resolve():
                return
        except OSError:
            pass
        target_text = self._read_text_file_if_exists(target)
        if target_text is None:
            safe_io.mkdir(target.parent)
            self._atomic_write_text(target, source_text)
            return
        if source_text == target_text:
            return
        if base_content is not None and source_text == base_content:
            return
        if base_content is not None and target_text == base_content:
            self._atomic_write_text(target, source_text)
            return
        if (
            base_content is not None
            and source_text.startswith(base_content)
            and target_text.startswith(base_content)
        ):
            delta = source_text[len(base_content) :]
            if not delta or delta in target_text:
                return
            merged = target_text
            if merged and not merged.endswith("\n") and not delta.startswith("\n"):
                merged += "\n"
            merged += delta
            self._atomic_write_text(target, merged)
            return
        fallback = source_text.strip()
        if not fallback or fallback in target_text:
            return
        merged = target_text
        if merged and not merged.endswith("\n"):
            merged += "\n"
        merged += f"\n### Sync-Ergebnis ({label})\n\n{fallback}\n"
        self._atomic_write_text(target, merged)

    def _sync_workspace_support_files(self, workspace: Path) -> Tuple[Path, Path, Path]:
        if workspace == self.workdir:
            return self.todo_file, self.questions_file, self.policy_workspace_file
        todo_rel = self._relative_to_workspace(self.todo_file)
        if todo_rel == self.todo_file:
            todo_rel = Path("documents") / "todos" / self.todo_file.name
        todo_target = workspace / todo_rel
        safe_io.mkdir(todo_target.parent)
        safe_io.write_bytes(todo_target, safe_io.read_bytes(self.todo_file))

        for result_file in sorted(self.workspace_todo_dir.glob("todo_result_*.md")):
            self._copy_file_if_exists(
                result_file, todo_target.parent / result_file.name
            )
        self._copy_file_if_exists(
            self.questions_file, todo_target.parent / "todo_fragen.md"
        )

        policy_rel = self._relative_to_workspace(self.policy_workspace_file)
        if policy_rel == self.policy_workspace_file:
            policy_rel = Path("config") / "policy.md"
        policy_target = workspace / policy_rel
        if self.policy_workspace_file.exists():
            self._copy_file_if_exists(self.policy_workspace_file, policy_target)
        else:
            safe_io.mkdir(policy_target.parent)
            safe_io.write_text(policy_target, "", exclusive=True)
        return todo_target, todo_target.parent / "todo_fragen.md", policy_target

    def _build_websearch_extra_args(self, cfg: Mapping[str, str]) -> List[str]:
        args: List[str] = []
        search_mode_raw = cfg.get("web_search")
        if search_mode_raw:
            mode = search_mode_raw.strip().lower()
            if mode in {"live", "cached", "disabled"}:
                args.extend(["-c", f'web_search="{mode}"'])
            else:
                print(
                    f"[warn] Unbekannter web_search-Wert '{search_mode_raw}' – ignoriert."
                )
        return args


    def _build_todo_execution_context(self, todo: TodoItem) -> TodoExecutionContext:
        cfg = dict(todo.config)
        codex_policy.reject_policy_keys(cfg, source="CFG")
        network_access = codex_policy.effective_network_access(self.network_access, cfg.get("network_access"))
        codex_policy.validate_config_profile(cfg.get("agent"))
        workdir = self.workdir
        if "workspace" in cfg and cfg["workspace"].strip():
            workdir = self._resolve_directive_workspace(cfg["workspace"])
            safe_io.mkdir(workdir)
        todo_file, questions_file, policy_file = self._sync_workspace_support_files(
            workdir
        )
        target_result_file = self._result_file_for_todo_context(todo, cfg)
        result_file = todo_file.parent / target_result_file.name
        result_seed_content = self._read_text_file_if_exists(result_file)
        questions_seed_content = self._read_text_file_if_exists(questions_file)
        process_stop_path = self.process_stop_path
        if workdir != self.workdir:
            process_stop_path = workdir / "process_stop"
        # A run-level CLI/environment override is authoritative for every
        # ToDo in this invocation. Per-ToDo CFG model selection remains the
        # fallback only when no run-level override was supplied.
        model = self.model if self.model is not None else cfg.get("model")
        if isinstance(model, str):
            model = model.strip() or None
        reasoning_effort = self.reasoning_effort
        agent = cfg.get("agent")
        if isinstance(agent, str):
            agent = agent.strip() or None
        parallel_group = cfg.get("parallel")
        if isinstance(parallel_group, str):
            parallel_group = parallel_group.strip() or None
        extra_args = self._build_websearch_extra_args(cfg)
        return TodoExecutionContext(
            workdir=workdir,
            todo_file=todo_file,
            result_file=result_file,
            questions_file=questions_file,
            process_stop_path=process_stop_path,
            policy_file=policy_file,
            model=model,
            reasoning_effort=reasoning_effort,
            agent=agent,
            parallel_group=parallel_group,
            extra_args=extra_args,
            target_result_file=target_result_file,
            result_seed_content=result_seed_content,
            questions_seed_content=questions_seed_content,
            todo_identifier=todo.identifier,
            network_access=network_access,
        )

    def _sync_context_back_to_primary_workspace(
        self,
        context: TodoExecutionContext,
        *,
        target_result_file: Optional[Path] = None,
    ) -> None:
        if context.workdir == self.workdir:
            return
        effective_result_target = (
            target_result_file
            or context.target_result_file
            or self._result_file_for_todo(context.todo_identifier or "todo")
        )
        with self._workspace_sync_lock:
            self._merge_text_back_to_primary(
                source=context.result_file,
                target=effective_result_target,
                base_content=context.result_seed_content,
                label=f"ToDo {context.todo_identifier or 'unknown'}",
            )
            self._merge_text_back_to_primary(
                source=context.questions_file,
                target=self.questions_file,
                base_content=context.questions_seed_content,
                label=f"ToDo {context.todo_identifier or 'unknown'} Fragen",
            )
            if context.process_stop_path.exists():
                try:
                    details = read_utf8(context.process_stop_path)
                except OSError:
                    details = ""
                if details:
                    existing = (
                        self._read_text_file_if_exists(self.process_stop_path) or ""
                    )
                    if details not in existing:
                        safe_io.mkdir(self.process_stop_path.parent)
                        if existing:
                            merged_details = existing
                            if not merged_details.endswith("\n"):
                                merged_details += "\n"
                            merged_details += f"\n---\n{details}"
                            self._atomic_write_text(self.process_stop_path, merged_details)
                        else:
                            self._atomic_write_text(self.process_stop_path, details)

    def _wait_condition_is_met(self, expression: str) -> bool:
        value = expression.strip()
        if not value:
            return True
        reject_bridge_wait_conditions(value)
        lowered = value.lower()
        if lowered.startswith("todo:"):
            target = value.split(":", 1)[1].strip()
            return bool(target and self._todo_status_map().get(target) == "DONE")
        if lowered.startswith("group:"):
            target = value.split(":", 1)[1].strip()
            return bool(target and target in self.completed_parallel_groups)
        if lowered.startswith("agent:"):
            target = value.split(":", 1)[1].strip()
            return bool(target and target in self.completed_agents)
        return self._todo_status_map().get(value) == "DONE"

    def _wait_directives_allow_execution(self, todo: TodoItem) -> bool:
        if not todo.wait_directives:
            return True
        if self.process_stop_detected or self.stop_triggered:
            return False
        for wait_cfg in todo.wait_directives:
            expressions = [
                part.strip()
                for part in str(wait_cfg.get("on", "")).split(",")
                if part.strip()
            ]
            if not expressions:
                continue
            mode = str(wait_cfg.get("mode", "all")).strip().lower()
            deadline = None
            timeout_seconds = wait_cfg.get("timeout_seconds")
            if isinstance(timeout_seconds, int) and timeout_seconds >= 0:
                deadline = time.monotonic() + timeout_seconds
            checks = [self._wait_condition_is_met(expr) for expr in expressions]
            done = all(checks) if mode != "any" else any(checks)
            while not done and deadline is not None and time.monotonic() < deadline:
                time.sleep(0.5)
                if self.process_stop_detected or self.stop_triggered:
                    return False
                checks = [self._wait_condition_is_met(expr) for expr in expressions]
                done = all(checks) if mode != "any" else any(checks)
            if done:
                continue
            on_timeout = str(wait_cfg.get("on_timeout", "stop")).strip().lower()
            if on_timeout == "continue":
                print(
                    f"[warn] WAIT-Bedingung für ToDo {todo.identifier} nicht erfüllt, fahre wegen on_timeout=continue fort."
                )
                continue
            print(
                f"[fatal] WAIT-Bedingung für ToDo {todo.identifier} nicht erfüllt: {wait_cfg.get('on')}"
            )
            return False
        return True

    def _next_todo(self) -> Optional[TodoItem]:
        todos = self._parse_todo_file()
        ordered = list(_todo_line_map(read_utf8(self.todo_file)))
        if self.start_id and not self.start_reached:
            if self.start_id not in ordered:
                raise RuntimeError(f"Start-ToDo {self.start_id} wurde aus dem laufenden Plan entfernt.")
            self.start_reached = True
            self.skip_before_ids.update(ordered[:ordered.index(self.start_id)])
        stop_position = ordered.index(self.stop_id) if self.stop_id in ordered else None
        for item in todos:
            if item.identifier in self.skip_before_ids or item.identifier in self.processed:
                continue
            if stop_position is not None and ordered.index(item.identifier) > stop_position:
                continue
            if item.depth > self.max_depth:
                continue
            return item
        return None

    def _parse_todo_file(self) -> List[TodoItem]:
        self.plan_authority.check()
        text = read_utf8(self.todo_file)
        lines = text.splitlines()
        visible = dict(visible_lines(text))
        items: List[TodoItem] = []
        for index, match in task_headers(text):
            if canonical_status(match.group(2)) != "Auftrag":
                continue
            identifier = match.group(1)
            title = match.group(3).strip()
            depth = identifier.count(".") + 1
            preceding_line = visible.get(index - 1)
            directives = self._collect_directive_lines(lines, todo_line_index=index, visible=visible)
            cfg, waits = self._parse_directive_block(directives, todo_id=identifier)
            items.append(TodoItem(
                identifier=identifier, title=title, depth=depth, line_index=index,
                preceding_line=preceding_line, directives=directives,
                config=cfg, wait_directives=waits,
            ))
        return items

    def _find_open_todo_item(self, identifier: str) -> Optional[TodoItem]:
        for item in self._parse_todo_file():
            if item.identifier == identifier:
                return item
        return None

    def _maybe_run_pending_reviews(
        self, trigger_parent: Optional[str] = None, force: bool = False
    ) -> None:
        self._ensure_runtime_tracking_state()
        if not self.pending_reviews or self.process_stop_detected:
            return

        status_map = self._todo_status_map()
        for parent, result_entry in list(self.pending_reviews.items()):
            if status_map.get(parent) == "OBSOLETE":
                del self.pending_reviews[parent]
                self.review_seen_children.pop(parent, None)
                continue
            child_ids = _direct_child_ids(parent, list(status_map))
            if child_ids:
                self.review_seen_children[parent] = True
            if not self.review_seen_children.get(parent, False):
                if force:
                    self._write_final_failure_process_stop(
                        todo_id=parent,
                        parent_id=parent,
                        reason_code="pending_parent_has_no_children",
                        phase="parent_review",
                        message=(
                            "Für den unvollständigen Elternauftrag wurden keine gültigen "
                            "direkten Unteraufträge materialisiert."
                        ),
                        result_file=result_entry[0],
                    )
                continue

            child_statuses = {
                child_id: status_map.get(child_id, "missing")
                for child_id in child_ids
            }
            not_done = {
                child_id: status
                for child_id, status in child_statuses.items()
                if status not in {"DONE", "OBSOLETE"}
            }
            if not_done:
                if force:
                    classification = {
                        "verdict": "FAIL",
                        "blocking_issues": [
                            {
                                "id": "CHILDREN-NOT-DONE",
                                "type": "technical_failure",
                                "summary": (
                                    "Nicht alle direkten Unteraufträge sind erfolgreich DONE: "
                                    + ", ".join(
                                        f"{child}={status}"
                                        for child, status in sorted(not_done.items())
                                    )
                                ),
                                "requirement": (
                                    "Alle direkten Kinder müssen erfolgreich DONE sein, "
                                    "bevor der Parent-Review beginnt."
                                ),
                                "acceptance_criterion": (
                                    "Alle direkten Kinder stehen im ToDo-File auf DONE."
                                ),
                                "references": [],
                                "fix_suggestion": (
                                    "Prüfe die nicht abgeschlossenen Kinder und ihre Logs."
                                ),
                            }
                        ],
                        "non_blocking_observations": [],
                        "breakdown_recommended": False,
                        "breakdown_reason": None,
                    }
                    self._write_final_failure_process_stop(
                        todo_id=parent,
                        parent_id=parent,
                        reason_code="child_todos_not_completed",
                        phase="parent_review_precondition",
                        message=(
                            "Der Elternauftrag kann nicht abschließend geprüft werden, "
                            "weil mindestens ein direktes Kind nicht DONE ist."
                        ),
                        classification=classification,
                        result_file=result_entry[0],
                    )
                continue

            if trigger_parent and not (
                trigger_parent == parent or trigger_parent.startswith(f"{parent}.")
            ):
                if not force:
                    continue

            review = self._run_parent_review(parent, result_entry)
            self.parent_review_attempts[parent] = (
                self.parent_review_attempts.get(parent, 0) + 1
            )
            if review.task_outcome.execution_error:
                self._stop_for_execution_error(parent, review.task_outcome)
                return
            if review.task_outcome.process_stop_triggered:
                self.process_stop_detected = True
                self.process_stop_details = review.task_outcome.message
                self.stop_triggered = True
                self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                return
            if review.passed:
                parent_todo = self._find_open_todo_item(parent)
                if parent_todo is None:
                    # It may already have been marked DONE by a resumed controller.
                    if self._todo_status_map().get(parent) != "DONE":
                        self._write_final_failure_process_stop(
                            todo_id=parent,
                            parent_id=parent,
                            reason_code="parent_todo_entry_missing",
                            phase="parent_review",
                            message=(
                                "Der Parent-Review bestand, aber der Elternauftrag konnte "
                                "im ToDo-File nicht als offener Auftrag gefunden werden."
                            ),
                            classification=review.classification,
                            result_file=result_entry[0],
                            task_outcome=review.task_outcome,
                        )
                        return
                else:
                    self._mark_todo_as_done(parent_todo)
                self.completed.add(parent)
                self.incomplete.discard(parent)
                self.failed.discard(parent)
                print(f"[ok]   Elternauftrag {parent} nach Unter-ToDos abgeschlossen.")
                del self.pending_reviews[parent]
                self.review_seen_children.pop(parent, None)
                continue

            self._record_review(
                result_entry[0],
                review.message or "Parent-Review meldet blockierende Lücken.",
                parent,
            )
            parent_todo = self._find_open_todo_item(parent)
            if parent_todo is None:
                self._write_final_failure_process_stop(
                    todo_id=parent,
                    parent_id=parent,
                    reason_code="parent_todo_missing_after_failed_review",
                    phase="parent_review",
                    message=(
                        "Der Elternauftrag ist nach negativem Parent-Review nicht mehr "
                        "als offenes ToDo verfügbar."
                    ),
                    classification=review.classification,
                    result_file=result_entry[0],
                    task_outcome=review.task_outcome,
                )
                return

            effective_policy = _normalize_breakdown_policy(
                parent_todo.config.get("breakdown"), default=self.breakdown_policy
            )
            rounds_used = max(
                self.breakdown_rounds.get(parent, 0),
                self._infer_breakdown_round(parent, fallback=1),
            )
            max_rounds = self._effective_breakdown_max_rounds(parent_todo)
            action = _breakdown_action(review.classification)

            if action == "complete":
                action = "stop"  # review.passed was false; do not bypass that result

            if (
                effective_policy == "off"
                or action == "blocked"
                or rounds_used >= max_rounds
                or parent_todo.depth >= self.max_depth
            ):
                reason_code = (
                    "parent_review_breakdown_disabled"
                    if effective_policy == "off"
                    else (
                        "parent_review_non_decomposable_blocker"
                        if action == "blocked"
                        else (
                            "parent_review_max_rounds_reached"
                            if rounds_used >= max_rounds
                            else "parent_review_max_depth_reached"
                        )
                    )
                )
                self._write_final_failure_process_stop(
                    todo_id=parent,
                    parent_id=parent,
                    reason_code=reason_code,
                    phase="final_parent_review",
                    message=(
                        f"Der Elternauftrag blieb nach {rounds_used} Breakdown-Runde(n) "
                        "und abschließendem Parent-Review unvollständig."
                    ),
                    classification=review.classification,
                    result_file=result_entry[0],
                    task_outcome=review.task_outcome,
                )
                return

            next_round = rounds_used + 1
            before_ids = set(
                _todo_line_map(read_utf8(self.todo_file))
            )
            if effective_policy == "legacy":
                repair_outcome = self._request_legacy_breakdown(parent_todo, result_entry[0])
                if not repair_outcome.completed:
                    if repair_outcome.execution_error:
                        self._stop_for_execution_error(parent, repair_outcome)
                        return
                    if repair_outcome.process_stop_triggered:
                        self.process_stop_detected = self.stop_triggered = True
                        self.process_stop_details = repair_outcome.message
                        self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                        return
                    self._write_final_failure_process_stop(
                        todo_id=parent,
                        parent_id=parent,
                        reason_code="parent_review_legacy_breakdown_failed",
                        phase="parent_repair_round",
                        message=repair_outcome.message or "Der zusätzliche Legacy-Breakdown blieb unvollständig.",
                        classification=repair_outcome.review_classification,
                        result_file=result_entry[0],
                        task_outcome=repair_outcome,
                    )
                    return
                after_ids = set(
                    _todo_line_map(read_utf8(self.todo_file))
                )
                new_children = _direct_child_ids(parent, sorted(after_ids - before_ids))
                if not new_children:
                    self._write_final_failure_process_stop(
                        todo_id=parent,
                        parent_id=parent,
                        reason_code="parent_review_legacy_breakdown_no_children",
                        phase="parent_repair_round",
                        message=(
                            "Der zusätzliche Legacy-Breakdown erzeugte keine neuen "
                            "direkten Unteraufträge."
                        ),
                        classification=review.classification,
                        result_file=result_entry[0],
                        task_outcome=review.task_outcome,
                    )
                    return
                self.breakdown_rounds[parent] = next_round
                self._write_breakdown_plan(todo=parent_todo, policy="legacy", max_children=len(new_children),
                    classification=review.classification, child_ids=new_children,
                    child_lines=_todo_line_map(read_utf8(self.todo_file)), breakdown_outcome=repair_outcome,
                    round_number=next_round)
            else:
                repair_outcome = self._request_minimal_breakdown(
                    todo=parent_todo,
                    result_file=result_entry[0],
                    outcome=TaskOutcome(
                        completed=False,
                        message=review.message,
                        review_findings=review.message,
                        review_classification=review.classification,
                    ),
                    round_number=next_round,
                )
                if repair_outcome is not None:
                    if repair_outcome.execution_error:
                        self._stop_for_execution_error(parent, repair_outcome)
                        return
                    if repair_outcome.process_stop_triggered:
                        self.process_stop_detected = self.stop_triggered = True
                        self.process_stop_details = repair_outcome.message
                        self.exit_code = RUN_TODOS_EXIT_PROCESS_STOP
                        return
                    self._write_final_failure_process_stop(
                        todo_id=parent,
                        parent_id=parent,
                        reason_code="parent_review_repair_breakdown_failed",
                        phase="parent_repair_round",
                        message=(
                            repair_outcome.message
                            or "Die zusätzliche Reparaturrunde konnte nicht materialisiert werden."
                        ),
                        classification=review.classification,
                        result_file=result_entry[0],
                        task_outcome=repair_outcome,
                    )
                    return

            self.review_seen_children[parent] = True
            print(
                f"[info] Elternauftrag {parent}: zusätzliche fokussierte "
                f"Reparaturrunde {next_round}/{max_rounds} materialisiert."
            )
            # Keep the parent pending until the new children are DONE.


    def _run_parent_review(
        self, parent_id: str, result_entry: Tuple[Path, str]
    ) -> ParentReviewOutcome:
        result_path, prompt_path = result_entry
        todo_prompt_path = self._path_for_prompt(self.todo_file)
        scope_guard = (
            self.runtime_profile.parent_review_scope_guard
            if self.runtime_profile_scope_active
            else ""
        )
        terminal_rule = (
            self.runtime_profile.parent_review_terminal_rule
            if self.runtime_profile_active
            and self.runtime_profile.parent_review_terminal_rule
            else _DEFAULT_PARENT_REVIEW_TERMINAL_RULE
        )
        base_task = (
            f"Prüfe read-only, ob das ToDo #{parent_id} aus `{todo_prompt_path}` "
            "mit seinen direkten und gegebenenfalls verschachtelten Unter-ToDos gegen "
            "die ursprünglichen Akzeptanzkriterien vollständig erledigt wurde. "
            f"{scope_guard}"
            "Verändere keine Fachoutputs, erweitere den Scope nicht und schließe "
            "Lücken in diesem Reviewlauf nicht selbst. Nicht blockierende "
            "Beobachtungen verhindern den Abschluss nicht. "
            f"Lies den gemeinsamen Ergebnisbericht `{prompt_path}` und die tatsächlichen Artefakte. "
        )
        base_task += "\n" + review_instructions(
            self.runtime_profile.autobuild_review_rules if self.runtime_profile_active else None
        ) + terminal_rule
        contract = getattr(self, "review_contracts", {}).get(parent_id)
        if contract is not None:
            contract_path, contract_text = contract
            write_log_text(contract_path, contract_text)
            base_task += build_review_context_reference(
                str(contract_path), contract_text=contract_text
            )
        task_text = self._augment_task_prompt(base_task)
        print(f"[info] Abschlussprüfung für {parent_id}.")
        task_outcome = self._run_autobuild(f"{parent_id}-review", task_text, sandbox_override="read-only")
        classification = _normalize_review_classification_payload(
            task_outcome.message
        )
        if (classification.get("valid") is False or classification.get("source_format") == "text_legacy") and not (
                task_outcome.execution_error or task_outcome.abort or task_outcome.process_stop_triggered):
            task_outcome = replace(task_outcome, completed=False, execution_error=execution_error(
                "Parent review requires a valid structured JSON verdict: " + classification["short_summary"],
                code="invalid_review", phase="parent_review",
            ))
        if not task_outcome.completed and review_classification_passes(classification):
            classification = {
                "verdict": "FAIL",
                "short_summary": "Der Parent-Review-Auftrag selbst wurde nicht erfolgreich abgeschlossen.",
                "blocking_issues": [
                    {
                        "id": "PARENT-REVIEW-TASK-FAILED",
                        "type": "technical_failure",
                        "summary": (
                            "Der read-only Parent-Review konnte nicht zuverlässig "
                            "abgeschlossen werden."
                        ),
                        "requirement": "Der Parent-Review muss einen gültigen PASS/FAIL-Vertrag liefern.",
                        "acceptance_criterion": "Ein erfolgreich ausgeführter strukturierter Parent-Review liegt vor.",
                        "references": [],
                        "fix_suggestion": "Prüfe die Parent-Review-Logs.",
                    }
                ],
                "non_blocking_observations": [],
                "breakdown_recommended": False,
                "breakdown_reason": None,
            }
        passed = bool(
            task_outcome.completed is True
            and not task_outcome.abort and not task_outcome.process_stop_triggered
            and not task_outcome.execution_error
            and review_classification_passes(classification)
        )
        if passed:
            print(f"[ok]   Abschlussprüfung für {parent_id}: PASS.")
        else:
            print(f"[warn] Abschlussprüfung für {parent_id}: FAIL.")
        return ParentReviewOutcome(
            passed=passed,
            classification=classification,
            message=task_outcome.message or "Keine Parent-Review-Nachricht erhalten.",
            task_outcome=task_outcome,
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatisiert ToDos über AutoBuild.", allow_abbrev=False,
        epilog="Kostenfreie Installationsdiagnose: python arquilo_doctor.py --help. Anleitung: documents/QUICKSTART.md.")
    add_removed_arguments(parser)
    parser.add_argument(
        "--todo-syntax", choices=("auto", "legacy", "marked-en"),
        default=environment_value("ARQUILO_TODO_SYNTAX") or "auto",
        help="Schreibweise für neue Task-Kommandos: auto (Datei), legacy oder marked-en (***Task***). Bestehende Listen bleiben lesbar.",
    )
    parser.add_argument(
        "--todo-preamble", choices=("auto", "off", "required"),
        default=environment_value("ARQUILO_TODO_PREAMBLE") or "auto",
        help="Projektvorbemerkung und Dateisemantik in AutoBuild-Aufträge einbetten: auto (wenn vorhanden), off oder required.",
    )
    parser.add_argument(
        "--todo-file",
        type=Path,
        default=None,
        help="Pfad zur ToDo-Liste.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Arbeitsverzeichnis für AutoBuild (Standard: Verzeichnis der ToDo-Datei).",
    )
    parser.add_argument(
        "--start",
        dest="start_id",
        default=None,
        help="Erstes ToDo (z. B. 3 oder 3.1).",
    )
    parser.add_argument(
        "--stop",
        dest="stop_id",
        default=None,
        help="Stoppt die Ausführung nach Abschluss des angegebenen ToDos (z. B. 4 oder 4.2).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximale ToDo-Tiefe (z. B. 3 für 3.2.1).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Fortsetzungsfaktor: maximal max-steps × max-retries Produktions-/Korrekturschritte; kein Gesamtauftrag-Replay.",
    )
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help="Gemeinsames Modellaufruflimit je Aufgabenbaum und Runnerlauf, inklusive Kinder/Reviews/Decide (Standard: 100).")
    parser.add_argument(
        "--breakdown-policy",
        choices=list(BREAKDOWN_POLICIES),
        default="minimal",
        help=(
            "Automatische Behandlung unvollständiger ToDos: minimal erzeugt nur die kleinste "
            "notwendige Restzerlegung, legacy nutzt den bisherigen freien Breakdown, off deaktiviert ihn."
        ),
    )
    parser.add_argument(
        "--breakdown-max-children",
        type=int,
        default=4,
        help="Maximale Zahl direkter Kinder je minimalem Breakdown (1-12).",
    )
    parser.add_argument(
        "--breakdown-max-rounds",
        type=int,
        default=2,
        help=(
            "Maximale Zahl fokussierter Breakdown-/Reparaturrunden je Elternauftrag "
            "einschließlich der ersten Kinderwelle (1-8). Danach erzeugt run_todos "
            "bei weiterem Vertragsmangel technisch process_stop."
        ),
    )
    parser.add_argument(
        "--process-stop-policy",
        choices=["model", "controller-only"],
        default="model",
        help=(
            "model erlaubt dem Auftrag, process_stop selbst zu schreiben; "
            "controller-only verlangt vollständige strukturierte Outputs und überlässt "
            "Repair/HOLD/Stop ausschließlich dem aufrufenden Controller."
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=3,
        help="Maximale Schritte für AutoBuild (entspricht --max-steps).",
    )
    parser.add_argument(
        "--sandbox",
        choices=["workspace-write"],
        default="workspace-write",
        help="Fest workspace-write (Standard); keine Erweiterung der Schreibrechte.",
    )
    parser.add_argument("--network-access", action="store_true",
                        help="Explizite zusätzliche Netzwerkfreigabe für sandboxed Shellbefehle.")
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optionales Modell für AutoBuild/codex exec. Überschreibt für "
            "diesen Lauf ~/.codex/config.toml."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=CODEX_REASONING_EFFORT_CHOICES,
        default=None,
        help=(
            "Optionaler reasoning effort für alle Codex-Aufrufe dieses Laufs. "
            "Wird pro Invocation übergeben und verändert config.toml nicht."
        ),
    )
    parser.add_argument(
        "--skip-codex-preflight",
        action="store_true",
        help=(
            "Ueberspringt den potenziell kostenpflichtigen Codex-Preflight fuer --sandbox workspace-write. "
            "Nur verwenden, wenn workspace-write extern geprueft wurde."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur Befehle sammeln und nicht ausführen.",
    )
    parser.add_argument(
        "--dry-run-file",
        type=Path,
        default=Path("run_todos_dry_run.md"),
        help="Ablage der Befehlsliste im Dry-Run.",
    )
    parser.add_argument(
        "--simulate-incomplete",
        action="append",
        default=[],
        help="ToDo-IDs, die im Dry-Run als incomplete markiert werden sollen (mehrfach).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optionaler Run-Identifier (z. B. 20240205T120000Z); bei Auslassung wird später ein Wert generiert.",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Commit nur explizit mit --git-path freigegebene Dateien; kein Push ohne --git-push.",
    )
    parser.add_argument("--git-path", action="append", default=[],
                        help="Einzelner relativer Dateipfad für geprüfte Commits (mehrfach, keine Globs).")
    parser.add_argument("--git-push", action="store_true", help="Zusätzlich ausgewählte Commits zum bestehenden Upstream pushen.")
    parser.add_argument("--state-dir", type=Path, help="Privater Controller-Zustand außerhalb des Workspaces.")
    parser.add_argument("--accept-plan-changes", action="store_true",
                        help="Bewusst vom Eigentümer geprüfte externe Planänderungen übernehmen; Budgets bleiben erhalten.")
    parser.add_argument(
        "--runtime-profile",
        type=Path,
        default=None,
        help="Optionales JSON-Runtime-Profil; dessen Preflight wird im echten Lauf ausgeführt.",
    )
    parser.add_argument(
        "--print-capabilities",
        action="store_true",
        help="ARQUILO-Kernverträge und erhaltene Kernoptionen als JSON anzeigen; keine Modellaufrufe.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    should_beep = True
    try:
        try:
            check_removed_environment()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        args = parse_args(argv)
        if args.print_capabilities:
            should_beep = False
            print(json.dumps(arquilo_capabilities_payload(), ensure_ascii=False, sort_keys=True))
            return 0
        try:
            for name in ("todo_file", "workdir", "runtime_profile", "dry_run_file"):
                value = getattr(args, name, None)
                if value is not None:
                    validate_path(value, label=name)
        except PathValidationError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        sandbox_level: Optional[str] = args.sandbox
        try:
            codex_policy.validate_start_policy(sandbox=sandbox_level, network_access=args.network_access)
            normalize_mode(args.todo_preamble)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.todo_file is None:
            print(
                "--todo-file ist erforderlich.",
                file=sys.stderr,
            )
            return 2
        todo_path = args.todo_file.expanduser().resolve()
        if not todo_path.exists():
            print(f"ToDo-Datei nicht gefunden: {todo_path}", file=sys.stderr)
            return 1
        workdir = (
            args.workdir.expanduser().resolve() if args.workdir else todo_path.parent
        )
        # Reject missing/invalid context before even the optional Codex
        # capability preflight. Dispatch still captures the live file afresh.
        try:
            validate_removed_directives(read_utf8(todo_path))
            augment_with_preamble("", todo_path, mode=args.todo_preamble)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 3
        try:
            recorder = DryRunRecorder(args.dry_run_file if args.dry_run else None)
        except (OSError, ValueError) as exc:
            print(f"Dry-run report must be a new, non-linked file: {exc}", file=sys.stderr)
            return 2
        try:
            runtime_profile = load_runtime_profile(args.runtime_profile)
            if args.dry_run:
                if runtime_profile.preflight is not None:
                    recorder.record("Runtime profile preflight skipped", "# dry-run: no profile command executed",
                                    note="Profilprüfung konfiguriert, im Trockenlauf nicht ausgeführt.")

        except RuntimeProfileError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        simulated = {entry.strip() for entry in args.simulate_incomplete}
        run_id = args.run_id.strip() if args.run_id else None
        try:
            runner = TodoRunner(
                todo_file=todo_path,
                workdir=workdir,
                max_depth=args.max_depth,
                max_retries=args.max_retries,
                max_calls=args.max_calls,
                start_id=args.start_id,
                stop_id=args.stop_id,
                dry_run=args.dry_run,
                dry_run_recorder=recorder,
                simulated_incomplete=simulated,
                max_steps=args.max_steps,
                sandbox=sandbox_level,
                network_access=args.network_access,
                run_id=run_id,
                git_enabled=args.git,
                git_paths=args.git_path, git_push=args.git_push,
                state_dir=args.state_dir, accept_plan_changes=args.accept_plan_changes,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                breakdown_policy=args.breakdown_policy,
                breakdown_max_children=args.breakdown_max_children,
                breakdown_max_rounds=args.breakdown_max_rounds,
                process_stop_policy=args.process_stop_policy,
                runtime_profile=runtime_profile,
                todo_syntax=args.todo_syntax,
                todo_preamble=args.todo_preamble,
            )
        except (GitIntegrationError, ReviewedGitError, PlanIntegrityError, OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            if not args.dry_run:
                run_runtime_profile_preflight(runtime_profile, workdir=workdir, todo_file=todo_path)
            if not args.skip_codex_preflight:
                run_codex_workspace_write_preflight(dry_run=args.dry_run, recorder=recorder,
                    model=args.model, reasoning_effort=args.reasoning_effort)
            runner.plan_authority.check()
        except (RuntimeError, ValueError, OSError) as exc:
            runner.close()
            print(str(exc), file=sys.stderr)
            return 3
        try:
            runner.run()
            exit_code = getattr(runner, "exit_code", 0)
            # TodoRunner always exposes an integer exit_code.  A wrapper or
            # test double may omit it or provide a non-integer sentinel; in
            # that compatibility case a completed run retains the historical
            # success status instead of coercing (for example) a MagicMock to 1.
            return exit_code if isinstance(exit_code, int) else 0
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except (GitIntegrationError, RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 3
    finally:
        if should_beep:
            _beep(3)


if __name__ == "__main__":
    sys.exit(main())
