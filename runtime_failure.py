# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Small, provider-neutral failure contract. No scheduler or persistence backend."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from runtime_contracts import ExitCode

# Keep the public integer constants and the v1 diagnostic payload unchanged.
EXIT_EXECUTION_ERROR = int(ExitCode.EXECUTION_ERROR)
EXIT_INVALID_REVIEW = int(ExitCode.INVALID_REVIEW)
EXIT_INCOMPLETE = int(ExitCode.INCOMPLETE)


def execution_error(message: str, *, code: str = "execution_failed", phase: str = "execution",
                    process_exit_code: Optional[int] = None) -> dict[str, Any]:
    """Classification is diagnostic only; it can never turn a failure into success.

    Automatic whole-task retry is deliberately NOT authorized: even a network
    failure may occur after a file edit or external side effect.
    """
    text = message.lower()
    category = "technical"
    if any(x in text for x in ("quota", "usage limit", "usage_limit", "insufficient_quota", "kontingent", "credits", "credit balance")):
        category = "quota"
    elif any(x in text for x in ("unauthorized", "authentication", "invalid api key", "401", "permission denied", "forbidden")):
        category = "authentication"
    elif any(x in text for x in ("rate limit", "rate_limit", "429")):
        category = "rate_limit"
    elif any(x in text for x in ("network", "connection", "timeout", "timed out", "disconnected", "dns", "502", "503", "504")):
        category = "network"
    if code == "invalid_review":
        category = "review_protocol"
    return {
        "schema_version": "arquilo.execution_error.v1",
        "code": code, "category": category, "phase": phase,
        "message": message, "process_exit_code": process_exit_code,
        "exit_code": EXIT_INVALID_REVIEW if code == "invalid_review" else EXIT_EXECUTION_ERROR,
        "automatic_task_retry": False,
    }


def failure_exit_code(error: Any, default: int = EXIT_EXECUTION_ERROR) -> int:
    if isinstance(error, Mapping):
        value = error.get("exit_code")
        if type(value) is int and value in (int(ExitCode.INVALID_CONFIGURATION), int(ExitCode.RUNNER_ERROR), EXIT_EXECUTION_ERROR, EXIT_INVALID_REVIEW):
            return value
    return default
