# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline self-test: real controller state with the repository's Fake-Codex pattern."""
from __future__ import annotations

import json

from adversarial.harness import IsolatedControllerCase
from test_public_runtime import PASS, extract_contract, result


class HarnessSelfTests(IsolatedControllerCase):
    def test_plan_fixture_preserves_lf_and_crlf_in_journal(self):
        for ending in ("\n", "\r\n"):
            with self.subTest(ending=repr(ending)), self.scratch() as root:
                work = root / "workspace"
                work.mkdir()
                todo = work / "tasks.md"
                plan = "1. ***Task***: Preserve exact fixture bytes." + ending
                # Exercise the common writer without changing production I/O.
                original_todo = self.todo
                try:
                    self.todo = todo
                    self.write_plan(plan)
                finally:
                    self.todo = original_todo
                self.assertEqual(todo.read_bytes(), plan.encode("utf-8"))
                runner = self.runner(todo_file=todo, workdir=work,
                                     state_dir=root / "controller-state")
                try:
                    journal = json.loads((runner.state_dir / "plan.json").read_bytes())
                    self.assertEqual(journal["text"], plan)
                    self.assertEqual(todo.read_bytes(), plan.encode("utf-8"))
                finally:
                    runner.close()

    def test_scratch_is_cleaned_after_exception(self):
        self.assertFalse(self.state_root.is_relative_to(self.work))
        self.assertTrue(self.victims.is_relative_to(self.base))
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with self.scratch() as scratch:
                (scratch / "test-only.txt").write_text("test data", encoding="utf-8", newline="")
                raise RuntimeError("synthetic failure")
        self.assertFalse(scratch.exists())

    def test_fake_review_and_independent_artifact_oracle(self):
        open_plan = "1. ***Task***: Create proof.txt containing verified.\n"
        done_plan = open_plan.replace("***Task***", "***DONE***")
        self.write_plan(open_plan)
        runner = self.runner(stop_id="1")
        phases = []

        def dispatch(**kwargs):
            phase = kwargs["phase"]
            phases.append((phase, kwargs["sandbox"]))
            if phase == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return result("Created proof.txt for separate review.")
            if phase == "review":
                self.assertIn("Create proof.txt containing verified.",
                              extract_contract(kwargs["prompt"])["task_text"])
                return result(json.dumps(PASS))
            self.fail(f"Unexpected Codex phase: {phase}")

        with self.fake_codex(dispatch):
            runner.run()

        self.assertEqual(phases, [("auftrag", "workspace-write"), ("review", "read-only")])
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(runner.completed, {"1"})
        self.assertEqual(runner.reviewed_this_run, {"1"})
        self.assert_accepted_artifact(runner, plan=done_plan,
                                      artifact="proof.txt", data=b"verified\n")

        # This is a harness negative control: a stale PASS string cannot make
        # the independent physical-output oracle accept a removed artifact.
        (self.work / "proof.txt").unlink()
        with self.assertRaisesRegex(AssertionError, "Missing artifact"):
            self.assert_accepted_artifact(runner, plan=done_plan,
                                          artifact="proof.txt", data=b"verified\n")
