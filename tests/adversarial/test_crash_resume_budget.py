# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline crash boundaries for persistent calls, plan status and worker returns."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from autobuild_contract import AutoBuildContext, AutoBuildOptions
from codex_transport import RunResult
from controller_state import PlanIntegrityError
from execution_budget import BudgetExhausted, CallBudget
import execution_budget
import run_todos
import safe_io


OPEN = "1. ***Task***: Create proof.txt containing verified.\n"
DONE = OPEN.replace("***Task***", "***DONE***")
PASS = {"verdict": "PASS", "short_summary": "Checked proof.txt bytes.",
        "blocking_issues": [], "non_blocking_observations": [],
        "breakdown_recommended": False, "breakdown_reason": None}


def answer(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


class CrashResumeBudgetTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan(OPEN)

    def journal(self, runner):
        return json.loads((runner.state_dir / "plan.json").read_text(encoding="utf-8"))

    def budget(self, runner):
        return runner.state_dir / "call_budgets" / "task_1"

    def test_reservation_write_failure_before_commit_cannot_dispatch_or_refund(self):
        runner = self.runner(max_calls=2)
        runner._call_budget_for("1")
        original = execution_budget.safe_io.atomic_write
        calls = []

        def fail_counter(path, data):
            if Path(path).name == "reservations.json":
                raise OSError("synthetic atomic replace failure")
            return original(path, data)

        with patch.object(execution_budget.safe_io, "atomic_write", side_effect=fail_counter), \
             self.fake_codex(lambda **kw: calls.append(kw) or answer("unexpected")):
            runner.run()
        self.assertEqual(calls, [])
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(self.journal(runner)["text"], OPEN)
        self.assertEqual(json.loads((self.budget(runner) / "reservations.json").read_text()), 0)
        self.assertFalse((self.work / "proof.txt").exists())

    def test_claim_write_failure_after_reservation_survives_restart(self):
        directory = self.base / "budget"
        budget = CallBudget(directory, 2, "1")
        original = execution_budget.safe_io.write_text

        def fail_claim(path, text, **kwargs):
            if Path(path).name == "call_000001.json":
                raise OSError("synthetic diagnostic write failure")
            return original(path, text, **kwargs)

        with patch.object(execution_budget.safe_io, "write_text", side_effect=fail_claim):
            with self.assertRaisesRegex(OSError, "diagnostic"):
                budget.consume("1", "production")
        self.assertFalse((directory / "call_000001.json").exists())
        resumed = CallBudget(directory, 2, "1")
        self.assertEqual(resumed.snapshot()["used"], 1)
        self.assertEqual(resumed.consume("1", "review")["number"], 2)
        with self.assertRaises(BudgetExhausted):
            resumed.consume("1", "retry")
        self.assertEqual(json.loads((directory / "reservations.json").read_text()), 2)

    def test_transport_failure_then_explicit_resume_keeps_consumption(self):
        first = self.runner(max_calls=3)
        calls = []

        def interrupted(**kwargs):
            calls.append(kwargs["phase"])
            return RunResult(process_exit_code=7, execution_error={
                "category": "technical", "code": "synthetic_worker_exit",
                "message": "Worker ended before answer", "phase": kwargs["phase"]})

        with self.fake_codex(interrupted):
            first.run()
        self.assertEqual(calls, ["auftrag"])
        self.assertNotEqual(first.exit_code, 0)
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(self.journal(first)["text"], OPEN)
        self.assertEqual(json.loads((first.run_dir / "run.json").read_text())["status"], "failed")
        self.assertEqual(json.loads((self.budget(first) / "reservations.json").read_text()), 1)
        first.close()

        # This transport error keeps the task open without a stop marker.
        self.assertFalse((self.work / "process_stop").exists())
        resumed = self.runner(max_calls=3)
        phases = []

        def successful(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return answer("Output written for review.")
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"verified\n")
            return answer(json.dumps(PASS))

        with self.fake_codex(successful):
            resumed.run()
        self.assertEqual(phases, ["auftrag", "review"])
        self.assertEqual(resumed.exit_code, 0)
        self.assertEqual(resumed.reviewed_this_run, {"1"})
        self.assert_accepted_artifact(resumed, plan=DONE, artifact="proof.txt", data=b"verified\n")
        self.assertEqual(json.loads((self.budget(resumed) / "reservations.json").read_text()), 3)

    def test_pending_status_write_recovers_only_approved_value(self):
        runner = self.runner()
        authority = runner.plan_authority
        original = safe_io.atomic_write
        fired = False

        def fail_task_file(path, data):
            nonlocal fired
            if Path(path) == self.todo and not fired:
                fired = True
                raise OSError("synthetic task status write failure")
            return original(path, data)

        with patch.object(safe_io, "atomic_write", side_effect=fail_task_file):
            with self.assertRaisesRegex(OSError, "status write"):
                authority.replace_approved(DONE)
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(self.journal(runner)["text"], OPEN)
        self.assertEqual(self.journal(runner)["pending"], DONE)
        runner.close()
        resumed = self.runner()
        self.assertEqual(self.todo.read_text(), DONE)
        self.assertEqual(self.journal(resumed)["text"], DONE)
        self.assertIsNone(self.journal(resumed)["pending"])
        self.assertFalse((self.work / "proof.txt").exists())
        resumed.close()

        # A third, unrelated workspace value is never adopted as pending work.
        self.write_plan(OPEN)
        with self.assertRaises(PlanIntegrityError):
            self.runner()

    def test_review_failure_retries_open_task_without_reusing_old_answer(self):
        first = self.runner(max_calls=4)
        phases = []

        def review_fails(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return answer("Ready for review.")
            return RunResult(process_exit_code=7, execution_error={
                "category": "technical", "code": "synthetic_review_exit",
                "message": "Review ended before answer", "phase": "review"})

        with self.fake_codex(review_fails):
            first.run()
        self.assertEqual(phases, ["auftrag", "review"])
        self.assertNotEqual(first.exit_code, 0)
        self.assertEqual(first.reviewed_this_run, set())
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(self.journal(first)["text"], OPEN)
        self.assertEqual(json.loads((first.run_dir / "run.json").read_text())["status"], "failed")
        self.assertEqual(json.loads((self.budget(first) / "reservations.json").read_text()), 2)
        first.close()

        resumed = self.runner(max_calls=4)
        phases.clear()

        def fresh_review(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                return answer("Existing output inspected.")
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"verified\n")
            return answer(json.dumps(PASS))

        with self.fake_codex(fresh_review):
            resumed.run()
        self.assertEqual(phases, ["auftrag", "review"])
        self.assertEqual(resumed.exit_code, 0)
        self.assert_accepted_artifact(resumed, plan=DONE, artifact="proof.txt", data=b"verified\n")
        self.assertEqual(json.loads((self.budget(resumed) / "reservations.json").read_text()), 4)

    def test_crash_after_status_file_before_journal_finalization_recovers(self):
        runner = self.runner(max_calls=2)
        original = safe_io.atomic_write
        fired = False

        def fail_final_journal(path, data):
            nonlocal fired
            if (Path(path) == runner.state_dir / "plan.json" and not fired
                    and b'"pending": null' in data and b'***DONE***' in data):
                fired = True
                raise OSError("synthetic final journal failure")
            return original(path, data)

        def successful(**kwargs):
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return answer("Ready for review.")
            return answer(json.dumps(PASS))

        with patch.object(safe_io, "atomic_write", side_effect=fail_final_journal), \
             self.fake_codex(successful):
            with self.assertRaisesRegex(OSError, "final journal"):
                runner.run()
        self.assertEqual(self.todo.read_text(), DONE)
        self.assertEqual(self.journal(runner)["text"], OPEN)
        self.assertEqual(self.journal(runner)["pending"], DONE)
        self.assertEqual(json.loads((self.budget(runner) / "reservations.json").read_text()), 2)
        runner.close()
        resumed = self.runner(max_calls=2)
        self.assertEqual(self.journal(resumed)["text"], DONE)
        self.assertIsNone(self.journal(resumed)["pending"])
        self.assertEqual((self.work / "proof.txt").read_bytes(), b"verified\n")
        with patch.object(resumed, "_run_autobuild_impl", side_effect=AssertionError("no replay")), \
             redirect_stdout(io.StringIO()):
            resumed.run()
        self.assertEqual(resumed.exit_code, 0)
        self.assertEqual(json.loads((self.budget(resumed) / "reservations.json").read_text()), 2)

    def test_optional_git_failure_is_run_failure_after_reviewed_status(self):
        runner = self.runner()
        runner.git_enabled = True
        runner.git_selection = type("SyntheticGit", (), {
            "commit": lambda self, message: (_ for _ in ()).throw(OSError("synthetic Git failure"))
        })()

        def successful(**kwargs):
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return answer("Ready for review.")
            return answer(json.dumps(PASS))

        with self.fake_codex(successful):
            with self.assertRaisesRegex(OSError, "Git failure"):
                runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(runner.reviewed_this_run, {"1"})
        self.assertEqual(json.loads((runner.run_dir / "run.json").read_text())["status"], "failed")
        self.assert_accepted_artifact(runner, plan=DONE, artifact="proof.txt", data=b"verified\n")
        self.assertFalse((self.work / "process_stop").exists())

    def test_private_worker_return_ignores_stale_and_duplicate_public_data(self):
        runner = self.runner(logs_in_workdir=True)
        log = runner.run_dir / "task-1"
        safe_io.mkdir(log)
        public = log / "autobuild_summary.json"
        options = AutoBuildOptions(logfile=log / "pretty.log", rawlog=log / "raw.jsonl",
                                   summary_json=public)
        context = AutoBuildContext(budget_directory=self.budget(runner), budget_root_id="1")
        stale = runner.state_dir / "worker_calls" / "stale" / "summary.json"
        safe_io.mkdir(stale.parent)
        stale.write_text('{"completed":true}', encoding="utf-8")
        private_paths = []

        def missing_return(command, **kwargs):
            request = Path(command[-1])
            private = Path(json.loads(request.read_text())["options"]["summary_json"])
            private_paths.append(private)
            self.assertFalse(private.is_relative_to(self.work))
            public.write_text('{"completed":true}\n{"completed":true}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"duplicate success", b"")

        with patch.object(run_todos.subprocess, "run", side_effect=missing_return):
            returned = runner._autobuild_python_attempt("test", self.work, options, context)
        self.assertEqual(len(private_paths), 1)
        self.assertNotEqual(private_paths[0], stale)
        self.assertFalse(private_paths[0].exists())
        self.assertFalse(returned.completed)
        self.assertEqual(returned.execution_error["code"], "invalid_autobuild_summary")
        self.assertEqual(self.journal(runner)["text"], OPEN)
        self.assertEqual(self.todo.read_text(), OPEN)

    def test_duplicate_private_return_keys_and_exit_mismatch_are_rejected(self):
        runner = self.runner(logs_in_workdir=True)
        log = runner.run_dir / "task-1"
        safe_io.mkdir(log)
        options = AutoBuildOptions(logfile=log / "pretty.log", rawlog=log / "raw.jsonl",
                                   summary_json=log / "autobuild_summary.json")
        context = AutoBuildContext(budget_directory=self.budget(runner), budget_root_id="1")

        def worker_with_bytes(raw, code):
            def invoke(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text())
                private = Path(request["options"]["summary_json"])
                private.write_bytes(raw)
                return subprocess.CompletedProcess(command, code, b"", b"")
            return invoke

        duplicate = (b'{"completed":false,"completed":true,"process_stop_triggered":false,'
                     b'"review_required":true,"exit_code":0,"status":"completed",'
                     b'"last_answer":"PASS"}')
        with patch.object(run_todos.subprocess, "run", side_effect=worker_with_bytes(duplicate, 0)):
            first = runner._autobuild_python_attempt("test", self.work, options, context)
        self.assertFalse(first.completed)
        self.assertEqual(first.execution_error["code"], "invalid_autobuild_summary")

        valid_failure = {
            "completed": False, "process_stop_triggered": False,
            "review_required": True, "exit_code": 7, "status": "failed",
            "last_answer": "synthetic worker failure", "execution_error": {
                "exit_code": 7, "code": "synthetic_worker_failure",
                "message": "Worker reported failure", "phase": "production"},
        }
        raw = json.dumps(valid_failure).encode()
        with patch.object(run_todos.subprocess, "run", side_effect=worker_with_bytes(raw, 0)):
            mismatch = runner._autobuild_python_attempt("test", self.work, options, context)
        self.assertFalse(mismatch.completed)
        self.assertEqual(mismatch.execution_error["code"], "autobuild_exit_mismatch")
        with patch.object(run_todos.subprocess, "run", side_effect=worker_with_bytes(raw, 7)):
            legitimate = runner._autobuild_python_attempt("test", self.work, options, context)
        self.assertFalse(legitimate.completed)
        self.assertEqual(legitimate.execution_error["code"], "synthetic_worker_failure")
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(self.journal(runner)["text"], OPEN)

    def test_unlimited_and_owner_limit_change_preserve_count(self):
        directory = self.base / "budget"
        finite = CallBudget(directory, 2, "1")
        self.assertEqual(finite.consume("1", "production")["number"], 1)
        unlimited = CallBudget(directory, 0, "1", allow_limit_change=True)
        self.assertTrue(unlimited.snapshot()["unlimited"])
        self.assertEqual(unlimited.consume("1", "review")["number"], 2)
        self.assertEqual(unlimited.consume("1", "retry")["number"], 3)
        with self.assertRaisesRegex(ValueError, "below 3"):
            CallBudget(directory, 2, "1", allow_limit_change=True)
        limited = CallBudget(directory, 4, "1", allow_limit_change=True)
        self.assertEqual(limited.snapshot()["used"], 3)
        self.assertEqual(limited.consume("1", "next")["number"], 4)
        self.assertEqual(json.loads((directory / "reservations.json").read_text()), 4)
        changes = list((directory / "limit_changes").glob("*/change.json"))
        self.assertGreaterEqual(len(changes), 2)
