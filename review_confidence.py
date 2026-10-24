# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Uncalibrated review-confidence metadata and an offline summary reader.

Confidence is advisory: it cannot change PASS/FAIL, authorize execution, or
replace evidence. Pure validation/normalization helpers do not perform I/O.
"""
from __future__ import annotations

from prompt_config import PromptConfig, PromptConfigError, load_prompt_config

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

CONFIDENCE_DIMENSIONS = (
    "requirements_coverage", "implementation_correctness", "test_evidence",
    "regression_safety",
)
CONFIDENCE_FIELDS = frozenset({
    "confidence", "confidence_level", "confidence_reason", "confidence_breakdown",
    "evidence", "uncertainties", "suggested_checks",
})
MAX_ITEMS = 64
MAX_TEXT = 2000
MAX_REPORT_BYTES = 8 * 1024 * 1024


def _score(value: Any) -> bool:
    # bool is an int subclass; strings, booleans and non-finite numbers are not scores.
    return value is None or (
        type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)
    )


def confidence_level(score: float | None) -> str:
    """Display bands, NOT acceptance thresholds or calibrated probabilities."""
    if not _score(score):
        raise ValueError("Confidence must be a finite number in [0, 1] or null.")
    if score is None:
        return "unknown"
    return "high" if score >= 0.9 else "medium" if score >= 0.7 else "low"


def confidence_protocol_error(payload: dict[str, Any]) -> str | None:
    """Validate optional metadata without relaxing the independent review contract."""
    score = payload.get("confidence")
    if not _score(score):
        return "Review confidence must be a finite number in [0, 1] or null."
    if "confidence_level" in payload and payload["confidence_level"] != confidence_level(score):
        return "Review confidence_level contradicts its confidence score."
    reason = payload.get("confidence_reason")
    if reason is not None and (
        not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_TEXT
    ):
        return f"Review confidence_reason must be non-empty text (max {MAX_TEXT}) or null."
    if score is not None and reason is None:
        return "A numeric review confidence requires confidence_reason."
    breakdown = payload.get("confidence_breakdown")
    if breakdown is not None:
        if not isinstance(breakdown, dict) or set(breakdown) - set(CONFIDENCE_DIMENSIONS):
            return "Review confidence_breakdown contains unknown dimensions or is not an object."
        if any(not _score(value) for value in breakdown.values()):
            return "Review confidence dimensions must be finite numbers in [0, 1] or null."
    for name in ("evidence", "uncertainties", "suggested_checks"):
        values = payload.get(name, [])
        if not isinstance(values, list) or len(values) > MAX_ITEMS or any(
            not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT
            for value in values
        ):
            return f"Review {name} must contain at most {MAX_ITEMS} non-empty strings (max {MAX_TEXT} each)."
    if score is not None and not payload.get("evidence"):
        return "A numeric review confidence requires explicit reviewer-reported evidence."
    return None


def normalize_review_confidence(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return fresh, idempotent metadata; historical missing scores stay unknown."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Review confidence metadata must belong to an object.")
    error = confidence_protocol_error(payload)
    if error:
        raise ValueError(error)
    score = payload.get("confidence")
    reason = payload.get("confidence_reason")
    breakdown = payload.get("confidence_breakdown") or {}
    return {
        "confidence": float(score) if score is not None else None,
        "confidence_level": confidence_level(score),
        "confidence_reason": reason.strip() if reason is not None else None,
        "confidence_breakdown": {
            name: float(breakdown[name]) if breakdown.get(name) is not None else None
            for name in CONFIDENCE_DIMENSIONS
        },
        **{name: [value.strip() for value in payload.get(name, [])]
           for name in ("evidence", "uncertainties", "suggested_checks")},
    }


def confidence_prompt_fields(*, prompt_config: PromptConfig | None = None) -> str:
    """Fragment inserted into the shared task/parent JSON grammar."""
    prompts = load_prompt_config(prompt_config)
    return (
        prompts.render('confidence_fields')
    )


def confidence_prompt_rules(*, prompt_config: PromptConfig | None = None) -> str:
    prompts = load_prompt_config(prompt_config)
    return (
        prompts.render('confidence_rules', max_text=MAX_TEXT, max_items=MAX_ITEMS)
    )


def format_review_confidence(classification: dict[str, Any]) -> str:
    """Render a validated review, escaping untrusted strings for terminal display."""
    # Local import keeps the validation helpers usable by review_contract itself.
    from review_contract import validate_review_classification
    review = validate_review_classification(classification)
    if not review["valid"]:
        raise ValueError(review["short_summary"])
    score = review["confidence"]
    shown = "not reported" if score is None else f"{score:g}; uncalibrated reviewer estimate"
    lines = [f"{review['verdict']} | confidence {review['confidence_level']} ({shown})"]
    if review["confidence_reason"]:
        lines.append("Reason: " + json.dumps(review["confidence_reason"], ensure_ascii=True))
    for name in CONFIDENCE_DIMENSIONS:
        value = review["confidence_breakdown"][name]
        lines.append(f"  {name}: " + ("unknown / not applicable" if value is None else f"{value:g}"))
    for name, label in (("evidence", "Evidence (reviewer-reported)"),
                        ("uncertainties", "Uncertainties"), ("suggested_checks", "Suggested checks (not executed)")):
        if review[name]:
            lines.append(label + ":")
            lines.extend("  - " + json.dumps(value, ensure_ascii=True) for value in review[name])
    lines.append("Advisory only: confidence does not change task acceptance.")
    return "\n".join(lines)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("summary", type=Path, help="AutoBuild summary JSON or a structured review JSON file")
    args = parser.parse_args(argv)
    try:
        with args.summary.open("rb") as handle:
            raw = handle.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("Summary exceeds the 8 MiB report limit.")
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys, parse_constant=_nonfinite)
        if not isinstance(payload, dict):
            raise ValueError("Summary/review must be a JSON object.")
        review = payload.get("review_classification", payload)
        if not isinstance(review, dict):
            raise ValueError("No structured review_classification is available.")
        print(format_review_confidence(review))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        print("Cannot read review confidence: " + json.dumps(str(exc), ensure_ascii=True), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
