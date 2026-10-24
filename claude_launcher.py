# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Resolve host-installed ClaudeCode without a shell or workspace PATH authority.

Windows supports native EXEs and the standard npm claude.cmd shim (global or
node_modules/.bin). The latter is translated to node.exe + cli.js; the
batch file is checked but never executed. Arbitrary wrappers are not supported.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import ntpath
import os
from pathlib import Path
from typing import Mapping

from host_launcher import HostLauncherError, search_directories, trusted_path


class ClaudeCodeLauncherError(OSError):
    """A launcher is absent, ambiguous or not supported without a shell."""


@dataclass(frozen=True, slots=True)
class ClaudeCodeLauncher:
    requested: str
    source: str
    kind: str
    argv: tuple[str, ...]

    def metadata(self) -> dict:
        return {"requested": self.requested, "source": self.source,
                "kind": self.kind, "argv_prefix": list(self.argv)}


def _usable(path: Path, windows: bool) -> bool:
    return path.is_file() and (windows or os.access(path, os.X_OK))


def _npm_shim(target: str) -> str:
    # cmd-shim's standard node/no-extra-flags template. Do not interpret batch
    # syntax or accept injected commands/arguments. LF/CRLF and BOM are benign.
    return (
        '@ECHO off\nGOTO start\n:find_dp0\nSET dp0=%~dp0\nEXIT /b\n'
        ':start\nSETLOCAL\nCALL :find_dp0\n\n'
        'IF EXIST "%dp0%\\node.exe" (\n'
        '  SET "_prog=%dp0%\\node.exe"\n) ELSE (\n'
        '  SET "_prog=node"\n  SET PATHEXT=%PATHEXT:;.JS;=;%\n)\n\n'
        'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & '
        f'"%_prog%"  "%dp0%\\{target}" %*\n'
    )


def _npm_launcher(selected: Path, requested: str, dirs: list[Path], workspace: Path) -> ClaudeCodeLauncher:
    if selected.name.lower() != "claude.cmd":
        raise ClaudeCodeLauncherError(f"Nicht unterstützter Windows-Wrapper {selected}; native claude.exe oder Standard-npm-claude.cmd verwenden.")
    local = selected.parent.name.lower() == ".bin" and selected.parent.parent.name.lower() == "node_modules"
    package = (selected.parent.parent if local else selected.parent / "node_modules") / "@anthropic-ai" / "claude-code"
    target = ("..\\" if local else "node_modules\\") + "@anthropic-ai\\claude-code\\cli.js"
    try:
        shim = selected.read_text(encoding="utf-8-sig")
        if shim != _npm_shim(target):
            raise ClaudeCodeLauncherError(f"Nicht unterstützter Inhalt in {selected}; nur der Standard-npm-Node-Wrapper ohne Zusatzbefehle ist freigegeben.")
        metadata_path = trusted_path(package / "package.json", workspace=workspace, windows=True)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict) or metadata.get("name") != "@anthropic-ai/claude-code"
                or metadata.get("bin") != {"claude": "cli.js"}):
            raise ClaudeCodeLauncherError(f"Unbekanntes npm-Paketlayout unter {package}; erwartet @anthropic-ai/claude-code mit cli.js.")
        script = trusted_path(package / "cli.js", workspace=workspace, windows=True)
        if not script.is_file():
            raise ClaudeCodeLauncherError(f"npm-ClaudeCode-Einstieg fehlt: {script}. Installation prüfen.")
    except (OSError, ValueError) as exc:
        if isinstance(exc, ClaudeCodeLauncherError):
            raise
        raise ClaudeCodeLauncherError(f"npm-ClaudeCode-Launcher {selected} kann nicht geprüft werden: {exc}") from exc
    node = None
    for directory in [selected.parent, *dirs]:
        try:
            candidate = trusted_path(directory / "node.exe", workspace=workspace, windows=True)
        except HostLauncherError:
            continue
        if candidate.suffix.lower() == ".exe" and candidate.is_file():
            node = candidate
            break
    if node is None:
        raise ClaudeCodeLauncherError(f"Für {selected} fehlt node.exe neben dem Wrapper oder im übergebenen PATH; native claude.exe oder Node-Installation verwenden.")
    return ClaudeCodeLauncher(requested, str(selected), "windows-npm-node", (str(node), str(script)))


def resolve_launcher(requested: str, *, cwd: Path, env: Mapping[str, str],
                     platform_name: str | None = None,
                     workspace: Path | None = None,
                     additional_workspace: Path | None = None) -> ClaudeCodeLauncher:
    """No process, global env access or cached resolution. platform_name is for
    filesystem contract tests; only real Windows runs verify CreateProcess.
    """
    try:
        windows = (platform_name or os.name) == "nt"
        selected = _resolve_launcher(requested, workspace=workspace if workspace is not None else cwd,
                                     env=env, windows=windows)
        if additional_workspace is not None:
            # A task's cwd can differ from the controller's original writable
            # workspace. Preserve both selector and physical-target boundaries.
            if "/" in requested or "\\" in requested or (windows and ntpath.splitdrive(requested)[0]):
                trusted_path(requested, workspace=additional_workspace, windows=windows)
            for path in (selected.source, *selected.argv):
                trusted_path(path, workspace=additional_workspace, windows=windows)
        return selected
    except HostLauncherError as exc:
        raise ClaudeCodeLauncherError(str(exc)) from exc


def _resolve_launcher(requested: str, *, workspace: Path, env: Mapping[str, str],
                      windows: bool) -> ClaudeCodeLauncher:
    if not requested or "\0" in requested or requested.startswith(("-", '"', "'")):
        raise ClaudeCodeLauncherError("ClaudeCode-Launcher muss ein unquotierter Dateipfad ohne Kommandoargumente sein.")
    forbidden = {"codex", "codex.exe", "codex.cmd", "codex.bat", "codex.ps1"}
    if ntpath.basename(requested).lower() in forbidden:
        raise ClaudeCodeLauncherError("Codex cannot be selected as the Claude Code executable")
    explicit = "/" in requested or "\\" in requested or (windows and bool(ntpath.splitdrive(requested)[0]))
    dirs = [] if explicit else search_directories(workspace=workspace, env=env, windows=windows)
    if explicit:
        candidates = [trusted_path(requested, workspace=workspace, windows=windows)]
        if windows and not candidates[0].suffix:
            candidates = [candidates[0].with_suffix(s) for s in (".exe", ".cmd", ".bat", ".ps1")]
    else:
        suffixes = (".exe", ".cmd", ".bat", ".ps1") if windows and not Path(requested).suffix else ("",)
        # Prefer native EXE across the supplied PATH, regardless of PATHEXT.
        candidates = [directory / (requested + suffix) for suffix in suffixes for directory in dirs]
    selected = None
    for candidate in candidates:
        try:
            path = trusted_path(candidate, workspace=workspace, windows=windows)
        except HostLauncherError:
            continue
        if _usable(path, windows):
            selected = path
            break
    if selected is None:
        raise ClaudeCodeLauncherError(f"ClaudeCode-Launcher {requested!r} außerhalb des Workspace nicht gefunden oder nicht ausführbar; absolute Host-Installation und PATH prüfen (Workspace: {workspace}).")
    if selected.name.lower() in forbidden:
        raise ClaudeCodeLauncherError("Claude Code executable must not resolve to Codex")
    if windows and selected.suffix.lower() != ".exe":
        if explicit:
            dirs = search_directories(workspace=workspace, env=env, windows=windows)
        return _npm_launcher(selected, requested, dirs, workspace)
    return ClaudeCodeLauncher(requested, str(selected), "windows-native" if windows else "posix-executable", (str(selected),))
