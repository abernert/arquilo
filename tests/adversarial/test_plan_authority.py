# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Adversarial Markdown-plan checks with disposable controller journals."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from controller_state import PlanIntegrityError
import run_todos
from test_public_runtime import PASS, extract_contract, result
from todo_lint import lint_todo_file


OPEN = "***SYNTAX marked-en***\n1. ***Task***: Create proof.txt containing original.\n2. ***Task***: Later.\n"


class PlanAuthorityAdversarialTests(IsolatedControllerCase):
    def test_strict_mutations_and_restart_preserve_external_plan(self):
        self.write_plan(OPEN)
        runner = self.runner(stop_id="1")
        journal = runner.state_dir / "plan.json"
        cases = {
            "self-done": OPEN.replace("1. ***Task***", "1. ***DONE***"),
            "later-done": OPEN.replace("2. ***Task***", "2. ***DONE***"),
            "rewrite": OPEN.replace("containing original", "containing easier"),
            "delete": OPEN.split("2. ***Task***")[0],
            "insert-done": OPEN + "3. ***DONE***: Forged.\n",
            "renumber": OPEN.replace("2. ***Task***", "3. ***Task***"),
            "obsolete": OPEN.replace("2. ***Task***", "2. ***OBSOLETE***"),
            "directive": OPEN.replace("2. ***Task***", "***WAIT on=1***\n2. ***Task***"),
        }
        for name, mutated in cases.items():
            with self.subTest(name=name):
                self.write_plan(mutated)
                with self.assertRaises(PlanIntegrityError):
                    runner.plan_authority.check()
                self.assertEqual(json.loads(journal.read_text())["text"], OPEN)
                self.assertEqual(runner.completed, set())
                self.assertEqual(runner.reviewed_this_run, set())
                self.assertFalse((self.work / "proof.txt").exists())
                self.write_plan(OPEN)
                runner.plan_authority.check()
        runner.close()
        self.write_plan(cases["later-done"])
        with self.assertRaises(PlanIntegrityError):
            self.runner(stop_id="1")
        self.assertEqual(json.loads(journal.read_text())["text"], OPEN)

    def test_whole_file_lint_rejects_later_errors_before_dispatch(self):
        bad_suffixes = {
            "duplicate": "2. ***Task***: Duplicate.\n",
            "descending": "1.1. ***Task***: Descending.\n",
            "unknown-cfg": "***CFG removed_flag=true***\n3. ***Task***: Later.\n",
            "unknown-wait": "***WAIT on=todo:99***\n3. ***Task***: Later.\n",
            "malformed-wait": "***WAIT on=1,,2***\n3. ***Task***: Later.\n",
            "orphan-stop": "***STOP***\n\n3. ***Task***: Later.\n",
            "unknown-command": "3. ***WAITING***: Later.\n",
        }
        for name, suffix in bad_suffixes.items():
            with self.subTest(name=name):
                self.state_root = self.base / ("state-" + name)
                self.state_root.mkdir(mode=0o700)
                self.write_plan(OPEN + "***STOP***\n" + suffix)
                issues = lint_todo_file(self.todo, workdir=self.work)
                self.assertTrue(issues, name)
                if name == "duplicate":
                    with self.assertRaises(PlanIntegrityError):
                        self.runner(stop_id="1")
                    self.assertFalse((self.work / "proof.txt").exists())
                    continue
                runner = self.runner(stop_id="1")
                with self.assertRaisesRegex(RuntimeError, "ToDo-Lint"):
                    with self.fake_codex(lambda **_: self.fail("Dispatched before full-file lint")):
                        runner.run()
                self.assertEqual(runner.attempted, set())
                self.assertEqual(runner.reviewed_this_run, set())
                self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"],
                                 self.todo.read_text())
                runner.close()

    def test_invisible_headers_unicode_and_directive_scope(self):
        plan = ("\ufeff***SYNTAX marked-en***\r\n"
                "```markdown\r\n77. ***DONE***: Example.\r\n```\r\n"
                "<!--\r\n88. ***Task***: Hidden.\r\n-->\r\n"
                "1. ***Task***: Create café.txt.\r\n"
                "***CFG result_file=todo_result_02.md***\r\n"
                "***WAIT on=1 timeout=0s***\r\n"
                "2. ***Task***: Later.\r\n"
                "***STOP***\r\n"
                "3. ***Task***: Beyond stop.\r\n")
        self.todo.write_bytes(plan.encode("utf-8"))
        self.assertEqual(lint_todo_file(self.todo, workdir=self.work), [])
        runner = self.runner(stop_id="2")
        items = runner._parse_todo_file()
        self.assertEqual([x.identifier for x in items], ["1", "2", "3"])
        self.assertEqual(items[0].config, {})
        self.assertEqual(items[1].config["result_file"], "todo_result_02.md")
        self.assertEqual(items[1].wait_directives[0]["on"], "1")
        self.assertTrue(runner._stop_marker_before(items[2]))
        self.assertFalse(runner._stop_marker_before(items[1]))
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)

    def test_indented_markdown_code_example_is_not_executable(self):
        plan = ("***SYNTAX marked-en***\n\n"
                "Example:\n\n"
                "    77. ***DONE***: An indented Markdown code example.\n"
                "\t78. ***Task***: A tab-indented example.\n"
                "    ***STOP***\n\n"
                "    ```\n"
                "1. ***Task***: Create proof.txt.\n")
        self.write_plan(plan)
        self.assertEqual(lint_todo_file(self.todo, workdir=self.work), [])
        runner = self.runner(stop_id="1")
        self.assertEqual([item.identifier for item in runner._parse_todo_file()], ["1"])
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)

    def test_indented_directives_and_fence_do_not_change_next_task(self):
        plan = ("***SYNTAX marked-en***\n"
                "Example:\n"
                "   \t***WAIT on=99 timeout=0s***\n"
                "    ***CFG max_calls=1***\n"
                "    ```\n"
                "1. ***Task***: Create proof.txt.\n"
                "2. ***Task***: Create second.txt.\n")
        self.write_plan(plan)
        self.assertEqual(lint_todo_file(self.todo, workdir=self.work), [])
        runner = self.runner(stop_id="2")
        items = runner._parse_todo_file()
        self.assertEqual([item.identifier for item in items], ["1", "2"])
        self.assertEqual(items[0].wait_directives, [])
        self.assertEqual(items[0].config, {})
        self.assertEqual(items[1].config, {})
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)

    def test_stop_before_next_task_is_a_selection_boundary(self):
        plan = ("***SYNTAX marked-en***\n"
                "1. ***DONE***: Owner supplied baseline.\n"
                "***WAIT on=1 timeout=0s***\n"
                "***STOP***\n"
                "2. ***Task***: Must remain open.\n")
        self.write_plan(plan)
        self.assertEqual(lint_todo_file(self.todo, workdir=self.work), [])
        runner = self.runner()
        with self.fake_codex(lambda **_: self.fail("STOP selected a worker")):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertTrue(runner.stop_marker_triggered)
        self.assertEqual(runner.attempted, set())
        self.assertEqual(runner.reviewed_this_run, set())
        self.assertEqual(self.todo.read_text(), plan)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)

    def test_mutable_and_owner_adoption_are_audited_not_review_proofs(self):
        self.write_plan(OPEN)
        runner = self.runner(allow_todo_modifications=True, stop_id="1")
        changed = OPEN + "3. ***DONE***: Owner-enabled marker, never executed.\n"
        self.write_plan(changed)
        runner.plan_authority.check()
        record = runner.plan_authority.mutations[0]
        archive = record["archive"]
        self.assertEqual((Path(archive) / "before.md").read_text(), OPEN)
        self.assertEqual((Path(archive) / "after.md").read_text(), changed)
        self.assertFalse(json.loads((Path(archive) / "change.json").read_text())["independently_verified"])
        self.assertEqual(runner.reviewed_this_run, set())
        self.assertEqual(runner.attempted, set())
        runner.close()
        strict = self.runner(stop_id="1")
        strict.plan_authority.check()
        strict.close()
        adopted = changed.replace("Later.", "Owner revised later.")
        self.write_plan(adopted)
        with self.assertRaises(PlanIntegrityError):
            self.runner(stop_id="1")
        owner = self.runner(stop_id="1", accept_plan_changes=True)
        prior = list((owner.state_dir / "owner-adoptions").glob("*/previous-plan.md"))
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0].read_text(), changed)
        self.assertEqual(json.loads((owner.state_dir / "plan.json").read_text())["text"], adopted)
        self.assertEqual(owner.reviewed_this_run, set())

    def test_real_review_uses_original_requirement_and_strict_mutation_blocks_done(self):
        self.write_plan(OPEN)
        runner = self.runner(stop_id="1")
        phases = []

        def dispatch(**kwargs):
            phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                self.write_plan(OPEN.replace("containing original", "containing easier"))
                (self.work / "proof.txt").write_text("original\n", encoding="utf-8", newline="")
                return result("Created proof.txt")
            if kwargs["phase"] == "review":
                self.assertIn("containing original", extract_contract(kwargs["prompt"])["task_text"])
                return result(json.dumps(PASS))
            self.fail("Unexpected phase")

        with self.fake_codex(dispatch):
            runner.run()
        self.assertIn("auftrag", phases)
        self.assertNotEqual(runner.exit_code, 0)
        self.assertNotIn("1", runner.completed)
        self.assertNotIn("1", runner.reviewed_this_run)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], OPEN)
        self.assertEqual((self.work / "proof.txt").read_bytes(), b"original\n")

    def test_parallel_copy_change_cannot_be_synced_into_primary_authority(self):
        plan = ("***SYNTAX marked-en***\n"
                "***CFG parallel=group workspace=child***\n"
                "1. ***Task***: Write a result in child.\n")
        self.write_plan(plan)
        runner = self.runner(stop_id="1", allow_todo_modifications=True)
        context = runner._build_todo_execution_context(runner._parse_todo_file()[0])
        self.assertEqual(context.todo_file.read_text(), plan)

        def corrupt_copy(*args, **kwargs):
            context.todo_file.write_text(plan.replace("***Task***", "***DONE***"), newline="")
            context.result_file.write_text("Child result.\n", newline="")
            return run_todos.TaskOutcome(completed=True, message="synthetic review PASS")

        with patch.object(runner, "_run_autobuild_impl", side_effect=corrupt_copy):
            outcome = runner._run_autobuild("1", "Original task", todo_file_override=context.todo_file,
                                            workdir_override=context.workdir)
        self.assertFalse(outcome.completed)
        self.assertEqual(outcome.execution_error["code"], "unapproved_plan_mutation")
        self.assertEqual(self.todo.read_text(), plan)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], plan)
        self.assertEqual(runner.reviewed_this_run, set())
        runner.plan_authority.check()
        # A normal copied plan may return a report, but sync-back has no plan path.
        context.todo_file.write_text(plan, newline="")
        runner._sync_context_back_to_primary_workspace(context)
        self.assertEqual((self.work / "todo_result_1.md").read_text(), "Child result.\n")
        self.assertEqual(self.todo.read_text(), plan)
        runner.plan_authority.check()

    def test_bounded_mutable_planning_then_guarded_restart(self):
        plan = ("***SYNTAX marked-en***\n"
                "1. ***Task***: Append a later open task.\n"
                "2. ***Task***: Create second.txt.\n")
        appended = "3. ***Task***: Future work.\n"
        self.write_plan(plan)
        first = self.runner(allow_todo_modifications=True, stop_id="1")
        first_phases = []

        def plan_dispatch(**kwargs):
            first_phases.append(kwargs["phase"])
            if kwargs["phase"] == "auftrag":
                self.write_plan(plan + appended)
                return result("Added a future task")
            if kwargs["phase"] == "review":
                self.assertIn("Append a later open task", extract_contract(kwargs["prompt"])["task_text"])
                return result(json.dumps(PASS))
            self.fail("Unexpected phase")

        with self.fake_codex(plan_dispatch):
            first.run()
        self.assertEqual(first_phases, ["auftrag", "review"])
        self.assertEqual(first.exit_code, 0)
        self.assertEqual(first.reviewed_this_run, {"1"})
        self.assertEqual(first.attempted, {"1"})
        self.assertIn("1. ***DONE***", self.todo.read_text())
        self.assertIn(appended, self.todo.read_text())
        manifest = json.loads((first.run_dir / "run.json").read_text())
        self.assertEqual(manifest["reviewed_this_run"], ["1"])
        self.assertFalse(manifest["plan_mutations"][0]["independently_verified"])
        self.assertEqual(json.loads((first.state_dir / "plan.json").read_text())["text"],
                         self.todo.read_text())
        second = self.runner(stop_id="2")

        def work_dispatch(**kwargs):
            if kwargs["phase"] == "auftrag":
                (self.work / "second.txt").write_bytes(b"second\n")
                return result("Created second.txt")
            if kwargs["phase"] == "review":
                return result(json.dumps(PASS))
            self.fail("Unexpected phase")

        with self.fake_codex(work_dispatch):
            second.run()
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(second.reviewed_this_run, {"2"})
        self.assertEqual((self.work / "second.txt").read_bytes(), b"second\n")
        self.assertIn("3. ***Task***", self.todo.read_text())
        self.assertEqual(json.loads((second.state_dir / "plan.json").read_text())["text"],
                         self.todo.read_text())
