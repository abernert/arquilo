# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Readable, versioned prompt catalogs; no execution or permission configuration.

A catalog is loaded once by each run owner. Immutable snapshots cross worker
boundaries; rendering replaces only declared {{name}} tokens, in one pass.
User task text, runtime-profile additions and skill instructions are never
translated or reinterpreted as templates.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib
from typing import Any

PROMPT_SCHEMA_VERSION = "arquilo.prompts.v1"
PROMPT_CONFIG_CONTRACT_VERSION = 1
MAX_CONFIG_BYTES = 512 * 1024
MAX_ELEMENT_BYTES = 128 * 1024
BUILTIN_DIRECTORY = Path(__file__).resolve().parent / "prompts"
TOKEN = re.compile(r"\{\{([^{}]*)\}\}")

# Names and parameter contracts, not prompt text. All catalogs must be complete.
PROMPT_PLACEHOLDERS = {
    'review_policy_rules': (),
    'reviewer_role': ('latest_answer', 'original_task'),
    'review_instructions': ('confidence_fields', 'confidence_rules', 'policy_rules'),
    'fix_no_blockers': (),
    'fix_assignment': ('blocking_issues', 'decision_text', 'original_task'),
    'review_contract_inline': ('contract',),
    'review_contract_file': ('path',),
    'confidence_fields': (),
    'confidence_rules': ('max_items', 'max_text'),
    'task_controller_only': ('process_stop_path', 'question_path'),
    'task_contract': (),
    'parent_terminal': (),
    'preflight': (),
    'task_agent_stop': ('process_stop_path', 'question_path'),
    'task_policy_intro': ('policy_path', 'policy_text'),
    'task_mutable_plan': (),
    'task_guarded_plan': (),
    'task_stop_boundary': ('stop_id',),
    'task_marked_syntax': (),
    'task_agent_hint': ('agent',),
    'task_policy_controller': (),
    'task_policy_agent': ('process_stop_path',),
    'task_assignment': ('result_path', 'task_id', 'todo_path'),
    'task_subworkspace': ('workspace',),
    'breakdown_legacy_boundary': (),
    'breakdown_legacy': ('result_path', 'review_boundary', 'scope_guard', 'task_command', 'task_id', 'todo_path'),
    'breakdown_single': (),
    'breakdown_multiple': ('max_children',),
    'breakdown_minimal': ('issues', 'mode_instruction', 'result_path', 'round_number', 'scope_guard', 'task_command', 'task_id', 'todo_path'),
    'parent_assignment': ('parent_id', 'result_path', 'scope_guard', 'todo_path'),
    'preamble_semantics': (),
    'preamble_envelope': ('byte_count', 'preamble', 'semantics', 'separator', 'task', 'todo_filename'),
    'decision_instructions': (),
    'decision_completion': (),
    'decision_plan_step': (),
    'decision_plan_final': (),
    'decision_system': (),
    'resource_header': (),
    'resource_instructions': (),
    'questions_document': (),
    'issue_missing_summary': (),
    'fix_issue_requirement': ('value',),
    'breakdown_issue_requirement': ('value',),
    'fix_issue_criterion': ('value',),
    'breakdown_issue_criterion': ('value',),
    'fix_issue_references': ('value',),
    'breakdown_issue_references': ('value',),
    'fix_issue_suggestion': ('value',),
    'breakdown_issue_suggestion': ('value',),
    'breakdown_no_issues': (),
    'decision_result_complete': (),
    'decision_result_incomplete': ('count',),
    'doctor_question': (),
}


class PromptConfigError(ValueError):
    """Invalid prompt configuration: fail before executing a task."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_metadata(identifier: str, version: str, language: str) -> None:
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier):
        raise PromptConfigError("Prompt catalog id must be a simple nonempty identifier")
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        raise PromptConfigError("Prompt catalog version must be a nonempty string (max. 64 characters)")
    if language not in ("mixed", "de", "en"):
        raise PromptConfigError("Prompt catalog language must be mixed, de or en")


def _validate_texts(texts: dict[str, str]) -> None:
    missing, unknown = set(PROMPT_PLACEHOLDERS) - set(texts), set(texts) - set(PROMPT_PLACEHOLDERS)
    if missing or unknown:
        raise PromptConfigError("Prompt element mismatch; missing=" + ",".join(sorted(missing))
                                + "; unknown=" + ",".join(sorted(unknown)))
    total = 0
    for key, text in texts.items():
        if not isinstance(text, str) or not text.strip() or "\0" in text:
            raise PromptConfigError(f"Prompt element {key} must be nonempty text without NUL")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError as exc:
            raise PromptConfigError(f"Prompt element {key} must be valid UTF-8 text") from exc
        total += size
        if size > MAX_ELEMENT_BYTES or total > MAX_CONFIG_BYTES:
            raise PromptConfigError("Prompt catalog is too large; no truncation performed")
        matches = list(TOKEN.finditer(text))
        fields = {m.group(1) for m in matches}
        if text.count("{{") != len(matches) or fields != set(PROMPT_PLACEHOLDERS[key]):
            raise PromptConfigError(f"Invalid placeholders in {key}; expected: "
                                    + ", ".join(PROMPT_PLACEHOLDERS[key]))


@dataclass(frozen=True, slots=True)
class PromptConfig:
    """Only immutable strings/tuples: safe to reuse across tasks and threads."""
    schema_version: str
    id: str
    version: str
    language: str
    texts: tuple[tuple[str, str], ...]
    source: str
    source_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != PROMPT_SCHEMA_VERSION:
            raise PromptConfigError("Unsupported prompt catalog schema")
        _validate_metadata(self.id, self.version, self.language)
        if (not isinstance(self.texts, (tuple, list)) or any(
                not isinstance(row, (tuple, list)) or len(row) != 2
                or not isinstance(row[0], str) for row in self.texts)):
            raise PromptConfigError("Invalid prompt snapshot entries")
        values = dict(self.texts)
        if len(values) != len(self.texts):
            raise PromptConfigError("Duplicate prompt snapshot entries")
        _validate_texts(values)
        object.__setattr__(self, "texts", tuple(sorted(values.items())))
        if (not isinstance(self.source, str) or len(self.source) > 8192 or "\0" in self.source
                or not isinstance(self.source_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256)):
            raise PromptConfigError("Invalid prompt source metadata")
        if self.content_sha256 != _digest(self._content()):
            raise PromptConfigError("Prompt snapshot content digest mismatch")

    def _content(self) -> dict:
        return dict(schema_version=self.schema_version, id=self.id, version=self.version,
                    language=self.language, prompts=dict(self.texts))

    def template(self, key: str) -> str:
        try:
            return dict(self.texts)[key]
        except KeyError as exc:
            raise PromptConfigError(f"Unknown prompt element: {key}") from exc

    def render(self, key: str, **values: object) -> str:
        template = self.template(key)
        if set(values) != set(PROMPT_PLACEHOLDERS[key]):
            raise PromptConfigError(f"Incorrect arguments for prompt element {key}")
        # A callable replacement treats backslashes literally; inserted text is
        # never scanned again, evaluated, or expanded as another template.
        return TOKEN.sub(lambda match: str(values[match.group(1)]), template)

    def metadata(self) -> dict:
        return {key: getattr(self, key) for key in ("schema_version", "id", "version", "language",
                                                   "source", "source_sha256", "content_sha256")}

    def snapshot(self) -> dict:
        return {**self.metadata(), "texts": [list(row) for row in self.texts]}


def load_prompt_config(selection: PromptConfig | dict | str | Path | None = None) -> PromptConfig:
    """Load default/de/en, an explicit file, or a validated worker snapshot.

    No environment or workspace is searched implicitly. CLI callers may select
    an environment default themselves; Python APIs use the explicit argument.
    A supplied snapshot is validated without rereading its former source path.
    """
    if isinstance(selection, PromptConfig):
        selection.__post_init__()
        return selection
    if isinstance(selection, dict):
        try:
            return PromptConfig(**selection)
        except TypeError as exc:
            raise PromptConfigError("Invalid prompt snapshot fields") from exc
    if selection is None:
        selection = "default"
    if not isinstance(selection, (str, Path)) or not str(selection).strip():
        raise PromptConfigError("Select default, de, en, or a TOML file path")
    path = BUILTIN_DIRECTORY / (selection + ".toml") if isinstance(selection, str) and selection in ("default", "de", "en") else Path(selection).expanduser()
    try:
        path = path.resolve(strict=True)
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise PromptConfigError("Prompt configuration must be a regular file")
        with path.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
    except (OSError, ValueError) as exc:
        if isinstance(exc, PromptConfigError):
            raise
        raise PromptConfigError("Cannot read selected prompt configuration") from exc
    if len(data) > MAX_CONFIG_BYTES:
        raise PromptConfigError("Prompt configuration is too large; no truncation performed")
    try:
        raw = tomllib.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        # Do not echo arbitrary user file contents in an error message.
        raise PromptConfigError("Invalid UTF-8/TOML prompt configuration") from exc
    if set(raw) != {"schema_version", "id", "version", "language", "prompts"} or not isinstance(raw.get("prompts"), dict):
        raise PromptConfigError("Invalid prompt catalog fields")
    texts = {}
    for key, entry in raw["prompts"].items():
        if not isinstance(entry, dict) or set(entry) != {"text"}:
            raise PromptConfigError(f"Prompt element {key} must contain exactly a text field")
        texts[key] = entry["text"]
    content = {key: raw[key] for key in ("schema_version", "id", "version", "language")}
    content["prompts"] = texts
    return PromptConfig(**{key: raw[key] for key in ("schema_version", "id", "version", "language")},
                        texts=tuple(texts.items()), source=str(path),
                        source_sha256=hashlib.sha256(data).hexdigest(), content_sha256=_digest(content))
