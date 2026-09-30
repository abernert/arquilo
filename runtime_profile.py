#!/usr/bin/env python3
# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Generic, declarative runtime-profile support for ARQUILO.

The core deliberately knows nothing about the domain that authored a profile.
A profile may tighten prompt contracts, protect marked blocks and run a
fail-closed preflight command.  It cannot disable ARQUILO security controls or
change the fixed sandbox, network grant or mandatory review.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import codex_policy
from removed_features import check_removed_fields, check_removed_environment
from runtime_files import PathValidationError, native_path, read_utf8
from runtime_config import ARQUILO_CODEX_MODEL_ENV, ARQUILO_CODEX_REASONING_EFFORT_ENV, environment_value
from legacy_naming import schema_matches
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence, Tuple

ARQUILO_RUNTIME_VERSION = "0.2.0"
ARQUILO_RUNTIME_PROFILE_SCHEMA_VERSION = "arquilo.runtime_profile.v1"
ARQUILO_RUNTIME_PROFILE_ENV = "ARQUILO_RUNTIME_PROFILE"
ARQUILO_RUNTIME_PROFILE_CONTRACT_VERSION = 1
ARQUILO_RUNTIME_PROFILE_PREFLIGHT_CONTRACT_VERSION = 1
ARQUILO_RUNTIME_PROFILE_PROTECTED_BLOCKS_CONTRACT_VERSION = 1
ARQUILO_RUNTIME_PROFILE_PROMPT_POLICY_CONTRACT_VERSION = 1


class RuntimeProfileError(RuntimeError):
    """Raised when a runtime profile is invalid or its preflight fails."""


@dataclass(frozen=True)
class PreflightSpec:
    command: Tuple[str, ...]
    timeout_seconds: float = 30.0
    cwd: Optional[str] = None
    environment: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class RuntimeProfile:
    schema_version: str = ARQUILO_RUNTIME_PROFILE_SCHEMA_VERSION
    profile_id: str = "arquilo.default"
    profile_version: str = "1"
    source_path: Optional[Path] = None
    activation_markers: Tuple[str, ...] = ()
    scope_activation_markers: Tuple[str, ...] = ()
    protected_markers: Tuple[str, ...] = ()
    controller_only_instruction: Optional[str] = None
    task_contract_instruction: Optional[str] = None
    breakdown_scope_guard: str = ""
    legacy_review_boundary: Optional[str] = None
    parent_review_scope_guard: str = ""
    parent_review_terminal_rule: Optional[str] = None
    autobuild_review_rules: Tuple[str, ...] = ()
    preflight: Optional[PreflightSpec] = None
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @property
    def profile_dir(self) -> Optional[Path]:
        return self.source_path.parent if self.source_path is not None else None

    def is_active_for_text(self, text: str) -> bool:
        return all(marker in text for marker in self.activation_markers)

    def is_active_for_file(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return self.is_active_for_text(text)

    def scope_is_active_for_text(self, text: str) -> bool:
        return all(marker in text for marker in self.scope_activation_markers)

    def scope_is_active_for_file(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return self.scope_is_active_for_text(text)

    def format_prompt(self, template: Optional[str], **context: Any) -> Optional[str]:
        if template is None:
            return None
        safe_context = {key: str(value) for key, value in context.items()}
        try:
            return template.format_map(_StrictFormatMap(safe_context))
        except (KeyError, ValueError) as exc:
            raise RuntimeProfileError(
                f"Runtime profile {self.profile_id!r} contains an invalid prompt placeholder: {exc}"
            ) from exc


class _StrictFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        raise KeyError(key)


def _as_non_empty_string(value: Any, *, label: str, required: bool = False) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise RuntimeProfileError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        if required:
            raise RuntimeProfileError(f"{label} must not be empty")
        return None
    return normalized




def _as_prompt_string(value: Any, *, label: str) -> Optional[str]:
    """Validate prompt text without normalising significant whitespace."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeProfileError(f"{label} must be a string")
    if not value.strip():
        return None
    return value

def _as_string_tuple(value: Any, *, label: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuntimeProfileError(f"{label} must be an array of strings")
    result = []
    seen = set()
    for index, item in enumerate(value):
        normalized = _as_non_empty_string(
            item, label=f"{label}[{index}]", required=True
        )
        assert normalized is not None
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _parse_preflight(raw: Any) -> Optional[PreflightSpec]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RuntimeProfileError("preflight must be an object")
    try:
        check_removed_fields(raw, source="Runtime-Profil preflight")
    except ValueError as exc:
        raise RuntimeProfileError(str(exc)) from exc
    command = _as_string_tuple(raw.get("command"), label="preflight.command")
    if not command:
        raise RuntimeProfileError("preflight.command must not be empty")
    timeout_raw = raw.get("timeout_seconds", 30)
    try:
        timeout_seconds = float(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeProfileError("preflight.timeout_seconds must be numeric") from exc
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        raise RuntimeProfileError(
            "preflight.timeout_seconds must be > 0 and <= 3600"
        )
    cwd = _as_non_empty_string(raw.get("cwd"), label="preflight.cwd")
    env_raw = raw.get("environment", {})
    if not isinstance(env_raw, dict):
        raise RuntimeProfileError("preflight.environment must be an object")
    try:
        check_removed_environment(env_raw)
    except ValueError as exc:
        raise RuntimeProfileError(str(exc)) from exc
    environment: dict[str, str] = {}
    for key, value in env_raw.items():
        normalized_key = _as_non_empty_string(
            key, label="preflight.environment key", required=True
        )
        if not isinstance(value, str):
            raise RuntimeProfileError(
                f"preflight.environment[{normalized_key!r}] must be a string"
            )
        assert normalized_key is not None
        environment[normalized_key] = value
    return PreflightSpec(
        command=command,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        environment=MappingProxyType(environment),
    )


def empty_runtime_profile() -> RuntimeProfile:
    return RuntimeProfile()


def resolve_runtime_profile_path(
    explicit_path: Optional[Path | str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    raw: Optional[str]
    if explicit_path is not None:
        raw = str(explicit_path)
    else:
        env = os.environ if environ is None else environ
        raw = environment_value(ARQUILO_RUNTIME_PROFILE_ENV, environ=env)
    if not raw or not str(raw).strip():
        return None
    try:
        return native_path(str(raw), label="runtime profile")
    except PathValidationError as exc:
        raise RuntimeProfileError(str(exc)) from exc


def load_runtime_profile(
    explicit_path: Optional[Path | str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> RuntimeProfile:
    path = resolve_runtime_profile_path(explicit_path, environ=environ)
    if path is None:
        return empty_runtime_profile()
    if not path.is_file():
        raise RuntimeProfileError(f"Runtime profile not found: {path}")
    try:
        raw = json.loads(read_utf8(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeProfileError(f"Runtime profile is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeProfileError("Runtime profile root must be an object")
    try:
        codex_policy.reject_policy_keys(raw, source="Runtime-Profil")
    except codex_policy.CodexPolicyError as exc:
        raise RuntimeProfileError(str(exc)) from exc
    schema_version = _as_non_empty_string(
        raw.get("schema_version"), label="schema_version", required=True
    )
    if not schema_matches(schema_version, ARQUILO_RUNTIME_PROFILE_SCHEMA_VERSION):
        raise RuntimeProfileError(
            f"Unsupported runtime profile schema {schema_version!r}; expected "
            f"{ARQUILO_RUNTIME_PROFILE_SCHEMA_VERSION!r}"
        )
    profile_id = _as_non_empty_string(
        raw.get("profile_id"), label="profile_id", required=True
    )
    profile_version = _as_non_empty_string(
        raw.get("profile_version", "1"), label="profile_version", required=True
    )
    prompt_raw = raw.get("prompt_policy", {})
    if not isinstance(prompt_raw, dict):
        raise RuntimeProfileError("prompt_policy must be an object")
    try:
        codex_policy.reject_policy_keys(prompt_raw, source="Runtime-Profil prompt_policy")
    except codex_policy.CodexPolicyError as exc:
        raise RuntimeProfileError(str(exc)) from exc
    metadata_raw = raw.get("metadata", {})
    if not isinstance(metadata_raw, dict):
        raise RuntimeProfileError("metadata must be an object")
    autobuild_rules = _as_string_tuple(
        prompt_raw.get("autobuild_review_rules"),
        label="prompt_policy.autobuild_review_rules",
    )
    assert profile_id is not None and profile_version is not None
    return RuntimeProfile(
        schema_version=ARQUILO_RUNTIME_PROFILE_SCHEMA_VERSION,
        profile_id=profile_id,
        profile_version=profile_version,
        source_path=path,
        activation_markers=_as_string_tuple(
            raw.get("activation_markers"), label="activation_markers"
        ),
        scope_activation_markers=_as_string_tuple(
            raw.get("scope_activation_markers"), label="scope_activation_markers"
        ),
        protected_markers=_as_string_tuple(
            raw.get("protected_markers"), label="protected_markers"
        ),
        controller_only_instruction=_as_prompt_string(
            prompt_raw.get("controller_only_instruction"),
            label="prompt_policy.controller_only_instruction",
        ),
        task_contract_instruction=_as_prompt_string(
            prompt_raw.get("task_contract_instruction"),
            label="prompt_policy.task_contract_instruction",
        ),
        breakdown_scope_guard=_as_prompt_string(
            prompt_raw.get("breakdown_scope_guard"),
            label="prompt_policy.breakdown_scope_guard",
        )
        or "",
        legacy_review_boundary=_as_prompt_string(
            prompt_raw.get("legacy_review_boundary"),
            label="prompt_policy.legacy_review_boundary",
        ),
        parent_review_scope_guard=_as_prompt_string(
            prompt_raw.get("parent_review_scope_guard"),
            label="prompt_policy.parent_review_scope_guard",
        )
        or "",
        parent_review_terminal_rule=_as_prompt_string(
            prompt_raw.get("parent_review_terminal_rule"),
            label="prompt_policy.parent_review_terminal_rule",
        ),
        autobuild_review_rules=autobuild_rules,
        preflight=_parse_preflight(raw.get("preflight")),
        metadata=MappingProxyType(dict(metadata_raw)),
    )


def _format_preflight_token(
    token: str,
    *,
    profile: RuntimeProfile,
    workdir: Path,
    todo_file: Path,
) -> str:
    profile_dir = profile.profile_dir
    context = {
        "python": sys.executable,
        "workdir": str(workdir),
        "todo_file": str(todo_file),
        "profile_path": str(profile.source_path or ""),
        "profile_dir": str(profile_dir or ""),
    }
    try:
        return token.format_map(_StrictFormatMap(context))
    except (KeyError, ValueError) as exc:
        raise RuntimeProfileError(
            f"Runtime profile {profile.profile_id!r} contains an invalid preflight placeholder: {exc}"
        ) from exc


def run_runtime_profile_preflight(
    profile: RuntimeProfile,
    *,
    workdir: Path,
    todo_file: Path,
    environ: Optional[Mapping[str, str]] = None,
) -> None:
    spec = profile.preflight
    if spec is None or not profile.is_active_for_file(todo_file):
        return
    command = [
        _format_preflight_token(
            token,
            profile=profile,
            workdir=workdir,
            todo_file=todo_file,
        )
        for token in spec.command
    ]
    cwd: Optional[Path] = None
    if spec.cwd:
        try:
            cwd = native_path(_format_preflight_token(
                spec.cwd, profile=profile, workdir=workdir, todo_file=todo_file,
            ), label="runtime profile preflight cwd")
        except (PathValidationError, OSError) as exc:
            raise RuntimeProfileError(str(exc)) from exc
    env = dict(os.environ if environ is None else environ)
    for key, value in spec.environment.items():
        env[key] = _format_preflight_token(
            value,
            profile=profile,
            workdir=workdir,
            todo_file=todo_file,
        )
    try:
        check_removed_environment(env)
    except ValueError as exc:
        raise RuntimeProfileError(str(exc)) from exc
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=spec.timeout_seconds,
            check=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise RuntimeProfileError(
            f"Runtime profile preflight could not be executed for {profile.profile_id!r}: {exc}"
        ) from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if len(details) > 2000:
            details = details[:2000] + "…"
        suffix = f": {details}" if details else ""
        raise RuntimeProfileError(
            f"Runtime profile preflight failed for {profile.profile_id!r} "
            f"with exit code {result.returncode}{suffix}"
        )
