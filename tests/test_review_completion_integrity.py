# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline completion gates with real controller persistence and synthetic models.

Model transports and semantic choices are explicit fakes. Artifact bytes, task
status, private journal, result validation and reload use the real runtime.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
import autobuild
from autobuild_contract import (
    AutoBuildContext, AutoBuildOptions, AutoBuildResultError, validate_result,
)
import codex_transport
from controller_state import PlanAuthority
from decision_exec import DecisionCall
import review_contract
import run_todos
from runtime_contracts import DecisionResult, ExecutionResult, ExecutionStatus


PASS = {
    "verdict": "PASS", "short_summary": "The requested bytes were inspected.",
    "blocking_issues": [], "non_blocking_observations": [],
    "breakdown_recommended": False, "breakdown_reason": None,
}
BLOCKER = {
    "id": "missing-output", "type": "local_fix", "summary": "proof.txt is missing.",
    "requirement": "Create proof.txt with bytes RIGHT.",
    "acceptance_criterion": "proof.txt contains exactly RIGHT.",
    "references": ["proof.txt"], "fix_suggestion": "Create the required file.",
}
FAIL = {**PASS, "verdict": "FAIL", "blocking_issues": [BLOCKER]}
LEGACY_FAIL = "Must fix: proof.txt is missing."
LEGACY_PASS = "No issues; the requested artifact was inspected."
PLAN = "***SYNTAX marked-en***\n1. ***Task***: Create proof.txt with bytes RIGHT.\n"
COMPLETE = {
    "selected_option": "COMPLETE", "source": "codex_exec",
    "explanation": "Synthetic choice.", "fallback_used": False, "error": None,
}


def semantic_choice(request, *, settings, option="COMPLETE"):
    return DecisionCall(result=DecisionResult(
        execution=ExecutionResult(status=ExecutionStatus.SUCCEEDED, answer=option,
                                  process_exit_code=0, completion_seen=True),
        options=request.options, option=option, explanation="Synthetic choice."),
        directory=None, attempt=None)


def model_answer(answer):
    return codex_transport.RunResult(assistant_messages=[answer],
                                    turn_completed=True, process_exit_code=0)


def completed_document(classification, *, decision=None):
    return autobuild.build_summary_document(autobuild.AutoBuildSummary(
        last_answer="Synthetic producer claims complete.", completed=True,
        auftrag_runs=1, review_runs=1, workspace=Path("workspace"),
        pretty_log=Path("pretty.log"), raw_log=Path("raw.jsonl"),
        readonly_result_path=None, review_classification=classification,
        decision=decision,
    ))


class ReviewCompletionContractTests(unittest.TestCase):
    def test_raw_json_cannot_select_legacy_provenance(self):
        for schema in ({}, {"schema_version": "autobuild.review.v2"}):
            for source in ("text_legacy", "json_legacy"):
                for review in (PASS, FAIL):
                    with self.subTest(schema=schema, source=source, verdict=review["verdict"]):
                        raw = json.dumps({**review, **schema, "source_format": source})
                        parsed = review_contract.parse_review_classification(raw)
                        self.assertTrue(parsed["valid"])
                        self.assertEqual(parsed["source_format"], "structured")
                        self.assertEqual(parsed["verdict"], review["verdict"])
                        self.assertEqual(parsed["blocking_issues"], review["blocking_issues"])

    def test_raw_json_cannot_relax_structured_blocker_requirements(self):
        for source in ("text_legacy", "json_legacy"):
            payload = {**FAIL, "schema_version": "autobuild.review.v2", "source_format": source,
                       "blocking_issues": [{"summary": "Missing output."}]}
            with self.subTest(source=source):
                self.assertFalse(review_contract.parse_review_classification(json.dumps(payload))["valid"])

    def test_stored_legacy_records_keep_provenance_and_blockers(self):
        for raw in (LEGACY_PASS, LEGACY_FAIL, '{"verdict":"PASS","issues":[]}',
                    '{"verdict":"FAIL","issues":["Missing output."]}'):
            with self.subTest(raw=raw):
                parsed = review_contract.parse_review_classification(raw)
                before = deepcopy(parsed)
                normalized = run_todos._normalize_review_classification_payload(parsed)
                self.assertEqual(normalized, before)
                self.assertEqual(parsed, before)
                self.assertEqual(review_contract.review_classification_passes(normalized),
                                 normalized["verdict"] == "PASS")

    def test_partial_normalized_metadata_cannot_remove_the_legacy_decision_gate(self):
        original = review_contract.parse_review_classification(LEGACY_PASS)
        for removed in (("schema_version",), ("source_format",),
                        ("schema_version", "source_format"), ("valid",)):
            classification = {key: value for key, value in original.items() if key not in removed}
            for decision in (None, COMPLETE):
                for exit_code in (None, 0):
                    with self.subTest(removed=removed, decision=decision, exit_code=exit_code):
                        payload = completed_document(classification, decision=decision)
                        with self.assertRaises(AutoBuildResultError):
                            validate_result(payload, process_exit_code=exit_code)
            with self.subTest(removed=removed):
                validated = review_contract.validate_review_classification(classification)
                self.assertFalse(validated["valid"])
                self.assertFalse(review_contract.review_classification_passes(classification))
                self.assertEqual(original["source_format"], "text_legacy")

    def test_unannotated_historical_review_dicts_still_normalize(self):
        for raw in (PASS, FAIL, {"verdict": "PASS", "issues": []},
                    {"verdict": "FAIL", "issues": ["Missing output."]}):
            with self.subTest(raw=raw):
                before = deepcopy(raw)
                normalized = review_contract.validate_review_classification(raw)
                self.assertTrue(normalized["valid"])
                self.assertEqual(normalized["verdict"], raw["verdict"])
                self.assertEqual(normalized["source_format"],
                                 "json_legacy" if "issues" in raw else "structured")
                self.assertEqual(raw, before)

    def test_fail_and_blockers_veto_semantic_complete_in_every_format(self):
        for raw in (LEGACY_FAIL, json.dumps(FAIL),
                    json.dumps({**FAIL, "source_format": "text_legacy"}),
                    '{"verdict":"FAIL","issues":["Missing output."]}'):
            with self.subTest(raw=raw), patch.object(
                    autobuild, "run_semantic_decision", side_effect=semantic_choice) as decide:
                result = autobuild.evaluate_completion_decision("Create proof.txt.", "Claimed complete.", raw)
                self.assertFalse(result.is_finished)
                self.assertEqual(result.selected_option, "INCOMPLETE")
                self.assertEqual(result.source, "review_contract")
                decide.assert_not_called()

    def test_no_blocker_legacy_prose_still_requires_a_successful_decision(self):
        for option in ("COMPLETE", "INCOMPLETE"):
            with self.subTest(option=option), patch.object(
                    autobuild, "run_semantic_decision",
                    side_effect=lambda request, settings: semantic_choice(
                        request, settings=settings, option=option)) as decide:
                result = autobuild.evaluate_completion_decision("Create proof.txt.", "Artifact ready.", LEGACY_PASS)
                self.assertEqual(result.is_finished, option == "COMPLETE")
                self.assertEqual(result.source, "codex_exec")
                decide.assert_called_once()

    def test_completed_summary_rejects_fail_and_blockers_despite_complete_decision(self):
        classifications = [review_contract.parse_review_classification(LEGACY_FAIL),
                           {**review_contract.parse_review_classification(json.dumps(FAIL)),
                            "source_format": "text_legacy"}]
        for classification in classifications:
            for exit_code in (None, 0):
                with self.subTest(classification=classification, exit_code=exit_code):
                    payload = completed_document(classification, decision=COMPLETE)
                    with self.assertRaises(AutoBuildResultError):
                        validate_result(payload, process_exit_code=exit_code)

    def test_present_raw_findings_cannot_contradict_a_completed_summary(self):
        classification = review_contract.parse_review_classification('{"verdict":"PASS","issues":[]}')
        for raw in (LEGACY_FAIL, json.dumps(FAIL),
                    '{"verdict":"FAIL","issues":["Required output is missing."]}',
                    '{"verdict":"PASS", broken JSON'):
            for decision in (None, COMPLETE):
                with self.subTest(raw=raw, decision=decision):
                    payload = completed_document(classification, decision=decision)
                    payload["review_findings"] = raw
                    with self.assertRaises(AutoBuildResultError):
                        validate_result(payload, process_exit_code=0)

    def test_raw_legacy_provenance_cannot_be_downgraded_by_normalized_metadata(self):
        for raw_json in (json.dumps(PASS), '{"verdict":"PASS","issues":[]}'):
            classification = review_contract.parse_review_classification(raw_json)
            with self.subTest(source=classification["source_format"]):
                payload = completed_document(classification)
                payload["review_findings"] = LEGACY_PASS
                with self.assertRaises(AutoBuildResultError):
                    validate_result(payload, process_exit_code=0)
                payload["decision"] = COMPLETE
                self.assertIs(validate_result(payload, process_exit_code=0), payload)

    def test_absent_raw_findings_remain_compatible_without_reinterpreting_the_answer(self):
        classification = review_contract.parse_review_classification(json.dumps(PASS))
        payload = completed_document(classification)
        # last_answer is production text, not the mandatory review. It must not
        # become a guessed replacement for a missing historical raw-review field.
        payload["last_answer"] = LEGACY_FAIL
        self.assertIsNone(payload["review_findings"])
        self.assertIs(validate_result(payload), payload)
        del payload["review_findings"]
        self.assertIs(validate_result(payload), payload)

    def test_contradictory_verdict_or_blockers_cannot_complete(self):
        normalized = review_contract.parse_review_classification(json.dumps(FAIL))
        for changes in ({"verdict": "PASS"}, {"blocking_issues": []}):
            for source in ("structured", "text_legacy", "json_legacy"):
                with self.subTest(changes=changes, source=source):
                    payload = completed_document({**normalized, **changes, "source_format": source},
                                                 decision=COMPLETE)
                    with self.assertRaises(AutoBuildResultError):
                        validate_result(payload)

    def test_successful_structured_and_legacy_summaries_remain_accepted(self):
        for raw in (json.dumps(PASS), '{"verdict":"PASS","issues":[]}', LEGACY_PASS):
            with self.subTest(raw=raw):
                classification = review_contract.parse_review_classification(raw)
                payload = completed_document(classification, decision=COMPLETE)
                self.assertIs(validate_result(payload, process_exit_code=0), payload)
        payload = completed_document(review_contract.parse_review_classification(LEGACY_PASS))
        with self.assertRaises(AutoBuildResultError):
            validate_result(payload)


class ReviewCompletionControllerTests(IsolatedControllerCase):
    def _reject_persist_and_resume(self, raw_review):
        self.write_plan(PLAN)
        runner = self.runner(max_steps=1, breakdown_policy="off")
        phases = []

        def dispatch(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "review":
                self.assertEqual(kwargs["sandbox"], "read-only")
                return model_answer(raw_review)
            self.assertEqual(kwargs["phase"], "auftrag")
            return model_answer("Synthetic producer claims complete without creating the file.")

        with self.fake_codex(dispatch), patch.object(
                autobuild, "run_semantic_decision", side_effect=semantic_choice) as decide:
            runner.run()
        self.assertEqual(phases, ["auftrag", "review"])
        self.assertNotIn("1", runner.completed)
        self.assertNotEqual(runner.exit_code, 0)
        self.assertFalse((self.work / "proof.txt").exists())
        self.assertEqual(self.todo.read_text(encoding="utf-8"), PLAN)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], PLAN)
        summaries = list(runner.run_dir.rglob("autobuild_summary.json"))
        self.assertEqual(len(summaries), 1)
        result = json.loads(summaries[0].read_text())
        self.assertFalse(result["completed"])
        self.assertEqual(result["review_classification"]["verdict"], "FAIL")
        self.assertTrue(result["review_classification"]["blocking_issues"])
        validate_result(result)
        decide.assert_not_called()
        runner.close()
        reloaded = PlanAuthority(self.todo, runner.state_dir, workspace=self.work)
        try:
            self.assertEqual(reloaded.text, PLAN)
        finally:
            reloaded.close()

        # A real second runner must dispatch the unfinished task and may accept
        # it only after the required file and a fresh passing review exist.
        # Exhausting the first attempt creates the normal controller stop;
        # clearing this disposable fixture simulates the owner's explicit resume.
        self.assertTrue(runner.process_stop_path.is_file())
        runner.process_stop_path.unlink()
        resumed = self.runner(max_steps=1, breakdown_policy="off")
        new_phases = []

        def fresh_dispatch(**kwargs):
            new_phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"RIGHT")
                return model_answer("Created proof.txt.")
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"RIGHT")
            return model_answer(json.dumps(PASS))

        with self.fake_codex(fresh_dispatch):
            resumed.run()
        self.assertEqual(new_phases, ["auftrag", "review"])
        self.assertEqual(resumed.exit_code, 0)
        self.assert_accepted_artifact(resumed, plan=PLAN.replace("***Task***", "***DONE***"),
                                      artifact="proof.txt", data=b"RIGHT")

    def test_source_spoof_cannot_persist_done_and_restart_still_dispatches(self):
        self._reject_persist_and_resume(json.dumps({**FAIL, "source_format": "text_legacy"}))

    def test_legacy_blocker_cannot_persist_done_and_restart_still_dispatches(self):
        self._reject_persist_and_resume(LEGACY_FAIL)

    def test_legacy_blocker_requires_correction_and_a_fresh_pass(self):
        self.write_plan(PLAN)
        runner = self.runner(max_steps=2, breakdown_policy="off")
        phases = []

        def dispatch(**kwargs):
            phase = kwargs["phase"]
            phases.append(phase)
            if phase in ("auftrag", "fix"):
                (self.work / "proof.txt").write_bytes(b"WRONG" if phase == "auftrag" else b"RIGHT")
                return model_answer("Synthetic production result.")
            return model_answer(LEGACY_FAIL if phases.count("review") == 1 else json.dumps(PASS))

        with self.fake_codex(dispatch), patch.object(
                autobuild, "run_semantic_decision", side_effect=semantic_choice) as decide:
            runner.run()
        self.assertEqual(phases, ["auftrag", "review", "fix", "review"])
        decide.assert_not_called()
        self.assert_accepted_artifact(runner, plan=PLAN.replace("***Task***", "***DONE***"),
                                      artifact="proof.txt", data=b"RIGHT")

    def test_nonblocking_legacy_review_and_complete_decision_can_persist_done(self):
        self.write_plan(PLAN)
        runner = self.runner(max_steps=1, breakdown_policy="off")

        def dispatch(**kwargs):
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"RIGHT")
                return model_answer("Created proof.txt.")
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"RIGHT")
            return model_answer(LEGACY_PASS)

        with self.fake_codex(dispatch), patch.object(
                autobuild, "run_semantic_decision", side_effect=semantic_choice) as decide:
            runner.run()
        decide.assert_called_once()
        self.assertEqual(runner.exit_code, 0)
        self.assert_accepted_artifact(runner, plan=PLAN.replace("***Task***", "***DONE***"),
                                      artifact="proof.txt", data=b"RIGHT")

    def test_private_worker_result_cannot_bypass_the_review_gate(self):
        self.write_plan(PLAN)
        runner = self.runner()
        for raw in (LEGACY_FAIL, LEGACY_PASS):
            classification = review_contract.parse_review_classification(raw)
            payload = completed_document(classification, decision=COMPLETE)
            encoded = json.dumps(payload).encode("utf-8")
            logs = self.base / ("worker-fail" if raw == LEGACY_FAIL else "worker-pass")
            logs.mkdir()
            options = AutoBuildOptions(logfile=logs / "pretty.log", rawlog=logs / "raw.jsonl",
                                       summary_json=logs / "summary.json", max_steps=1)

            def fake_worker(command, **kwargs):
                self.assertIn("--request-json", command)
                request_path = Path(command[-1])
                self.assertFalse(request_path.is_relative_to(self.work))
                request = json.loads(request_path.read_text())
                Path(request["options"]["summary_json"]).write_bytes(encoded)
                return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

            with self.subTest(raw=raw), patch.object(run_todos.subprocess, "run", side_effect=fake_worker):
                result = runner._autobuild_python_attempt("Task", self.work, options, AutoBuildContext())
                self.assertEqual(result.completed, raw == LEGACY_PASS)
                self.assertEqual(result.exit_code, 0 if raw == LEGACY_PASS else 7)
                if raw == LEGACY_FAIL:
                    self.assertEqual(result.execution_error["code"], "invalid_autobuild_summary")
                    self.assertTrue(options.summary_json.with_suffix(".boundary_error.json").exists())
                self.assertEqual(options.summary_json.read_bytes(), encoded)

    def test_parent_subject_fail_remains_blocked_and_valid_pass_is_accepted(self):
        self.write_plan(PLAN)
        runner = self.runner()
        for finding in (FAIL, PASS):
            raw = json.dumps({**finding, "source_format": "text_legacy"})
            outcome = run_todos.TaskOutcome(completed=True, message=raw)
            with self.subTest(verdict=finding["verdict"]), patch.object(
                    runner, "_run_autobuild", return_value=outcome) as execute, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = runner._run_parent_review("1", (self.work / "result.md", "result.md"))
            self.assertEqual(result.passed, finding["verdict"] == "PASS")
            self.assertEqual(result.classification["source_format"], "structured")
            self.assertEqual(execute.call_args.kwargs["sandbox_override"], "read-only")


if __name__ == "__main__":
    unittest.main()
