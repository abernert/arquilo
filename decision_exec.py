# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Fresh, restricted Codex executions and archived decisions (1011–1013).

execute_attempt returns a technical TransportResult; execute_decision also
validates the CLI-owned response file. Callers own the
logs; the working directory is deliberately retained until explicitly cleaned
after archiving. No credentials, global configuration or project files are read
or copied by this module. An empty cwd is NOT an absolute read sandbox.
"""
from __future__ import annotations

from execution_budget import CallBudget, BudgetExhausted

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
from typing import Callable, Mapping

from codex_launcher import resolve_launcher
from codex_policy import CodexPolicyError
import codex_transport as transport
import decision_archive as archive
from decision_request import DecisionRequest
from decision_response import response_schema, validate_response
from runtime_contracts import DecisionResult, ExecutionResult, ExecutionStatus, Failure, FailureKind
from runtime_files import atomic_write_text, native_path, safe_component, unique_directory


def _outside(path: Path, project: Path, label: str) -> Path:
    if path.is_relative_to(project):
        raise CodexPolicyError(f"{label} must be outside the project tree: {path}")
    return path


def _absolute(value: str | Path, label: str) -> Path:
    if not Path(value).is_absolute():
        raise CodexPolicyError(f"{label} must be an explicit absolute path")
    return native_path(value, label=label)


def configured_codex_home(source: Mapping[str, str], explicit: Path | None = None) -> Path:
    """Resolve only the config HOME location, never inspect config or credentials.

    An explicit settings path wins; otherwise honor the caller's CODEX_HOME.
    Absence of a file auth store is normal for external providers/keyrings.
    """
    env = {k.upper(): v for k, v in source.items()} if os.name == "nt" else source
    value = explicit if explicit is not None else env.get("CODEX_HOME")
    if value is None:
        home = env.get("USERPROFILE" if os.name == "nt" else "HOME")
        value = (Path(home) if home else Path.home()) / ".codex"
    path = _absolute(value, "Codex configuration home")
    if path.exists() and not path.is_dir():
        raise CodexPolicyError("Codex configuration home is not a directory.")
    return path


def decision_environment(source: Mapping[str, str], *, project_root: Path,
                         trusted_codex_home: Path | None = None) -> dict[str, str]:
    """Inherit a COPY of trusted host environment, including provider/proxy/CA vars.

    The source must come from the host/caller, not a task or model. No .env is
    loaded and no environment values/configuration/auth contents are archived.
    Keep spelling and values unchanged; case-folding only detects Windows aliases.
    """
    result: dict[str, str] = {}
    seen: dict[str, str] = {}
    for key, value in source.items():
        if (not isinstance(key, str) or not isinstance(value, str) or not key
                or "\0" in key + value or "=" in key):
            raise CodexPolicyError("Process environment must contain valid NUL-free strings.")
        canonical = key.upper() if os.name == "nt" else key
        if canonical in seen and seen[canonical] != value:
            raise CodexPolicyError("Conflicting environment variable spellings.")
        seen[canonical] = value
        result[key] = value
    home = configured_codex_home(result, trusted_codex_home)
    _outside(home, _absolute(project_root, "project_root"), "Codex configuration home")
    if trusted_codex_home is not None:
        for key in list(result):
            if key == "CODEX_HOME" or (os.name == "nt" and key.upper() == "CODEX_HOME"):
                del result[key]
        result["CODEX_HOME"] = str(home)
    return result


@dataclass(frozen=True, slots=True)
class DecisionAttempt:
    """A retained attempt, with no field suggesting semantic acceptance."""

    cwd: Path
    result: transport.TransportResult

    def cleanup_workdir(self) -> None:
        """Caller must first persist required artifacts, including CLI response.

        No automatic cleanup, including on successful execution or archive errors.
        The wrapper places every output outside cwd, so this removes only work.
        """
        shutil.rmtree(self.cwd)


def execute_attempt(
    request: DecisionRequest, *, project_root: Path, trusted_codex_home: Path | None,
    env: Mapping[str, str], raw_log: Path, pretty_log: Path,
    temp_root: Path | None = None, launcher: str = "codex",
    output_schema: Path | None = None, output_last_message: Path | None = None,
    timeouts: transport.TransportTimeouts | None = None,
    model_provider: str | None = None, config_profile: str | None = None,
    process_stop_path: Path | None = None,
    cancel_requested: Callable[[], str | None] | None = None,
) -> DecisionAttempt:
    """Run a fresh non-repo attempt using the single shared Codex transport.

    trusted_codex_home/env/launcher are host configuration, never task input.
    The temporary root must be outside the project and any Git repository.
    A named trusted profile/provider can be selected explicitly, never from task text.
    There is no network/extra_args/resume escape hatch in this API.
    """
    if not isinstance(request, DecisionRequest):
        raise TypeError("request must be DecisionRequest")
    prompt = request.to_prompt()  # Validate before filesystem/process work.
    project = _absolute(project_root, "project_root")
    child_env = decision_environment(env, project_root=project, trusted_codex_home=trusted_codex_home)
    base = _outside(_absolute(temp_root if temp_root is not None else tempfile.gettempdir(), "temp_root"),
                    project, "Decide temporary root")
    if not base.is_dir():
        raise CodexPolicyError("Decide temporary root must exist")
    host_env = {k.upper(): v for k, v in child_env.items()} if os.name == "nt" else child_env
    home_value = host_env.get("USERPROFILE" if os.name == "nt" else "HOME")
    host_home = Path(home_value).resolve() if home_value else Path.home().resolve()
    config_home = configured_codex_home(child_env, trusted_codex_home)
    for parent in (base, *base.parents):
        # A user's normal home can still contain .codex when CODEX_HOME selects
        # another trusted configuration. Windows TEMP normally descends from
        # that home. Do not mistake it for an unrelated project configuration.
        trusted_user_parent = parent == host_home or (parent / ".codex").resolve() == config_home
        if ((parent / ".git").exists() or (not trusted_user_parent and (
                (parent / ".codex").exists() or (parent / ".agents").exists()))):
            raise CodexPolicyError(f"Decide temporary root inherits repository/configuration context from {parent}")
    outputs = {}
    for name, value in (("raw_log", raw_log), ("pretty_log", pretty_log),
                        ("output_schema", output_schema), ("output_last_message", output_last_message)):
        if value is not None:
            if name == "output_last_message":
                # lstat also sees dangling links; never resolve/delete an old
                # response and then let it masquerade as this attempt's output.
                try:
                    Path(value).lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise CodexPolicyError("Decision response path must initially be absent")
            outputs[name] = _absolute(value, name)
    selected = resolve_launcher(launcher, cwd=base, env=child_env)
    for path in (selected.source, *selected.argv):
        _outside(native_path(path, label="Codex launcher"), project, "Codex launcher")
    cwd = Path(tempfile.mkdtemp(prefix="arquilo-decide-", dir=base)).resolve()
    try:
        if any(path.is_relative_to(cwd) for path in outputs.values()):
            raise CodexPolicyError("Decision logs/schema/response must stay outside its disposable cwd")
        call = transport.CodexExecRequest(
            prompt=prompt, cwd=cwd, env=child_env, launcher=(selected.source,),
            model=request.model, reasoning_effort=request.reasoning_effort,
            model_provider=model_provider, config_profile=config_profile,
            network_access=False, sandbox="read-only", decision_only=True,
            phase="decide", timeouts=timeouts or transport.TransportTimeouts(total=120),
            process_stop_path=process_stop_path, cancel_requested=cancel_requested, **outputs,
        )
    except Exception:
        # Preparation only; no execution/artifacts exist to preserve yet.
        cwd.rmdir()
        raise
    return DecisionAttempt(cwd=cwd, result=transport.execute(call))


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionExecSettings:
    """Explicit host settings; log_root is the common Codex log root.

    max_attempts=1 disables replay; 2 permits one invalid-format repair.
    """

    project_root: Path
    trusted_codex_home: Path | None = None
    env: Mapping[str, str]
    log_root: Path
    temp_root: Path | None = None
    launcher: str = "codex"
    model_provider: str | None = None
    config_profile: str | None = None
    timeouts: transport.TransportTimeouts | None = None
    process_stop_path: Path | None = None
    cancel_requested: Callable[[], str | None] | None = None
    max_attempts: int = 1
    call_budget: CallBudget | None = None

    def __post_init__(self) -> None:
        from codex_policy import validate_config_profile, validate_model_provider
        validate_model_provider(self.model_provider)
        validate_config_profile(self.config_profile)
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 2:
            raise ValueError("Decide max_attempts must be 1 or 2 (at most one format repair)")
        for name in ("project_root", "trusted_codex_home", "log_root", "temp_root", "process_stop_path"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _absolute(value, name))
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))


@dataclass(frozen=True, slots=True)
class ArchivedDecisionAttempt:
    """One immutable outcome, including any separate archive failure."""

    result: DecisionResult
    directory: Path | None
    attempt: DecisionAttempt | None
    archive_complete: bool
    archive_error: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionCall:
    """Final outcome plus every attempt; normal return never deletes logs."""

    result: DecisionResult
    directory: Path | None
    attempt: DecisionAttempt | None
    attempts: tuple[ArchivedDecisionAttempt, ...] = ()
    request: DecisionRequest | None = None

    def cleanup_workdirs(self) -> None:
        """Opt-in removal of only disposable workdirs after committed archives.

        Failed/partial archiving prevents all cleanup. Check every attempt
        before deleting any directory. Logs, responses and manifests remain.
        """
        if not self.attempts or any(not row.archive_complete for row in self.attempts):
            raise RuntimeError("Decision archive is incomplete; retain all temporary workdirs")
        for row in self.attempts:
            manifest = json.loads((row.directory / "call.json").read_text(encoding="utf-8"))
            if not manifest.get("archive_complete"):
                raise RuntimeError("Decision archive is not committed")
            if row.attempt is not None and row.directory.resolve().is_relative_to(row.attempt.cwd.resolve()):
                raise RuntimeError("Decision archive must not be inside the disposable workdir")
        for row in self.attempts:
            if row.attempt is not None and row.attempt.cwd.exists():
                row.attempt.cleanup_workdir()


def _failure(request: DecisionRequest, code: str, message: str,
             previous: DecisionResult | None = None) -> DecisionResult:
    execution = previous.execution if previous is not None else None
    return DecisionResult(options=request.options, execution=ExecutionResult(
        status=ExecutionStatus.FAILED, answer=execution.answer if execution else "",
        process_exit_code=execution.process_exit_code if execution else None,
        completion_seen=execution.completion_seen if execution else False,
        failure=Failure(kind=FailureKind.EXECUTION, code=code, message=message, phase=request.phase)))


def _attempt_directory(parent: Path, number: int) -> Path:
    directory = parent / f"attempt-{number:03d}"
    directory.mkdir()  # Never reuse an old or concurrently occupied attempt.
    return directory


def execute_decision(request: DecisionRequest, *, settings: DecisionExecSettings) -> DecisionCall:
    """Archive each fresh attempt; optionally replay one invalid JSON answer.

    The CLI writes response.json through --output-last-message (-o). We never
    write that file, recover it from stdout or reuse a previous answer. Format
    retries keep the exact same input/prompt/schema and use fresh sessions and
    paths. Technical errors, missing/unreadable files and archive errors never
    qualify. No ambient config/environment dump, hash, signature or log deletion.
    """
    if not isinstance(request, DecisionRequest) or not isinstance(settings, DecisionExecSettings):
        raise TypeError("Expected DecisionRequest and DecisionExecSettings")
    prompt = request.to_prompt()
    parent = None
    try:
        branch = settings.log_root / "decide"
        for value in (request.run_id, request.task_id, request.phase):
            branch /= safe_component(value, limit=40)
        if not branch.resolve().is_relative_to(settings.log_root):
            raise OSError("Decision archive path escapes the configured log root")
        parent = unique_directory(branch, prefix="decision")
    except KeyboardInterrupt:
        result = DecisionResult(options=request.options, execution=ExecutionResult(
            status=ExecutionStatus.CANCELLED, cancellation_reason="KeyboardInterrupt allocating archive"))
        return DecisionCall(result, parent, None,
                            (ArchivedDecisionAttempt(result, parent, None, False, "Archive allocation interrupted"),), request)
    except (OSError, ValueError, RuntimeError) as exc:
        result = _failure(request, "decision_archive_failed", f"Cannot allocate decision archive: {exc}")
        return DecisionCall(result, None, None,
                            (ArchivedDecisionAttempt(result, None, None, False, str(exc)),), request)
    records = []
    for number in range(1, settings.max_attempts + 1):
        directory, attempt, original_result = None, None, None
        manifest = archive.initial_manifest(request, settings, decision_id=parent.name, number=number,
            retry_of=records[-1].directory.name if records else None,
            retry_reason="decision_invalid_response" if records else None)
        try:
            directory = _attempt_directory(parent, number)
            archive.write_json(directory / "call.json", manifest)
            archive.write_json(directory / "input.json", request.to_dict())
            atomic_write_text(directory / "prompt.md", prompt)
            schema_path, response_path = directory / "schema.json", directory / "response.json"
            atomic_write_text(schema_path, json.dumps(response_schema(request), ensure_ascii=False, indent=2) + "\n")
        except KeyboardInterrupt:
            result = DecisionResult(options=request.options, execution=ExecutionResult(
                status=ExecutionStatus.CANCELLED, cancellation_reason="KeyboardInterrupt preparing archive"))
            records.append(_archive_failed(directory, attempt, result, manifest, "Archive preparation interrupted"))
            break
        except (OSError, ValueError, RuntimeError) as exc:
            result = _failure(request, "decision_archive_failed", f"Cannot prepare decision archive: {exc}")
            records.append(_archive_failed(directory, attempt, result, manifest, str(exc)))
            break
        try:
            if settings.call_budget is not None:
                settings.call_budget.consume(request.task_id, f"{request.phase}:decide:{number}")
            attempt = execute_attempt(request,
                project_root=settings.project_root, trusted_codex_home=settings.trusted_codex_home,
                env=settings.env, raw_log=directory / "events.jsonl", pretty_log=directory / "pretty.log",
                temp_root=settings.temp_root, launcher=settings.launcher, timeouts=settings.timeouts,
                model_provider=settings.model_provider, config_profile=settings.config_profile,
                output_schema=schema_path, output_last_message=response_path,
                process_stop_path=settings.process_stop_path, cancel_requested=settings.cancel_requested)
            result = validate_response(request, attempt.result.execution, response_path)
        except BudgetExhausted as exc:
            result = _failure(request, "call_budget_exhausted", str(exc))
        except KeyboardInterrupt:
            result = DecisionResult(options=request.options, execution=ExecutionResult(
                status=ExecutionStatus.CANCELLED, cancellation_reason="KeyboardInterrupt"))
        except (OSError, ValueError, RuntimeError) as exc:
            result = _failure(request, "decision_setup_failed", f"Cannot prepare decision execution: {exc}")
        retry = (number < settings.max_attempts and result.failure is not None
                 and result.failure.code == "decision_invalid_response"
                 and result.execution is not None and result.execution.succeeded)
        original_result = result
        try:
            manifest = archive.finish_manifest(manifest, directory=directory, result=result,
                                               attempt=attempt, retry_scheduled=retry)
            archive.write_json(directory / "call.json", manifest)
            records.append(ArchivedDecisionAttempt(result, directory, attempt, True))
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
            detail = f"{type(exc).__name__}: {exc}"
            result = _failure(request, "decision_archive_failed", f"Cannot commit decision archive: {detail}", original_result)
            records.append(_archive_failed(directory, attempt, result, manifest, detail, original_result))
            break
        if not retry:
            break
    final = records[-1]
    return DecisionCall(final.result, final.directory, final.attempt, tuple(records), request)


def _archive_failed(directory, attempt, result, manifest, error, original_result=None) -> ArchivedDecisionAttempt:
    """Best-effort failure snapshot; never delete or retry after archive errors.

    If even this write fails, the return object is the structured diagnostic;
    an earlier preparing manifest and atomic-write recovery file may remain.
    """
    failed = manifest | {"finished_at": archive.timestamp(), "status": "archive_failed",
        "archive_complete": False, "archive_error": error, "result": asdict(result),
        "original_result": asdict(original_result) if original_result is not None else None,
        "cwd": str(attempt.cwd) if attempt else None,
        "cli_version": attempt.result.trace.capture.get("decision_cli_version") if attempt else None,
        "capture_directory": str(attempt.result.trace.capture_dir) if attempt else None,
        "retry": manifest["retry"] | {"scheduled": False}}
    if directory is not None:
        try:
            archive.write_json(directory / "call.json", failed)
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
            error += f"; failure status could not be archived: {type(exc).__name__}: {exc}"
    return ArchivedDecisionAttempt(result, directory, attempt, False, error)
