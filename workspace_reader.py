# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Read-only text broker. Model-selected paths are data, never shell commands."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import safe_io

from workbench_files import WorkbenchError, child_path, digest, read_bytes

TEXT_SUFFIXES = {".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
                 ".json", ".toml", ".yaml", ".yml", ".csv", ".html", ".css",
                 ".java", ".c", ".h", ".cpp", ".rs", ".go", ".sql"}
SKIP_DIRS = {"node_modules", "venv", "__pycache__", "dist", "build", "vendor"}
SECRET = re.compile(r"(?:^|[._-])(?:auth|credentials?|secrets?|tokens?|passwords?)(?:[._-]|$)", re.I)


def allowed_path(relative: str) -> bool:
    parts = relative.split("/")
    return (all(p and not p.startswith(".") and p not in SKIP_DIRS for p in parts)
            and not SECRET.search(parts[-1])
            and (Path(parts[-1]).suffix.lower() in TEXT_SUFFIXES
                 or parts[-1] in {"LICENSE", "NOTICE", "VERSION", "Makefile"}))


class WorkspaceReader:
    def __init__(self, root: Path, *, file_limit: int = 512 * 1024,
                 total_limit: int = 160 * 1024, inventory_limit: int = 1500):
        self.root, self.file_limit, self.total_limit = root, file_limit, total_limit
        self.files: dict[str, tuple[bytes, list[str]]] = {}
        self.sources: dict[str, dict] = {}
        self.used = 0
        self.truncated_inventory = False
        self.inventory: list[str] = []
        scanned = 0
        visited = 0
        # No shell, Git, project configuration, macros or project-code execution.
        for directory, dirs, names in os.walk(root, followlinks=False):
            visited += 1
            if visited > inventory_limit:
                self.truncated_inventory = True
                break
            rel_dir = Path(directory).relative_to(root)
            safe_dirs = []
            for d in sorted(dirs):
                if d.startswith(".") or d in SKIP_DIRS:
                    continue
                try:
                    safe_io.check_path(Path(directory) / d, missing_ok=False)
                    safe_dirs.append(d)
                except (OSError, ValueError):
                    continue
            dirs[:] = safe_dirs
            if len(rel_dir.parts) >= 10:
                dirs[:] = []
                self.truncated_inventory = True
            for name in sorted(names):
                scanned += 1
                if scanned > inventory_limit:
                    self.truncated_inventory = True
                    break
                relative = (rel_dir / name).as_posix()
                if not allowed_path(relative):
                    continue
                try:
                    path = child_path(root, relative)
                    info = path.lstat()
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= file_limit:
                        self.inventory.append(relative)
                except (OSError, ValueError):
                    continue
            if scanned > inventory_limit:
                break

    def read(self, relative: str, start: int = 1, end: int = 160) -> dict:
        if relative not in self.inventory or not allowed_path(relative):
            raise WorkbenchError("File is outside the approved text inventory", code="source_denied", status=403)
        if type(start) is not int or type(end) is not int or start < 1 or end < start or end - start >= 400:
            raise WorkbenchError("Invalid source range (maximum 400 lines)")
        path = child_path(self.root, relative)
        if relative not in self.files:
            data = read_bytes(path, self.file_limit)
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                raise WorkbenchError("Binary content is not accepted")
            self.files[relative] = data, text.splitlines()
        data, lines = self.files[relative]
        if start > len(lines):
            raise WorkbenchError("Requested range is outside the file")
        last = min(end, len(lines))
        excerpt = "\n".join(lines[start - 1:last])
        ident = "S" + digest((relative + "\0" + digest(data) + f":{start}:{last}").encode())[:16]
        if ident not in self.sources:
            size = len(excerpt.encode("utf-8"))
            if self.used + size > self.total_limit:
                raise WorkbenchError("Question evidence budget reached", code="evidence_limit")
            self.used += size
            self.sources[ident] = {"id": ident, "path": relative, "sha256": digest(data),
                "start_line": start, "end_line": last, "total_lines": len(lines), "text": excerpt}
        return self.sources[ident]

    def initial(self, question: str, depth: str, selected: list[str] | None) -> list[dict]:
        if selected:
            if len(selected) > 12:
                raise WorkbenchError("Select at most 12 files")
            # Explicit selections fail closed instead of silently disappearing.
            return [self.read(path) for path in selected]
        words = set(re.findall(r"[\w-]{3,}", question.lower()))
        def score(path):
            base = Path(path).name.lower()
            return (sum(8 for word in words if word in path.lower())
                    + (6 if base in {"readme.md", "tasks.md"} else 0)
                    + (3 if base.startswith("todo_result") else 0)
                    - len(Path(path).parts))
        maximum = {"overview": 3, "normal": 5, "deep": 8}[depth]
        result = []
        for path in sorted(self.inventory, key=lambda p: (-score(p), p)):
            if len(result) >= maximum:
                break
            try:
                result.append(self.read(path))
            except (UnicodeError, OSError, WorkbenchError):
                continue
        return result

    def changed(self) -> list[str]:
        changed = []
        for relative, (data, _lines) in self.files.items():
            try:
                if digest(read_bytes(child_path(self.root, relative), self.file_limit)) != digest(data):
                    changed.append(relative)
            except (OSError, ValueError):
                changed.append(relative)
        return changed
