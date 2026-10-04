# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Review prompt/parser alignment; no model, provider or OS-sandbox claims."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import autobuild
import run_todos
from review_contract import (
    build_review_prompt, parse_review_classification, review_classification_passes,
    review_instructions,
)

PASS = {
    "verdict": "PASS", "short_summary": "The requested artifact was checked.",
    "blocking_issues": [], "non_blocking_observations": [],
    "breakdown_recommended": False, "breakdown_reason": None,
}
BLOCKER = {
    "id": "ISSUE-1", "type": "local_fix", "summary": "The output is missing.",
    "requirement": "Create the requested output.",
    "acceptance_criterion": "The requested output exists.",
    "references": [], "fix_suggestion": "Create the output.",
}


def review(**changes):
    return {**deepcopy(PASS), **changes}


def parse(payload):
    return parse_review_classification(json.dumps(payload))


class ReviewInstructionTests(unittest.TestCase):
    def assert_breakdown_rules(self, prompt):
        for rule in (
            "If verdict is PASS, set breakdown_recommended=false and breakdown_reason=null.",
            "If breakdown_recommended=false, set breakdown_reason=null, including for a FAIL verdict.",
            "A non-empty breakdown_reason is allowed only when verdict is FAIL and breakdown_recommended=true.",
            'Use JSON null, never an empty string, whitespace-only string, or the string "null".',
            "Explain why no breakdown is needed in short_summary or non_blocking_observations, not in breakdown_reason.",
            "Do not change the verdict, discard blockers, or recommend unnecessary breakdown just to satisfy these field constraints.",
        ):
            self.assertIn(rule, prompt)

    def test_shared_instructions_describe_parser_field_dependencies(self):
        self.assert_breakdown_rules(review_instructions())

    def test_profile_rules_are_additive_and_do_not_hide_format_rules(self):
        for rules in (None, [], ["Check the supplied units."]):
            with self.subTest(rules=rules):
                prompt = review_instructions(rules)
                self.assert_breakdown_rules(prompt)
                self.assertIn("An error or contradiction in an input", prompt)
                if rules:
                    self.assertIn(rules[0], prompt)

    def test_task_review_builder_contains_same_rules(self):
        self.assert_breakdown_rules(build_review_prompt("Original task", "Latest answer"))

    def test_autobuild_review_builder_contains_same_rules(self):
        prompt = autobuild._build_global_review_prompt(
            original_task="Original task", latest_answer="Latest answer",
            review_policy_rules=["Check the supplied units."],
        )
        self.assert_breakdown_rules(prompt)

    def test_parent_review_dispatch_contains_rules_and_remains_read_only(self):
        # Exercise the real parent-review prompt path; only execution is simulated.
        runner = object.__new__(run_todos.TodoRunner)
        runner.todo_file = Path("tasks.md")
        runner.runtime_profile_scope_active = False
        runner.runtime_profile_active = False
        runner._path_for_prompt = str
        runner._augment_task_prompt = lambda prompt: prompt
        runner._run_autobuild = Mock(return_value=SimpleNamespace(
            message=json.dumps(PASS), completed=True, execution_error=None,
            abort=False, process_stop_triggered=False,
        ))
        with redirect_stdout(io.StringIO()):
            outcome = runner._run_parent_review("1", (Path("result.md"), "result.md"))
        self.assertTrue(outcome.passed)
        call = runner._run_autobuild.call_args
        self.assert_breakdown_rules(call.args[1])
        self.assertEqual(call.kwargs["sandbox_override"], "read-only")

    def test_prompt_pass_example_is_valid_json_and_accepted_by_real_parser(self):
        prompt = review_instructions()
        marker = "Example of a valid PASS response (illustrative only; verify the actual task before choosing a verdict):\n"
        self.assertIn(marker, prompt)
        example, end = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])
        self.assertEqual(set(example), set(PASS))
        self.assertIsNone(example["breakdown_reason"])
        self.assertFalse(example["breakdown_recommended"])
        self.assertTrue(review_classification_passes(parse(example)))

    def test_documented_full_example_is_accepted(self):
        document = (ROOT / "documents/REVIEW_CORE.md").read_text(encoding="utf-8")
        examples = re.findall(r"```json\n(.*?)\n```", document, re.S)
        self.assertTrue(examples)
        for example in examples:
            with self.subTest(example=example):
                self.assertTrue(parse_review_classification(example)["valid"])
        self.assertIn("A non-empty `breakdown_reason` is allowed only", document)


class ReviewValidationRegressionTests(unittest.TestCase):
    def test_reported_pass_with_no_breakdown_explanation_remains_invalid(self):
        # Synthetic equivalent of the reported failure, not a private run log.
        value = review(breakdown_reason="The task is complete; no breakdown is needed.")
        parsed = parse(value)
        self.assertFalse(parsed["valid"])
        self.assertIn("Review breakdown_reason contradicts", parsed["short_summary"])
        self.assertFalse(review_classification_passes(parsed))

    def test_null_reason_accepts_same_findings_without_discarding_observations(self):
        observation = {"summary": "An optional wording improvement.",
                       "references": ["result.md:1"], "suggestion": "Optional only."}
        value = review(non_blocking_observations=[observation])
        before = deepcopy(value)
        parsed = parse(value)
        self.assertTrue(review_classification_passes(parsed))
        self.assertEqual(parsed["non_blocking_observations"], [observation])
        self.assertEqual(parsed["short_summary"], value["short_summary"])
        self.assertIsNone(parsed["breakdown_reason"])
        self.assertEqual(value, before)

    def test_valid_fail_without_breakdown_keeps_its_blocker(self):
        parsed = parse(review(verdict="FAIL", blocking_issues=[deepcopy(BLOCKER)]))
        self.assertTrue(parsed["valid"])
        self.assertFalse(review_classification_passes(parsed))
        self.assertEqual(parsed["blocking_issues"], [BLOCKER])
        self.assertIsNone(parsed["breakdown_reason"])

    def test_valid_fail_with_breakdown_keeps_its_reason(self):
        blocker = {**BLOCKER, "type": "decomposition_needed"}
        reason = "Two independent required outputs remain."
        parsed = parse(review(verdict="FAIL", blocking_issues=[blocker],
                              breakdown_recommended=True, breakdown_reason=reason))
        self.assertTrue(parsed["valid"])
        self.assertFalse(review_classification_passes(parsed))
        self.assertEqual(parsed["breakdown_reason"], reason)

    def test_no_breakdown_accepts_only_null_or_omitted_reason(self):
        for verdict in ("PASS", "FAIL"):
            base = review(verdict=verdict,
                          blocking_issues=[] if verdict == "PASS" else [deepcopy(BLOCKER)])
            for reason in ("No work remains.", "", " ", "null", False, 0, [], {}):
                with self.subTest(verdict=verdict, reason=reason):
                    self.assertFalse(parse({**base, "breakdown_reason": reason})["valid"])
            self.assertTrue(parse(base)["valid"])
            del base["breakdown_reason"]
            self.assertTrue(parse(base)["valid"])

    def test_contradictory_verdict_and_breakdown_are_not_repaired_to_pass(self):
        cases = (
            review(breakdown_recommended=True),
            review(blocking_issues=[deepcopy(BLOCKER)]),
            review(verdict="FAIL"),
            review(verdict="FAIL", blocking_issues=[deepcopy(BLOCKER)],
                   breakdown_reason="A reason without a recommendation."),
            review(verdict="FAIL", blocking_issues=[{**BLOCKER, "type": "decomposition_needed"}]),
        )
        for value in cases:
            with self.subTest(value=value):
                parsed = parse(value)
                self.assertFalse(parsed["valid"])
                self.assertFalse(review_classification_passes(parsed))

    def test_invalid_review_never_becomes_finished_in_autobuild(self):
        value = review(breakdown_reason="The task is complete; no breakdown is needed.")
        decision = autobuild.evaluate_completion_decision("Task", "Answer", json.dumps(value))
        self.assertFalse(decision.is_finished)

    def test_legacy_verdict_and_issues_still_work(self):
        for verdict, issues in (("PASS", []), ("FAIL", ["Missing required output."])):
            with self.subTest(verdict=verdict):
                parsed = parse({"verdict": verdict, "issues": issues})
                self.assertTrue(parsed["valid"])
                self.assertEqual(parsed["verdict"], verdict)
                self.assertEqual(parsed["source_format"], "json_legacy")


if __name__ == "__main__":
    unittest.main()
