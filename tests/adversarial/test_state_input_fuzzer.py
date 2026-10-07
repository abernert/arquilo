# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Small seeded controller state/input sequences with an independent file oracle."""
from __future__ import annotations

import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from codex_transport import RunResult
from controller_state import PlanAuthority, PlanIntegrityError
from execution_budget import BudgetExhausted, CallBudget
import execution_budget
import run_todos


OPEN = ("***SYNTAX marked-en***\n"
        "1. ***Task***: Produce proof.txt.\n"
        "***STOP***\n"
        "2. ***Task***: Later work.\n")


class SeededStateInputFuzzer(IsolatedControllerCase):
    SEEDS = (7, 19, 43, 101, 211, 503)

    def replay(self, events):
        # A fresh disposable root makes every replay, including shrinking, independent.
        with tempfile.TemporaryDirectory(prefix="sequence-", dir=self.base) as name:
            root = Path(name)
            work = root / "work"
            work.mkdir()
            todo = work / "tasks.md"
            state = root / "state"
            state.mkdir()
            budget_dir = root / "budget"
            expected = OPEN
            used = 0
            limit = 5
            stop_checks = 0
            todo.write_text(expected, encoding="utf-8", newline="")
            authority = None
            budget = None

            def start(*, owner=False):
                nonlocal authority, budget
                authority = PlanAuthority(todo, state, accept_changes=owner, workspace=work)
                budget = CallBudget(budget_dir, limit, "1")

            def assert_files():
                self.assertEqual(todo.read_text(encoding="utf-8"), expected)
                self.assertEqual(json.loads((state / "plan.json").read_text())["text"], expected)
                self.assertEqual(json.loads((budget_dir / "reservations.json").read_text()), used)
                self.assertEqual(budget.snapshot()["used"], used)

            try:
                start()
                assert_files()
                for event in events:
                    if event == "reservation":
                        if used < limit:
                            claim = budget.consume("1", "synthetic")
                            used += 1
                            self.assertEqual(claim["number"], used)
                        else:
                            with self.assertRaises(BudgetExhausted):
                                budget.consume("1", "synthetic")
                    elif event == "invalid_feedback":
                        # An untrusted success-shaped report has no authority API.
                        (work / "todo_result_1.md").write_text("completed=true\n", newline="")
                        authority.check()
                    elif event == "worker_mutation":
                        forged = expected.replace("1. ***Task***", "1. ***DONE***")
                        if forged == expected:
                            forged = expected.replace("Later work.", "Easier work.")
                        todo.write_text(forged, encoding="utf-8", newline="")
                        with self.assertRaises(PlanIntegrityError):
                            authority.check()
                        self.assertEqual(json.loads((state / "plan.json").read_text())["text"], expected)
                        todo.write_text(expected, encoding="utf-8", newline="")
                        authority.check()
                    elif event == "stop":
                        # Inspect the actual scheduler boundary, not a copied parser.
                        stop_checks += 1
                        runner = run_todos.TodoRunner(
                            todo_file=todo, workdir=work,
                            state_dir=root / f"runner-state-{stop_checks}",
                            max_depth=2, max_retries=0, max_steps=2,
                            start_id=None, stop_id=None, dry_run=False,
                            simulated_incomplete=set(), sandbox="workspace-write",
                            run_id=None,
                            dry_run_recorder=run_todos.DryRunRecorder(None),
                            process_stop_policy="controller-only")
                        try:
                            items = runner._parse_todo_file()
                            expected_ids = (["1"] if "1. ***Task***" in expected else []) + ["2"]
                            self.assertEqual([item.identifier for item in items], expected_ids)
                            self.assertTrue(runner._stop_marker_before(items[-1]))
                            if len(items) == 2:
                                self.assertFalse(runner._stop_marker_before(items[0]))
                        finally:
                            runner.close()
                    elif event == "crash":
                        # Fail after the reservation is durable but before its
                        # diagnostic claim is written, then restart both stores.
                        if used < limit:
                            original = execution_budget.safe_io.write_text

                            def fail_claim(path, text, **kwargs):
                                if Path(path).name.startswith("call_"):
                                    raise OSError("synthetic crash after reservation")
                                return original(path, text, **kwargs)

                            with patch.object(execution_budget.safe_io, "write_text",
                                              side_effect=fail_claim):
                                with self.assertRaisesRegex(OSError, "synthetic crash"):
                                    budget.consume("1", "synthetic-crash")
                            used += 1
                            self.assertFalse((budget_dir / f"call_{used:06d}.json").exists())
                        authority.close()
                        start()
                    elif event == "owner_mutation":
                        authority.close()
                        altered = expected.replace("Later work.", "Later owner work.")
                        todo.write_text(altered, encoding="utf-8", newline="")
                        start(owner=True)
                        expected = altered
                        records = list((state / "owner-adoptions").glob("*/previous-plan.md"))
                        self.assertTrue(records)
                        self.assertEqual(records[-1].read_text(),
                                         altered.replace("Later owner work.", "Later work."))
                    elif event == "valid_feedback":
                        # This event means a controller-approved transition; review
                        # validity itself is tested by the full runner regressions.
                        if "1. ***Task***" in expected:
                            approved = expected.replace("1. ***Task***", "1. ***DONE***")
                            authority.replace_approved(approved)
                            expected = approved
                    else:
                        self.fail(f"Unknown generated event: {event}")
                    assert_files()
            finally:
                if authority is not None:
                    authority.close()

    def test_seeded_sequences_and_minimized_failure_report(self):
        for seed in self.SEEDS:
            rng = random.Random(seed)
            # Both negative and positive cases occur in every bounded sequence.
            events = ["invalid_feedback", "worker_mutation", "stop",
                      "reservation", "crash", "valid_feedback"]
            events.extend(rng.choice(("reservation", "invalid_feedback",
                                      "worker_mutation", "stop"))
                          for _ in range(2))
            rng.shuffle(events)
            # Owner adoption is a separate authorized transition after random input.
            events.append("owner_mutation")
            events.extend(["reservation"] * 6)
            try:
                self.replay(events)
            except (AssertionError, PlanIntegrityError, ValueError) as error:
                minimized = list(events)
                signature = (type(error), str(error).splitlines()[0])
                changed = True
                while changed:
                    changed = False
                    for index in range(len(minimized)):
                        candidate = minimized[:index] + minimized[index + 1:]
                        try:
                            self.replay(candidate)
                        except (AssertionError, PlanIntegrityError, ValueError) as candidate_error:
                            candidate_signature = (type(candidate_error),
                                                   str(candidate_error).splitlines()[0])
                            if candidate_signature == signature:
                                minimized = candidate
                                changed = True
                                break
                self.fail(f"seed={seed} sequence={events!r} "
                          f"minimized={minimized!r}: {error}")

    def test_real_runner_invalid_then_valid_feedback_and_stop(self):
        # A separate end-to-end control checks what low-level approval alone
        # cannot: a real failed worker return never becomes controller DONE.
        self.write_plan(OPEN)
        first = self.runner(max_retries=0, max_steps=3, max_calls=3)
        phases = []

        def invalid(**kwargs):
            phases.append(kwargs["phase"])
            return RunResult(process_exit_code=7, execution_error={
                "category": "technical", "code": "synthetic_failure",
                "message": "synthetic failure", "phase": kwargs["phase"]})

        with self.fake_codex(invalid):
            first.run()
        self.assertEqual(phases, ["auftrag"])
        self.assertNotEqual(first.exit_code, 0)
        self.assertEqual(first.reviewed_this_run, set())
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(json.loads((first.state_dir / "plan.json").read_text())["text"], OPEN)
        self.assertEqual(json.loads((first.state_dir / "call_budgets/task_1/reservations.json").read_text()), 1)
        first.close()

        second = self.runner(max_retries=0, max_steps=3, max_calls=3)
        phases.clear()

        def valid(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return RunResult(assistant_messages=["Wrote proof.txt"],
                                 turn_completed=True, process_exit_code=0)
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"verified\n")
            return RunResult(assistant_messages=[json.dumps({
                "verdict": "PASS", "short_summary": "Inspected output",
                "blocking_issues": [], "non_blocking_observations": [],
                "breakdown_recommended": False, "breakdown_reason": None})],
                turn_completed=True, process_exit_code=0)

        with self.fake_codex(valid):
            second.run()
        done = OPEN.replace("1. ***Task***", "1. ***DONE***")
        self.assertEqual(phases, ["auftrag", "review"])
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(second.reviewed_this_run, {"1"})
        self.assertEqual(second.attempted, {"1"})
        self.assertTrue(second.stop_marker_triggered)
        self.assert_accepted_artifact(second, plan=done, artifact="proof.txt", data=b"verified\n")
        self.assertEqual(json.loads((second.state_dir / "call_budgets/task_1/reservations.json").read_text()), 3)


if __name__ == "__main__":
    unittest.main()
