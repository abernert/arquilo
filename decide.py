# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Decide APIs backed by archived, strictly validated Codex Exec."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union
from uuid import uuid4

from decision_exec import DecisionCall, DecisionExecSettings, execute_decision
from decision_request import (
    DEFAULT_MAX_INPUT_BYTES, BooleanMapping, ContextSection, DecisionInputError,
    DecisionKind, DecisionRequest, evaluation_request, load_evaluation_context,
)

class DecisionError(ValueError):
    """Unusable decision, retaining the result and evidence for its caller."""

    def __init__(self, call: DecisionCall):
        self.call, self.result = call, call.result
        execution = call.result.execution
        failure = call.result.failure or (execution.failure if execution else None)
        code = failure.code if failure else "decision_cancelled"
        message = failure.message if failure else (execution.cancellation_reason if execution else "No execution")
        super().__init__(f"{code}: {message}; decision files: {call.directory}")


def configure(*, api_key=None, base_url=None, client=None) -> None:
    """Migration diagnostic; API clients/credentials no longer configure Decide."""
    raise DecisionInputError("decision_api_removed", "configure",
        "Decide uses Codex authentication. Pass per-call DecisionExecSettings instead of API credentials/client.")


def run_decision(request: DecisionRequest, *, settings: DecisionExecSettings | None = None,
                 max_attempts: int | None = None) -> DecisionCall:
    """Structured API; every failed/cancelled attempt has no usable option.

    Standalone defaults use the current project and the OS user's ~/.codex.
    A custom auth home must be explicitly trusted through settings; inherited
    CODEX_HOME, API keys and .env files cannot select it implicitly.
    """
    if not isinstance(request, DecisionRequest):
        raise DecisionInputError("decision_invalid_input", "request", "Expected DecisionRequest")
    if max_attempts is not None and (type(max_attempts) is not int or not 1 <= max_attempts <= 2):
        raise DecisionInputError("decision_invalid_input", "max_attempts", "Expected 1 or 2 total attempts")
    # model=None is intentional: let Codex/provider configuration select its
    # effective default. Only an explicit request/CLI/config override should
    # add --model to the Codex invocation.
    if settings is None:
        project = Path.cwd().resolve()
        settings = DecisionExecSettings(project_root=project, trusted_codex_home=Path.home() / ".codex",
            env=dict(os.environ), log_root=project / ".codex_runs")
    if max_attempts is not None:
        settings = replace(settings, max_attempts=max_attempts)
    return execute_decision(request, settings=settings)


def _decide_with_options(request: DecisionRequest, *, max_retries: int | None = None,
                         settings: DecisionExecSettings | None = None) -> Tuple[str, str]:
    """Legacy max_retries counts total attempts, as in the original API.

    None uses settings (one attempt by default); 2 permits one format replay.
    There is no semantic fallback on failure and no unbounded retry budget.
    """
    if max_retries is not None and (type(max_retries) is not int or not 1 <= max_retries <= 2):
        raise DecisionInputError("decision_invalid_input", "max_retries", "Expected 1 or 2 total attempts")
    overrides = {} if max_retries is None else {"max_attempts": max_retries}
    call = run_decision(request, settings=settings, **overrides)
    if not call.result.valid:
        raise DecisionError(call)
    return request.selected_option(call.result), call.result.explanation


def _request(
    question: str, options: Sequence[str], *, model: Optional[str],
    system_prompt: Optional[str], reasoning_effort: Optional[str],
    context: Sequence[ContextSection], run_id: Optional[str], task_id: str,
    phase: str, attempt_id: str, max_input_bytes: int,
    request: Optional[DecisionRequest] = None,
    boolean_mapping: Optional[BooleanMapping] = None,
) -> DecisionRequest:
    if request is not None:
        if not isinstance(request, DecisionRequest):
            raise DecisionInputError("decision_invalid_input", "request", "Expected DecisionRequest")
        if not isinstance(options, (list, tuple)) or question != request.question or tuple(options) != request.options:
            raise DecisionInputError("decision_invalid_input", "request", "Question/options disagree with request")
        for name, override in (("model", model), ("reasoning_effort", reasoning_effort), ("system_prompt", system_prompt)):
            if override is not None and override != getattr(request, name):
                raise DecisionInputError("decision_invalid_input", name, "Override disagrees with request")
        if context or run_id is not None or task_id != "question" or phase != "decide" or attempt_id != "1":
            raise DecisionInputError("decision_invalid_input", "request", "Pass identity/context inside the request only")
        if max_input_bytes != DEFAULT_MAX_INPUT_BYTES and max_input_bytes != request.max_input_bytes:
            raise DecisionInputError("decision_invalid_input", "max_input_bytes", "Pass the limit inside the request only")
        return request
    return DecisionRequest(question=question, options=options, context=context,
        run_id=run_id if run_id is not None else f"standalone-{uuid4().hex}", task_id=task_id,
        phase=phase, attempt_id=attempt_id, model=model,
        reasoning_effort=reasoning_effort, system_prompt=system_prompt,
        kind=DecisionKind.BOOLEAN if boolean_mapping else DecisionKind.CHOICE,
        boolean_mapping=boolean_mapping, max_input_bytes=max_input_bytes)


def decide(
    question: str, options: Sequence[str], *, model: Optional[str] = None,
    system_prompt: Optional[str] = None, max_retries: int | None = None,
    api_key: Optional[str] = None, base_url: Optional[str] = None,
    client: object | None = None,
    settings: DecisionExecSettings | None = None,
    reasoning_effort: Optional[str] = None, context: Sequence[ContextSection] = (),
    run_id: Optional[str] = None, task_id: str = "question", phase: str = "decide",
    attempt_id: str = "1", max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    request: Optional[DecisionRequest] = None,
) -> Tuple[str, str]:
    """Choose an exact option. The question/context must be self-contained.

    Legacy callers receive a fresh standalone run ID. Production callers pass
    their explicit request, including the actual attempt's evidence and IDs.
    """
    prepared = _request(question, options, model=model, system_prompt=system_prompt,
        reasoning_effort=reasoning_effort, context=context, run_id=run_id, task_id=task_id,
        phase=phase, attempt_id=attempt_id, max_input_bytes=max_input_bytes, request=request)
    if any(value is not None for value in (client, api_key, base_url)):
        configure(api_key=api_key, base_url=base_url, client=client)
    return _decide_with_options(prepared, max_retries=max_retries, settings=settings)


def decide_bool(
    question: str, *, model: Optional[str] = None, system_prompt: Optional[str] = None,
    max_retries: int | None = None, reasoning_effort: Optional[str] = None,
    context: Sequence[ContextSection] = (), run_id: Optional[str] = None,
    task_id: str = "question", phase: str = "decide", attempt_id: str = "1",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    boolean_mapping: BooleanMapping = BooleanMapping(),
    settings: DecisionExecSettings | None = None,
) -> Tuple[bool, str]:
    """true/false by default; YES/NO requires its explicit BooleanMapping."""
    if not isinstance(boolean_mapping, BooleanMapping):
        raise DecisionInputError("decision_invalid_input", "boolean_mapping", "Expected BooleanMapping")
    prepared = _request(question, boolean_mapping.options, model=model, system_prompt=system_prompt,
        reasoning_effort=reasoning_effort, context=context, run_id=run_id, task_id=task_id,
        phase=phase, attempt_id=attempt_id, max_input_bytes=max_input_bytes,
        boolean_mapping=boolean_mapping)
    option, explanation = _decide_with_options(prepared, max_retries=max_retries, settings=settings)
    return boolean_mapping.decode(option), explanation


def evaluate(
    context_path: Union[str, Path], *, stage: str = "step", plan_id: Optional[str] = None,
    step_id: Optional[str] = None, model: Optional[str] = None,
    system_prompt: Optional[str] = None, max_retries: int | None = None,
    reasoning_effort: Optional[str] = None, run_id: Optional[str] = None,
    task_id: str = "plan", attempt_id: str = "1",
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    settings: DecisionExecSettings | None = None,
) -> Dict[str, Any]:
    """Evaluate a full, explicit planning context; invalid/missing input raises.

    Both stages require task, preamble (possibly empty), the selected plan and
    its step_results. Final additionally requires latest_answer/review_findings.
    Nothing is truncated and a requested plan is never replaced by another.
    """
    context = load_evaluation_context(context_path, max_input_bytes=max_input_bytes)
    request, resolved_plan_id, resolved_step_id = evaluation_request(
        context, stage=stage, plan_id=plan_id, step_id=step_id,
        run_id=run_id if run_id is not None else f"standalone-{uuid4().hex}",
        task_id=task_id, attempt_id=attempt_id, model=model, reasoning_effort=reasoning_effort,
        system_prompt=system_prompt, max_input_bytes=max_input_bytes)
    status, explanation = decide(request.question, request.options, request=request,
                                 max_retries=max_retries, settings=settings)
    decision: Dict[str, Any] = {"status": status, "explanation": explanation, "plan_id": resolved_plan_id}
    if stage == "step":
        decision["step_id"] = resolved_step_id
    return decision


__all__ = ["decide", "decide_bool", "evaluate", "run_decision", "DecisionError", "DecisionExecSettings"]
