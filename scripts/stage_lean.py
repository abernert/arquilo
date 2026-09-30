# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Export the explicit allowlist to a new directory or a reproducible ZIP (stdlib only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from runtime_files import validate_component, validate_path
from legacy_naming import schema_matches

MANIFEST = "documents/lean_package.json"
SELECTION_REMOVED = (
    "Optionale Paketauswahl (--with-optional / Python optional; "
    "ace, iact, openclaw, services, legacy-tools) wurde entfernt (ToDo 1028/1035). "
    "Auswahlargument vollständig entfernen, auch bei leeren Werten. "
    "Es gibt nur den Lean-Kern und keine Nachinstallation von Zusatzgruppen."
)


def _reject_selection(positional: tuple, keywords: dict) -> None:
    # Diagnostic only: do not inspect values, resolve paths or load a manifest.
    if positional or "optional" in keywords:
        raise ValueError(SELECTION_REMOVED)
    if keywords:
        raise TypeError("Unbekannte Paketargumente: " + ", ".join(sorted(keywords)))


def _check_source_file(source: Path, name: str) -> None:
    file = source / name
    if file.is_symlink() or any(parent.is_symlink() for parent in file.parents if parent != source.parent):
        raise ValueError(f"Symlinks sind keine Paketdateien: {name}")
    if not file.resolve().is_relative_to(source) or not file.is_file():
        raise ValueError(f"Paketdatei fehlt oder liegt außerhalb der Quelle: {name}")


def package_files(source: Path, *removed_selection: object, **removed_options: object) -> list[str]:
    _reject_selection(removed_selection, removed_options)
    if sys.version_info < (3, 11):
        raise ValueError("ARQUILO benötigt Python >=3.11.")
    validate_path(source, label="Paketquelle")
    source = source.resolve()
    _check_source_file(source, MANIFEST)
    manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not schema_matches(manifest.get("schema_version"), "arquilo.lean.package.v1"):
        raise ValueError("Unbekannte Paket-Positivliste.")
    if "optional_groups" in manifest:
        raise ValueError(SELECTION_REMOVED + " Veraltete Positivliste aktualisieren.")
    names = manifest["runtime_files"]
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names):
        raise ValueError("Die Paket-Positivliste muss explizite Dateinamen enthalten.")
    if type(manifest.get("runtime_file_count")) is not int or manifest["runtime_file_count"] != len(names):
        raise ValueError("Dateizahl der Paket-Positivliste stimmt nicht.")
    # ZIPs must also unpack unambiguously on case-insensitive Windows/macOS.
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("Doppelte Dateien in der Paket-Positivliste (auch Groß-/Kleinschreibung).")
    for name in names:
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or ":" in name or path.as_posix() != name or any(c in name for c in "*?[]")):
            raise ValueError(f"Ungültiger expliziter Paketpfad: {name!r}")
        for component in path.parts:
            validate_component(component)
        _check_source_file(source, name)
    return sorted(names)


def stage_package(destination: Path, *, source: Path = ROOT,
                  **removed_options: object) -> dict:
    _reject_selection((), removed_options)
    names = package_files(source)
    validate_path(destination, label="Paketziel")
    source, destination = source.resolve(), destination.absolute()
    if destination.is_symlink():
        raise FileExistsError(f"Paketziel ist bereits ein Symlink: {destination}")
    # Never overwrite an installation or merge with an earlier, larger package.
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    actual = sorted(p.relative_to(destination).as_posix()
                    for p in destination.rglob("*") if p.is_file())
    if actual != names:
        raise ValueError("Paketinhalt stimmt nicht mit der Positivliste überein.")
    return {"schema_version": "arquilo.lean.staging.v1", "source": str(source),
            "destination": str(destination), "file_count": len(names), "files": names, "status": "PASS"}


def zip_package(destination: Path, *, source: Path = ROOT,
                **removed_options: object) -> dict:
    _reject_selection((), removed_options)
    names = package_files(source)
    validate_path(destination, label="Paketziel")
    source, destination = source.resolve(), destination.absolute()
    if destination.is_symlink():
        raise FileExistsError(f"Paketziel ist bereits ein Symlink: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also refuses existing files and symlinks. Never
    # replace a running installation or an earlier distribution artifact.
    with destination.open("xb") as output:
        try:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in names:
                    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, (source / name).read_bytes())
        except BaseException:
            output.close()
            destination.unlink()
            raise
    return {"schema_version": "arquilo.lean.distribution.v1", "format": "zip",
            "source": str(source), "destination": str(destination),
            "file_count": len(names), "files": names, "status": "PASS"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--zip", action="store_true", help="ZIP statt Verzeichnis erzeugen; kein Buildtool erforderlich.")
    argv = list(sys.argv[1:] if argv is None else argv)
    for arg in argv:
        if arg == "--":
            break
        if arg.partition("=")[0] == "--with-optional":
            parser.error(SELECTION_REMOVED)
    args = parser.parse_args(argv)
    try:
        exporter = zip_package if args.zip else stage_package
        result = exporter(args.destination)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"Paket konnte nicht bereitgestellt werden: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
