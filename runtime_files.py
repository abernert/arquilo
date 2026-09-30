# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Native paths, portable generated names and closed, atomic UTF-8 snapshots.

No shell, global cwd/environment changes, fixed temp root or third-party code.
Streaming logs deliberately remain append-only; complete snapshots use replace.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile


class PathValidationError(ValueError):
    """A path uses an unsupported filesystem spelling or namespace."""


class AtomicWriteError(OSError):
    """A failed snapshot write; destination is never truncated as a fallback."""


_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    prefix + number for prefix in ("COM", "LPT") for number in "123456789¹²³"
}
_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_component(name: str) -> str:
    """Validate one ordinary Windows filename, even on a POSIX test host."""
    if (not name or name in {".", ".."} or _INVALID_COMPONENT.search(name)
            or name.endswith((".", " "))
            or name.split(".", 1)[0].rstrip(" ").upper() in _DEVICES):
        raise PathValidationError(f"Unsupported filename {name!r}: reserved device, character or trailing dot/space")
    return name


def safe_component(value: str, *, fallback: str = "item", limit: int = 96) -> str:
    """Keep existing ASCII identifiers; bound and repair generated filenames."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", value.strip())[:limit].strip(". ")
    name = name or validate_component(fallback)
    if name.split(".", 1)[0].upper() in _DEVICES:
        name = "_" + name
    return validate_component(name)


def validate_path(value: str | os.PathLike[str], *, windows: bool | None = None,
                  label: str = "path") -> None:
    """Reject special/ambiguous paths before pathlib can normalize them away."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise PathValidationError(f"{label}: expected a non-empty filesystem path without NUL")
    windows = os.name == "nt" if windows is None else windows
    win = PureWindowsPath(raw)
    if raw.startswith(("\\\\", "//", "\\??\\")) or win.drive.startswith("\\"):
        raise PathValidationError(f"{label}: UNC/device/extended paths are not supported: {raw!r}; use a local ordinary path")
    if win.drive and not win.root:
        raise PathValidationError(f"{label}: drive-relative paths are not supported: {raw!r}")
    if windows:
        if win.root and not win.drive:
            raise PathValidationError(f"{label}: a rooted Windows path needs a drive letter: {raw!r}")
        for part in win.parts[1:] if win.anchor else win.parts:
            if part not in {".", ".."}:
                try:
                    validate_component(part)
                except PathValidationError as exc:
                    raise PathValidationError(f"{label}: {exc}") from exc
    elif win.drive or "\\" in raw:
        raise PathValidationError(f"{label}: Windows path spelling is not supported on this host: {raw!r}; use a native path")


def native_path(value: str | os.PathLike[str], *, base: Path | None = None,
                label: str = "path") -> Path:
    """Resolve with the host's pathlib, never with POSIX string normalization."""
    validate_path(value, label=label)
    path = Path(value).expanduser()
    if base is not None and not path.is_absolute():
        validate_path(base, label=f"{label} base")
        path = base / path
    validate_path(path, label=label)
    path = path.resolve()
    validate_path(path, label=label)
    return path


def read_utf8(path: Path, *, preserve_newlines: bool = False,
              preserve_bom: bool = False) -> str:
    """Text inputs accept one BOM at byte zero; misplaced BOMs fail explicitly."""
    with path.open("r", encoding="utf-8", newline="" if preserve_newlines else None) as handle:
        text = handle.read()
    body = text.removeprefix("\ufeff")
    if "\ufeff" in body:
        raise UnicodeError(f"{path}: UTF-8 BOM is only permitted once at the start of the file")
    return text if preserve_bom else body


def io_error_message(operation: str, path: Path, exc: OSError) -> str:
    detail = f"{operation} {path}: {exc}"
    if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32, 33}:
        detail += "; close applications holding the file open and check file/directory permissions"
    if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == 206:
        detail += "; path exceeds this filesystem/Windows configuration: use a shorter local root or enable long-path support"
    return detail


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a complete snapshot in the same directory, after closing it.

    Failed replacement keeps the complete UTF-8 candidate at the named recovery
    path. Failed staging removes the partial file. No truncate/copy fallback,
    implicit retry, lock stealing or claim of multi-writer transaction isolation.
    """
    path = native_path(path, label="output file")
    data = text.encode("utf-8")  # Validate before creating anything.
    temporary = None
    staged = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                         prefix=".dora-write-", suffix=".pending", delete=False) as handle:
            temporary = Path(handle.name)
            if handle.write(data) != len(data):
                raise OSError("Incomplete UTF-8 staging write")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        staged = True
        os.replace(temporary, path)
    except OSError as exc:
        detail = io_error_message("Cannot atomically write", path, exc)
        if temporary is not None:
            if staged:
                detail += f"; original destination retained; complete recovery file: {temporary}"
            else:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    detail += f"; partial staging file {temporary} could not be removed: {cleanup_error}"
        error = AtomicWriteError(detail)
        error.destination = path
        error.recovery_path = temporary if staged else None
        raise error from exc
    except BaseException:
        if temporary is not None and not staged:
            temporary.unlink(missing_ok=True)
        raise


def unique_directory(parent: Path, *, prefix: str) -> Path:
    """Atomically reserve a new directory; safe under concurrent allocations."""
    parent = native_path(parent, label="directory root")
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=safe_component(prefix) + "-", dir=parent))
    except OSError as exc:
        raise OSError(io_error_message("Cannot allocate directory under", parent, exc)) from exc
