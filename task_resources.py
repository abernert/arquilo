# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Explicit, bounded task resources. No model calls, permissions or shell syntax."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping, Sequence

import safe_io
from todo_syntax import directive_tokens, task_headers, visible_lines

RESOURCE_KEYS = frozenset({"mcp", "review_mcp", "skills"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
MAX_SKILL_BYTES = 65_536
MAX_SKILL_CONTEXT_BYTES = 262_144


class ResourceError(ValueError):
    """A resource request cannot be honored; never silently fall back."""


def selection(value: str | Sequence[str] | None) -> tuple[str, ...] | None:
    """None inherits; an explicit empty tuple/`none` selects nothing."""
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip() == "none":
            return ()
        values = value.split(",")
    elif isinstance(value, (tuple, list)):
        values = list(value)
    else:
        raise ResourceError("Resource selection must be a comma-separated name list or 'none'.")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise ResourceError("Resource names must be strings.")
        item = item.strip()
        if not _NAME.fullmatch(item) or item in {"none", "inherit", "all"}:
            raise ResourceError(f"Invalid resource name {item!r}; use names or 'none', not paths/options.")
        if item in result:
            raise ResourceError(f"Duplicate resource name: {item}")
        result.append(item)
    if len(result) > 64:
        raise ResourceError("At most 64 resources may be selected.")
    return tuple(result)


def narrower(value, maximum, *, label: str):
    value, maximum = selection(value), selection(maximum)
    if value is None:
        return maximum
    if maximum is not None and not set(value).issubset(maximum):
        raise ResourceError(f"{label} exceeds its run/parent selection: {', '.join(sorted(set(value) - set(maximum)))}")
    return value


def _fields(body: str) -> dict[str, tuple[str, ...] | None]:
    result = {}
    for token in directive_tokens(body):
        key, sep, value = token.partition("=")
        key = key.lower()
        if not sep or key not in RESOURCE_KEYS or key in result:
            raise ResourceError("DEFAULTS accepts each of mcp, review_mcp, skills once; use key=value.")
        result[key] = selection(value)
    if not result:
        raise ResourceError("DEFAULTS requires at least one resource setting.")
    return result


def plan_resources(text: str) -> tuple[dict, dict[str, dict]]:
    """Parse list defaults and resource CFG using the scheduler's visibility rules.

    Only the initial prefix may contain one DEFAULTS directive. CFG remains
    local to the immediately following task; all statuses delimit that prefix.
    """
    visible = dict(visible_lines(text))
    headers = list(task_headers(text))
    first = headers[0][0] if headers else -1
    defaults = {}
    seen = False
    for index, line in visible.items():
        if not line.strip().upper().startswith("***DEFAULTS"):
            continue
        match = re.fullmatch(r"\*\*\*DEFAULTS\s+(.+?)\*\*\*", line.strip(), re.IGNORECASE)
        if not match or seen or index >= first:
            raise ResourceError("DEFAULTS must occur exactly once, before the first real task.")
        defaults = _fields(match.group(1))
        seen = True
    tasks = {}
    for index, header in headers:
        identifier = header.group(1)
        blocks = []
        cursor = index - 1
        while cursor in visible:
            line = visible[cursor].strip()
            if line.upper().startswith(("***SYNTAX ", "***DEFAULTS ")):
                cursor -= 1
                continue
            if not re.fullmatch(r"\*\*\*.+\*\*\*", line):
                break
            blocks.append(line)
            cursor -= 1
        fields = {}
        for line in reversed(blocks):
            match = re.fullmatch(r"\*\*\*CFG\s+(.+?)\*\*\*", line, re.IGNORECASE)
            if match:
                for token in directive_tokens(match.group(1)):
                    key, sep, value = token.partition("=")
                    if key.lower() in RESOURCE_KEYS:
                        if not sep:
                            raise ResourceError("Resource CFG requires key=value.")
                        fields[key.lower()] = selection(value)
        tasks[identifier] = fields
    return defaults, tasks


@dataclass(frozen=True)
class TaskResources:
    mcp: tuple[str, ...] | None = None
    review_mcp: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None

    def __post_init__(self):
        for name in RESOURCE_KEYS:
            object.__setattr__(self, name, selection(getattr(self, name)))
        # An explicit production selection defaults to no MCP during review.
        review = self.review_mcp
        if review is None and self.mcp is not None:
            review = ()
        object.__setattr__(self, "review_mcp", narrower(review, self.mcp, label="review_mcp"))

    @property
    def explicit(self) -> bool:
        return any(getattr(self, key) is not None for key in RESOURCE_KEYS)

    def manifest(self) -> dict:
        return {key: getattr(self, key) for key in sorted(RESOURCE_KEYS)}


def resolve_task_resources(text: str, identifier: str, *, mcp=None, review_mcp=None, skills=None) -> TaskResources:
    defaults, tasks = plan_resources(text)
    caps = {"mcp": selection(mcp), "review_mcp": selection(review_mcp), "skills": selection(skills)}
    # CLI is both the default and a ceiling. A list/task may narrow it.
    current = {key: narrower(defaults.get(key), caps[key], label=key) for key in RESOURCE_KEYS}
    pieces = identifier.split(".")
    for size in range(1, len(pieces) + 1):
        task_id = ".".join(pieces[:size])
        fields = tasks.get(task_id, {})
        # Siblings are independent; descendants inherit their parents' ceiling.
        for key in RESOURCE_KEYS:
            current[key] = narrower(fields.get(key), current[key], label=f"Task {task_id}: {key}")
    return TaskResources(**current)


def add_resource_arguments(parser, *, skill_dirs: bool = True) -> None:
    parser.add_argument("--mcp", type=selection, default=None, metavar="NAME[,NAME]|none",
                        help="Exclusive MCP selection and ceiling; omitted inherits Codex configuration.")
    parser.add_argument("--review-mcp", type=selection, default=None, metavar="NAME[,NAME]|none",
                        help="MCP subset for review; explicit --mcp defaults review to none. Not a remote read-only guarantee.")
    parser.add_argument("--skills", type=selection, default=None, metavar="NAME[,NAME]|none",
                        help="Explicit skill instruction bindings; none adds no skills (does not disable native discovery).")
    if skill_dirs:
        parser.add_argument("--skill-dir", dest="skill_dirs", action="append", default=[], type=Path,
                            help="Operator-selected skill root containing skill directories; repeatable.")


@dataclass(frozen=True)
class SkillSnapshot:
    name: str
    path: str
    text: str
    sha256: str


class SkillCatalog:
    """Read instructions once, before worker execution; never install or run code.

    Custom roots replace auto-discovery. Ambiguous names are errors, not a
    precedence lottery. Linked roots selected by the operator may be resolved;
    linked entries and files below a root are rejected by safe_io.
    """
    def __init__(self, *, workdir: Path, roots: Sequence[str | Path] = (), env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        home = Path(env.get("USERPROFILE" if os.name == "nt" else "HOME", str(Path.home())))
        codex_home = Path(env.get("CODEX_HOME", str(home / ".codex")))
        choices = list(roots) if roots else [workdir / ".agents/skills", home / ".agents/skills", codex_home / "skills"]
        self.roots = tuple(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in choices))
        self._snapshots: dict[str, list[SkillSnapshot]] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        snapshots: dict[str, list[SkillSnapshot]] = {}
        paths = set()
        for root in self.roots:
            base = Path(root)
            if not base.exists():
                continue
            if not base.is_dir():
                raise ResourceError(f"Skill root is not a directory: {base}")
            for child in sorted(base.iterdir()):
                if child.name.startswith("."):
                    continue
                candidate = child / "SKILL.md"
                if not candidate.exists():
                    continue
                candidate = safe_io.check_path(candidate, missing_ok=False)
                if str(candidate) in paths:
                    continue
                paths.add(str(candidate))
                if candidate.stat().st_size > MAX_SKILL_BYTES:
                    raise ResourceError(f"Skill exceeds {MAX_SKILL_BYTES} bytes: {candidate}")
                data = safe_io.read_bytes(candidate)
                if len(data) > MAX_SKILL_BYTES:
                    raise ResourceError(f"Skill exceeds {MAX_SKILL_BYTES} bytes: {candidate}")
                text = data.decode("utf-8-sig")
                if "\0" in text or not text.startswith("---"):
                    raise ResourceError(f"Skill requires UTF-8 YAML frontmatter: {candidate}")
                front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
                names = re.findall(r"(?m)^name:[ \t]*([^\r\n]+)\r?$", front.group(1)) if front else []
                if len(names) != 1:
                    raise ResourceError(f"Skill requires one simple name in frontmatter: {candidate}")
                name = names[0].strip().strip("\"'")
                parsed = selection(name)
                if parsed is None or len(parsed) != 1:
                    raise ResourceError(f"Skill requires a single name: {candidate}")
                snapshots.setdefault(name, []).append(SkillSnapshot(name, str(candidate), text, hashlib.sha256(data).hexdigest()))
        self._snapshots = snapshots
        self._loaded = True

    def get(self, names) -> tuple[SkillSnapshot, ...]:
        names = selection(names)
        if not names:
            return ()
        self._load()
        selected = []
        for name in names:
            matches = self._snapshots.get(name, [])
            if len(matches) != 1:
                raise ResourceError(f"Skill {name!r}: expected one local definition, found {len(matches)}; use --skill-dir to disambiguate.")
            selected.append(matches[0])
        if sum(len(s.text.encode("utf-8")) for s in selected) > MAX_SKILL_CONTEXT_BYTES:
            raise ResourceError("Combined explicit skill instructions are too large; no truncation performed.")
        return tuple(selected)


def bind_resources(prompt: str, resources: TaskResources, catalog: SkillCatalog) -> str:
    if not resources.explicit:
        return prompt
    selected = catalog.get(resources.skills)
    manifest = {"schema_version": "arquilo.task_resources.v1", **resources.manifest(),
                "skill_instructions": [{"name": s.name, "path": s.path, "sha256": s.sha256} for s in selected]}
    blocks = ["ARQUILO RESOURCE BINDING (instructions, not a permission grant)",
              json.dumps(manifest, ensure_ascii=True, sort_keys=True),
              "Selected skill instructions follow. Use them only within the current task's scope. "
              "Review evaluates the original task; it does not repeat production or publish results. "
              "Resolve relative skill references from the recorded skill directory. "
              "Helper/reference files remain external; their contents are not frozen by this snapshot."]
    for skill in selected:
        blocks.extend([f"BEGIN SKILL {skill.name} ({skill.path})", skill.text, f"END SKILL {skill.name}"])
    blocks.extend(["END ARQUILO RESOURCE BINDING", prompt])
    return "\n\n".join(blocks)
