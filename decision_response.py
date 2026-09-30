# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Strict, standard-library validation of the CLI-owned Decide response file."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from decision_request import DecisionRequest
from runtime_contracts import DecisionResult, ExecutionResult, Failure, FailureKind

MAX_RESPONSE_BYTES = 1024 * 1024


class DecisionResponseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def response_schema(request: DecisionRequest) -> dict:
    """A fresh schema for this exact option set; never normalize enum values."""
    return {
        "type": "object",
        "properties": {
            "option": {"type": "string", "enum": list(request.options)},
            "explanation": {"type": "string", "minLength": 1, "pattern": r"\S"},
        },
        "required": ["option", "explanation"],
        "additionalProperties": False,
    }


def parse_response(data: bytes, options: tuple[str, ...]) -> tuple[str, str]:
    """Accept one UTF-8 JSON object, with at most one BOM at byte zero.

    Whitespace around the document is JSON whitespace. The option and the
    explanation themselves are returned verbatim, never trimmed or case-folded.
    """
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise ValueError("Duplicate JSON key")
            obj[key] = value
        return obj

    def constant(value):
        raise ValueError("Non-finite JSON number")

    try:
        text = data.decode("utf-8-sig")
        obj = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        if type(obj) is not dict or set(obj) != {"option", "explanation"}:
            raise ValueError("Expected exactly option and explanation")
        option, explanation = obj["option"], obj["explanation"]
        if type(option) is not str or option not in options:
            raise ValueError("Option must exactly match an allowed value")
        if type(explanation) is not str or not explanation.strip():
            raise ValueError("Explanation must be a non-empty string")
        # JSON escapes can otherwise smuggle lone surrogates into Python str.
        option.encode("utf-8")
        explanation.encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DecisionResponseError("decision_invalid_response", f"Invalid decision JSON: {exc}") from exc
    return option, explanation


def _read_response(path: Path) -> bytes:
    """Bound the read and reject links/special files instead of following them."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise DecisionResponseError("decision_response_file_type", "Response must be a new regular file, not a link")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise DecisionResponseError("decision_response_file_changed", "Response file changed while opening")
            data = stream.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise DecisionResponseError("decision_response_too_large", f"Response exceeds {MAX_RESPONSE_BYTES} bytes")
        return data
    except FileNotFoundError as exc:
        raise DecisionResponseError("decision_response_missing", "CLI did not create its final response file") from exc
    except OSError as exc:
        raise DecisionResponseError("decision_response_unreadable", f"Cannot read CLI response: {exc}") from exc


def validate_response(request: DecisionRequest, execution: ExecutionResult,
                      response_path: Path) -> DecisionResult:
    """A perfect file cannot cure a failed, cancelled or incomplete execution.

    The caller must allocate a fresh response path and run the transport first.
    Neither execution.answer nor any log is a substitute for this file.
    """
    if not execution.succeeded:
        return DecisionResult(execution=execution, options=request.options)
    try:
        option, explanation = parse_response(_read_response(response_path), request.options)
    except DecisionResponseError as exc:
        return DecisionResult(execution=execution, options=request.options,
            failure=Failure(kind=FailureKind.DECISION_PROTOCOL, code=exc.code,
                            message=str(exc), phase=request.phase))
    return DecisionResult(execution=execution, options=request.options,
                          option=option, explanation=explanation)
