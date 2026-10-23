# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Select host programs without granting the workspace executable authority.

Only absolute paths outside the workspace participate. Host installations and
the caller's environment remain trusted; this is not an OS sandbox or a defence
against another host process replacing a trusted installation concurrently.
"""
from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import Mapping


class HostLauncherError(OSError):
    """No unambiguous host executable is available outside the workspace."""


def windows_absolute(value: str) -> bool:
    """Require a fully qualified local drive, never C:foo, \\foo or a UNC/device path."""
    drive, tail = ntpath.splitdrive(value)
    return (len(drive) == 2 and drive[0].isalpha() and drive[1] == ":"
            and tail.startswith(("/", "\\")))


def _absolute(value: str, windows: bool) -> bool:
    if windows:
        if windows_absolute(value):
            return True
        # The platform override permits fixture files on POSIX. Real Windows
        # still requires the drive qualification checked above.
        return os.name != "nt" and value.startswith("/") and not value.startswith("//")
    return Path(value).is_absolute()


def _inside(path: Path, root: Path) -> bool:
    if path.is_relative_to(root):
        return True
    # Resolve handles symlink/junction aliases. samefile also handles physical
    # case/Unicode aliases on filesystems whose spelling is not canonicalized.
    for parent in (path, *path.parents):
        try:
            if parent.samefile(root):
                return True
        except FileNotFoundError:
            continue
    return False


def trusted_path(value: str | Path, *, workspace: Path, windows: bool = False) -> Path:
    """Validate both the selector and physical target, returning an absolute target."""
    raw = os.fspath(value)
    if not raw or "\0" in raw or not _absolute(raw, windows):
        raise HostLauncherError(f"Host launcher/PATH must use an absolute local path: {raw!r}")
    path = Path(raw).absolute()
    root = Path(workspace).absolute()
    try:
        resolved, physical_root = path.resolve(), root.resolve()
        if _inside(path, root) or _inside(resolved, physical_root):
            raise HostLauncherError(f"Host launcher/PATH must stay outside the workspace: {path}")
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, HostLauncherError):
            raise
        raise HostLauncherError(f"Cannot verify host path {path}: {exc}") from exc
    return resolved


def _path_values(env: Mapping[str, str], windows: bool) -> list[tuple[str, str]]:
    if windows:
        values = [(key, value) for key, value in env.items() if key.upper() == "PATH"]
    else:
        values = [("PATH", env["PATH"])] if "PATH" in env else []
    if len({value for _, value in values}) > 1:
        raise HostLauncherError("Conflicting PATH/Path values in the Windows process environment.")
    return values


def search_directories(*, workspace: Path, env: Mapping[str, str], windows: bool) -> list[Path]:
    values = _path_values(env, windows)
    dirs = []
    for entry in (values[0][1] if values else "").split(";" if windows else os.pathsep):
        entry = entry.removeprefix('"').removesuffix('"') if windows else entry
        if not entry or not _absolute(entry, windows):
            continue
        try:
            path = trusted_path(entry, workspace=workspace, windows=windows)
        except HostLauncherError:
            continue
        if path not in dirs:
            dirs.append(path)
    return dirs


def launcher_environment(env: Mapping[str, str], *, workspace: Path,
                         executable: str | Path, platform_name: str | None = None) -> dict[str, str]:
    """Keep host provisioning, but remove workspace/relative interpreter lookup.

    In particular, a trusted POSIX npm entry point's /usr/bin/env node must not
    find project/node. An absent PATH remains absent; an explicitly unsafe-only
    PATH is replaced with the selected host executable's directory, never ''.
    """
    windows = (platform_name or os.name) == "nt"
    result = dict(env)
    values = _path_values(env, windows)
    if values:
        dirs = search_directories(workspace=workspace, env=env, windows=windows)
        if not dirs:
            dirs = [trusted_path(executable, workspace=workspace, windows=windows).parent]
        for key, _ in values:
            del result[key]
        result[values[0][0]] = (";" if windows else os.pathsep).join(map(str, dirs))
    return result


def resolve_executable(requested: str, *, workspace: Path, env: Mapping[str, str],
                       platform_name: str | None = None) -> Path:
    """Resolve a native host program once; Windows Git uses git.exe, never a shell."""
    windows = (platform_name or os.name) == "nt"
    if not requested or "\0" in requested or requested.startswith(("-", '"', "'")):
        raise HostLauncherError("Host launcher must be an unquoted executable path without arguments.")
    explicit = "/" in requested or "\\" in requested or (windows and bool(ntpath.splitdrive(requested)[0]))
    if explicit:
        base = trusted_path(requested, workspace=workspace, windows=windows)
        candidates = [base.with_suffix(".exe") if windows and not base.suffix else base]
    else:
        name = requested + ".exe" if windows and not Path(requested).suffix else requested
        candidates = [path / name for path in search_directories(workspace=workspace, env=env, windows=windows)]
    for candidate in candidates:
        try:
            path = trusted_path(candidate, workspace=workspace, windows=windows)
        except HostLauncherError:
            continue
        if (path.is_file() and (windows or os.access(path, os.X_OK))
                and (not windows or path.suffix.lower() == ".exe")):
            return path
    raise HostLauncherError(f"Host launcher {requested!r} unavailable outside the workspace; use an absolute trusted installation in PATH.")
