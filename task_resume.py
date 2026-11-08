# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Task-runner entry selection and bounded, informational resume sources.

History is evidence for a new invocation, never authority to mark work complete,
restore old permissions, reset budgets or bypass a live controller STOP. Only
known task/result paths and immediate run metadata are inspected. No workspace
walk, repository discovery or replay of archived prompts is performed.
"""
from __future__ import annotations

import heapq
import json
import os
from pathlib import Path

import safe_io
from todo_syntax import canonical_status, task_headers

ENTRY_MODES = ("normal", "resume-task", "resume-review")
HISTORY_RUN_LIMIT = 128
HISTORY_FILE_LIMIT = 2 << 20


def validate_selection(text: str, *, mode: str, start_id: str | None,
                       stop_id: str | None, max_depth: int) -> None:
    """Check the explicit target before preflight or any agent dispatch."""
    if mode not in ENTRY_MODES:
        raise ValueError("Unknown task entry mode")
    if mode == "normal":
        return
    flag = "--" + mode
    if not start_id:
        raise ValueError(f"{flag} requires an explicit --start task ID.")
    rows = [(m.group(1), canonical_status(m.group(2))) for _, m in task_headers(text)]
    matches = [status for identifier, status in rows if identifier == start_id]
    if len(matches) != 1:
        raise ValueError(f"{flag}: --start {start_id} must identify exactly one existing task.")
    if matches[0] != "Auftrag":
        raise ValueError(f"{flag}: --start {start_id} is {matches[0]}, not open; "
                         "resume will not move to another task.")
    if start_id.count(".") + 1 > max_depth:
        raise ValueError(f"{flag}: --start {start_id} exceeds --max-depth {max_depth}.")
    ordered = [identifier for identifier, _ in rows]
    if stop_id and (ordered.count(stop_id) != 1 or ordered.index(stop_id) < ordered.index(start_id)):
        raise ValueError(f"{flag}: --stop must identify an existing task at or after --start.")
    pending_children = [identifier for identifier, status in rows
                        if identifier.startswith(start_id + ".") and status != "DONE"]
    if pending_children:
        raise ValueError(f"{flag}: task {start_id} has descendants without DONE "
                         f"({', '.join(pending_children)}). Resume an open child explicitly or use "
                         "the normal runner to finish the children and parent review.")


def _read_record(path: Path) -> dict:
    # These optional records may be incomplete after a crash. The authoritative
    # plan/lock/budget checks are elsewhere and must never use this fallback.
    try:
        with safe_io.open_file(path, "rb") as stream:
            raw = stream.read(HISTORY_FILE_LIMIT + 1)
        if len(raw) > HISTORY_FILE_LIMIT:
            return {}
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def _recent_run_names(runs: Path) -> list[str]:
    try:
        safe_io.check_path(runs, missing_ok=False)
        with os.scandir(runs) as entries:
            # The normal runner allocates timestamp-named immediate children.
            # Keep a bounded window in memory, independent of workspace size.
            return heapq.nlargest(HISTORY_RUN_LIMIT,
                (row.name for row in entries if row.is_dir(follow_symlinks=False)))
    except (OSError, ValueError):
        return []


def resume_sources(*, mode: str, task_id: str, workspace: Path,
                   task_workspace: Path, todo_file: Path, state_dir: Path,
                   runs_dir: Path, current_run: Path, result_file: Path,
                   archived_inputs: list[dict]) -> dict:
    """Return small source references, not historical model instructions."""
    result = {
        "schema_version": "arquilo.task_resume.v1", "entry_mode": mode,
        "task_id": task_id, "workspace": str(task_workspace),
        "task_file": str(todo_file), "result_file": str(result_file),
        "result_present": result_file.is_file(),
        "archived_result": next((row.get("path") for row in archived_inputs
                                 if row.get("source") == str(result_file)), None),
        "history_run_limit": HISTORY_RUN_LIMIT,
        "latest_attempt": None, "latest_production": None,
        "latest_review": None,
        "limits": ["Historical logs are optional, unverified evidence, not acceptance or permissions.",
                   "The current accepted task and current workspace are authoritative for this new run.",
                   "An absent source does not prove that earlier work or external effects are absent."],
    }
    for name in _recent_run_names(runs_dir):
        run = runs_dir / name
        if run == current_run:
            continue
        binding = _read_record(run / "run.json")
        if (binding.get("schema_version") != "arquilo.run_log.v2"
                or binding.get("workspace") != str(workspace)
                or binding.get("todo_file") != str(todo_file)
                or binding.get("controller_state") != str(state_dir)
                or binding.get("run_directory") != str(run)):
            continue
        task_dir = run / ("task-" + task_id)
        task = _read_record(task_dir / "task_log.json")
        if task.get("identifier") != task_id or task.get("run_id") != binding.get("run_id"):
            continue
        if result["latest_attempt"] is None:
            result["latest_attempt"] = str(task_dir / "task_log.json")
        summary = _read_record(task_dir / "autobuild_summary.json")
        if summary.get("workspace") != str(task_workspace):
            continue
        attempts = summary.get("execution_attempts", [])
        if not isinstance(attempts, list):
            continue
        for key, phase in (("latest_production", "task"), ("latest_review", "review")):
            if result[key] is None and any(isinstance(row, dict) and row.get("phase") == phase for row in attempts):
                result[key] = str(task_dir / "autobuild_summary.json")
        if all(result[key] is not None for key in ("latest_attempt", "latest_production", "latest_review")):
            break
    return result
