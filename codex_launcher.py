# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Resolve Codex without a shell, using only the call's cwd and environment.

Windows supports native EXEs and the standard npm codex.cmd shim (global or
node_modules/.bin). The latter is translated to node.exe + bin/codex.js; the
batch file is checked but never executed. Arbitrary wrappers are not supported.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import ntpath
import os
from pathlib import Path
from typing import Mapping


class CodexLauncherError(OSError):
    """A launcher is absent, ambiguous or not supported without a shell."""


@dataclass(frozen=True, slots=True)
class CodexLauncher:
    requested: str
    source: str
    kind: str
    argv: tuple[str, ...]

    def metadata(self) -> dict:
        return {"requested": self.requested, "source": self.source,
                "kind": self.kind, "argv_prefix": list(self.argv)}


def _windows_path(value: str) -> None:
    drive, tail = ntpath.splitdrive(value)
    if drive.startswith(("\\\\", "//")):
        raise CodexLauncherError("UNC-/Gerätepfade als Codex-Launcher/PATH sind noch nicht unterstützt; lokalen Laufwerkspfad verwenden.")
    if (drive and not tail.startswith(("/", "\\"))) or (not drive and (
            value.startswith("\\") or (os.name == "nt" and value.startswith("/")))):
        raise CodexLauncherError(f"Mehrdeutiger Windows-Pfad {value!r}; absoluten Laufwerkspfad oder relativen Pfad mit Verzeichnis verwenden.")


def _search_dirs(cwd: Path, env: Mapping[str, str], windows: bool) -> list[Path]:
    values = [v for k, v in env.items() if k.upper() == "PATH"] if windows else [env.get("PATH", "")]
    if len(set(values)) > 1:
        raise CodexLauncherError("Widersprüchliche PATH/Path-Werte in der Windows-Prozessumgebung.")
    path = values[0] if values else ""
    dirs = []
    for entry in path.split(";" if windows else os.pathsep):
        # Windows never implicitly searches the workspace, even for empty PATH
        # entries. An explicit '.' entry still deliberately selects that cwd.
        if windows and not entry:
            continue
        entry = entry.removeprefix('"').removesuffix('"') if windows else entry
        if windows:
            _windows_path(entry)
        dirs.append((cwd / entry).absolute())
    return dirs if path else []


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


def _npm_launcher(selected: Path, requested: str, dirs: list[Path]) -> CodexLauncher:
    if selected.name.lower() != "codex.cmd":
        raise CodexLauncherError(f"Nicht unterstützter Windows-Wrapper {selected}; native codex.exe oder Standard-npm-codex.cmd verwenden.")
    local = selected.parent.name.lower() == ".bin" and selected.parent.parent.name.lower() == "node_modules"
    package = (selected.parent.parent if local else selected.parent / "node_modules") / "@openai" / "codex"
    target = ("..\\" if local else "node_modules\\") + "@openai\\codex\\bin\\codex.js"
    try:
        shim = selected.read_text(encoding="utf-8-sig")
        if shim != _npm_shim(target):
            raise CodexLauncherError(f"Nicht unterstützter Inhalt in {selected}; nur der Standard-npm-Node-Wrapper ohne Zusatzbefehle ist freigegeben.")
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict) or metadata.get("name") != "@openai/codex"
                or metadata.get("bin") != {"codex": "bin/codex.js"}):
            raise CodexLauncherError(f"Unbekanntes npm-Paketlayout unter {package}; erwartet @openai/codex mit bin/codex.js.")
        script = package / "bin" / "codex.js"
        if not script.is_file():
            raise CodexLauncherError(f"npm-Codex-Einstieg fehlt: {script}. Installation prüfen.")
    except (OSError, ValueError) as exc:
        if isinstance(exc, CodexLauncherError):
            raise
        raise CodexLauncherError(f"npm-Codex-Launcher {selected} kann nicht geprüft werden: {exc}") from exc
    node = next((p / "node.exe" for p in [selected.parent, *dirs] if (p / "node.exe").is_file()), None)
    if node is None:
        raise CodexLauncherError(f"Für {selected} fehlt node.exe neben dem Wrapper oder im übergebenen PATH; native codex.exe oder Node-Installation verwenden.")
    return CodexLauncher(requested, str(selected), "windows-npm-node", (str(node), str(script)))


def resolve_launcher(requested: str, *, cwd: Path, env: Mapping[str, str],
                     platform_name: str | None = None) -> CodexLauncher:
    """No process, global env access or cached resolution. platform_name is for
    filesystem contract tests; only real Windows runs verify CreateProcess.
    """
    windows = (platform_name or os.name) == "nt"
    if not requested or "\0" in requested or requested.startswith(("-", '"', "'")):
        raise CodexLauncherError("Codex-Launcher muss ein unquotierter Dateipfad ohne Kommandoargumente sein.")
    if windows:
        _windows_path(requested)
    explicit = "/" in requested or "\\" in requested or (windows and bool(ntpath.splitdrive(requested)[0]))
    dirs = [] if explicit else _search_dirs(cwd, env, windows)
    if explicit:
        candidates = [(cwd / requested).absolute()]
        if windows and not candidates[0].suffix:
            candidates = [candidates[0].with_suffix(s) for s in (".exe", ".cmd", ".bat", ".ps1")]
    else:
        suffixes = (".exe", ".cmd", ".bat", ".ps1") if windows and not Path(requested).suffix else ("",)
        # Prefer native EXE across the supplied PATH, regardless of PATHEXT.
        candidates = [directory / (requested + suffix) for suffix in suffixes for directory in dirs]
    selected = next((p for p in candidates if _usable(p, windows)), None)
    if selected is None:
        raise CodexLauncherError(f"Codex-Launcher {requested!r} nicht gefunden oder nicht ausführbar; Installation und übergebenen PATH prüfen (cwd: {cwd}).")
    if windows and selected.suffix.lower() != ".exe":
        if explicit:
            dirs = _search_dirs(cwd, env, windows)
        return _npm_launcher(selected, requested, dirs)
    return CodexLauncher(requested, str(selected), "windows-native" if windows else "posix-executable", (str(selected),))
