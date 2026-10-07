# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline controller path checks with disposable sibling state and victims."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import safe_io
from autobuild_contract import AutoBuildContext, AutoBuildOptions
from controller_state import PlanIntegrityError, state_directory
from adversarial.harness import IsolatedControllerCase


class StatePathTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan("1. ***Task***: Write proof.txt.\n")

    def link(self, source: Path, target: Path, *, directory: bool = False):
        try:
            source.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Native symlink creation unavailable: {exc}")

    def test_state_root_is_external_private_and_rejects_workspace_alias(self):
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.todo, self.work / "sub" / ".." / "state")
        runner = self.runner(project_id="pilot", max_calls=2)
        self.assertFalse(runner.state_dir.is_relative_to(self.work))
        if os.name != "nt":
            self.assertEqual(runner.state_dir.parent.stat().st_mode & 0o777, 0o700)
        budget = runner._call_budget_for("1")
        self.assertEqual(budget.consume("1", "production")["number"], 1)
        runner.close()
        continued = self.runner(max_calls=2)
        self.assertEqual(continued.state_dir, runner.state_dir)
        self.assertEqual(continued.project_id, "pilot")
        self.assertEqual(continued._call_budget_for("1").snapshot()["used"], 1)
        self.assertEqual(json.loads(safe_io.read_text(continued.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))

    def test_linked_state_root_and_journal_reads_preserve_victims(self):
        victim = self.victims / "sentinel"
        victim.write_text("keep", encoding="utf-8")
        linked_root = self.base / "linked-state"
        self.link(linked_root, self.victims, directory=True)
        with self.assertRaises((safe_io.UnsafePathError, OSError)):
            state_directory(self.work, self.todo, linked_root)
        runner = self.runner()
        journal = runner.state_dir / "plan.json"
        original = safe_io.read_bytes(journal)
        runner.close()
        journal.unlink()
        self.link(journal, victim)
        with self.assertRaises((safe_io.UnsafePathError, OSError)):
            self.runner()
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        journal.unlink()
        safe_io.write_bytes(journal, original)
        self.assertEqual(json.loads(safe_io.read_text(journal))["text"],
                         self.todo.read_text(encoding="utf-8"))

    def test_hardlinked_budget_counter_read_rejected_without_refund(self):
        runner = self.runner(max_calls=2)
        budget = runner._call_budget_for("1")
        budget.consume("1", "production")
        counter = budget.directory / "reservations.json"
        original = safe_io.read_bytes(counter)
        victim = self.victims / "counter"
        victim.write_bytes(original)
        counter.unlink()
        try:
            os.link(victim, counter)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Native hardlink creation unavailable: {exc}")
        with self.assertRaises(safe_io.UnsafePathError):
            budget.consume("1", "review")
        self.assertEqual(victim.read_bytes(), original)
        counter.unlink()
        safe_io.write_bytes(counter, original)
        self.assertEqual(budget.consume("1", "review")["number"], 2)
        self.assertEqual(budget.snapshot()["used"], 2)

    def test_breakdown_round_metadata_rejects_linked_read(self):
        runner = self.runner()
        parent = runner.state_dir / "breakdowns" / "1"
        safe_io.mkdir(parent)
        victim = self.victims / "round.json"
        victim.write_text('{"round": 77}', encoding="utf-8")
        self.link(parent / "breakdown_plan.json", victim)
        with self.assertRaises(safe_io.UnsafePathError):
            runner._infer_breakdown_round("1")
        self.assertEqual(victim.read_text(encoding="utf-8"), '{"round": 77}')
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))
        (parent / "breakdown_plan.json").unlink()
        safe_io.write_text(parent / "breakdown_plan.json", '{"round": 2}')
        self.assertEqual(runner._infer_breakdown_round("1"), 2)

    def test_workspace_summary_read_rejects_link_to_external_file(self):
        runner = self.runner(logs_in_workdir=True)
        report = self.victims / "external-summary.json"
        report.write_text(json.dumps({"workspace": str(self.work), "file_changes": [
            {"path": "proof.txt"}]}), encoding="utf-8")
        (self.work / "proof.txt").write_text("ordinary artifact", encoding="utf-8")
        summary = runner.run_dir / "summary.json"
        self.link(summary, report)
        self.assertIsNone(runner._load_autobuild_summary_payload(summary))
        self.assertEqual(runner._collect_changed_files_from_summary(summary), [])
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["file_changes"],
                         [{"path": "proof.txt"}])
        summary.unlink()
        safe_io.write_text(summary, report.read_text(encoding="utf-8"))
        self.assertEqual(runner._collect_changed_files_from_summary(summary),
                         [self.work / "proof.txt"])

    def test_workspace_summary_hardlink_does_not_supply_candidates(self):
        runner = self.runner(logs_in_workdir=True)
        victim = self.victims / "summary.json"
        content = json.dumps({"workspace": str(self.work), "file_changes": [{"path": "proof.txt"}]})
        victim.write_text(content, encoding="utf-8")
        (self.work / "proof.txt").write_text("ordinary artifact", encoding="utf-8")
        summary = runner.run_dir / "summary.json"
        try:
            os.link(victim, summary)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Native hardlink creation unavailable: {exc}")
        self.assertEqual(runner._collect_changed_files_from_summary(summary), [])
        self.assertEqual(victim.read_text(encoding="utf-8"), content)
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))
        summary.unlink()
        safe_io.write_text(summary, content)
        self.assertEqual(runner._collect_changed_files_from_summary(summary),
                         [self.work / "proof.txt"])

    def test_result_report_read_rejects_external_link(self):
        runner = self.runner()
        victim = self.victims / "non-utf8-report"
        sentinel = b"\xff\xfeprivate"
        victim.write_bytes(sentinel)
        report = self.work / "todo_result_1.md"
        self.link(report, victim)
        with self.assertRaises(safe_io.UnsafePathError):
            runner._record_review(report, "synthetic review", "1")
        self.assertEqual(victim.read_bytes(), sentinel)
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))
        report.unlink()
        safe_io.write_text(report, "# ToDo 1\n")
        runner._record_review(report, "synthetic review", "1")
        self.assertIn("synthetic review", safe_io.read_text(report))

    def test_result_report_crlf_update_keeps_one_feedback_section(self):
        runner = self.runner()
        report = self.work / "todo_result_1.md"
        report.write_bytes(b"# ToDo 1\r\n\r\n## Letztes Reviewer Feedback\r\n\r\nold\r\n")
        runner._record_review(report, "new review", "1")
        content = report.read_text(encoding="utf-8")
        self.assertEqual(content.count("## Letztes Reviewer Feedback"), 1)
        self.assertIn("new review", content)
        self.assertNotIn("old\n", content)

    def test_private_worker_return_link_does_not_authorize_completion(self):
        runner = self.runner(logs_in_workdir=True)
        visible = runner.run_dir / "visible.json"
        options = AutoBuildOptions(summary_json=visible,
                                   logfile=runner.run_dir / "pretty.log",
                                   rawlog=runner.run_dir / "raw.jsonl")
        context = AutoBuildContext(budget_directory=runner._call_budget_for("1").directory,
                                   budget_root_id="1")
        victim = self.victims / "forged-return.json"
        victim.write_text('{"completed":true}', encoding="utf-8")

        def fake_process(command, **_):
            request = json.loads(safe_io.read_text(Path(command[-1])))
            private = Path(request["options"]["summary_json"])
            self.assertFalse(private.is_relative_to(self.work))
            self.link(private, victim)
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with patch("run_todos.subprocess.run", side_effect=fake_process):
            result = runner._autobuild_python_attempt("synthetic", self.work, options, context)
        self.assertFalse(result.completed)
        self.assertEqual(result.execution_error["code"], "invalid_autobuild_summary")
        self.assertEqual(victim.read_text(encoding="utf-8"), '{"completed":true}')
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "POSIX anchored directory-descriptor read race; native Windows test remains separate")
    def test_parent_swap_during_plan_read_uses_original_directory(self):
        runner = self.runner()
        original_text = safe_io.read_text(runner.state_dir / "plan.json")
        victim_dir = self.victims / "alternate-state"
        victim_dir.mkdir()
        (victim_dir / "plan.json").write_text('{"text":"forged"}', encoding="utf-8")
        parent = runner.state_dir
        moved = parent.with_name("moved_state")
        at_open = threading.Event()
        swapped = threading.Event()
        actual_open = os.open
        reads = []

        def intercepted_open(path, flags, *args, **kwargs):
            if path == "plan.json" and kwargs.get("dir_fd") is not None:
                at_open.set()
                if not swapped.wait(5):
                    raise TimeoutError("read barrier was not reached")
            return actual_open(path, flags, *args, **kwargs)

        def reader():
            try:
                reads.append(safe_io.read_text(parent / "plan.json"))
            except BaseException as exc:
                reads.append(exc)

        with patch("safe_io.os.open", side_effect=intercepted_open):
            thread = threading.Thread(target=reader)
            thread.start()
            try:
                self.assertTrue(at_open.wait(5), "read did not reach open barrier")
                parent.rename(moved)
                self.link(parent, victim_dir, directory=True)
            finally:
                swapped.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(reads, [original_text])
        self.assertEqual((victim_dir / "plan.json").read_text(encoding="utf-8"),
                         '{"text":"forged"}')

    @unittest.skipIf(os.name == "nt", "POSIX anchored directory-descriptor race; native Windows test remains separate")
    def test_parent_swap_during_budget_counter_write_cannot_redirect(self):
        runner = self.runner(max_calls=2)
        budget = runner._call_budget_for("1")
        budget.consume("1", "production")
        victim_dir = self.victims / "destination"
        victim_dir.mkdir()
        victim = victim_dir / "reservations.json"
        victim.write_text("sentinel", encoding="utf-8")
        parent = budget.directory
        moved = parent.with_name("moved_budget")
        at_replace = threading.Event()
        swapped = threading.Event()
        actual_replace = os.replace
        failure = []

        def intercepted_replace(src, dst, **kwargs):
            at_replace.set()
            if not swapped.wait(5):
                raise TimeoutError("swap barrier was not reached")
            return actual_replace(src, dst, **kwargs)

        def writer():
            try:
                safe_io.atomic_write(parent / "reservations.json", b"2\n")
            except BaseException as exc:
                failure.append(exc)

        with patch("safe_io.os.replace", side_effect=intercepted_replace):
            thread = threading.Thread(target=writer)
            thread.start()
            try:
                self.assertTrue(at_replace.wait(5), "write did not reach replacement barrier")
                parent.rename(moved)
                self.link(parent, victim_dir, directory=True)
            finally:
                swapped.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failure, failure)
        self.assertEqual(victim.read_text(encoding="utf-8"), "sentinel")
        self.assertEqual(safe_io.read_bytes(moved / "reservations.json"), b"2\n")
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))

    def test_workspace_logs_keep_private_plan_and_budget(self):
        runner = self.runner(logs_in_workdir=True, max_calls=2)
        budget = runner._call_budget_for("1")
        budget.consume("1", "production")
        self.assertTrue(runner.run_dir.is_relative_to(self.work))
        self.assertFalse(runner.state_dir.is_relative_to(self.work))
        public = runner.run_dir / "autobuild_summary.json"
        safe_io.write_text(public, '{"completed": true, "call_budget": {"used": 0}}')
        self.assertEqual(budget.snapshot()["used"], 1)
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / "plan.json"))["text"],
                         self.todo.read_text(encoding="utf-8"))
        self.assertEqual(runner.reviewed_this_run, set())
