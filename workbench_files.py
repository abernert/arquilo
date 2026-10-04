# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Bounded, no-follow I/O and locks shared by the local interaction services."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Iterator

import safe_io
from controller_state import default_state_root

MAX_TEXT_BYTES = 1024 * 1024


class WorkbenchError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: Path, limit: int = MAX_TEXT_BYTES) -> bytes:
    with safe_io.open_file(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if len(data) > limit:
        raise WorkbenchError("File exceeds the size limit", code="too_large", status=413)
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise WorkbenchError("File changed while reading; retry", code="conflict", status=409)
    return data


def strict_json(data: str | bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def constant(_value):
        raise ValueError("Non-finite JSON number")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def write_json(path: Path, value: object) -> None:
    safe_io.atomic_write(path, (json.dumps(value, ensure_ascii=False, allow_nan=False,
                                         indent=2) + "\n").encode("utf-8"))


def private_root(workspace: Path, selected: str | Path | None, name: str) -> Path:
    root = safe_io.lexical_path(Path(selected).expanduser() if selected is not None
                                else default_state_root().parent / name)
    if root.is_relative_to(workspace) or workspace.is_relative_to(root):
        raise WorkbenchError("Private state/archive must be outside and not above the workspace")
    safe_io.mkdir(root)
    info = root.stat()
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise WorkbenchError("Private directory must be user-owned with mode 0700")
    return root


def workspace_path(value: str | Path) -> Path:
    # The root is explicitly owner-selected. Descendants are never resolved through links.
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise WorkbenchError("Workdir must be an existing directory")
    return root


def child_path(root: Path, value: str) -> Path:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or "\x00" in value or Path(value).is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise WorkbenchError("Expected a project-relative path without traversal")
    path = safe_io.lexical_path(root / value)
    if not path.is_relative_to(root):
        raise WorkbenchError("Path is outside the workspace")
    return safe_io.check_path(path)


@contextmanager
def lease(path: Path) -> Iterator[None]:
    """Nonblocking OS lock; matches PlanAuthority's controller.lock protocol."""
    with safe_io.open_file(path, "a+b", shared=True) as handle:
        locked = False
        try:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                raise WorkbenchError("Another controller/service owns this plan", code="busy", status=409) from exc
            yield
        finally:
            if locked:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
