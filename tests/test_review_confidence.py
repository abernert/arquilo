# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline confidence contracts; simulated reviews do not establish calibration."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import autobuild
from autobuild_contract import AutoBuildResultError, validate_result
import run_todos
import review_confidence as confidence
from review_contract import (
    build_fix_prompt, build_review_prompt, parse_review_classification,
    review_classification_passes, review_instructions,
)

PASS = {
    "verdict": "PASS", "short_summary": "The requested artifact was inspected.",
    "blocking_issues": [], "non_blocking_observations": [],
    "breakdown_recommended": False, "breakdown_reason": None,
}
BLOCKER = {
    "id": "ISSUE-1", "type": "local_fix", "summary": "Required output is missing.",
    "requirement": "Create the output.", "acceptance_criterion": "The output exists.",
    "references": [], "fix_suggestion": "Create the output.",
}
DETAILS = {
    "confidence": 0.91,
    "confidence_reason": "The output and relevant tests were inspected; Windows was not exercised.",
    "confidence_breakdown": {
        "requirements_coverage": 0.95, "implementation_correctness": 0.9,
        "test_evidence": 0.85, "regression_safety": None,
    },
    "evidence": ["result.md:1-12 matches the requested sections.", "Observed 3/3 focused tests passing."],
    "uncertainties": ["Native Windows execution was not checked."],
    "suggested_checks": ["Run the focused tests on Windows."],
}


def review(**changes):
    return {**deepcopy(PASS), **deepcopy(DETAILS), **changes}


def parse(value):
    return parse_review_classification(json.dumps(value))


class ConfidenceContractTests(unittest.TestCase):
    def test_complete_metadata_roundtrips_without_mutating_input(self):
        value = review()
        before = deepcopy(value)
        normalized = parse(value)
        self.assertTrue(normalized["valid"])
        self.assertEqual(normalized["confidence_level"], "high")
        for name, detail in DETAILS.items():
            self.assertEqual(normalized[name], detail)
        self.assertEqual(parse(normalized), normalized)
        self.assertEqual(value, before)

    def test_legacy_reviews_are_unknown_not_zero_or_high(self):
        for value in (PASS, {"verdict": "PASS", "issues": []}, {"verdict": "FAIL", "issues": ["Missing output."]}):
            with self.subTest(value=value):
                result = parse(value)
                self.assertTrue(result["valid"])
                self.assertIsNone(result["confidence"])
                self.assertEqual(result["confidence_level"], "unknown")
                self.assertEqual(result["evidence"], [])
                self.assertTrue(all(v is None for v in result["confidence_breakdown"].values()))
                self.assertEqual(parse(result), result)
        result = parse_review_classification("No issues; confidence 99%.")
        self.assertEqual(result["source_format"], "text_legacy")
        self.assertIsNone(result["confidence"])

    def test_display_band_boundaries_are_not_acceptance_thresholds(self):
        for score, band in ((0, "low"), (0.6999, "low"), (0.7, "medium"),
                            (0.8999, "medium"), (0.9, "high"), (1, "high"), (None, "unknown")):
            with self.subTest(score=score):
                result = parse(review(confidence=score))
                self.assertTrue(review_classification_passes(result))
                self.assertEqual(result["confidence_level"], band)

    def test_invalid_score_types_and_ranges_fail_closed(self):
        for value in (True, False, "0.91", -0.001, 1.001, float("nan"), float("inf"),
                      float("-inf"), [], {}, 10 ** 200):
            with self.subTest(value=value):
                result = parse(review(confidence=value))
                self.assertFalse(result["valid"])
                self.assertFalse(review_classification_passes(result))
                self.assertIsNone(result["confidence"])

    def test_numeric_score_requires_reason_and_evidence(self):
        for name, value in (("confidence_reason", None), ("confidence_reason", ""),
                            ("confidence_reason", " "), ("confidence_reason", 5), ("evidence", [])):
            with self.subTest(name=name, value=value):
                self.assertFalse(parse(review(**{name: value}))["valid"])
        for name in ("confidence_reason", "evidence"):
            value = review()
            del value[name]
            self.assertFalse(parse(value)["valid"])

    def test_unknown_or_inapplicable_scores_are_allowed(self):
        result = parse({**PASS, "confidence": None, "confidence_breakdown": None})
        self.assertTrue(result["valid"])
        self.assertEqual(result["confidence_level"], "unknown")
        result = parse(review(confidence_breakdown={"requirements_coverage": 0.8}))
        self.assertTrue(result["valid"])
        self.assertIsNone(result["confidence_breakdown"]["test_evidence"])
        self.assertIsNone(result["confidence_breakdown"]["regression_safety"])

    def test_breakdown_types_and_unknown_dimensions_are_rejected(self):
        for value in ([], "high", {"regression_risk": 0.9}, {"test_evidence": True},
                      {"test_evidence": "0.9"}, {"test_evidence": 1.01}, {"test_evidence": float("nan")}):
            with self.subTest(value=value):
                self.assertFalse(parse(review(confidence_breakdown=value))["valid"])

    def test_level_is_derived_and_cannot_be_forged(self):
        self.assertTrue(parse(review(confidence_level="high"))["valid"])
        for value in ("low", "very_high", 1, None, True):
            self.assertFalse(parse(review(confidence_level=value))["valid"])
        self.assertFalse(parse(review(confidence=None, confidence_level="high"))["valid"])

    def test_lists_are_bounded_nonempty_strings(self):
        for name in ("evidence", "uncertainties", "suggested_checks"):
            for value in (None, "text", {}, [""], [" "], [0], [False], [{"text": "x"}],
                          ["x"] * 65, ["x" * 2001]):
                with self.subTest(name=name, value=str(value)[:50]):
                    self.assertFalse(parse(review(**{name: value}))["valid"])
            self.assertTrue(parse(review(**{name: ["x"] * 64}))["valid"])
        self.assertFalse(parse(review(confidence_reason="x" * 2001))["valid"])

    def test_normalized_lists_are_fresh_and_whitespace_is_trimmed(self):
        value = review(evidence=[" file:1 "], confidence_reason=" inspected ")
        result = parse(value)
        self.assertEqual(result["evidence"], ["file:1"])
        self.assertEqual(result["confidence_reason"], "inspected")
        result["evidence"].append("new")
        self.assertEqual(value["evidence"], [" file:1 "])
        a = confidence.normalize_review_confidence()
        a["evidence"].append("not shared")
        self.assertEqual(confidence.normalize_review_confidence()["evidence"], [])

    def test_duplicate_unknown_and_contradictory_fields_stay_invalid(self):
        raw = json.dumps(review())
        self.assertFalse(parse_review_classification(raw[:-1] + ', "confidence": 0.1}')["valid"])
        raw = raw.replace('"test_evidence": 0.85', '"test_evidence": 0.85, "test_evidence": 0.9')
        self.assertFalse(parse_review_classification(raw)["valid"])
        for value in (review(unrecognized=True), review(blocking_issues=[BLOCKER]),
                      review(verdict="FAIL"), review(breakdown_reason="No breakdown needed."),
                      review(breakdown_recommended=True)):
            self.assertFalse(parse(value)["valid"])

    def test_a_certain_fail_never_becomes_pass(self):
        result = parse(review(verdict="FAIL", blocking_issues=[BLOCKER], confidence=1,
                              confidence_breakdown={"implementation_correctness": 0.05}))
        self.assertTrue(result["valid"])
        self.assertEqual(result["confidence_level"], "high")
        self.assertFalse(review_classification_passes(result))
        self.assertEqual(result["blocking_issues"], [BLOCKER])

    def test_invalid_or_missing_review_never_keeps_a_score(self):
        for text in ("", "{}", json.dumps(review(blocking_issues=[BLOCKER]))):
            result = parse_review_classification(text)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["confidence"])
            self.assertEqual(result["confidence_level"], "unknown")

    def test_standalone_helpers_reject_invalid_inputs(self):
        for value in (True, -1, 2, "high", float("nan")):
            with self.assertRaises(ValueError):
                confidence.confidence_level(value)
        for value in ([], {"confidence": 0.8}):
            with self.assertRaises(ValueError):
                confidence.normalize_review_confidence(value)


class ConfidenceIntegrationTests(unittest.TestCase):
    def test_shared_task_and_parent_prompts_request_confidence_without_new_authority(self):
        prompts = [review_instructions(), review_instructions(["Check the supplied units."]),
                   build_review_prompt("Task", "Answer"), autobuild._build_global_review_prompt(
                       original_task="Task", latest_answer="Answer")]
        for prompt in prompts:
            for text in ('"confidence"', '"evidence"', '"uncertainties"', '"suggested_checks"',
                         "uncalibrated", "not new requirements or execution authority",
                         "Never hide a concrete unmet acceptance criterion", "Use null for unknown"):
                self.assertIn(text, prompt)

    def test_prompt_example_matches_extended_grammar(self):
        marker = "Example of a valid PASS response (illustrative only; verify the actual task before choosing a verdict):\n"
        example, _ = json.JSONDecoder().raw_decode(review_instructions().split(marker)[1])
        self.assertEqual(set(example), set(PASS) | (confidence.CONFIDENCE_FIELDS - {"confidence_level"}))
        self.assertTrue(parse(example)["valid"])
        self.assertIsNone(example["confidence"])

    def test_completion_decision_remains_verdict_driven_without_extra_calls(self):
        for score in (0.1, 0.8, 0.99, None):
            for verdict in ("PASS", "FAIL"):
                with self.subTest(score=score, verdict=verdict):
                    payload = review(confidence=score, verdict=verdict,
                                     blocking_issues=[] if verdict == "PASS" else [BLOCKER])
                    decision = autobuild.evaluate_completion_decision("Task", "Answer", json.dumps(payload))
                    self.assertEqual(decision.is_finished, verdict == "PASS")
                    self.assertEqual(decision.source, "review_contract")

    def test_follow_up_suggestions_do_not_enter_correction_requirements(self):
        value = review(verdict="FAIL", blocking_issues=[BLOCKER], suggested_checks=["OPTIONAL_CHECK_SENTINEL"])
        prompt = build_fix_prompt("Task", json.dumps(value), "Fix the confirmed blocker.")
        self.assertIn(BLOCKER["requirement"], prompt)
        self.assertNotIn("OPTIONAL_CHECK_SENTINEL", prompt)

    def test_parent_review_keeps_subject_confidence_separate_from_audit_success(self):
        for verdict, score in (("PASS", 0.4), ("FAIL", 0.99)):
            runner = object.__new__(run_todos.TodoRunner)
            runner.todo_file = Path("tasks.md")
            runner.runtime_profile_scope_active = False
            runner.runtime_profile_active = False
            runner._path_for_prompt = str
            runner._augment_task_prompt = lambda prompt: prompt
            payload = review(verdict=verdict, confidence=score,
                             blocking_issues=[] if verdict == "PASS" else [BLOCKER])
            runner._run_autobuild = Mock(return_value=SimpleNamespace(
                message=json.dumps(payload), completed=True, execution_error=None,
                abort=False, process_stop_triggered=False))
            with redirect_stdout(io.StringIO()):
                outcome = runner._run_parent_review("1", (Path("result.md"), "result.md"))
            self.assertEqual(outcome.passed, verdict == "PASS")
            self.assertEqual(outcome.classification["confidence"], score)
            self.assertEqual(outcome.classification["uncertainties"], DETAILS["uncertainties"])
            self.assertEqual(runner._run_autobuild.call_args.kwargs["sandbox_override"], "read-only")
            self.assertIn('"confidence"', runner._run_autobuild.call_args.args[1])

    def test_summary_serialization_worker_validation_and_runner_keep_metadata(self):
        classification = parse(review())
        summary = autobuild.AutoBuildSummary(
            last_answer="The requested output is present.", completed=True,
            auftrag_runs=1, review_runs=1, workspace=Path("workspace"),
            pretty_log=Path("pretty.log"), raw_log=Path("raw.jsonl"),
            readonly_result_path=None, review_findings=json.dumps(review()),
            review_classification=classification)
        payload = autobuild.build_summary_document(summary)
        self.assertEqual(validate_result(payload)["review_classification"], classification)
        self.assertEqual(run_todos._normalize_review_classification_payload(classification), classification)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "summary.json"
            autobuild.write_summary_json(summary, target)
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["review_classification"], classification)
        payload["review_classification"] = {**classification, "confidence": True}
        with self.assertRaises(AutoBuildResultError):
            validate_result(payload)

    def test_documented_examples_and_runtime_package(self):
        document = (ROOT / "documents/REVIEW_CORE.md").read_text(encoding="utf-8")
        for text in re.findall(r"```json\n(.*?)\n```", document, re.S):
            self.assertTrue(parse_review_classification(text)["valid"])
        manifest = json.loads((ROOT / "documents/lean_package.json").read_text(encoding="utf-8"))
        self.assertIn("review_confidence.py", manifest["runtime_files"])
        self.assertNotIn("tests/test_review_confidence.py", manifest["runtime_files"])
        self.assertEqual(manifest["runtime_file_count"], len(manifest["runtime_files"]))


class ConfidenceReportTests(unittest.TestCase):
    def test_report_shows_labels_limits_and_non_executed_suggestions(self):
        text = confidence.format_review_confidence(review())
        for value in ("PASS | confidence high", "uncalibrated reviewer estimate",
                      "regression_safety: unknown / not applicable", "reviewer-reported",
                      "Native Windows", "Suggested checks (not executed)", "Advisory only"):
            self.assertIn(value, text)
        self.assertIn("confidence unknown", confidence.format_review_confidence(PASS))
        self.assertIn("FAIL | confidence high", confidence.format_review_confidence(
            review(verdict="FAIL", blocking_issues=[BLOCKER])))

    def test_untrusted_terminal_controls_are_escaped(self):
        text = confidence.format_review_confidence(review(evidence=["file:1\x1b[31m\nspoof"]))
        self.assertNotIn("\x1b", text)
        self.assertIn("\\u001b[31m\\nspoof", text)

    def test_cli_reads_summary_or_review_without_modifying_file(self):
        for payload in (review(), {"review_classification": parse(review())}, PASS):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "summary.json"
                content = json.dumps(payload).encode()
                path.write_bytes(content)
                output = io.StringIO()
                with redirect_stdout(output):
                    result = confidence.main([str(path)])
                self.assertEqual(result, 0)
                self.assertIn("PASS | confidence", output.getvalue())
                self.assertEqual(path.read_bytes(), content)

    def test_cli_rejects_invalid_missing_duplicate_and_oversized_data(self):
        cases = ("{}", "[]", '{"review_classification": null}',
                 '{"review_classification": {}, "review_classification": {}}',
                 '{"confidence": NaN}', '{"confidence": 1e999}', "broken",
                 json.dumps(review(confidence_level="low")))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "summary.json"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(confidence.main([str(path)]), 2)
            for text in cases:
                path.write_text(text, encoding="utf-8")
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(confidence.main([str(path)]), 2)
            path.write_bytes(b" " * (confidence.MAX_REPORT_BYTES + 1))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(confidence.main([str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
