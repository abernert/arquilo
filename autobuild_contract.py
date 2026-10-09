# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Small AutoBuild call boundary; no processes, configuration reads or scheduler."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import codex_policy
from removed_features import check_removed_fields
from execution_budget import DEFAULT_MAX_CALLS, positive_limit
from runtime_contracts import AutoBuildStatus, ExitCode
from review_contract import parse_review_classification
from legacy_naming import schema_matches


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoBuildOptions:
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

    def __post_init__(self):
        positive_limit(self.max_calls)
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

    def __post_init__(self):
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
    for name in ("completed", "process_stop_triggered", "review_required"):
        if type(payload.get(name)) is not bool:
            raise AutoBuildResultError(f"Invalid AutoBuild summary field: {name}")
    _validate_diagnostic_metadata(payload)
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
        try:
            normalized = parse_review_classification(json.dumps(review, allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            raise AutoBuildResultError("AutoBuild review is not finite JSON") from exc
        if normalized.get("valid") is not True:
            raise AutoBuildResultError("AutoBuild completion contains an invalid review contract")
        if review.get("source_format") == "text_legacy":
            decision = payload.get("decision")
            if (not isinstance(decision, dict) or decision.get("selected_option") != "COMPLETE"
                    or decision.get("source") != "codex_exec" or decision.get("error") is not None
                    or decision.get("fallback_used") is not False):
                raise AutoBuildResultError("Legacy prose requires a successful explicit Codex decision")
        if review.get("source_format") != "text_legacy" and (
                review.get("verdict") != "PASS" or review.get("blocking_issues") != []
                or review.get("breakdown_recommended") is not False):
            raise AutoBuildResultError("AutoBuild completion contradicts its structured review")
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
