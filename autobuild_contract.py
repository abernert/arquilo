# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Small AutoBuild call boundary; immutable validated options, no scheduler or processes."""
from __future__ import annotations

from prompt_config import PromptConfig, PromptConfigError, load_prompt_config

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import codex_policy
import agent_backend
from task_resources import TaskResources
from removed_features import check_removed_fields
from execution_budget import DEFAULT_MAX_CALLS, positive_limit
from runtime_contracts import AutoBuildStatus, ExitCode
from review_contract import (
    parse_review_classification, review_classification_passes, validate_review_classification,
)
from legacy_naming import schema_matches


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoBuildOptions:
    backend: str = "codex"
    sandbox: str = "workspace-write"
    network_access: bool = False
    config_profile: str | None = None
    extra_arg: tuple[str, ...] = ()
    model: str | None = None
    reasoning_effort: str | None = None
    logfile: str | Path | None = None
    rawlog: str | Path | None = None
    summary_json: str | Path | None = None
    process_stop_path: str | Path | None = None
    max_steps: int = 3
    max_calls: int = DEFAULT_MAX_CALLS
    auto_continue: bool = False
    print_end_answer: bool = False
    verbose: bool = False
    mcp: tuple[str, ...] | None = None
    review_mcp: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None
    skill_dirs: tuple[str, ...] = ()
    prompt_config: PromptConfig | str | Path | dict | None = None

    def __post_init__(self):
        agent_backend.validate_options(self.backend, config_profile=self.config_profile, extra_args=self.extra_arg)
        positive_limit(self.max_calls)
        object.__setattr__(self, "prompt_config", load_prompt_config(self.prompt_config))
        resources = TaskResources(mcp=self.mcp, review_mcp=self.review_mcp, skills=self.skills)
        agent_backend.validate_resources(self.backend, mcp=resources.mcp, review_mcp=resources.review_mcp)
        for key in ("mcp", "review_mcp", "skills"):
            object.__setattr__(self, key, getattr(resources, key))
        if isinstance(self.skill_dirs, str) or not isinstance(self.skill_dirs, (list, tuple)):
            raise ValueError("skill_dirs must be a sequence of operator-selected paths")
        if any(not isinstance(p, (str, Path)) or not str(p) or "\0" in str(p) for p in self.skill_dirs):
            raise ValueError("Invalid skill directory")
        object.__setattr__(self, "skill_dirs", tuple(str(p) for p in self.skill_dirs))
        codex_policy.validate_start_policy(sandbox=self.sandbox,
            network_access=self.network_access, allow_read_only=True)
        codex_policy.validate_config_profile(self.config_profile)
        object.__setattr__(self, "extra_arg", tuple(codex_policy.validate_extra_args(self.extra_arg)))
        if type(self.max_steps) is not int or self.max_steps < 1:
            raise ValueError("max_steps muss eine positive Ganzzahl sein.")
        for name in ("auto_continue", "print_end_answer", "verbose"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} muss bool sein.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoBuildContext:
    task_source: str = "inline"
    todo_identifier: str | None = None
    decision_todo_file: str | Path | None = None
    decision_run_id: str | None = None
    decision_attempt_id: str = "1"
    decision_phase: str = "completion"
    review_policy_rules: tuple[str, ...] | None = None
    budget_directory: str | Path | None = None
    budget_root_id: str | None = None
    allow_todo_modifications: bool = False
    process_stop_paths: tuple[str | Path, ...] = ()
    launcher_workspace: str | Path | None = None
    git_review: dict | None = None
    git_review_optional: bool = False

    def __post_init__(self):
        if type(self.git_review_optional) is not bool:
            raise ValueError("git_review_optional must be bool")
        if self.git_review is not None:
            from git_snapshot import validate_request
            object.__setattr__(self, "git_review", json.loads(json.dumps(validate_request(self.git_review))))
        if self.launcher_workspace is not None:
            if (not isinstance(self.launcher_workspace, (str, Path))
                    or "\0" in str(self.launcher_workspace)
                    or not Path(self.launcher_workspace).is_absolute()):
                raise ValueError("launcher_workspace must be an absolute controller-selected path")
            object.__setattr__(self, "launcher_workspace", str(self.launcher_workspace))
        if not isinstance(self.process_stop_paths, (tuple, list)):
            raise ValueError("process_stop_paths must be a sequence of absolute controller paths")
        for path in self.process_stop_paths:
            if not isinstance(path, (str, Path)) or "\0" in str(path) or not Path(path).is_absolute():
                raise ValueError("process_stop_paths must contain absolute controller paths")
        object.__setattr__(self, "process_stop_paths", tuple(str(p) for p in self.process_stop_paths))
        if type(self.allow_todo_modifications) is not bool:
            raise ValueError("allow_todo_modifications must be bool")
        if self.task_source not in ("inline", "todo"):
            raise ValueError("task_source muss inline oder todo sein.")
        for name in ("decision_attempt_id", "decision_phase"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} muss nichtleerer Text sein.")
        if self.review_policy_rules is not None:
            if isinstance(self.review_policy_rules, str) or not all(
                    isinstance(v, str) and v.strip() for v in self.review_policy_rules):
                raise ValueError("review_policy_rules muss eine Textliste sein.")
            object.__setattr__(self, "review_policy_rules", tuple(self.review_policy_rules))


def call_payload(*, options: AutoBuildOptions, context: AutoBuildContext, **inputs) -> dict:
    """JSON form for the retained parallel Python worker."""
    check_removed_fields(inputs, source="AutoBuild-Payload")
    def plain(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        return value
    return plain(dict(inputs, options=asdict(options), context=asdict(context)))


def decode_call(payload: Any) -> dict:
    allowed = {"task", "task_file", "workdir", "file", "options", "context"}
    if isinstance(payload, dict):
        check_removed_fields(payload, source="AutoBuild-Payload")
        for key in ("options", "context"):
            if isinstance(payload.get(key), dict):
                check_removed_fields(payload[key], source=f"AutoBuild-Payload.{key}")
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError("AutoBuild-Aufruf verwendet entfernte/unbekannte Parameter; "
                         "Kernoptionen unter options und Auftragskontext unter context angeben.")
    try:
        return {**payload, "options": AutoBuildOptions(**payload.get("options", {})),
                "context": AutoBuildContext(**payload.get("context", {}))}
    except TypeError as exc:
        raise ValueError(f"Ungültiger AutoBuild-Aufruf: {exc}") from exc


def core_status(exit_code: int) -> str:
    return {0: AutoBuildStatus.COMPLETE.value, 6: AutoBuildStatus.CANCELLED.value,
            9: AutoBuildStatus.INCOMPLETE.value}.get(exit_code, AutoBuildStatus.FAILED.value)


class AutoBuildResultError(ValueError):
    """A malformed result is a technical boundary error, not a user option error."""


def _optional_path(record: dict, key: str) -> None:
    if key in record and record[key] is not None and (
            not isinstance(record[key], str) or not record[key].strip() or "\0" in record[key]):
        raise AutoBuildResultError(f"Invalid AutoBuild diagnostic path: {key}")


def _stop_metadata(record: dict) -> None:
    if "process_stop_triggered" in record and type(record["process_stop_triggered"]) is not bool:
        raise AutoBuildResultError("Invalid diagnostic stop flag")
    details = record.get("process_stop_details")
    # Old v1 payloads may omit the reason or carry null. New writers always
    # provide an explicit fallback; never infer a reason from last_answer.
    if details is not None and (not isinstance(details, str) or not details.strip()):
        raise AutoBuildResultError("Invalid diagnostic stop details")
    if details is not None and record.get("process_stop_triggered") is not True:
        raise AutoBuildResultError("Stop details without an observed stop")


def _validate_diagnostic_metadata(payload: dict) -> None:
    _stop_metadata(payload)
    attempts = payload.get("execution_attempts", [])
    if not isinstance(attempts, list) or any(not isinstance(a, dict) for a in attempts):
        raise AutoBuildResultError("Invalid execution_attempts")
    for attempt in attempts:
        _stop_metadata(attempt)
        for key in ("capture_directory", "stderr_file"):
            _optional_path(attempt, key)
        if "stream_diagnostics" in attempt:
            diagnostics = attempt["stream_diagnostics"]
            if not isinstance(diagnostics, list):
                raise AutoBuildResultError("Invalid stream diagnostics")
            for diagnostic in diagnostics:
                if (not isinstance(diagnostic, dict) or diagnostic.get("kind") != "codex_reconnect"
                        or type(diagnostic.get("event_index")) is not int or diagnostic["event_index"] < 1
                        or not isinstance(diagnostic.get("event"), dict)
                        or diagnostic["event"].get("type") != "error"
                        or not isinstance(diagnostic["event"].get("message"), str)):
                    raise AutoBuildResultError("Invalid reconnect diagnostic")
    terminal = payload.get("terminal_attempt")
    if terminal is not None:
        if (not isinstance(terminal, dict) or set(terminal) != {"phase", "index", "capture_directory"}
                or not isinstance(terminal["phase"], str)
                or terminal["phase"] not in {"task", "review", "decide"}
                or type(terminal["index"]) is not int or terminal["index"] < 1):
            raise AutoBuildResultError("Invalid terminal_attempt")
        _optional_path(terminal, "capture_directory")
        matches = [a for a in attempts if a.get("phase") == terminal["phase"]
                   and type(a.get("index")) is int and a["index"] == terminal["index"]]
        if len(matches) != 1 or matches[0].get("capture_directory") != terminal["capture_directory"]:
            raise AutoBuildResultError("Terminal attempt does not identify exactly one returned execution")


def validate_result(payload: Any, *, process_exit_code: int | None = None) -> dict:
    """Validate the same summary at the in-process and Python-worker boundaries."""
    if not isinstance(payload, dict):
        raise AutoBuildResultError("AutoBuild summary must be an object")
    try:
        backend = agent_backend.validate_backend(payload.get("backend", "codex"))
    except ValueError as exc:
        raise AutoBuildResultError("Invalid AutoBuild backend") from exc
    for name in ("completed", "process_stop_triggered", "review_required"):
        if type(payload.get(name)) is not bool:
            raise AutoBuildResultError(f"Invalid AutoBuild summary field: {name}")
    _validate_diagnostic_metadata(payload)
    publication_error = payload.get("git_publication_error")
    if publication_error is not None:
        if (not isinstance(publication_error, dict)
                or set(publication_error) != {"code", "message"}
                or publication_error["code"] != "git_review_unavailable"
                or not isinstance(publication_error["message"], str)
                or not 0 < len(publication_error["message"]) <= 4096
                or payload.get("git_review") is not None):
            raise AutoBuildResultError("Invalid optional Git capture diagnostic")
    code = payload.get("exit_code")
    if type(code) is not int or code not in {int(v) for v in ExitCode}:
        raise AutoBuildResultError("Invalid AutoBuild exit_code")
    if payload.get("status") != core_status(code) or payload["completed"] != (code == 0):
        raise AutoBuildResultError("AutoBuild status/completed contradicts exit_code")
    budget = payload.get("call_budget")
    if budget is not None:
        if (not isinstance(budget, dict) or not (budget.get("schema_version") == "arquilo.call_budget.v2"
                    or schema_matches(budget.get("schema_version"), "arquilo.call_budget.v1"))
                or any(type(budget.get(k)) is not int for k in ("limit", "used"))
                or budget["limit"] < 0 or budget["used"] < 0 or "remaining" not in budget
                or (budget.get("schema_version") != "arquilo.call_budget.v2" and budget["limit"] == 0)
                or (budget["limit"] == 0 and budget.get("remaining") is not None)
                or (budget["limit"] > 0 and (
                    type(budget.get("remaining")) is not int or budget["used"] > budget["limit"]
                    or budget["remaining"] != budget["limit"] - budget["used"]))
                or ("unlimited" in budget and (type(budget["unlimited"]) is not bool
                    or budget["unlimited"] != (budget["limit"] == 0)))):
            raise AutoBuildResultError("Invalid shared call budget")
    exhausted = payload.get("budget_exhausted")
    if exhausted is not None:
        if (not isinstance(exhausted, dict) or budget is None or budget["limit"] == 0 or budget["remaining"] != 0
                or exhausted.get("root_id") != budget.get("root_id") or code != 9
                or not exhausted.get("blocked_phase")):
            raise AutoBuildResultError("Budget exhaustion contradicts AutoBuild result")
    error = payload.get("execution_error")
    if code in (2, 3, 7, 8):
        if not isinstance(error, dict) or type(error.get("exit_code")) is not int or error["exit_code"] != code:
            raise AutoBuildResultError("AutoBuild failure requires a matching error payload")
        if not all(isinstance(error.get(k), str) and error[k].strip() for k in ("code", "message", "phase")):
            raise AutoBuildResultError("AutoBuild failure requires a diagnostic")
    elif error is not None:
        raise AutoBuildResultError("AutoBuild non-error status carries an error")
    if code == 6 and not payload["process_stop_triggered"]:
        raise AutoBuildResultError("AutoBuild cancellation requires a stop signal")
    if payload["process_stop_triggered"] and code in (0, 9):
        raise AutoBuildResultError("AutoBuild stop contradicts successful execution")
    if not isinstance(payload.get("last_answer"), str):
        raise AutoBuildResultError("AutoBuild last_answer must be text")
    if code == 0 and (not payload["last_answer"].strip() or not payload["review_required"]):
        raise AutoBuildResultError("AutoBuild completion requires an answer and mandatory review")
    if code == 0:
        review = payload.get("review_classification")
        if not isinstance(review, dict) or review.get("valid") is not True:
            raise AutoBuildResultError("AutoBuild completion requires a valid review")
        normalized = validate_review_classification(review)
        if normalized.get("valid") is not True:
            raise AutoBuildResultError("AutoBuild completion contains an invalid review contract")
        if not review_classification_passes(normalized):
            raise AutoBuildResultError("AutoBuild completion contradicts its review verdict or blockers")
        needs_decision = normalized.get("source_format") == "text_legacy"
        raw_findings = payload.get("review_findings")
        if raw_findings is not None:
            # This is the same latest reviewer output that produced the stored
            # classification, not production prose or an independent report.
            # Older summaries may omit it; present evidence cannot be waived.
            raw_review = parse_review_classification(raw_findings)
            if not review_classification_passes(raw_review):
                raise AutoBuildResultError("AutoBuild completion contradicts its raw review findings")
            needs_decision = needs_decision or raw_review.get("source_format") == "text_legacy"
        if needs_decision:
            decision = payload.get("decision")
            expected_source = "claude_code" if backend == "claude-code" else "codex_exec"
            if (not isinstance(decision, dict) or decision.get("selected_option") != "COMPLETE"
                    or decision.get("source") != expected_source or decision.get("error") is not None
                    or decision.get("fallback_used") is not False):
                raise AutoBuildResultError("Legacy prose requires a successful explicit decision from the selected backend")
    if process_exit_code is not None and process_exit_code != code:
        raise AutoBuildResultError(f"AutoBuild exit mismatch: summary {code}, process {process_exit_code}")
    return payload


def strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj
