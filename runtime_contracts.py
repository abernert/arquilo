# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Immutable, provider-neutral results for the Lean runtime (Python >= 3.11).

These are validated boundary values, not mutable event accumulators. Transport,
parsing and orchestration remain responsible for collecting their evidence.
No I/O, environment/configuration access, retry policy or provider imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class ContractError(ValueError):
    """A caller supplied malformed or contradictory result data."""


class ExitCode(IntEnum):
    """Existing normal-run codes; queue/admin commands keep their own codes."""

    OK = 0
    INVALID_CONFIGURATION = 2
    RUNNER_ERROR = 3
    PROCESS_STOP = 6
    EXECUTION_ERROR = 7
    INVALID_REVIEW = 8
    INCOMPLETE = 9


class FailureKind(str, Enum):
    CONFIGURATION = "configuration"
    RUNNER = "runner"
    EXECUTION = "execution"
    REVIEW_PROTOCOL = "review_protocol"
    DECISION_PROTOCOL = "decision_protocol"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _text(value: object, name: str, *, empty: bool = False) -> None:
    _require(type(value) is str and (empty or bool(value.strip())),
             f"{name} must be {'a string' if empty else 'a non-empty string'}")


def _texts(value: object, name: str) -> None:
    _require(type(value) is tuple, f"{name} must be an immutable tuple")
    for item in value:
        _text(item, name)


@dataclass(frozen=True, slots=True, kw_only=True)
class Failure:
    kind: FailureKind
    code: str
    message: str
    phase: str

    def __post_init__(self) -> None:
        _require(isinstance(self.kind, FailureKind), "kind must be a FailureKind")
        for name in ("code", "message", "phase"):
            _text(getattr(self, name), name)

    @property
    def exit_code(self) -> ExitCode:
        return {
            FailureKind.CONFIGURATION: ExitCode.INVALID_CONFIGURATION,
            FailureKind.RUNNER: ExitCode.RUNNER_ERROR,
            FailureKind.EXECUTION: ExitCode.EXECUTION_ERROR,
            FailureKind.REVIEW_PROTOCOL: ExitCode.INVALID_REVIEW,
            FailureKind.DECISION_PROTOCOL: ExitCode.EXECUTION_ERROR,
        }[self.kind]


class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    """One call, including partial answers on failure/cancellation.

    A natural nonzero process exit is never success. A transport may explicitly
    record that it terminated a successful turn's lingering process instead.
    Timeout is an EXECUTION failure; intentional interruption is CANCELLED.
    """

    status: ExecutionStatus
    answer: str = ""
    process_exit_code: int | None = None
    completion_seen: bool = False
    failure: Failure | None = None
    cancellation_reason: str | None = None
    cleanup_reason: str | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.status, ExecutionStatus), "status must be an ExecutionStatus")
        _text(self.answer, "answer", empty=True)
        _require(self.process_exit_code is None or type(self.process_exit_code) is int,
                 "process_exit_code must be an integer or None (not bool)")
        _require(type(self.completion_seen) is bool, "completion_seen must be bool")
        _require(self.failure is None or isinstance(self.failure, Failure), "invalid failure")
        for name in ("cancellation_reason", "cleanup_reason"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        if self.status is ExecutionStatus.SUCCEEDED:
            _require(self.failure is None and self.cancellation_reason is None,
                     "successful execution cannot contain failure or cancellation")
            _require(self.completion_seen, "successful execution needs a completion event")
            _text(self.answer, "successful answer")
            _require(self.process_exit_code is not None, "successful execution needs a process exit")
            _require(self.process_exit_code == 0 or self.cleanup_reason is not None,
                     "natural nonzero process exit cannot be success")
        elif self.status is ExecutionStatus.FAILED:
            _require(self.failure is not None and self.failure.kind is FailureKind.EXECUTION,
                     "failed execution needs an EXECUTION failure")
            _require(self.cancellation_reason is None and self.cleanup_reason is None,
                     "failed execution cannot claim cancellation or successful cleanup")
        else:
            _require(self.cancellation_reason is not None, "cancelled execution needs a reason")
            _require(self.failure is None and self.cleanup_reason is None,
                     "cancelled execution cannot also claim failure or successful cleanup")

    @property
    def succeeded(self) -> bool:
        return self.status is ExecutionStatus.SUCCEEDED

    @property
    def exit_code(self) -> ExitCode:
        return {
            ExecutionStatus.SUCCEEDED: ExitCode.OK,
            ExecutionStatus.FAILED: ExitCode.EXECUTION_ERROR,
            ExecutionStatus.CANCELLED: ExitCode.PROCESS_STOP,
        }[self.status]


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class IssueKind(str, Enum):
    LOCAL_FIX = "local_fix"
    DECOMPOSITION_NEEDED = "decomposition_needed"
    MISSING_INPUT = "missing_input"
    SCOPE_CONFLICT = "scope_conflict"
    TECHNICAL_FAILURE = "technical_failure"
    BLOCKED_EXTERNAL = "blocked_external"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewIssue:
    """A finding about the subject; not a failure of the reviewer process."""

    summary: str
    requirement: str
    kind: IssueKind = IssueKind.LOCAL_FIX
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.summary, "issue summary")
        _text(self.requirement, "issue requirement")
        _require(isinstance(self.kind, IssueKind), "kind must be an IssueKind")
        _texts(self.references, "references")


def _validate_assessment(execution: ExecutionResult | None, failure: Failure | None,
                         kind: FailureKind) -> bool:
    _require(execution is None or isinstance(execution, ExecutionResult), "invalid execution")
    _require(failure is None or isinstance(failure, Failure), "invalid assessment failure")
    _require(failure is None or failure.kind is kind, "wrong assessment failure kind")
    if execution is None:
        _require(failure is not None, "missing call needs an explicit protocol failure")
    elif not execution.succeeded:
        _require(failure is None, "transport failure/cancellation must not become a protocol failure")
    return execution is not None and execution.succeeded and failure is None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewResult:
    """A valid FAIL is a technically successful review, but rejects its subject.

    Missing/invalid reviews carry REVIEW_PROTOCOL failures without a verdict.
    Failed or cancelled calls carry no usable verdict; raw output stays in
    execution.answer. Findings about audited source defects belong in issues.
    """

    execution: ExecutionResult | None
    verdict: ReviewVerdict | None = None
    summary: str = ""
    blocking_issues: tuple[ReviewIssue, ...] = ()
    observations: tuple[str, ...] = ()
    breakdown_reason: str | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        valid = _validate_assessment(self.execution, self.failure, FailureKind.REVIEW_PROTOCOL)
        _text(self.summary, "review summary", empty=True)
        _require(type(self.blocking_issues) is tuple and all(
            isinstance(issue, ReviewIssue) for issue in self.blocking_issues),
            "blocking_issues must be a tuple of ReviewIssue objects")
        _texts(self.observations, "observations")
        if valid:
            _require(isinstance(self.verdict, ReviewVerdict), "valid review needs an explicit verdict")
            _text(self.summary, "review summary")
            _require((self.verdict is ReviewVerdict.FAIL) == bool(self.blocking_issues),
                     "review verdict contradicts blocking issues")
            if self.breakdown_reason is not None:
                _text(self.breakdown_reason, "breakdown_reason")
                _require(self.verdict is ReviewVerdict.FAIL, "PASS cannot require a breakdown")
        else:
            _require(self.verdict is None and not self.summary and not self.blocking_issues
                     and not self.observations and self.breakdown_reason is None,
                     "unusable review cannot carry a verdict or normalized findings")

    @property
    def valid(self) -> bool:
        return self.execution is not None and self.execution.succeeded and self.failure is None

    @property
    def accepted(self) -> bool:
        return self.valid and self.verdict is ReviewVerdict.PASS

    @property
    def exit_code(self) -> ExitCode:
        if self.failure is not None:
            return self.failure.exit_code
        return self.execution.exit_code


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionResult:
    """Exact option choice; no implicit truth/NO or completion interpretation.

    The caller supplies its request's immutable option set. Request context,
    boolean option mapping and response-file parsing follow in 1010--1012.
    """

    execution: ExecutionResult | None
    options: tuple[str, ...]
    option: str | None = None
    explanation: str | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        _texts(self.options, "options")
        _require(bool(self.options) and len(set(self.options)) == len(self.options),
                 "options must be non-empty and contain no duplicates")
        valid = _validate_assessment(self.execution, self.failure, FailureKind.DECISION_PROTOCOL)
        if valid:
            _text(self.option, "option")
            _require(self.option in self.options, "option must exactly match an allowed value")
            _text(self.explanation, "explanation")
        else:
            _require(self.option is None and self.explanation is None,
                     "unusable decision cannot carry a choice or explanation")

    @property
    def valid(self) -> bool:
        return self.execution is not None and self.execution.succeeded and self.failure is None

    @property
    def exit_code(self) -> ExitCode:
        if self.failure is not None:
            return self.failure.exit_code
        return self.execution.exit_code

    def __bool__(self) -> bool:
        raise TypeError("DecisionResult is not a boolean; check valid and the exact option")


class AutoBuildStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoBuildResult:
    """Final boundary result for one task attempt, with its current review.

    accepted describes content only; completed additionally requires successful
    mandatory calls, no stop/failure, and no pending obligations (e.g. parent
    review). Prior attempts belong in logs, not in these current-call fields.
    A missing required decision must be supplied as an invalid DecisionResult.
    There is deliberately no review-bypass flag or writable completed field.
    """

    execution: ExecutionResult | None
    review: ReviewResult | None = None
    decision: DecisionResult | None = None
    pending_work: tuple[str, ...] = ()
    failure: Failure | None = None
    cancellation_reason: str | None = None

    def __post_init__(self) -> None:
        _require(self.execution is None or isinstance(self.execution, ExecutionResult), "invalid execution")
        _require(self.review is None or isinstance(self.review, ReviewResult), "invalid review")
        _require(self.decision is None or isinstance(self.decision, DecisionResult), "invalid decision")
        _require(self.failure is None or isinstance(self.failure, Failure), "invalid failure")
        _texts(self.pending_work, "pending_work")
        if self.cancellation_reason is not None:
            _text(self.cancellation_reason, "cancellation_reason")
        if self.execution is None:
            _require(self.failure is not None or self.cancellation_reason is not None,
                     "no attempt needs an explicit failure or cancellation")
        if self.execution is None or not self.execution.succeeded:
            _require(self.review is None and self.decision is None,
                     "failed/unstarted production cannot have current review or decision results")

    @property
    def technical_success(self) -> bool:
        return (self.execution is not None and self.execution.succeeded
                and self.review is not None and self.review.valid
                and (self.decision is None or self.decision.valid)
                and self.failure is None and self.cancellation_reason is None)

    @property
    def accepted(self) -> bool:
        return self.review is not None and self.review.accepted

    @property
    def completed(self) -> bool:
        return self.technical_success and self.accepted and not self.pending_work

    @property
    def exit_code(self) -> ExitCode:
        # Concrete errors outrank cancellation, as in legacy summary_exit_code.
        codes = []
        if self.failure is not None:
            codes.append(self.failure.exit_code)
        for result in (self.execution, self.review, self.decision):
            if result is not None:
                codes.append(result.exit_code)
        for code in codes:
            if code not in (ExitCode.OK, ExitCode.PROCESS_STOP):
                return code
        if self.cancellation_reason is not None or ExitCode.PROCESS_STOP in codes:
            return ExitCode.PROCESS_STOP
        if self.review is None:
            return ExitCode.INVALID_REVIEW
        return ExitCode.OK if self.completed else ExitCode.INCOMPLETE

    @property
    def status(self) -> AutoBuildStatus:
        code = self.exit_code
        if code is ExitCode.OK:
            return AutoBuildStatus.COMPLETE
        if code is ExitCode.PROCESS_STOP:
            return AutoBuildStatus.CANCELLED
        if code is ExitCode.INCOMPLETE:
            return AutoBuildStatus.INCOMPLETE
        return AutoBuildStatus.FAILED
