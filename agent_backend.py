# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Explicit run-wide backend selection. No import-time configuration or fallback."""
from __future__ import annotations
from typing import Mapping
import os
from runtime_config import optional_text

BACKENDS = ("codex", "claude-code")


def validate_backend(value: str) -> str:
    if value not in BACKENDS:
        extra = " OpenCode is reserved for a later release." if value in {"open-code", "opencode"} else ""
        raise ValueError(f"Unsupported backend {value!r}; choose codex or claude-code." + extra)
    return value


def validate_options(backend: str, *, config_profile=None, extra_args=(), model_provider=None,
                     trusted_codex_home=None) -> None:
    validate_backend(backend)
    if backend == "claude-code" and (config_profile is not None or extra_args or
                                     model_provider is not None or trusted_codex_home is not None):
        raise ValueError("Claude Code does not accept Codex profiles/providers/HOME or raw extra arguments. "
                         "Use the trusted Claude Code user configuration and provider environment.")


def resolve_model(value: str | None, *, backend: str, environ: Mapping[str, str] | None = None) -> str | None:
    validate_backend(backend)
    if backend == "codex":
        from runtime_config import resolve_model as codex_model
        return codex_model(value, environ=environ)
    env = os.environ if environ is None else environ
    return optional_text(value) or optional_text(env.get("ARQUILO_CLAUDE_CODE_MODEL"))


def resolve_effort(value: str | None, *, backend: str, environ: Mapping[str, str] | None = None) -> str | None:
    validate_backend(backend)
    if backend == "codex":
        from runtime_config import resolve_reasoning_effort
        return resolve_reasoning_effort(value, environ=environ)
    env = os.environ if environ is None else environ
    result = optional_text(value) or optional_text(env.get("ARQUILO_CLAUDE_CODE_REASONING_EFFORT"))
    if result is not None and result not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Claude Code effort must be low, medium, high, xhigh or max; no Codex effort mapping is implicit.")
    return result


def logs_name(backend: str) -> str:
    return ".codex_runs" if validate_backend(backend) == "codex" else ".arquilo_runs"


def add_backend_argument(parser) -> None:
    parser.add_argument("--backend", choices=BACKENDS, default="codex",
                        help="Agent runtime for ALL phases including review and Decide (default: codex).")
