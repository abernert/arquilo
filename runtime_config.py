# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Small, shared configuration boundary; no import-time environment or file I/O."""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Mapping
import warnings
from legacy_naming import historical_environment_aliases

ARQUILO_CODEX_MODEL_ENV = "ARQUILO_CODEX_MODEL"
ARQUILO_CODEX_REASONING_EFFORT_ENV = "ARQUILO_CODEX_REASONING_EFFORT"
CODEX_REASONING_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# Compatibility only. New configurations use CLI options or the ARQUILO names.
LEGACY_ENV = {
    "ARQUILO_DECISION_MODEL": ("AUTOBUILD_DECISION_MODEL", "METACODEX_DECISION_MODEL"),
    "ARQUILO_DECISION_SYSTEM_PROMPT": ("AUTOBUILD_DECISION_SYSTEM_PROMPT", "METACODEX_DECISION_SYSTEM_PROMPT"),
    "ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS": ("AUTOBUILD_CODEX_POST_TURN_EXIT_GRACE_SECONDS",),
    "ARQUILO_CODEX_STALL_TIMEOUT_SECONDS": ("AUTOBUILD_CODEX_STALL_TIMEOUT_SECONDS",),
    "ARQUILO_CODEX_KILL_GRACE_SECONDS": ("AUTOBUILD_CODEX_KILL_GRACE_SECONDS",),
}


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Configuration values must be strings")
    return value.strip() or None


def environment_value(name: str, *, environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    aliases = (*historical_environment_aliases(name), *LEGACY_ENV.get(name, ()))
    used = [alias for alias in aliases if optional_text(env.get(alias)) is not None]
    if used:
        warnings.warn(f"{', '.join(used)} deprecated; use {name}. {name} takes precedence.",
                      FutureWarning, stacklevel=2)
    for key in (name, *aliases):
        value = optional_text(env.get(key))
        if value is not None:
            return value
    return None


def resolve_model(value: str | None, *, environ: Mapping[str, str] | None = None) -> str | None:
    return optional_text(value) or environment_value(ARQUILO_CODEX_MODEL_ENV, environ=environ)


def resolve_reasoning_effort(value: str | None, *, environ: Mapping[str, str] | None = None) -> str | None:
    resolved = optional_text(value) or environment_value(ARQUILO_CODEX_REASONING_EFFORT_ENV, environ=environ)
    if resolved is None:
        return None
    resolved = resolved.lower()
    if resolved not in CODEX_REASONING_EFFORT_CHOICES:
        raise ValueError(f"Unsupported Codex reasoning effort {resolved!r}; allowed: "
                         + ", ".join(CODEX_REASONING_EFFORT_CHOICES))
    return resolved


def transport_timeout_values(*, environ: Mapping[str, str] | None = None) -> dict[str, float]:
    result = {}
    for field, name, default in (
        ("post_turn_grace", "ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS", 120.0),
        ("stall", "ARQUILO_CODEX_STALL_TIMEOUT_SECONDS", 7200.0),
        ("kill_grace", "ARQUILO_CODEX_KILL_GRACE_SECONDS", 10.0),
    ):
        raw = environment_value(name, environ=environ)
        try:
            value = default if raw is None else float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite nonnegative number") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite nonnegative number")
        result[field] = value
    return result


def resolve_codex_home(*, environ: Mapping[str, str] | None = None) -> Path:
    """Use the owner's Codex home, not an ARQUILO-specific credential store.

    The result is validated against the task workspace by decision_environment.
    Values are host configuration; never accept them from task/model output.
    """
    env = os.environ if environ is None else environ
    values = [value for key, value in env.items()
              if key == "CODEX_HOME" or (os.name == "nt" and key.upper() == "CODEX_HOME")]
    if any(not isinstance(value, str) or "\0" in value for value in values):
        raise ValueError("CODEX_HOME must be a NUL-free path")
    if len(set(values)) > 1:
        raise ValueError("Conflicting CODEX_HOME values")
    value = values[0] if values else None
    if value is not None and (not isinstance(value, str) or "\0" in value):
        raise ValueError("CODEX_HOME must be a NUL-free path")
    if not value or not value.strip():
        return Path.home() / ".codex"
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("CODEX_HOME must be absolute")
    return path
