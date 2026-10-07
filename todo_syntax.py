# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Markdown task headers shared by the runner and linter.

The file remains the editable plan. No state database or rewrite-on-load.
Supported examples: `1. Auftrag: ...`, `1. Task: ...`,
`1. ***Task***: ...`, `1. ***DONE***: ...`, `1. ***OBSOLETE***: ...`.
"""
from __future__ import annotations

import re
import shlex
from typing import Iterator, Match

COMMAND_WORD = r"(?:Auftrag|Task|DONE|OBSOLETE|\*\*\*(?:Task|DONE|OBSOLETE)\*\*\*)"
TASK_PATTERN = re.compile(r"^(\s*\d+(?:\.\d+)*)(?:\.)?\s+(" + COMMAND_WORD + r"):\s*(.*)$", re.I)
OPEN_TASK_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)(?:\.)?\s+(?:Auftrag|Task|\*\*\*Task\*\*\*):\s*(.*)$", re.I)
SYNTAX_PATTERN = re.compile(r"^\*\*\*SYNTAX\s+(auto|legacy|marked-en)\*\*\*$", re.I)
SYNTAX_VALUES = ("auto", "legacy", "marked-en")


def visible_lines(text: str) -> Iterator[tuple[int, str]]:
    """Ignore fenced code examples and HTML comments; keep physical line numbers."""
    text = text.removeprefix("\ufeff")
    if "\ufeff" in text:
        raise UnicodeError("UTF-8 BOM is only permitted once at the start of the ToDo file")
    fence_char = None
    fence_len = 0
    in_comment = False
    for index, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        # ARQUILO treats four leading columns (including a tab stop) as an
        # indented code block. Such examples cannot supply task headers or
        # directives, and their backticks must not open/close a real fence.
        # Still process an indented closing HTML comment while in_comment.
        if not in_comment and (raw.startswith("    ") or re.match(r"^ {0,3}\t", raw)):
            continue
        fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            token = fence.group(1)
            if fence_char is None and not in_comment:
                fence_char, fence_len = token[0], len(token)
            elif fence_char == token[0] and len(token) >= fence_len and not stripped[len(token):].strip():
                fence_char = None
            continue
        if fence_char:
            continue
        if in_comment:
            if "-->" in raw:
                in_comment = False
            continue
        if "<!--" in raw:
            prefix, comment = raw.split("<!--", 1)
            if "-->" not in comment:
                in_comment = True
            # A trailing note must not hide a real task from the scheduler.
            # Commands inside (or after) an HTML comment are not activated.
            if prefix.strip():
                yield index, prefix
            continue
        yield index, raw


def directive_tokens(body: str) -> list[str]:
    """CFG/WAIT text grammar on every host, not a command for any shell.

    Preserve the established shlex POSIX quoting: quote Windows backslash
    paths with single quotes, or use forward slashes. No expansion occurs.
    """
    return shlex.split(body, comments=False, posix=True)


def task_headers(text: str) -> Iterator[tuple[int, Match[str]]]:
    for index, line in visible_lines(text):
        match = TASK_PATTERN.match(line.strip())
        if match:
            yield index, match


def canonical_status(word: str) -> str:
    token = word.strip("*").strip().upper()
    return "Auftrag" if token in {"AUFTRAG", "TASK"} else token


def normalize_syntax(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in SYNTAX_VALUES:
        raise ValueError(f"Unknown todo syntax {value!r}; expected auto, legacy or marked-en.")
    return normalized


def effective_syntax(text: str, preference: str = "auto") -> str:
    preference = normalize_syntax(preference)
    if preference != "auto":
        return preference
    for _, line in visible_lines(text):
        match = SYNTAX_PATTERN.match(line.strip())
        if match and match.group(1).lower() != "auto":
            return match.group(1).lower()
    return "marked-en" if any(m.group(2).startswith("***") for _, m in task_headers(text)) else "legacy"


def render_command(status: str, syntax: str) -> str:
    status = canonical_status(status)
    if syntax == "marked-en":
        return "***Task***" if status == "Auftrag" else f"***{status}***"
    return status
