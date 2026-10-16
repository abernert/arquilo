# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""One-time task-list initialization, before any agent or controller startup."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import safe_io
from controller_state import PlanIntegrityError, state_directory_path
from runtime_files import validate_path
from todo_context import (MAX_PREAMBLE_BYTES, extract_preamble, has_project_text,
                          normalize_mode)
from todo_lint import lint_todo_text


def initialize_todo_template(
    destination: Path, template: Path, *, workdir: Path | None = None,
    state_root: Path | None = None, preamble_mode: str = "auto",
    validate_directives: Callable[[str], None],
) -> tuple[Path, Path, bool]:
    """Return (working file, canonical workspace, created).

    Relative CLI paths remain relative to the invocation directory, not workdir.
    The owner-selected workspace root may be canonicalized; descendants may not
    escape through links. An unused template is neither resolved nor opened.
    Only template bytes are copied: no referenced files, substitutions or resets.
    """
    validate_path(destination, label="todo_file")
    if workdir is not None:
        validate_path(workdir, label="workdir")
    raw_target = safe_io.lexical_path(destination)
    raw_workspace = raw_target.parent if workdir is None else safe_io.lexical_path(workdir)
    validate_path(raw_workspace, label="workdir")
    workspace = raw_workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workdir must already exist and be a directory: {workspace}")
    # Resolve only the explicit root, never links below it or the destination leaf.
    target = (workspace / raw_target.relative_to(raw_workspace)
              if raw_target.is_relative_to(raw_workspace) else raw_target)
    if target == workspace or not target.is_relative_to(workspace):
        raise ValueError("With --todo-template, --todo-file must be inside --workdir.")
    target = safe_io.check_path(target)
    if target.exists():
        if not target.is_file():
            raise ValueError(f"Existing task-list path is not a regular file: {target}")
        return target, workspace, False

    # This lookup is side-effect-free and uses precisely the runner's state key.
    # Even an empty plan-specific directory is evidence of previous startup.
    if state_root is not None:
        validate_path(state_root, label="state_dir")
    state = safe_io.check_path(state_directory_path(workspace, target, state_root))
    if state.exists():
        raise PlanIntegrityError(
            f"Task list is missing but controller state already exists: {state}. "
            "Restore the working task list using that state; do not reinitialize "
            "from a template, reset state, or use --accept-plan-changes to bypass this check."
        )

    validate_path(template, label="todo_template")
    source = safe_io.check_path(safe_io.lexical_path(template), missing_ok=False)
    data = safe_io.read_bytes(source)
    text = data.decode("utf-8").removeprefix("\ufeff")
    if "\ufeff" in text:
        raise UnicodeError("UTF-8 BOM is only permitted once at the start of a template.")
    issues = lint_todo_text(text, workdir=workspace)
    if issues:
        raise ValueError("Invalid task-list template: " + "; ".join(
            f"line {issue.line}: {issue.message}" for issue in issues[:8]))
    validate_directives(text)
    normalize_mode(preamble_mode)
    if preamble_mode != "off":
        prefix = extract_preamble(text)
        has_text = has_project_text(prefix)
        if not has_text and preamble_mode == "required":
            raise ValueError("Project preamble required before the first template task.")
        if has_text and len(prefix.encode("utf-8")) > MAX_PREAMBLE_BYTES:
            raise ValueError("Template project preamble exceeds the supported byte limit.")

    # Recheck before publishing. A concurrent target creation is never overwritten.
    if safe_io.check_path(state).exists():
        raise PlanIntegrityError("Controller state appeared during initialization; restore/check the working task list.")
    safe_io.atomic_create(target, data)
    return target, workspace, True
