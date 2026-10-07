# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline controller transitions for child acceptance, WAIT and parallel handoff."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import threading
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
import run_todos


PASS = {
    "verdict": "PASS", "short_summary": "Inspected the physical output.",
    "blocking_issues": [], "non_blocking_observations": [],
    "breakdown_recommended": False, "breakdown_reason": None,
}
FAIL = {
    **PASS, "verdict": "FAIL", "short_summary": "Original output remains missing.",
    "blocking_issues": [{
        "id": "MISSING", "type": "technical_failure", "summary": "Parent output missing",
        "requirement": "Create parent.txt", "acceptance_criterion": "parent.txt exists",
        "references": [], "fix_suggestion": "Inspect the original requirement.",
    }],
}
BREAKDOWN = {
    **FAIL, "blocking_issues": [{
        "id": "LOCAL", "type": "local_fix", "summary": "Child work needed",
        "requirement": "Create parent.txt", "acceptance_criterion": "parent.txt exists",
        "references": [], "fix_suggestion": "Create the output.",
    }],
}
PARENT = "1. ***Task***: Create parent.txt containing complete.\n"
CHILD = "1.1. ***Task***: Create child.txt and check parent.txt.\n"


class BreakdownWaitParallelTests(IsolatedControllerCase):
    def make_breakdown(self, children=CHILD):
        self.write_plan(PARENT)
        runner = self.runner(stop_id="1", breakdown_max_rounds=1)
        classification = {**BREAKDOWN, "breakdown_recommended": children != CHILD}
        def produce(identifier, *args, **kwargs):
            self.assertEqual(identifier, "1-breakdown")
            self.write_plan(PARENT + children)
            return run_todos.TaskOutcome(completed=True, message="Reviewed child plan")
        with patch.object(runner, "_run_autobuild_impl", side_effect=produce), redirect_stdout(io.StringIO()):
            outcome = runner._request_minimal_breakdown(
                todo=runner._parse_todo_file()[0], result_file=self.work / "todo_result_1.md",
                outcome=run_todos.TaskOutcome(completed=False, message="Child work needed",
                                              review_classification=classification),
            )
        self.assertIsNone(outcome)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], PARENT + children)
        runner.close()

    def test_obsolete_child_cannot_authorize_parent_review_after_restart(self):
        self.make_breakdown()
        obsolete = PARENT + CHILD.replace("***Task***", "***OBSOLETE***")
        self.write_plan(obsolete)  # Explicit owner change, not a reviewed child completion.
        runner = self.runner(accept_plan_changes=True, breakdown_max_rounds=1)
        calls = []
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            return run_todos.TaskOutcome(completed=True, message=json.dumps(PASS))
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        self.assertNotIn("1-review", calls)
        self.assertNotIn("1", runner.completed)
        self.assertNotIn("1", runner.reviewed_this_run)
        self.assertEqual(self.todo.read_text(), obsolete)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], obsolete)
        self.assertNotEqual(runner.exit_code, 0)
        stops = list((self.work / "var" / "process_stops").glob("*.json"))
        self.assertEqual(len(stops), 1)
        self.assertEqual(json.loads(stops[0].read_text())["reason_code"], "child_todos_not_completed")

    def test_done_sibling_does_not_mask_obsolete_child(self):
        second = "1.2. ***Task***: Create second child artifact.\n"
        self.make_breakdown(CHILD + second)
        amended = PARENT + CHILD + second.replace("***Task***", "***OBSOLETE***")
        self.write_plan(amended)
        runner = self.runner(accept_plan_changes=True, breakdown_max_rounds=1)
        calls = []
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            if identifier == "1.1":
                (self.work / "child.txt").write_bytes(b"child\n")
            return run_todos.TaskOutcome(completed=True, message=json.dumps(PASS))
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        self.assertNotIn("1-review", calls)
        self.assertNotIn("1", runner.completed)
        self.assertNotIn("1", runner.reviewed_this_run)
        expected = PARENT + CHILD.replace("***Task***", "***DONE***") + second.replace("***Task***", "***OBSOLETE***")
        self.assertEqual(calls, ["1.1"])
        self.assertEqual((self.work / "child.txt").read_bytes(), b"child\n")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)
        self.assertNotEqual(runner.exit_code, 0)
        stops = list((self.work / "var" / "process_stops").glob("*.json"))
        self.assertEqual(len(stops), 1)
        self.assertEqual(json.loads(stops[0].read_text())["reason_code"], "child_todos_not_completed")

    def test_completed_child_does_not_replace_failed_parent_review(self):
        self.make_breakdown()
        runner = self.runner(breakdown_max_rounds=1)
        calls = []
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            if identifier == "1.1":
                (self.work / "child.txt").write_bytes(b"child\n")
                return run_todos.TaskOutcome(completed=True, message="Child checked")
            self.assertEqual(identifier, "1-review")
            self.assertEqual(kwargs.get("sandbox_override"), "read-only")
            self.assertFalse((self.work / "parent.txt").exists())
            return run_todos.TaskOutcome(completed=True, message=json.dumps(FAIL))
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        expected = PARENT + CHILD.replace("***Task***", "***DONE***")
        self.assertEqual(calls, ["1.1", "1-review"])
        self.assertEqual((self.work / "child.txt").read_bytes(), b"child\n")
        self.assertFalse((self.work / "parent.txt").exists())
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)
        self.assertNotIn("1", runner.completed)
        self.assertNotEqual(runner.exit_code, 0)
        stops = list((self.work / "var" / "process_stops").glob("*.json"))
        self.assertEqual(len(stops), 1)
        self.assertEqual(json.loads(stops[0].read_text())["reason_code"],
                         "parent_review_non_decomposable_blocker")

    def test_valid_child_and_separate_parent_review_complete_after_restart(self):
        self.make_breakdown()
        runner = self.runner()
        calls = []
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            if identifier == "1.1":
                (self.work / "child.txt").write_bytes(b"child\n")
                (self.work / "parent.txt").write_bytes(b"complete\n")
                return run_todos.TaskOutcome(completed=True, message="Child checked")
            self.assertEqual(identifier, "1-review")
            self.assertEqual(kwargs.get("sandbox_override"), "read-only")
            self.assertEqual((self.work / "parent.txt").read_bytes(), b"complete\n")
            return run_todos.TaskOutcome(completed=True, message=json.dumps(PASS))
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        self.assertEqual(calls, ["1.1", "1-review"])
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(runner.completed, {"1", "1.1"})
        self.assertEqual((self.work / "parent.txt").read_bytes(), b"complete\n")
        expected = (PARENT + CHILD).replace("***Task***", "***DONE***")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)

    def test_missing_child_on_restart_never_replays_parent(self):
        self.make_breakdown()
        self.write_plan(PARENT)
        runner = self.runner(accept_plan_changes=True)
        calls = []
        with patch.object(runner, "_run_autobuild_impl", side_effect=lambda *a, **k: calls.append(a[0])), \
             redirect_stdout(io.StringIO()):
            runner.run()
        self.assertEqual(calls, [])
        self.assertEqual(self.todo.read_text(), PARENT)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], PARENT)
        self.assertNotIn("1", runner.completed)
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(runner.terminal_execution_error["code"], "invalid_breakdown_resume")

    def test_wait_on_obsolete_stops_and_timeout_continue_executes(self):
        initial = ("1. ***OBSOLETE***: Earlier work.\n"
                   "***WAIT on=todo:1 timeout=0s***\n"
                   "2. ***Task***: Create allowed.txt.\n")
        self.write_plan(initial)
        blocked = self.runner()
        calls = []
        with patch.object(blocked, "_run_autobuild_impl", side_effect=lambda *a, **k: calls.append(a[0])), \
             redirect_stdout(io.StringIO()):
            blocked.run()
        self.assertEqual(calls, [])
        self.assertEqual(blocked.exit_code, run_todos.EXIT_INCOMPLETE)
        self.assertEqual(json.loads((blocked.state_dir / "plan.json").read_text())["text"], initial)
        blocked.close()

        continued_text = initial.replace("timeout=0s***", "timeout=0s on_timeout=continue***")
        self.write_plan(continued_text)
        continued = self.runner(accept_plan_changes=True)
        def worker(identifier, *args, **kwargs):
            self.assertEqual(identifier, "2")
            (self.work / "allowed.txt").write_bytes(b"allowed\n")
            return run_todos.TaskOutcome(completed=True, message="Separately checked")
        with patch.object(continued, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            continued.run()
        expected = continued_text.replace("2. ***Task***", "2. ***DONE***")
        self.assertEqual(continued.exit_code, 0)
        self.assertEqual(continued.completed, {"2"})
        self.assertEqual((self.work / "allowed.txt").read_bytes(), b"allowed\n")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((continued.state_dir / "plan.json").read_text())["text"], expected)

    def test_wait_on_stored_done_allows_restart(self):
        plan = ("1. ***DONE***: Earlier task.\n"
                "***WAIT on=todo:1 timeout=0s***\n"
                "2. ***Task***: Create resumed.txt.\n")
        self.write_plan(plan)
        runner = self.runner()
        def worker(identifier, *args, **kwargs):
            self.assertEqual(identifier, "2")
            (self.work / "resumed.txt").write_bytes(b"resumed\n")
            return run_todos.TaskOutcome(completed=True, message="Reviewed")
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        expected = plan.replace("2. ***Task***", "2. ***DONE***")
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(runner.completed, {"1", "2"})
        self.assertEqual((self.work / "resumed.txt").read_bytes(), b"resumed\n")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)

    def test_parallel_duplicate_workspace_blocks_before_dispatch(self):
        plan = ("***CFG parallel=g workspace=child***\n1. ***Task***: First.\n"
                "***CFG parallel=g workspace=child***\n2. ***Task***: Second.\n")
        self.write_plan(plan)
        runner = self.runner()
        calls = []
        with patch.object(runner, "_run_autobuild_impl", side_effect=lambda *a, **k: calls.append(a[0])), \
             redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "doppelte Workspace"):
            runner.run()
        self.assertEqual(calls, [])
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.todo.read_text(), plan)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)

    def test_parallel_late_worker_syncs_distinct_reports_without_plan_authority(self):
        plan = ("***CFG parallel=g workspace=a result_file=todo_result_1.md***\n"
                "1. ***Task***: Write alpha.\n"
                "***CFG parallel=g workspace=b result_file=todo_result_1.md***\n"
                "2. ***Task***: Write beta.\n")
        self.write_plan(plan)
        runner = self.runner()
        first_ready = threading.Event()
        def worker(identifier, *args, **kwargs):
            context_file = kwargs["result_file_override"]
            if identifier == "1":
                context_file.write_text("alpha\n", encoding="utf-8")
                first_ready.set()
            else:
                self.assertTrue(first_ready.wait(5), "first worker did not reach handoff")
                context_file.write_text("beta\n", encoding="utf-8")
            return run_todos.TaskOutcome(completed=True, message="Reviewed worker output")
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        shared = (self.work / "todo_result_1.md").read_text()
        self.assertIn("alpha", shared)
        self.assertIn("beta", shared)
        self.assertEqual(shared.count("alpha"), 1)
        self.assertEqual(shared.count("beta"), 1)
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(runner.completed, {"1", "2"})
        expected = plan.replace("***Task***", "***DONE***")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)

    def test_parallel_contradictory_worker_result_stays_open(self):
        plan = ("***CFG parallel=g workspace=a result_file=todo_result_1.md***\n"
                "1. ***Task***: Write first.\n"
                "***CFG parallel=g workspace=b result_file=todo_result_2.md***\n"
                "2. ***Task***: Write second.\n")
        self.write_plan(plan)
        runner = self.runner()
        def worker(identifier, *args, **kwargs):
            kwargs["result_file_override"].write_text(identifier + " report\n", encoding="utf-8")
            if identifier == "1":
                return run_todos.TaskOutcome(completed=True, abort=True, message="Conflicting completion")
            (self.work / "second.txt").write_bytes(b"second\n")
            return run_todos.TaskOutcome(completed=True, message="Reviewed")
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        self.assertNotIn("1", runner.completed)
        self.assertIn("2", runner.completed)
        self.assertFalse((self.work / "first.txt").exists())
        self.assertEqual((self.work / "second.txt").read_bytes(), b"second\n")
        self.assertIn("1 report", (self.work / "todo_result_1.md").read_text())
        self.assertIn("2 report", (self.work / "todo_result_2.md").read_text())
        expected = plan.replace("2. ***Task***", "2. ***DONE***")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)
        self.assertNotEqual(runner.exit_code, 0)

    def test_duplicate_parallel_feedback_is_not_appended_twice(self):
        plan = ("***CFG parallel=g workspace=a result_file=todo_result_1.md***\n"
                "1. ***Task***: Write first.\n"
                "***CFG parallel=g workspace=b result_file=todo_result_1.md***\n"
                "2. ***Task***: Write second.\n")
        self.write_plan(plan)
        runner = self.runner()
        def worker(identifier, *args, **kwargs):
            kwargs["result_file_override"].write_text("same report\n", encoding="utf-8")
            (self.work / ("first.txt" if identifier == "1" else "second.txt")).write_bytes(identifier.encode())
            return run_todos.TaskOutcome(completed=True, message="Reviewed")
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        self.assertEqual((self.work / "todo_result_1.md").read_text(), "same report\n")
        self.assertEqual((self.work / "first.txt").read_bytes(), b"1")
        self.assertEqual((self.work / "second.txt").read_bytes(), b"2")
        self.assertEqual(runner.completed, {"1", "2"})
        expected = plan.replace("***Task***", "***DONE***")
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)

    def test_stop_limited_parallel_batch_keeps_later_task_open(self):
        plan = ("***CFG parallel=g workspace=a***\n1. ***Task***: Create first.txt.\n"
                "***CFG parallel=g workspace=b***\n2. ***Task***: Create second.txt.\n")
        self.write_plan(plan)
        runner = self.runner(stop_id="1")
        calls = []
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            (self.work / "first.txt").write_bytes(b"first\n")
            return run_todos.TaskOutcome(completed=True, message="Reviewed")
        with patch.object(runner, "_run_autobuild_impl", side_effect=worker), redirect_stdout(io.StringIO()):
            runner.run()
        expected = plan.replace("1. ***Task***", "1. ***DONE***")
        self.assertEqual(calls, ["1"])
        self.assertEqual((self.work / "first.txt").read_bytes(), b"first\n")
        self.assertFalse((self.work / "second.txt").exists())
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], expected)
