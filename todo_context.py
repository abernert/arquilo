# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Project preambles for one run_todos -> AutoBuild handoff.

The editable Markdown workspace remains authoritative. This is a context
snapshot, not a task store, scheduler or authorization mechanism.
"""
from __future__ import annotations

from prompt_config import PromptConfig, PromptConfigError, load_prompt_config

from pathlib import Path
import re

from runtime_files import read_utf8
from todo_syntax import task_headers, visible_lines

TODO_PREAMBLE_CONTRACT_VERSION = 1
PREAMBLE_MODES = ("auto", "off", "required")
MAX_PREAMBLE_BYTES = 65536



class TaskContextError(RuntimeError):
    """Required context is missing, unreadable or too large; never truncate it."""


def normalize_mode(mode: str) -> str:
    if mode not in PREAMBLE_MODES:
        raise ValueError(f"Invalid --todo-preamble {mode!r}; expected {PREAMBLE_MODES}.")
    return mode


def extract_preamble(text: str) -> str:
    """Exact prefix before the first visible Task/Auftrag/DONE/OBSOLETE header.

    Only a leading encoding BOM is removed. Line endings and whitespace stay
    intact; examples and comments follow the scheduler's visibility rules.
    """
    first = next(task_headers(text), None)
    if first is None:
        return ""
    return "".join(text.splitlines(keepends=True)[:first[0]]).removeprefix("\ufeff")


def has_project_text(preamble: str) -> bool:
    for _, line in visible_lines(preamble):
        value = line.strip()
        if not value or re.fullmatch(r"\*\*\*.*\*\*\*", value):
            continue
        if value in ("---", "***", "___"):
            continue
        return True
    return False


def augment_with_preamble(task_text: str, todo_file: Path, *, mode: str = "auto",
                          prompt_config: PromptConfig | None = None) -> str:
    """Capture live context once; AutoBuild reuses it for review and repair.

    The next central handoff reads the file again, including in a subworkspace.
    Standalone AutoBuild has no implicit ToDo preamble. No referenced files are
    loaded and no hashes or signatures are calculated.
    """
    prompts = load_prompt_config(prompt_config)
    normalize_mode(mode)
    if mode == "off":
        return task_text
    try:
        prefix = extract_preamble(read_utf8(todo_file, preserve_newlines=True))
    except (OSError, UnicodeError) as exc:
        raise TaskContextError(f"Cannot read ToDo preamble from {todo_file}: {exc}") from exc
    if not has_project_text(prefix):
        if mode == "required":
            raise TaskContextError(f"Project preamble required before the first task: {todo_file}")
        return task_text
    size = len(prefix.encode("utf-8"))
    if size > MAX_PREAMBLE_BYTES:
        raise TaskContextError(
            f"ToDo preamble has {size} UTF-8 bytes (limit {MAX_PREAMBLE_BYTES}). "
            "Shorten it or explicitly select --todo-preamble off; context was NOT truncated."
        )
    # Delimiters label source text; they are not a security boundary.
    return (
        prompts.render('preamble_envelope', semantics=prompts.render('preamble_semantics'), todo_filename=todo_file.name, byte_count=size, preamble=prefix, separator='' if prefix.endswith('\n') else '\n', task=task_text)
    )


def __getattr__(name: str):
    if name == "SEMANTICS":
        return load_prompt_config().render("preamble_semantics")
    raise AttributeError(name)
