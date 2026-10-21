# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Pure contract-bound review rules, parsing and correction prompts.

Standard library only. No provider, environment or orchestration. Prompt builders
use a supplied immutable catalog (or load the shipped default for direct callers).
JSON is authoritative only after validation; legacy prose still needs Decide.
"""
from __future__ import annotations

from prompt_config import PromptConfig, PromptConfigError, load_prompt_config

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from review_confidence import (
    CONFIDENCE_FIELDS, confidence_prompt_fields, confidence_prompt_rules,
    confidence_protocol_error, normalize_review_confidence,
)



def render_review_policy_rules(
    review_policy_rules: Optional[Sequence[str]],
    *, prompt_config: PromptConfig | None = None,
) -> str:
    # Profiles add domain rules; they cannot erase the generic audit/scope rules.
    prompts = load_prompt_config(prompt_config)
    rules = (*prompts.render("review_policy_rules").splitlines(), *(review_policy_rules or ()))
    rendered: List[str] = []
    for raw in rules:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("- "):
            rendered.append(text + ("\n" if not text.endswith("\n") else ""))
        else:
            rendered.append(f"- {text}\n")
    return "".join(rendered)


def build_review_prompt(
    original_task: str,
    latest_answer: str,
    *,
    review_policy_rules: Optional[Sequence[str]] = None,
    prompt_config: PromptConfig | None = None,
) -> str:
    prompts = load_prompt_config(prompt_config)
    return (
        prompts.render('reviewer_role', original_task=original_task, latest_answer=latest_answer)
    ) + review_instructions(review_policy_rules, prompt_config=prompts)


def review_instructions(review_policy_rules: Optional[Sequence[str]] = None, *, prompt_config: PromptConfig | None = None) -> str:
    """One response grammar and scope policy for task and parent reviewers."""
    prompts = load_prompt_config(prompt_config)
    return (
        prompts.render('review_instructions', confidence_fields=confidence_prompt_fields(prompt_config=prompts), confidence_rules=confidence_prompt_rules(prompt_config=prompts), policy_rules=render_review_policy_rules(review_policy_rules, prompt_config=prompts))
    )


def build_fix_prompt(original_task: str, findings: str, decision_text: str, *, prompt_config: PromptConfig | None = None) -> str:
    prompts = load_prompt_config(prompt_config)
    findings_block = _format_blocking_review_issues(findings, prompt_config=prompts)
    if not findings_block:
        findings_block = prompts.render('fix_no_blockers')
    return (
        prompts.render('fix_assignment', original_task=original_task, blocking_issues=findings_block, decision_text=decision_text)
    )


def build_review_context_reference(path: str, *, contract_text: str | None = None, prompt_config: PromptConfig | None = None) -> str:
    """Attach a controller-captured contract without requiring a sandboxed file read.

    The path-only form remains for compatibility. Runtime reviewers should pass
    the controller snapshot inline so review correctness does not depend on
    platform-specific sandbox access to ARQUILO's archived run logs.
    """
    prompts = load_prompt_config(prompt_config)
    if contract_text is None:
        return (
            prompts.render('review_contract_file', path=path)
        )

    inline = contract_text.rstrip("\n")
    return (
        prompts.render('review_contract_inline', contract=inline)
    )


_REVIEW_BLOCKING_TYPES = {
    "local_fix",
    "decomposition_needed",
    "missing_input",
    "scope_conflict",
    "technical_failure",
    "blocked_external",
}


def _normalize_review_references(raw: Any) -> List[str]:
    values: List[str] = []
    if isinstance(raw, list):
        candidates = raw
    elif isinstance(raw, (str, int, float)):
        candidates = [raw]
    else:
        candidates = []
    for value in candidates:
        if not isinstance(value, (str, int, float)):
            continue
        cleaned = str(value).strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _normalize_blocking_review_issue(raw: Any, index: int) -> Dict[str, Any]:
    if isinstance(raw, dict):
        issue_type_raw = raw.get("type")
        issue_type = (
            str(issue_type_raw).strip().lower()
            if isinstance(issue_type_raw, (str, int, float))
            else "local_fix"
        )
        if issue_type not in _REVIEW_BLOCKING_TYPES:
            issue_type = "local_fix"
        summary_raw = raw.get("summary") or raw.get("message") or raw.get("description")
        summary = (
            str(summary_raw).strip()
            if isinstance(summary_raw, (str, int, float))
            else ""
        )
        issue_id_raw = raw.get("id")
        issue_id = (
            str(issue_id_raw).strip()
            if isinstance(issue_id_raw, (str, int, float))
            else ""
        ) or f"ISSUE-{index}"
        requirement_raw = raw.get("requirement")
        acceptance_raw = raw.get("acceptance_criterion")
        fix_raw = raw.get("fix_suggestion") or raw.get("suggestion")
        return {
            "id": issue_id,
            "type": issue_type,
            "summary": summary or "Blocking issue reported without summary.",
            "requirement": (
                str(requirement_raw).strip()
                if isinstance(requirement_raw, (str, int, float))
                else ""
            ),
            "acceptance_criterion": (
                str(acceptance_raw).strip()
                if isinstance(acceptance_raw, (str, int, float))
                else ""
            ),
            "references": _normalize_review_references(raw.get("references")),
            "fix_suggestion": (
                str(fix_raw).strip()
                if isinstance(fix_raw, (str, int, float))
                else ""
            ),
        }
    summary = str(raw).strip() if isinstance(raw, (str, int, float)) else ""
    return {
        "id": f"ISSUE-{index}",
        "type": "local_fix",
        "summary": summary or "Blocking issue reported without summary.",
        "requirement": "",
        "acceptance_criterion": "",
        "references": [],
        "fix_suggestion": "",
    }


def _normalize_non_blocking_observation(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        summary_raw = raw.get("summary") or raw.get("message") or raw.get("description")
        suggestion_raw = raw.get("suggestion") or raw.get("fix_suggestion")
        return {
            "summary": (
                str(summary_raw).strip()
                if isinstance(summary_raw, (str, int, float))
                else "Non-blocking observation."
            ),
            "references": _normalize_review_references(raw.get("references")),
            "suggestion": (
                str(suggestion_raw).strip()
                if isinstance(suggestion_raw, (str, int, float))
                else ""
            ),
        }
    return {
        "summary": str(raw).strip() if isinstance(raw, (str, int, float)) else "Non-blocking observation.",
        "references": [],
        "suggestion": "",
    }


def _coerce_review_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "ja", "1", "on"}:
            return True
        if normalized in {"false", "no", "nein", "0", "off", "", "null", "none"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _legacy_blocking_lines(text: str) -> Tuple[List[str], bool]:
    """Return explicit blocking lines and whether a no-blocker marker exists.

    Legacy prose may contain both ``Muss behoben werden: Keine Mängel`` and
    additional bullets. A global substring check would incorrectly turn such
    mixed output into PASS, so classify line by line.
    """

    blocking_lines: List[str] = []
    explicit_none = False
    markers = (
        "muss behoben werden",
        "must be resolved",
        "must fix",
        "blocking issue",
        "blocking issues",
        "pflichtmangel",
    )
    none_markers = (
        "keine mängel",
        "keine maengel",
        "keine abweichungen",
        "keine probleme",
        "keine beanstandungen",
        "keine",
        "none",
        "no issue",
        "no defect",
    )
    for raw_line in text.splitlines():
        cleaned_line = raw_line.strip().lstrip("-•* ").replace("**", "").replace("__", "")
        normalized_line = cleaned_line.lower()
        if "muss nicht behoben werden" in normalized_line or "non-blocking" in normalized_line:
            continue
        matching = next((marker for marker in markers if marker in normalized_line), None)
        if matching is None:
            continue
        tail = normalized_line.split(matching, 1)[1].lstrip(" :–—-")
        if not tail:
            # An unfilled heading is not an explicit statement that no defect exists.
            blocking_lines.append(cleaned_line)
            continue
        if any(tail.startswith(marker) for marker in none_markers):
            explicit_none = True
            continue
        blocking_lines.append(cleaned_line)
    return blocking_lines, explicit_none


def _invalid_review(message: str) -> Dict[str, Any]:
    """Invalid/missing reviewer output is a technical failure, not an empty PASS."""
    return {
        "schema_version": "autobuild.review.v2", "source_format": "invalid",
        "valid": False, "verdict": "FAIL", "short_summary": message,
        "blocking_issues": [{
            "id": "INVALID-REVIEW", "type": "technical_failure", "summary": message,
            "requirement": "A valid review of this attempt must be available.",
            "acceptance_criterion": "Obtain a well-formed, non-contradictory review.",
            "references": [], "fix_suggestion": "Inspect reviewer logs; do not change the task to repair this failure.",
        }],
        "non_blocking_observations": [], "breakdown_recommended": False,
        "breakdown_reason": None,
        **normalize_review_confidence(),
    }


def _review_protocol_error(payload: Dict[str, Any]) -> Optional[str]:
    allowed = {"verdict", "short_summary", "issues", "blocking_issues",
               "non_blocking_observations", "breakdown_recommended", "breakdown_reason",
               "schema_version", "source_format", "valid"} | CONFIDENCE_FIELDS
    if set(payload) - allowed:
        return "Review contains unknown fields."
    if "valid" in payload and type(payload["valid"]) is not bool:
        return "Review valid must be a boolean."
    if payload.get("valid") is False:
        return str(payload.get("short_summary") or "Previously invalid review.")
    if "short_summary" in payload and not (
            isinstance(payload["short_summary"], str) and payload["short_summary"].strip()):
        return "Review short_summary must be non-empty text."
    if "schema_version" in payload and payload["schema_version"] != "autobuild.review.v2":
        return "Unknown review schema_version."
    if "source_format" in payload and (not isinstance(payload["source_format"], str)
            or payload["source_format"] not in {"structured", "json_legacy", "text_legacy"}):
        return "Unknown review source_format."
    verdict = payload.get("verdict")
    if not isinstance(verdict, str) or verdict.strip().upper() not in {"PASS", "FAIL"}:
        return "Review verdict must explicitly be PASS or FAIL."
    verdict = verdict.strip().upper()
    explicit = any(k in payload for k in ("blocking_issues", "non_blocking_observations", "breakdown_recommended"))
    if explicit and "issues" in payload:
        return "Review mixes legacy issues with the explicit blocking contract."
    key = "blocking_issues" if explicit else "issues"
    issues = payload.get(key)
    if not isinstance(issues, list):
        return f"Review {key} must be an explicit list."
    for item in issues:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and any(
            isinstance(item.get(k), str) and item[k].strip()
            for k in ("summary", "message", "description", "code")
        ):
            continue
        return f"Review {key} contains an empty or malformed issue."
    if explicit:
        # Normalized legacy results retain their declared weaker input format.
        # They remain FAIL when blocked and cannot acquire a fabricated PASS.
        normalized_legacy = (payload.get("schema_version") == "autobuild.review.v2"
                             and payload.get("source_format") in {"json_legacy", "text_legacy"})
        seen_ids = set()
        for item in issues:
            if not isinstance(item, dict):
                return "Structured blocking issues must be objects tied to the contract."
            if set(item) - {"id", "type", "summary", "requirement", "acceptance_criterion", "references", "fix_suggestion"}:
                return "Structured blocking issue contains unknown fields."
            for key in ("summary", "requirement", "acceptance_criterion"):
                if normalized_legacy and key != "summary":
                    continue
                if not isinstance(item.get(key), str) or not item[key].strip():
                    return f"Structured blocking issue requires non-empty {key}."
            if "type" in item and (not isinstance(item["type"], str) or item["type"] not in _REVIEW_BLOCKING_TYPES):
                return "Unknown blocking issue type."
            if "id" in item:
                identifier = item["id"]
                if not isinstance(identifier, str) or not identifier.strip() or identifier.strip() in seen_ids:
                    return "Blocking issue IDs must be non-empty and unique."
                seen_ids.add(identifier.strip())
            if "references" in item and (not isinstance(item["references"], list) or any(
                    not isinstance(ref, str) or not ref.strip() for ref in item["references"])):
                return "Blocking issue references must be non-empty text entries."
            if "fix_suggestion" in item and not isinstance(item["fix_suggestion"], str):
                return "Blocking issue fix_suggestion must be text."
        observations = payload.get("non_blocking_observations", [])
        if not isinstance(observations, list):
            return "Review non_blocking_observations must be a list."
        for item in observations:
            if not isinstance(item, dict) or not isinstance(item.get("summary"), str) or not item["summary"].strip():
                return "Review observation requires a non-empty summary."
            if set(item) - {"summary", "references", "suggestion"}:
                return "Review observation contains unknown fields."
            if "references" in item and (not isinstance(item["references"], list) or any(
                    not isinstance(ref, str) or not ref.strip() for ref in item["references"])):
                return "Review observation references must be non-empty text entries."
            if "suggestion" in item and not isinstance(item["suggestion"], str):
                return "Review observation suggestion must be text."
        if "breakdown_recommended" in payload and type(payload["breakdown_recommended"]) is not bool:
            return "Review breakdown_recommended must be a boolean."
        if (verdict == "PASS" and issues) or (verdict == "FAIL" and not issues):
            return "Review verdict contradicts its blocking_issues."
        if verdict == "PASS" and payload.get("breakdown_recommended") is True:
            return "A PASS review cannot require a breakdown."
        if payload.get("breakdown_recommended") is False and any(
                item.get("type") == "decomposition_needed" for item in issues):
            return "Decomposition issue contradicts breakdown_recommended=false."
    elif (verdict == "PASS" and issues) or (verdict == "FAIL" and not issues):
        return "Legacy review verdict contradicts its issues."
    reason = payload.get("breakdown_reason")
    if reason is not None:
        if not isinstance(reason, str) or not reason.strip():
            return "Review breakdown_reason must be non-empty text or null."
        if verdict == "PASS" or payload.get("breakdown_recommended") is not True:
            return "Review breakdown_reason contradicts its verdict or recommendation."
    return confidence_protocol_error(payload)


def parse_review_classification(review_findings: str) -> Dict[str, Any]:
    """Normalize structured and legacy reviewer output.

    Only explicit blocking issues determine PASS/FAIL. Optional observations
    remain visible but never force an additional repair loop or breakdown.
    """

    if not isinstance(review_findings, str):
        return _invalid_review("Reviewer output must be text.")
    cleaned = review_findings.strip()
    if not cleaned:
        return _invalid_review("Reviewer returned no output.")
    if re.fullmatch(r"(?:blocking issues?|must fix|must be resolved|muss behoben werden|non-blocking observations?)\s*:?[ \t\r\n]*", cleaned, re.I):
        return _invalid_review("Reviewer returned only an unfilled section heading.")
    candidate = cleaned
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            return _invalid_review("Unterminated JSON review fence.")
        candidate = "\n".join(lines[1:-1]).strip()
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate review key: {key}")
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    try:
        payload = json.loads(candidate, object_pairs_hook=unique_keys, parse_constant=nonfinite)
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        if candidate.startswith(("{", "[", '"')) or cleaned.startswith("```") or candidate in {"NaN", "Infinity", "-Infinity"}:
            return _invalid_review(f"Malformed JSON review: {exc}")
        payload = None
    else:
        if not isinstance(payload, dict):
            return _invalid_review("Review JSON must be an object.")
    if payload is not None:
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError, RecursionError):
            return _invalid_review("Review contains invalid Unicode or non-finite JSON data.")
        protocol_error = _review_protocol_error(payload)
        if protocol_error:
            return _invalid_review(protocol_error)
    elif cleaned.startswith(("{", "[", "```")) or cleaned.lower() in {"null", "true", "false"}:
        return _invalid_review("Reviewer returned malformed JSON or a non-object JSON value.")
    explicit_contract = False
    blocking: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    raw_breakdown: Any = False
    breakdown_reason: Optional[str] = None
    short_summary = ""

    if isinstance(payload, dict):
        explicit_contract = (
            "blocking_issues" in payload
            or "non_blocking_observations" in payload
            or "breakdown_recommended" in payload
        )
        short_raw = payload.get("short_summary")
        if isinstance(short_raw, (str, int, float)):
            short_summary = str(short_raw).strip()

        blocking_raw = payload.get("blocking_issues")
        if isinstance(blocking_raw, list):
            blocking = [
                _normalize_blocking_review_issue(item, index)
                for index, item in enumerate(blocking_raw, start=1)
            ]

        observations_raw = payload.get("non_blocking_observations")
        if isinstance(observations_raw, list):
            observations = [
                _normalize_non_blocking_observation(item)
                for item in observations_raw
            ]

        # Backward-compatible JSON: old reviewers used verdict + issues.
        if not explicit_contract:
            verdict_raw = payload.get("verdict")
            verdict = (
                str(verdict_raw).strip().upper()
                if isinstance(verdict_raw, (str, int, float))
                else ""
            )
            issues_raw = payload.get("issues")
            if isinstance(issues_raw, list):
                if verdict == "FAIL":
                    blocking = [
                        _normalize_blocking_review_issue(item, index)
                        for index, item in enumerate(issues_raw, start=1)
                    ]
                else:
                    observations = [
                        _normalize_non_blocking_observation(item)
                        for item in issues_raw
                    ]
            if verdict == "FAIL" and not blocking:
                blocking = [
                    _normalize_blocking_review_issue(
                        short_summary or "Legacy reviewer returned FAIL.", 1
                    )
                ]

        raw_breakdown = payload.get("breakdown_recommended", False)
        breakdown_raw_reason = payload.get("breakdown_reason")
        if isinstance(breakdown_raw_reason, (str, int, float)):
            breakdown_reason = str(breakdown_raw_reason).strip() or None

    if payload is None:
        normalized = cleaned.lstrip("-•* ").lower()
        normalized_plain = normalized.replace("**", "").replace("__", "")
        no_issue_prefixes = (
            "no issues",
            "no_issues",
            "keine abweichungen",
            "keine probleme",
            "keine beanstandungen",
            "keine mängel",
            "keine maengel",
        )
        explicit_blocking_lines, explicit_no_blocking = _legacy_blocking_lines(cleaned)
        if explicit_blocking_lines:
            blocking = [
                _normalize_blocking_review_issue(line, index)
                for index, line in enumerate(explicit_blocking_lines, start=1)
            ]
        elif normalized.startswith(no_issue_prefixes) or explicit_no_blocking:
            short_summary = cleaned
        else:
            non_blocking_markers = (
                "muss nicht behoben werden",
                "non-blocking",
                "nicht zwingend",
            )
            only_non_blocking = any(
                marker in normalized_plain for marker in non_blocking_markers
            )
            if only_non_blocking:
                observations = [_normalize_non_blocking_observation(cleaned)]
            else:
                # Unknown legacy prose is treated conservatively as blocking.
                blocking = [_normalize_blocking_review_issue(cleaned, 1)]
        short_summary = short_summary or cleaned[:500]

    breakdown_recommended = _coerce_review_bool(raw_breakdown) or any(
        issue.get("type") == "decomposition_needed" for issue in blocking
    )
    if breakdown_recommended and not breakdown_reason:
        breakdown_reason = "Reviewer identified genuinely independent remaining workstreams."

    verdict = "FAIL" if blocking else "PASS"
    if not short_summary:
        short_summary = (
            f"{len(blocking)} blocking issue(s)."
            if blocking
            else "No blocking issues remain."
        )
    return {
        "schema_version": "autobuild.review.v2",
        "valid": True,
        # Normalized legacy reviews use explicit fields but retain their validated input format.
        "source_format": (
            payload.get("source_format", "structured" if explicit_contract else "json_legacy")
            if payload is not None else "text_legacy"
        ),
        "verdict": verdict,
        "short_summary": short_summary,
        "blocking_issues": blocking,
        "non_blocking_observations": observations,
        "breakdown_recommended": breakdown_recommended,
        "breakdown_reason": breakdown_reason,
        **normalize_review_confidence(payload),
    }


def review_classification_passes(classification: Any) -> bool:
    """Return true only when a normalized review has no blocking issues.

    This small public helper lets orchestration layers distinguish the
    successful execution of a review *task* from a PASS verdict about the
    artifact being reviewed.
    """

    if not isinstance(classification, dict):
        return False
    try:
        classification = parse_review_classification(json.dumps(classification, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return False
    issues = classification.get("blocking_issues")
    return (
        classification.get("valid") is True
        and classification.get("verdict") == "PASS"
        and isinstance(issues, list) and len(issues) == 0
    )


def review_requires_runner_handling(classification: Any) -> bool:
    """Return true when another local fix loop would be the wrong response."""

    if not isinstance(classification, dict):
        return False
    issues_raw = classification.get("blocking_issues")
    if not isinstance(issues_raw, list):
        return False
    issue_types = {
        str(item.get("type") or "local_fix").strip().lower()
        for item in issues_raw
        if isinstance(item, dict)
    }
    return bool(
        issue_types
        & {
            "decomposition_needed",
            "missing_input",
            "scope_conflict",
            "technical_failure",
            "blocked_external",
        }
    )


def _format_blocking_review_issues(review_findings: str, *, prompt_config: PromptConfig | None = None) -> Optional[str]:
    prompts = load_prompt_config(prompt_config)
    classification = parse_review_classification(review_findings)
    issues = classification.get("blocking_issues")
    if not isinstance(issues, list) or not issues:
        return None
    lines: List[str] = []
    for index, issue in enumerate(issues, start=1):
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id") or f"ISSUE-{index}").strip()
        issue_type = str(issue.get("type") or "local_fix").strip()
        summary = str(issue.get("summary") or prompts.render("issue_missing_summary")).strip()
        requirement = str(issue.get("requirement") or "").strip()
        criterion = str(issue.get("acceptance_criterion") or "").strip()
        refs = _normalize_review_references(issue.get("references"))
        suggestion = str(issue.get("fix_suggestion") or "").strip()
        lines.append(f"{index}. [{issue_id}] ({issue_type}) {summary}")
        if requirement:
            lines.append(prompts.render("fix_issue_requirement", value=requirement))
        if criterion:
            lines.append(prompts.render("fix_issue_criterion", value=criterion))
        if refs:
            lines.append(prompts.render("fix_issue_references", value=", ".join(refs)))
        if suggestion:
            lines.append(prompts.render("fix_issue_suggestion", value=suggestion))
    return "\n".join(lines) if lines else None


def __getattr__(name: str):
    if name == "DEFAULT_CONTRACT_REVIEW_POLICY_RULES":
        return tuple(load_prompt_config().render("review_policy_rules").splitlines())
    raise AttributeError(name)
