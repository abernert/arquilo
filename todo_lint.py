#!/usr/bin/env python3
# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Lint run_todos-compatible ToDo files and their CFG/WAIT/STOP directives.

This file validates ARQUILO Markdown task lists. It keeps the
existing linter contract and adds the CFG keys introduced by the minimal
breakdown implementation:

* breakdown
* breakdown_max_children
* breakdown_max_rounds

The validation ranges mirror run_todos.py:

* breakdown: minimal | legacy | off, plus the runtime aliases
  structured | none | disabled | false
* breakdown_max_children: integer from 1 through 12
* breakdown_max_rounds: integer from 1 through 8
"""

from __future__ import annotations

import argparse
from removed_features import reject_bridge_wait_conditions
from todo_syntax import TASK_PATTERN, SYNTAX_PATTERN, canonical_status, task_headers, visible_lines, directive_tokens
from runtime_files import PathValidationError, native_path, read_utf8
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

TODO_PATTERN = TASK_PATTERN
DIRECTIVE_PATTERN = re.compile(r"^\*\*\*(.+?)\*\*\*$")
STOP_SENTINEL = "***STOP***"

# Machine-readable capability marker for package/contract checks.
TODO_LINT_BREAKDOWN_CFG_CONTRACT_VERSION = 1

CFG_ALLOWED_KEYS = {
    "workspace",
    "agent",
    "model",
    "parallel",
    "web_search",
    "websearch",
    "network_access",
    "result_file",
    "completion_anchor",
    "breakdown",
    "breakdown_max_children",
    "breakdown_max_rounds",
}
WAIT_ALLOWED_KEYS = {"on", "mode", "timeout", "on_timeout"}
WAIT_CONDITION_TODO_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")

# These values intentionally mirror _normalize_breakdown_policy() in
# run_todos.py.  Aliases are accepted because the runtime accepts them too.
BREAKDOWN_POLICY_VALUES: Set[str] = {
    "minimal",
    "legacy",
    "off",
    "structured",  # runtime alias for minimal
    "none",        # runtime alias for off
    "disabled",    # runtime alias for off
    "false",       # runtime alias for off
}
BREAKDOWN_MAX_CHILDREN_MIN = 1
BREAKDOWN_MAX_CHILDREN_MAX = 12
BREAKDOWN_MAX_ROUNDS_MIN = 1
BREAKDOWN_MAX_ROUNDS_MAX = 8


@dataclass(frozen=True)
class LintIssue:
    line: int
    message: str
    code: str = "invalid_todo"

    def render(self, source: Path) -> str:
        return f"{source}:{self.line}: {self.message}"


def _parse_duration_seconds(raw_value: str) -> Optional[int]:
    value = raw_value.strip().lower()
    if not value:
        return None
    match = re.match(r"^(\d+)([smhd]?)$", value)
    if not match:
        return None
    number = int(match.group(1))
    unit = match.group(2) or "s"
    factor = 1
    if unit == "m":
        factor = 60
    elif unit == "h":
        factor = 3600
    elif unit == "d":
        factor = 86400
    return number * factor


def _directive_bool_value(raw_value: str) -> Optional[bool]:
    value = raw_value.strip().lower()
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    if value in truthy:
        return True
    if value in falsy:
        return False
    return None


def _parse_bounded_integer(
    raw_value: str,
    *,
    minimum: int,
    maximum: int,
) -> Optional[int]:
    value = raw_value.strip()
    if not re.fullmatch(r"[+-]?\d+", value):
        return None
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def _parse_key_value_tokens(tokens: Sequence[str]) -> Tuple[Dict[str, str], List[str]]:
    params: Dict[str, str] = {}
    malformed: List[str] = []
    for token in tokens:
        if "=" not in token:
            malformed.append(token)
            continue
        key, raw_value = token.split("=", 1)
        normalized_key = key.strip().lower()
        if not normalized_key:
            malformed.append(token)
            continue
        params[normalized_key] = raw_value.strip()
    return params, malformed


def _validate_wait_condition(
    expression: str,
    *,
    line_number: int,
    issues: List[LintIssue],
    todo_refs: List[Tuple[int, str]],
) -> None:
    condition = expression.strip()
    if not condition:
        issues.append(LintIssue(line=line_number, message="WAIT on= enthaelt eine leere Bedingung."))
        return
    lowered = condition.lower()
    if lowered.startswith("todo:"):
        target = condition.split(":", 1)[1].strip()
        if not target:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT on=todo:<id> braucht eine gueltige ToDo-ID.",
                )
            )
            return
        if not WAIT_CONDITION_TODO_PATTERN.match(target):
            issues.append(
                LintIssue(
                    line=line_number,
                    message=f"WAIT-Bedingung todo:{target} ist ungueltig.",
                )
            )
            return
        todo_refs.append((line_number, target))
        return
    if lowered.startswith("group:"):
        target = condition.split(":", 1)[1].strip()
        if not target:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT on=group:<name> braucht einen Gruppennamen.",
                )
            )
        return
    if lowered.startswith("agent:"):
        target = condition.split(":", 1)[1].strip()
        if not target:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT on=agent:<name> braucht einen Agentnamen.",
                )
            )
        return
    try:
        reject_bridge_wait_conditions(condition)
    except ValueError as exc:
        issues.append(LintIssue(line=line_number, message=str(exc), code="removed_feature"))
        return
    if WAIT_CONDITION_TODO_PATTERN.match(condition):
        todo_refs.append((line_number, condition))
        return
    issues.append(
        LintIssue(
            line=line_number,
            message=(
                "WAIT on= enthaelt ungueltigen Ausdruck "
                f"'{condition}' (erlaubt: todo:/group:/agent:/<id>)."
            ),
        )
    )


def _validate_directive(
    directive_line: str,
    *,
    line_number: int,
    todo_line: int,
    workdir: Path,
    issues: List[LintIssue],
    todo_refs: List[Tuple[int, str]],
) -> None:
    normalized_directive = directive_line.strip()
    match = DIRECTIVE_PATTERN.match(normalized_directive)
    if not match:
        issues.append(
            LintIssue(
                line=line_number,
                message=f"Ungueltige Directive-Syntax: {normalized_directive}",
            )
        )
        return
    if normalized_directive == STOP_SENTINEL:
        if line_number != todo_line - 1:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="STOP muss direkt vor der ToDo-Zeile stehen.",
                )
            )
        return
    body = match.group(1).strip()
    if not body:
        issues.append(
            LintIssue(line=line_number, message="Leere Directive ist ungueltig.")
        )
        return
    try:
        tokens = directive_tokens(body)
    except ValueError as exc:
        issues.append(
            LintIssue(
                line=line_number,
                message=f"Directive kann nicht geparst werden: {exc}",
            )
        )
        return
    if not tokens:
        issues.append(
            LintIssue(
                line=line_number, message="Directive ohne Kommando ist ungueltig."
            )
        )
        return
    command = tokens[0].upper()
    if command == "STOP":
        issues.append(
            LintIssue(
                line=line_number,
                message="STOP-Marker muss exakt ***STOP*** sein.",
            )
        )
        if len(tokens) > 1:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="STOP-Directive darf keine Parameter enthalten.",
                )
            )
        if line_number != todo_line - 1:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="STOP muss direkt vor der ToDo-Zeile stehen.",
                )
            )
        return

    if command == "WAIT":
        for token in tokens[1:]:
            key, _, value = token.partition("=")
            if key.lower() == "on":
                try:
                    reject_bridge_wait_conditions(value)
                except ValueError as exc:
                    issues.append(LintIssue(line=line_number, message=str(exc), code="removed_feature"))
                    return

    params, malformed_tokens = _parse_key_value_tokens(tokens[1:])
    for token in malformed_tokens:
        issues.append(
            LintIssue(
                line=line_number,
                message=f"Ungueltiger Parameter ohne key=value: {token}",
            )
        )

    if command == "CFG":
        from codex_policy import reject_policy_keys
        try:
            reject_policy_keys(params, source="CFG")
        except ValueError as exc:
            issues.append(LintIssue(line=line_number, message=str(exc), code="codex_policy"))
            return
        for key, value in params.items():
            if key not in CFG_ALLOWED_KEYS:
                issues.append(
                    LintIssue(
                        line=line_number,
                        message=f"Unbekannter CFG-Parameter: {key}",
                    )
                )
                continue
            if not value:
                issues.append(
                    LintIssue(
                        line=line_number,
                        message=f"CFG-Parameter {key} darf nicht leer sein.",
                        code="codex_policy" if key in {"agent", "network_access", "workspace"} else "invalid_todo",
                    )
                )
                continue

            if key in {"web_search", "websearch"}:
                mode = value.strip().lower()
                if mode not in {"live", "cached", "disabled"}:
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                f"CFG {key}={value} ist ungueltig "
                                "(erlaubt: live|cached|disabled)."
                            ),
                        )
                    )
            elif key == "agent":
                from codex_policy import validate_config_profile
                try:
                    validate_config_profile(value)
                except ValueError as exc:
                    issues.append(LintIssue(line=line_number, message=str(exc), code="codex_policy"))
            elif key == "network_access":
                from codex_policy import effective_network_access
                try:
                    # Static grammar validation; the Runner checks the actual
                    # explicit grant at execution, even after this succeeds.
                    effective_network_access(True, value)
                except ValueError as exc:
                    issues.append(LintIssue(line_number, str(exc), code="codex_policy"))
            elif key in {"result_file", "completion_anchor"}:
                if "/" in value or "\\" in value or not re.fullmatch(
                    r"todo_result_\d+(?:_[A-Za-z0-9_.-]+)?\.md",
                    value.strip(),
                ):
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                f"CFG {key} muss ein lokaler "
                                "todo_result_*.md-Dateiname sein."
                            ),
                        )
                    )
            elif key == "workspace":
                try:
                    resolved = native_path(value, base=workdir, label="CFG workspace")
                except (PathValidationError, OSError) as exc:
                    issues.append(LintIssue(line=line_number, message=str(exc), code="codex_policy"))
                    continue
                try:
                    resolved.relative_to(workdir)
                except ValueError:
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                f"CFG workspace zeigt aus dem Workspace heraus: {value}"
                            ),
                            code="codex_policy",
                        )
                    )
            elif key == "breakdown":
                mode = value.strip().lower()
                if mode not in BREAKDOWN_POLICY_VALUES:
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                f"CFG breakdown={value} ist ungueltig "
                                "(erlaubt: minimal|legacy|off; Runtime-Aliasse: "
                                "structured|none|disabled|false)."
                            ),
                        )
                    )
            elif key == "breakdown_max_children":
                if _parse_bounded_integer(
                    value,
                    minimum=BREAKDOWN_MAX_CHILDREN_MIN,
                    maximum=BREAKDOWN_MAX_CHILDREN_MAX,
                ) is None:
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                "CFG breakdown_max_children muss eine ganze Zahl "
                                f"zwischen {BREAKDOWN_MAX_CHILDREN_MIN} und "
                                f"{BREAKDOWN_MAX_CHILDREN_MAX} sein."
                            ),
                        )
                    )
            elif key == "breakdown_max_rounds":
                if _parse_bounded_integer(
                    value,
                    minimum=BREAKDOWN_MAX_ROUNDS_MIN,
                    maximum=BREAKDOWN_MAX_ROUNDS_MAX,
                ) is None:
                    issues.append(
                        LintIssue(
                            line=line_number,
                            message=(
                                "CFG breakdown_max_rounds muss eine ganze Zahl "
                                f"zwischen {BREAKDOWN_MAX_ROUNDS_MIN} und "
                                f"{BREAKDOWN_MAX_ROUNDS_MAX} sein."
                            ),
                        )
                    )

        return

    if command == "WAIT":
        for key in params.keys():
            if key not in WAIT_ALLOWED_KEYS:
                issues.append(
                    LintIssue(
                        line=line_number,
                        message=f"Unbekannter WAIT-Parameter: {key}",
                    )
                )
        on_value = params.get("on", "").strip()
        if not on_value:
            issues.append(
                LintIssue(line=line_number, message="WAIT braucht on=<bedingung>.")
            )
        else:
            for expression in on_value.split(","):
                _validate_wait_condition(
                    expression,
                    line_number=line_number,
                    issues=issues,
                    todo_refs=todo_refs,
                )
        wait_mode = params.get("mode")
        if wait_mode is not None and wait_mode.strip().lower() not in {"all", "any"}:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT mode muss all oder any sein.",
                )
            )
        timeout = params.get("timeout")
        if timeout is not None and _parse_duration_seconds(timeout) is None:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT timeout ist ungueltig (z. B. 30s, 5m, 1h, 1d).",
                )
            )
        on_timeout = params.get("on_timeout")
        if on_timeout is not None and on_timeout.strip().lower() not in {
            "stop",
            "continue",
        }:
            issues.append(
                LintIssue(
                    line=line_number,
                    message="WAIT on_timeout muss stop oder continue sein.",
                )
            )
        return

    issues.append(
        LintIssue(
            line=line_number,
            message=f"Unbekannte Directive: {command}",
        )
    )


def lint_todo_file(
    todo_file: Path, *, workdir: Optional[Path] = None
) -> List[LintIssue]:
    try:
        source = native_path(todo_file, label="ToDo-Datei")
        resolved_workdir = native_path(workdir or source.parent, label="workdir")
    except (PathValidationError, OSError) as exc:
        return [LintIssue(line=1, message=str(exc))]
    if not source.exists():
        return [LintIssue(line=1, message=f"ToDo-Datei nicht gefunden: {source}")]
    if not source.is_file():
        return [LintIssue(line=1, message=f"Pfad ist keine Datei: {source}")]
    try:
        text = read_utf8(source)
    except (OSError, UnicodeError) as exc:
        return [LintIssue(line=1, message=f"Datei kann nicht gelesen werden: {exc}")]

    issues: List[LintIssue] = []
    todo_ids: Dict[str, int] = {}
    todo_tuples: List[Tuple[Tuple[int, ...], int, str]] = []
    directive_lines: Set[int] = set()
    used_directives: Set[int] = set()
    wait_todo_refs: List[Tuple[int, str]] = []
    todo_entries: List[Tuple[int, str]] = []

    visible = dict(visible_lines(text))
    syntax_seen = False
    for zero_index, raw_line in visible.items():
        index = zero_index + 1
        stripped = raw_line.strip()
        if stripped.upper().startswith("***SYNTAX"):
            if not SYNTAX_PATTERN.fullmatch(stripped):
                issues.append(LintIssue(index, "Ungueltige SYNTAX: erwartet ***SYNTAX auto|legacy|marked-en***."))
            if syntax_seen or todo_entries:
                issues.append(LintIssue(index, "SYNTAX ist genau einmal vor der ersten Aufgabe erlaubt."))
            syntax_seen = True
            continue
        if re.match(r"^\d+(?:\.\d+)*(?:\.)?\s+\*\*\*", stripped) and not TODO_PATTERN.match(stripped):
            issues.append(LintIssue(index, "Unbekanntes oder fehlerhaftes Task-Kommando; erwartet ***Task***, ***DONE*** oder ***OBSOLETE***."))
        if DIRECTIVE_PATTERN.match(stripped):
            directive_lines.add(index)
        match = TODO_PATTERN.match(stripped)
        if not match:
            continue
        identifier = match.group(1)
        status = canonical_status(match.group(2))
        title = match.group(3).strip()
        todo_entries.append((index, identifier))
        if not title:
            issues.append(
                LintIssue(
                    line=index,
                    message=f"ToDo {identifier} hat keinen Text nach '{status}:'.",
                )
            )
        if identifier in todo_ids:
            issues.append(
                LintIssue(
                    line=index,
                    message=(
                        f"Doppelte ToDo-ID {identifier} "
                        f"(bereits in Zeile {todo_ids[identifier]})."
                    ),
                )
            )
        else:
            todo_ids[identifier] = index
        number_tuple = tuple(int(part) for part in identifier.split("."))
        todo_tuples.append((number_tuple, index, identifier))

    if not todo_entries:
        issues.append(LintIssue(line=1, message="Keine ToDo-Zeilen gefunden."))

    previous: Optional[Tuple[int, ...]] = None
    previous_line = 0
    previous_identifier = ""
    for number_tuple, line_number, identifier in todo_tuples:
        if previous is not None and number_tuple <= previous:
            issues.append(
                LintIssue(
                    line=line_number,
                    message=(
                        "ToDo-Reihenfolge ist nicht strikt aufsteigend: "
                        f"{identifier} folgt auf {previous_identifier} (Zeile {previous_line})."
                    ),
                )
            )
        previous = number_tuple
        previous_line = line_number
        previous_identifier = identifier

    for todo_line, _identifier in todo_entries:
        cursor = todo_line - 1
        directive_block: List[Tuple[int, str]] = []
        while cursor >= 1:
            stripped = visible.get(cursor - 1, "").strip()
            if SYNTAX_PATTERN.fullmatch(stripped):
                cursor -= 1
                continue
            if (cursor - 1) not in visible or not stripped:
                break
            if not DIRECTIVE_PATTERN.match(stripped):
                break
            directive_block.append((cursor, stripped))
            cursor -= 1
        directive_block.reverse()
        for line_number, directive_line in directive_block:
            used_directives.add(line_number)
            _validate_directive(
                directive_line,
                line_number=line_number,
                todo_line=todo_line,
                workdir=resolved_workdir,
                issues=issues,
                todo_refs=wait_todo_refs,
            )

    for line_number in sorted(directive_lines - used_directives):
        issues.append(
            LintIssue(
                line=line_number,
                message=(
                    "Directive steht nicht direkt vor einer ToDo-Zeile "
                    "und wird daher ignoriert."
                ),
            )
        )

    known_ids = set(todo_ids.keys())
    for line_number, target in wait_todo_refs:
        if target not in known_ids:
            issues.append(
                LintIssue(
                    line=line_number,
                    message=f"WAIT referenziert unbekannte ToDo-ID: {target}",
                )
            )

    return sorted(issues, key=lambda issue: (issue.line, issue.message))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lintet ToDo-Listen inkl. CFG/WAIT/STOP-Directives."
    )
    parser.add_argument(
        "--todo-file",
        type=Path,
        required=True,
        help="Pfad zur ToDo-Datei.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help=(
            "Workspace-Root fuer CFG workspace=... Pruefungen "
            "(Default: Verzeichnis der ToDo-Datei)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    # Validation must precede resolution, especially for UNC/device paths.
    todo_file = args.todo_file
    workdir = args.workdir
    issues = lint_todo_file(todo_file, workdir=workdir)
    if not issues:
        print(f"[ok] ToDo-Liste ist gueltig: {todo_file}")
        return 0
    for issue in issues:
        print(issue.render(todo_file), file=sys.stderr)
    print(
        f"[fatal] ToDo-Lint fehlgeschlagen: {len(issues)} Problem(e) gefunden.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
