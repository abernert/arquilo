# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Neutral ToDo-ID recognition shared by Runner and AutoBuild."""

from __future__ import annotations

import re
from typing import Optional

_TODO_ID_FULL_RE = re.compile(r"^\d+(?:\.\d+)*$")
_TODO_IDENTIFIER_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[-_].+)?$")


def extract_todo_id(value: Optional[str]) -> Optional[str]:
    """Extract a ToDo-ID from a raw identifier string if possible.

    Accepts either a plain ToDo-ID (`61.6`) or an identifier with an
    explicit `-` / `_` suffix (`61.6-main`) and returns the numeric
    dotted ID (`61.6`).
    """

    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = _TODO_IDENTIFIER_RE.fullmatch(cleaned)
    if match:
        todo_id = match.group(1)
        if _TODO_ID_FULL_RE.fullmatch(todo_id):
            return todo_id
    return None
