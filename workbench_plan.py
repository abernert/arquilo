# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Owner plan editing: preview, canonical lint, compare-and-save, and backups."""
from __future__ import annotations

from dataclasses import asdict
import difflib
from pathlib import Path
import re
import threading

import safe_io
from controller_state import state_directory
from todo_lint import lint_todo_file
from todo_syntax import canonical_status, task_headers, visible_lines, TASK_PATTERN
from workbench_files import (MAX_TEXT_BYTES, WorkbenchError, child_path, digest,
                             lease, read_bytes, strict_json)


class PlanService:
    def __init__(self, workspace: Path, todo: Path, state_root: Path):
        self.workspace, self.todo = workspace, safe_io.lexical_path(todo)
        if not self.todo.is_relative_to(workspace) or self.todo.suffix.lower() != ".md":
            raise WorkbenchError("Task file must be a Markdown file inside the workspace")
        relative = self.todo.relative_to(workspace).as_posix()
        child_path(workspace, relative)
        if any(part.startswith(".") for part in Path(relative).parts):
            raise WorkbenchError("Task file cannot be in a hidden/control directory")
        self.state_root = state_root
        self.state = state_directory(workspace, self.todo, state_root)
        self.private = self.state / "workbench"
        safe_io.mkdir(self.private)
        self.lock = threading.RLock()

    def raw(self) -> bytes | None:
        try:
            return read_bytes(self.todo)
        except FileNotFoundError:
            return None

    def view(self) -> dict:
        data = self.raw()
        text = "" if data is None else data.decode("utf-8")
        tasks = [{"id": m.group(1).strip(), "status": canonical_status(m.group(2)),
                  "title": m.group(3), "line": line + 1}
                 for line, m in task_headers(text)]
        adoption = False
        try:
            journal = strict_json(read_bytes(self.state / "plan.json", MAX_TEXT_BYTES * 2))
            if not isinstance(journal, dict) or not isinstance(journal.get("text"), str):
                raise WorkbenchError("Invalid controller journal; inspect it without resetting")
            adoption = journal["text"] != text
        except FileNotFoundError:
            pass
        return {"text": text, "revision": "absent" if data is None else digest(data),
                "exists": data is not None, "tasks": tasks, "needs_owner_adoption": adoption}

    def validate(self, text: str) -> list[dict]:
        if not isinstance(text, str) or "\x00" in text:
            raise WorkbenchError("Plan must be UTF-8 text without NUL")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise WorkbenchError("Plan is too large", status=413)
        # Private staging, never an active workspace file or model call.
        stage = safe_io.unique_directory(self.private / "validation", "draft") / "tasks.md"
        safe_io.write_text(stage, text, exclusive=True)
        try:
            issues = [asdict(item) for item in lint_todo_file(stage, workdir=self.workspace)]
            for line, value in visible_lines(text):
                if (re.match(r"^\S+\s+(?:\*{3})?(?:Task|Auftrag|DONE|OBSOLETE)(?:\*{3})?:", value.strip(), re.I)
                        and not TASK_PATTERN.match(value.strip())):
                    issues.append({"line": line + 1, "code": "invalid_id",
                                   "message": "Task IDs must be numeric, optionally dotted (for example 2.1)."})
            return issues
        finally:
            stage.unlink()
            stage.parent.rmdir()

    @staticmethod
    def _normalize(text: str, old: str) -> str:
        # Browser textarea normalizes CRLF. Preserve the source's existing convention and BOM.
        if old.startswith("\ufeff") and not text.startswith("\ufeff"):
            text = "\ufeff" + text
        if "\r\n" in old and "\n" not in old.replace("\r\n", ""):
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        return text

    def preview(self, text: str, revision: str) -> dict:
        current = self.view()
        if revision != current["revision"]:
            raise WorkbenchError("Plan changed since it was loaded; reload/compare before saving",
                                 code="conflict", status=409)
        text = self._normalize(text, current["text"])
        issues = self.validate(text)
        return {"text": text, "revision": revision, "issues": issues, "valid": not issues,
                "diff": "".join(difflib.unified_diff(current["text"].splitlines(True),
                       text.splitlines(True), fromfile="saved/tasks.md", tofile="draft/tasks.md")),
                "warning": "Saving is an owner edit, not a reviewed completion. Runtime adoption is separate."}

    def save(self, text: str, revision: str) -> dict:
        with self.lock, lease(self.state / "controller.lock"):
            preview = self.preview(text, revision)
            if preview["issues"]:
                raise WorkbenchError("Plan has validation errors; it was not saved", code="invalid_plan", status=422)
            if self.view()["revision"] != revision:
                raise WorkbenchError("Plan changed during validation", code="conflict", status=409)
            old = self.raw()
            data = preview["text"].encode("utf-8")
            if old != data:
                backup = safe_io.unique_directory(self.private / "edits", "edit")
                if old is not None:
                    safe_io.write_bytes(backup / "before.md", old, exclusive=True)
                safe_io.write_bytes(backup / "after.md", data, exclusive=True)
                # Detect ordinary external editors immediately before the atomic replace.
                actual = self.raw()
                if ("absent" if actual is None else digest(actual)) != revision:
                    raise WorkbenchError("Plan changed during save", code="conflict", status=409)
                safe_io.atomic_write(self.todo, data)
            return self.view()


def generated_plan(ideas: str, base: str = "") -> str:
    """Append open tasks, preserving all existing text/IDs. Never writes a file."""
    if not isinstance(ideas, str) or len(ideas.encode("utf-8")) > MAX_TEXT_BYTES:
        raise WorkbenchError("Invalid task input")
    items = [line.strip() for line in ideas.splitlines() if line.strip()]
    if not items or len(items) > 200:
        raise WorkbenchError("Enter between 1 and 200 tasks, one per line")
    roots = [int(m.group(1).strip().split(".")[0]) for _, m in task_headers(base)]
    first = max(roots, default=0) + 1
    separator = "\r\n" if "\r\n" in base else "\n"
    prefix = base + (separator * 2 if base and not base.endswith(separator) else separator if base else "")
    return prefix + separator.join(f"{n}. ***Task***: {item}"
                                  for n, item in enumerate(items, first)) + separator
