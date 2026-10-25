# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral in-process execution evidence; no environment or process I/O."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import math
from runtime_contracts import ExecutionResult

@dataclass(frozen=True, slots=True, kw_only=True)
class TransportTimeouts:
    post_turn_grace: float = 120.0
    stall: float = 7200.0
    kill_grace: float = 10.0
    total: float | None = None

    def __post_init__(self) -> None:
        for name in ("post_turn_grace", "stall", "kill_grace", "total"):
            value = getattr(self, name)
            if name == "total" and value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")

@dataclass
class CommandExec:
    command: str
    status: str
    exit_code: Optional[int] = None
    aggregated_output: str = ""

@dataclass
class FileChange:
    # Struktur je nach CLI-Version; wir halten es generisch:
    raw: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RunResult:
    assistant_messages: List[str] = field(default_factory=list)
    commands: List[CommandExec] = field(default_factory=list)
    file_changes: List[FileChange] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    turn_failed: Optional[Dict[str, Any]] = None
    process_stop_triggered: bool = False
    process_stop_details: Optional[str] = None
    # Additions stay after the existing positional fields for older callers.
    turn_completed: bool = False
    process_exit_code: Optional[int] = None
    stream_errors: List[Dict[str, Any]] = field(default_factory=list)
    execution_error: Optional[Dict[str, Any]] = None
    post_turn_cleanup: bool = False
    capture_dir: Optional[Path] = None
    capture: Dict[str, Any] = field(default_factory=dict)
    cleanup_reason: Optional[str] = None
    stream_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    _stdout_event_count: int = field(default=0, repr=False)

    @property
    def end_answer(self) -> str:
        return self.assistant_messages[-1].strip() if self.assistant_messages else ""

@dataclass(frozen=True, slots=True)
class TransportResult:
    """Validated status plus the retained command/file/usage trace for old callers."""

    execution: ExecutionResult
    trace: RunResult
