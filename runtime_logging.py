# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Ordinary run/task logs, without signing, keys or content digests.

Copies are debugging records, not tamper proofs. Source data stays in the
shared workspace; missing/deleted files are recorded explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import shutil
import safe_io
from typing import Any, Iterable

from runtime_files import atomic_write_text, safe_component


@dataclass
class TaskLogRecord:
    identifier: str
    todo_id: str
    log_dir: Path
    workspace: Path
    input_sources: list[Path] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


class LogWriteError(RuntimeError):
    """A normal log or its retained I/O could not be persisted."""


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_log_json(path: Path, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    write_log_text(path, serialized)
    return serialized


def write_log_text(path: Path, text: str) -> None:
    try:
        atomic_write_text(path, text)
    except OSError as exc:
        raise LogWriteError(f"Protokoll {path} konnte nicht geschrieben werden: {exc}") from exc


def copy_log_files(log_dir: Path, stage: str, sources: Iterable[Path],
                   *, workspace: Path) -> list[dict[str, Any]]:
    """Copy selected I/O byte for byte; never walk or hash the whole workspace.

    External source files (e.g. a supplied ToDo) get collision-free numbered
    names. Paths below the log directory are referenced, never recursively
    copied. I/O failures propagate, so an incomplete archive cannot be PASS.
    """
    if stage not in {"inputs", "outputs", "final"}:
        raise ValueError("Unknown task log stage")
    records = []
    seen = set()
    base = workspace.resolve()
    log_root = safe_io.lexical_path(log_dir)
    for source in sources:
        source = safe_io.check_path(source)
        if source in seen:
            continue
        seen.add(source)
        row: dict[str, Any] = {"source": str(source)}
        if not source.exists():
            row["status"] = "missing"
        elif not source.is_file():
            row["status"] = "not_a_file"
        elif source.is_relative_to(log_root):
            row.update(status="retained", path=str(source))
        else:
            relative = (source.relative_to(base) if source.is_relative_to(base)
                        else Path("external") / str(len(records)) / safe_component(source.name))
            target = log_dir / stage / relative
            try:
                safe_io.write_bytes(target, safe_io.read_bytes(source))
            except OSError as exc:
                raise LogWriteError(f"I/O-Protokoll {source} -> {target} fehlgeschlagen: {exc}") from exc
            row.update(status="copied", path=str(target), bytes=target.stat().st_size)
        records.append(row)
    return records
