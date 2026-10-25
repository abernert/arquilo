# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Inspect or retry accepted Git publications without starting an agent."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from controller_state import PlanAuthority, PlanIntegrityError, state_directory, state_directory_path
from runtime_files import native_path
from reviewed_git import ReviewedGitError, list_publications, recover_publication
from runtime_contracts import ExitCode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arquilo git", allow_abbrev=False,
        description="Inspect and retry private reviewed publications; no model or task execution.",
    )
    parser.add_argument("command", choices=("status", "retry"))
    parser.add_argument("--workdir", type=Path, required=True,
                        help="Original Git working-tree root; use the same path as the task run.")
    parser.add_argument("--todo-file", type=Path, required=True,
                        help="Original task-list path identifying the existing controller state.")
    parser.add_argument("--state-dir", type=Path,
                        help="Original private state base, if the task run used --state-dir.")
    parser.add_argument("--publication",
                        help="Exact publication ID returned by status; required for retry.")
    return parser


def _task_path(workspace: Path, source: Path) -> Path:
    # Match the task runner's existing materialization mapping without copying,
    # adopting, or changing the owner's source or working task list.
    repo = Path(__file__).resolve().parent
    if workspace == repo or source.is_relative_to(workspace):
        return source
    try:
        relative_parent = source.relative_to(repo).parent
    except ValueError:
        relative_parent = Path("documents") / "todos"
    return workspace / relative_parent / source.name


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "retry" and not args.publication:
        parser.error("retry requires --publication from 'arquilo git status'")
    if args.command == "status" and args.publication:
        parser.error("--publication is used only with retry")
    authority = None
    try:
        workspace = native_path(args.workdir, label="workdir")
        source = native_path(args.todo_file, label="todo_file")
        todo = _task_path(workspace, source)
        state = state_directory_path(workspace, todo, args.state_dir)
        if args.command == "status":
            result = {"schema_version": "arquilo.git_publication_status.v1",
                      "workspace": str(workspace),
                      "publications": list_publications(state, workspace)}
        else:
            if not (state / "identity.json").is_file():
                raise ReviewedGitError("No existing controller identity for this workspace/task list.")
            state = state_directory(workspace, todo, args.state_dir)
            if os.path.lexists(workspace / "process_stop"):
                print(json.dumps({"status": "stopped", "code": "process_stop",
                                  "message": "Inspect and explicitly clear process_stop before publication retry."}))
                return int(ExitCode.PROCESS_STOP)
            # Serialize with ordinary controllers and retain their original
            # plan identity. No adoption, task selection or budget creation.
            authority = PlanAuthority(todo, state, workspace=workspace)
            if os.path.lexists(workspace / "process_stop"):
                return int(ExitCode.PROCESS_STOP)
            result = recover_publication(workspace, state, args.publication)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ReviewedGitError, PlanIntegrityError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "code": "git_publication_refused",
                          "message": str(exc)[:4096]}, ensure_ascii=False), file=sys.stderr)
        return int(ExitCode.INCOMPLETE)
    finally:
        if authority is not None:
            authority.close()


if __name__ == "__main__":
    raise SystemExit(main())
