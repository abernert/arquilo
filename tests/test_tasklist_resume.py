# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""CLI resume phases through the real controller and synthetic native processes.

The temporary Python child stands in for the model CLI. No provider, user
workspace, private recovery archive or existing repository is accessed.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import arquilo
import autobuild
from autobuild_contract import validate_result
import codex_transport as transport
from controller_state import PlanAuthority, state_directory
from execution_budget import CallBudget
import mcp_selection
import run_todos
from test_reconnect_stop import ANSWER, COMPLETE, FAILED, PASS, FAIL, answer
from test_reconnect_stop_controller import ControllerFixture
from test_claude_backend import Fixture as ClaudeFixture

PLAN = (
    "134. ***TASK***: Earlier unselected task.\n"
    "135. ***TASK***: Inspect the existing result and deliver result-135.txt.\n"
    "136. ***TASK***: Deliver result-136.txt.\n"
    "137. ***TASK***: Deliver result-137.txt.\n"
    "138. ***TASK***: Later unselected task.\n"
)


def passing():
    return {"events": [answer(json.dumps(PASS)), COMPLETE]}


def production():
    return {"events": [ANSWER, COMPLETE]}


class TasklistResumeTests(ControllerFixture):
    def setUp(self):
        super().setUp()
        self.todo.write_text(PLAN, encoding="utf-8")
        self.root = self.base / "private-state"
        self.last_output = ""
        self.last_calls = []
        self.last_contexts = []

    def arguments(self, mode="resume-review", *, start="135", stop="137", max_steps=1,
                  max_calls=12, extra=()):
        args = ["tasklist", "run", "--workdir", str(self.work), "--todo-file", str(self.todo),
                "--state-dir", str(self.root), "--max-steps", str(max_steps),
                "--max-retries", "1", "--max-calls", str(max_calls),
                "--breakdown-policy", "off", "--process-stop-policy", "controller-only",
                "--skip-backend-preflight", "--prompt-config", "en"]
        if start is not None:
            args += ["--start", start]
        if stop is not None:
            args += ["--stop", stop]
        if mode:
            args.append("--" + mode)
        return [*args, *extra]

    def invoke(self, scenarios, *, args=None, callback=None):
        calls = []
        contexts = []
        run = autobuild.run_codex_exec_json
        start = run_todos.autobuild_start

        def record(**kwargs):
            calls.append(dict(kwargs))
            result = run(**dict(kwargs, timeouts=transport.TransportTimeouts(
                total=8, stall=4, post_turn_grace=1, kill_grace=.05)))
            if callback is not None:
                callback(kwargs, result)
            return result

        def record_context(*args, **kwargs):
            contexts.append(kwargs["context"])
            return start(*args, **kwargs)

        output = io.StringIO()
        with self.launch(scenarios) as launched, \
                patch.object(autobuild, "run_codex_exec_json", side_effect=record), \
                patch.object(run_todos, "autobuild_start", side_effect=record_context), \
                redirect_stdout(output), redirect_stderr(output):
            try:
                code = arquilo.main(self.arguments() if args is None else args)
            except SystemExit as exc:
                code = exc.code
        self.last_output = output.getvalue()
        self.last_calls = calls
        self.last_contexts = contexts
        self.assertEqual(launched.call_count, len(calls), self.last_output)
        return code

    def phases(self):
        return [(call["console_todo_id"], call["phase"]) for call in self.last_calls]

    def summaries(self, task="135"):
        found = sorted(self.root.glob(f"*/runs/*/task-{task}/autobuild_summary.json"))
        return [validate_result(json.loads(path.read_text(encoding="utf-8"))) for path in found]

    def assert_status(self, task, status):
        lines = run_todos._todo_line_map(self.todo.read_text(encoding="utf-8"))
        self.assertEqual(lines[task][0], "Auftrag" if status == "TASK" else status, self.last_output)

    def assert_no_model_or_status_change(self, args):
        original = self.todo.read_bytes()
        self.assertNotEqual(self.invoke([], args=args), 0, self.last_output)
        self.assertEqual(self.phases(), [], self.last_output)
        self.assertEqual(self.todo.read_bytes(), original)

    def test_review_start_135_then_136_and_137_run_normally(self):
        code = self.invoke([passing(), production(), passing(), production(), passing()])
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review"), ("136", "auftrag"), ("136", "review"),
                                        ("137", "auftrag"), ("137", "review")])
        self.assertEqual([context.entry_mode for context in self.last_contexts],
                         ["resume-review", "normal", "normal"])
        self.assertIn("[ARQUILO resume-review]", self.last_calls[0]["prompt"])
        self.assertNotIn("[ARQUILO resume-review]", self.last_calls[1]["prompt"])
        self.assertEqual(self.last_calls[0]["sandbox"], "read-only")
        for task in ("135", "136", "137"):
            self.assert_status(task, "DONE")
        for task in ("134", "138"):
            self.assert_status(task, "TASK")
        summary = self.summaries()[0]
        self.assertEqual((summary["auftrag_runs"], summary["review_runs"]), (0, 1))
        self.assertEqual(summary["call_budget"]["used"], 1)
        self.assertEqual([item["phase"] for item in summary["execution_attempts"]], ["review"])
        self.assertEqual(summary["terminal_attempt"]["phase"], "review")

    def test_resume_task_continuation_is_only_for_exact_first_task(self):
        report = self.work / "todo_result_135.md"
        report.write_text("Historical partial result; verify before reuse.\n", encoding="utf-8")
        code = self.invoke([production(), passing(), production(), passing(), production(), passing()],
                           args=self.arguments("resume-task"))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "auftrag"), ("135", "review"),
                                        ("136", "auftrag"), ("136", "review"),
                                        ("137", "auftrag"), ("137", "review")])
        self.assertEqual([context.entry_mode for context in self.last_contexts],
                         ["resume-task", "normal", "normal"])
        self.assertIn("[ARQUILO resume-task]", self.last_calls[0]["prompt"])
        self.assertIn("todo_result_135.md", self.last_calls[0]["prompt"])
        self.assertNotIn("[ARQUILO resume-task]", self.last_calls[2]["prompt"])
        self.assertNotIn("[ARQUILO resume-task]", self.last_calls[4]["prompt"])
        self.assertEqual(self.summaries()[0]["auftrag_runs"], 1)
        contracts = list(self.root.glob("*/runs/*/task-135/review_contract_*.json"))
        self.assertEqual(len(contracts), 1)
        original = json.loads(contracts[0].read_text(encoding="utf-8"))["original_request"]
        self.assertNotIn("[ARQUILO resume-task]", original)
        historical = list(self.root.glob("*/runs/*/task-135/inputs/todo_result_135.md"))
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0].read_bytes(), report.read_bytes())

    def test_review_fail_uses_one_fix_then_review_with_max_steps_one(self):
        code = self.invoke([{"events": [answer(json.dumps(FAIL)), COMPLETE]}, production(), passing(),
                            production(), passing(), production(), passing()])
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases()[:3], [("135", "review"), ("135", "fix"), ("135", "review")])
        self.assertEqual(self.phases()[3:], [("136", "auftrag"), ("136", "review"),
                                           ("137", "auftrag"), ("137", "review")])
        self.assertIn("Missing output.", self.last_calls[1]["prompt"])
        summary = self.summaries()[0]
        self.assertEqual((summary["auftrag_runs"], summary["review_runs"]), (1, 2))
        self.assertEqual(summary["call_budget"]["used"], 3)
        self.assert_status("135", "DONE")

    def test_repeated_valid_fail_stops_at_fix_limit_without_next_task(self):
        negative = {"events": [answer(json.dumps(FAIL)), COMPLETE]}
        code = self.invoke([negative, production(), negative])
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review"), ("135", "fix"), ("135", "review")])
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")
        self.assertEqual(self.summaries()[0]["auftrag_runs"], 1)

    def test_technical_review_failure_does_not_trigger_fix_or_follow_on(self):
        code = self.invoke([{"events": [FAILED], "exit": 1}])
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")
        summary = self.summaries()[0]
        self.assertFalse(summary["completed"])
        self.assertEqual(summary["auftrag_runs"], 0)
        self.assertIsNotNone(summary["execution_error"])

    def test_invalid_review_cannot_trigger_fix_or_done(self):
        code = self.invoke([{"events": [answer('{"verdict":"PASS"}'), COMPLETE]}])
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assertEqual(self.summaries()[0]["execution_error"]["code"], "invalid_review")
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")

    def test_nonzero_review_exit_overrides_pass_text(self):
        code = self.invoke([{**passing(), "exit": 1}])
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assertFalse(self.summaries()[0]["completed"])
        self.assert_status("135", "TASK")

    def test_active_root_stop_blocks_before_model(self):
        self.stop.write_text("Operator paused this runner.\n", encoding="utf-8")
        self.assert_no_model_or_status_change(self.arguments())
        self.assertEqual(self.stop.read_text(encoding="utf-8"), "Operator paused this runner.\n")

    def test_stop_during_review_blocks_acceptance_and_follow_on(self):
        def stop(_kwargs, _result):
            self.stop.write_text("Operator pause during review.\n", encoding="utf-8")
        code = self.invoke([passing()], callback=stop)
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")
        self.assertTrue(self.summaries()[0]["process_stop_triggered"])

    def test_existing_budget_claims_survive_review_start(self):
        state = state_directory(self.work, self.todo, self.root)
        budget = CallBudget(state / "call_budgets" / "task_135", 3, "135")
        budget.consume("135", "completion:auftrag")
        budget.consume("135", "completion:review")
        before = {p.name: p.read_bytes() for p in budget.directory.glob("call_*.json")}
        code = self.invoke([passing()], args=self.arguments(stop="135", max_calls=3))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assertEqual(self.summaries()[0]["call_budget"]["used"], 3)
        self.assertEqual({name: (budget.directory / name).read_bytes() for name in before}, before)
        self.assert_status("135", "DONE")

    def test_exhausted_budget_is_not_reset_by_resume(self):
        state = state_directory(self.work, self.todo, self.root)
        budget = CallBudget(state / "call_budgets" / "task_135", 1, "135")
        budget.consume("135", "completion:auftrag")
        self.assert_no_model_or_status_change(self.arguments(max_calls=1))
        self.assertEqual(budget.snapshot()["used"], 1)
        self.assert_status("136", "TASK")

    def test_model_and_selected_review_resources_are_preserved(self):
        skills = self.base / "operator-skills"
        skill = skills / "inspect" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: inspect\ndescription: Synthetic inspection skill.\n---\n"
                         "SYNTHETIC-SKILL-EVIDENCE: inspect current outputs.\n", encoding="utf-8")
        args = self.arguments(stop="135", extra=["--model", "synthetic-model", "--reasoning-effort", "medium",
            "--mcp", "writer,reader", "--review-mcp", "reader", "--skills", "inspect", "--skill-dir", str(skills)])
        with patch.object(mcp_selection, "resolve_inventory", return_value=("writer", "reader")):
            code = self.invoke([passing()], args=args)
        self.assertEqual(code, 0, self.last_output)
        call = self.last_calls[0]
        self.assertEqual(call["model"], "synthetic-model")
        self.assertEqual(call["reasoning_effort"], "medium")
        self.assertEqual(call["mcp_servers"], ("reader",))
        self.assertIn("SYNTHETIC-SKILL-EVIDENCE", call["prompt"])
        self.assertEqual(call["sandbox"], "read-only")

    def test_unfinished_history_and_old_test_cache_do_not_block_current_review(self):
        state = state_directory(self.work, self.todo, self.root)
        archive = state / "runs" / "2026-01-01T00-00-00.000Z" / "task-135"
        archive.mkdir(parents=True)
        unfinished = archive / "autobuild_summary.json"
        unfinished.write_text('{"completed":', encoding="utf-8")
        raw = archive / "autobuild_raw.jsonl"
        raw.write_text('{"type":"turn.started"}\n', encoding="utf-8")
        old_cache = self.work / "test-work" / "task-90" / "uv-cache" / "sdists-v10"
        old_cache.mkdir(parents=True)
        git_file = old_cache / ".git"
        git_file.write_text("gitdir: no-longer-existing-repository\n", encoding="utf-8")
        nested_stop = old_cache / "process_stop"
        nested_stop.write_text("Historical STOP fixture.\n", encoding="utf-8")
        report = self.work / "todo_result_135.md"
        report.write_text("Partial evidence; the prior process ended unexpectedly.\n", encoding="utf-8")
        preserved = {p: p.read_bytes() for p in (unfinished, raw, git_file, nested_stop, report)}
        code = self.invoke([passing()], args=self.arguments(stop="135"))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assertEqual({p: p.read_bytes() for p in preserved}, preserved)
        self.assert_status("135", "DONE")

    def test_missing_archive_and_response_are_not_required_for_fresh_review(self):
        self.assertFalse(self.root.exists())
        code = self.invoke([passing()], args=self.arguments(stop="135"))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assert_status("135", "DONE")

    def test_exact_done_start_does_not_shift_resume_to_next_open_task(self):
        self.todo.write_text(PLAN.replace("135. ***TASK***", "135. ***DONE***"), encoding="utf-8")
        self.assert_no_model_or_status_change(self.arguments())
        self.assert_status("136", "TASK")

    def test_exact_obsolete_start_does_not_shift_resume_to_next_open_task(self):
        self.todo.write_text(PLAN.replace("135. ***TASK***", "135. ***OBSOLETE***"), encoding="utf-8")
        self.assert_no_model_or_status_change(self.arguments("resume-task"))
        self.assert_status("136", "TASK")

    def test_unknown_start_is_rejected_before_model(self):
        self.assert_no_model_or_status_change(self.arguments(start="999"))

    def test_resume_requires_explicit_start(self):
        self.assert_no_model_or_status_change(self.arguments(start=None))

    def test_resume_flags_are_mutually_exclusive(self):
        self.assert_no_model_or_status_change(self.arguments(extra=["--resume-task"]))

    def test_reversed_range_is_rejected_before_model(self):
        self.assert_no_model_or_status_change(self.arguments(start="137", stop="135"))

    def test_start_beyond_max_depth_refuses_before_backend_preflight(self):
        self.todo.write_text("135. ***DONE***: Earlier parent.\n"
            "135.1. ***TASK***: Selected nested task.\n"
            "136. ***TASK***: Later task.\n", encoding="utf-8")
        args = self.arguments(start="135.1", stop="136", extra=["--max-depth", "1"])
        args.remove("--skip-backend-preflight")
        with patch.object(run_todos, "run_codex_workspace_write_preflight") as preflight, \
                patch.object(run_todos, "run_runtime_profile_preflight") as profile:
            self.assert_no_model_or_status_change(args)
        preflight.assert_not_called()
        profile.assert_not_called()
        self.assertIn("max-depth", self.last_output)

    def test_parent_with_open_descendant_refuses_before_backend_preflight(self):
        for child_status in ("TASK", "OBSOLETE"):
            self.todo.write_text("135. ***TASK***: Parent still requires its child.\n"
                f"135.1. ***{child_status}***: Child without a successful acceptance.\n"
                "136. ***TASK***: Later task.\n", encoding="utf-8")
            for mode in ("resume-task", "resume-review"):
                with self.subTest(mode=mode, child_status=child_status):
                    args = self.arguments(mode, stop="136")
                    args.remove("--skip-backend-preflight")
                    with patch.object(run_todos, "run_codex_workspace_write_preflight") as preflight:
                        self.assert_no_model_or_status_change(args)
                    preflight.assert_not_called()
                    self.assertIn("descendants", self.last_output)

    def test_resumed_subworkspace_retains_newer_local_report_before_archiving(self):
        self.todo.write_text("***CFG workspace=one***\n"
            "135. ***TASK***: Inspect the existing result in one.\n"
            "136. ***TASK***: Later task.\n", encoding="utf-8")
        primary = self.work / "todo_result_135.md"
        primary.write_text("Older report copied before the interrupted attempt.\n", encoding="utf-8")
        local = self.work / "one" / "todo_result_135.md"
        local.parent.mkdir()
        latest = "Newer partial work from the interrupted attempt; verify this current result.\n"
        local.write_text(latest, encoding="utf-8")
        questions = self.work / "todo_fragen.md"
        questions.write_text("Older shared questions.\n", encoding="utf-8")
        local_questions = local.parent / "todo_fragen.md"
        newer_questions = "Newer local question evidence from the interrupted attempt.\n"
        local_questions.write_text(newer_questions, encoding="utf-8")
        seen = []
        def inspect_current(kwargs, _result):
            seen.append((kwargs["cwd"], local.read_text(encoding="utf-8"),
                         local_questions.read_text(encoding="utf-8")))
        code = self.invoke([passing()], args=self.arguments(stop="135"), callback=inspect_current)
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(seen, [(local.parent, latest, newer_questions)])
        self.assertEqual(local.read_text(encoding="utf-8"), latest)
        self.assertEqual(primary.read_text(encoding="utf-8"), latest)
        self.assertEqual(questions.read_text(encoding="utf-8"), newer_questions)
        history = list(self.root.glob("*/runs/*/task-135/inputs/todo_result_135.md"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].read_text(encoding="utf-8"), latest)
        self.assert_status("135", "DONE")

    def test_missing_exact_report_is_not_replaced_by_a_nested_test_report(self):
        nested = self.work / "test-work" / "historical" / "todo_result_135.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("WRONG-REPORT: unrelated historical synthetic evidence.\n", encoding="utf-8")
        selected = self.work / "todo_result_135.md"
        self.assertFalse(selected.exists())
        with patch.object(run_todos.TodoRunner, "_locate_workspace_result_file",
                          side_effect=AssertionError("Resume must use the exact result path")):
            code = self.invoke([passing()], args=self.arguments(stop="135"))
        self.assertEqual(code, 0, self.last_output)
        contexts = list(self.root.glob("*/runs/*/task-135/resume_context.json"))
        self.assertEqual(len(contexts), 1)
        context = json.loads(contexts[0].read_text(encoding="utf-8"))
        self.assertEqual(context["result_file"], str(selected))
        self.assertFalse(context["result_present"])
        self.assertIsNone(context["archived_result"])
        self.assertNotIn("WRONG-REPORT", self.last_calls[0]["prompt"])
        self.assertEqual(nested.read_text(encoding="utf-8"),
                         "WRONG-REPORT: unrelated historical synthetic evidence.\n")

    def test_serial_resumed_member_does_not_satisfy_group_wait_before_peer_finishes(self):
        self.todo.write_text("***CFG workspace=one parallel=pair***\n"
            "135. ***TASK***: Inspect existing result in one.\n"
            "***CFG workspace=two parallel=pair***\n"
            "136. ***TASK***: Produce result in two.\n"
            "***WAIT on=group:pair timeout=0 on_timeout=stop***\n"
            "137. ***TASK***: Only start after the group is finished.\n", encoding="utf-8")
        handle = run_todos.TodoRunner._handle_todo
        group_states = []
        def observe(runner, todo):
            outcome = handle(runner, todo)
            if todo.identifier == "135":
                group_states.append(runner._wait_condition_is_met("group:pair"))
            return outcome
        with patch.object(run_todos.TodoRunner, "_handle_todo", observe):
            code = self.invoke([passing(), production(), passing(), production(), passing()])
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(group_states, [False])
        self.assertEqual(self.phases(), [("135", "review"), ("136", "auftrag"), ("136", "review"),
                                        ("137", "auftrag"), ("137", "review")])
        for task in ("135", "136", "137"):
            self.assert_status(task, "DONE")

    def test_unselected_or_later_same_named_groups_do_not_hold_resumed_group_open(self):
        self.todo.write_text("***CFG workspace=earlier parallel=pair***\n"
            "134. ***TASK***: Unselected earlier group member.\n"
            "***CFG workspace=one parallel=pair***\n"
            "135. ***TASK***: Last selected member of this contiguous group.\n"
            "***WAIT on=group:pair timeout=0 on_timeout=stop***\n"
            "136. ***TASK***: Start after the selected group is finished.\n"
            "137. ***TASK***: Last selected task.\n"
            "***CFG workspace=later parallel=pair***\n"
            "138. ***TASK***: Unselected later group with the same name.\n", encoding="utf-8")
        code = self.invoke([passing(), production(), passing(), production(), passing()])
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review"), ("136", "auftrag"), ("136", "review"),
                                        ("137", "auftrag"), ("137", "review")])
        self.assert_status("134", "TASK")
        self.assert_status("138", "TASK")
        self.assert_status("136", "DONE")

    def test_parent_with_done_children_can_enter_review_with_matching_saved_plan(self):
        self.todo.write_text("135. ***TASK***: Parent awaits acceptance.\n"
            "135.1. ***DONE***: Previously accepted child.\n"
            "136. ***TASK***: Later task.\n", encoding="utf-8")
        state = state_directory(self.work, self.todo, self.root)
        saved = state / "breakdowns" / "135" / "breakdown_plan.json"
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps({"schema_version": "run_todos.breakdown.v3", "parent_id": "135",
                                     "children": [{"id": "135.1"}], "round": 1}), encoding="utf-8")
        before = saved.read_bytes()
        code = self.invoke([passing(), production(), passing()], args=self.arguments(stop="136"))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review"), ("136", "auftrag"), ("136", "review")])
        self.assert_status("135", "DONE")
        self.assert_status("135.1", "DONE")
        self.assertEqual(saved.read_bytes(), before)

    def test_mismatched_saved_child_plan_is_not_bypassed_by_explicit_resume(self):
        self.todo.write_text("135. ***TASK***: Parent awaits acceptance.\n"
            "135.1. ***DONE***: Previously accepted child.\n"
            "136. ***TASK***: Later task.\n", encoding="utf-8")
        state = state_directory(self.work, self.todo, self.root)
        saved = state / "breakdowns" / "135" / "breakdown_plan.json"
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps({"schema_version": "run_todos.breakdown.v3", "parent_id": "135",
                                     "children": [{"id": "135.2"}], "round": 1}), encoding="utf-8")
        self.assert_no_model_or_status_change(self.arguments(stop="136"))
        self.assert_status("135", "TASK")

    def test_resume_review_breakdown_finishes_child_and_parent_before_sibling(self):
        decompose = json.loads(json.dumps(FAIL))
        decompose["blocking_issues"][0]["type"] = "decomposition_needed"
        decompose.update(breakdown_recommended=True, breakdown_reason="Separate remaining child work.")
        args = self.arguments()
        args[args.index("--breakdown-policy") + 1] = "minimal"
        checked_parent = []
        def produce_child(kwargs, _result):
            identifier = kwargs["console_todo_id"]
            if identifier == "135-breakdown" and kwargs["phase"] == "auftrag":
                text = self.todo.read_text(encoding="utf-8")
                text = text.replace("136. ***TASK***", "135.1. ***TASK***: Finish remaining output.\n136. ***TASK***")
                self.todo.write_text(text, encoding="utf-8")
            if identifier == "136":
                statuses = run_todos._todo_line_map(self.todo.read_text(encoding="utf-8"))
                checked_parent.append((statuses["135"][0], statuses["135.1"][0]))
        scenarios = [{"events": [answer(json.dumps(decompose)), COMPLETE]},
                     production(), passing(),  # Reviewed breakdown creates the child.
                     production(), passing(),  # Child implementation and review.
                     passing(), passing(),     # Parent acceptance task and its review.
                     production(), passing(), production(), passing()]
        code = self.invoke(scenarios, args=args, callback=produce_child)
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review"), ("135-breakdown", "auftrag"),
            ("135-breakdown", "review"), ("135.1", "auftrag"), ("135.1", "review"),
            ("135-review", "auftrag"), ("135-review", "review"),
            ("136", "auftrag"), ("136", "review"), ("137", "auftrag"), ("137", "review")])
        self.assertEqual(checked_parent, [("DONE", "DONE"), ("DONE", "DONE")])
        self.assertEqual([context.entry_mode for context in self.last_contexts],
                         ["resume-review", "normal", "normal", "normal", "normal", "normal"])
        self.assert_status("135", "DONE")
        self.assert_status("135.1", "DONE")

    def test_mutable_resume_target_edit_after_pass_is_not_accepted_even_at_stop(self):
        def change_contract(_kwargs, _result):
            text = self.todo.read_text(encoding="utf-8")
            self.todo.write_text(text.replace("deliver result-135.txt.", "deliver different-result.txt."),
                                 encoding="utf-8")
        code = self.invoke([passing()], callback=change_contract,
                           args=self.arguments(stop="135", extra=["--allow-todo-modifications"]))
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")
        runs = list(self.root.glob("*/runs/*/run.json"))
        self.assertEqual(len(runs), 1)
        record = json.loads(runs[0].read_text(encoding="utf-8"))
        self.assertEqual(record["execution_error"]["code"], "resume_target_changed")
        self.assertEqual(record["reviewed_this_run"], [])
        self.assertIn("different-result.txt", self.todo.read_text(encoding="utf-8"))

    def test_mutable_resume_target_removal_after_pass_does_not_start_next_task(self):
        def remove_contract(_kwargs, _result):
            rows = self.todo.read_text(encoding="utf-8").splitlines(keepends=True)
            self.todo.write_text("".join(row for row in rows if not row.startswith("135.")), encoding="utf-8")
        code = self.invoke([passing()], callback=remove_contract,
                           args=self.arguments(extra=["--allow-todo-modifications"]))
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assertNotIn("135", run_todos._todo_line_map(self.todo.read_text(encoding="utf-8")))
        self.assert_status("136", "TASK")
        runs = list(self.root.glob("*/runs/*/run.json"))
        self.assertEqual(len(runs), 1)
        record = json.loads(runs[0].read_text(encoding="utf-8"))
        self.assertEqual(record["execution_error"]["code"], "resume_target_changed")
        self.assertEqual(record["reviewed_this_run"], [])

    def test_resume_dry_runs_show_entry_without_model_or_controller_state_writes(self):
        initial_plan = self.todo.read_bytes()
        for mode in ("resume-task", "resume-review"):
            with self.subTest(mode=mode):
                report = self.base / (mode + "-preview.md")
                code = self.invoke([], args=self.arguments(mode, stop="135", extra=[
                    "--dry-run", "--dry-run-file", str(report)]))
                self.assertEqual(code, 0, self.last_output)
                self.assertEqual(self.phases(), [])
                self.assertEqual(self.todo.read_bytes(), initial_plan)
                self.assertFalse(self.root.exists())
                preview = report.read_text(encoding="utf-8")
                self.assertIn("entry_mode=" + repr(mode), preview)
                self.assertIn("[ARQUILO " + mode + "]", preview)

    def test_normal_run_keeps_existing_skip_done_semantics(self):
        self.todo.write_text(PLAN.replace("135. ***TASK***", "135. ***DONE***"), encoding="utf-8")
        code = self.invoke([production(), passing(), production(), passing()], args=self.arguments(mode=None))
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("136", "auftrag"), ("136", "review"),
                                        ("137", "auftrag"), ("137", "review")])
        self.assertEqual([context.entry_mode for context in self.last_contexts], ["normal", "normal"])

    def test_live_controller_lock_is_not_bypassed_by_resume(self):
        state = state_directory(self.work, self.todo, self.root)
        owner = PlanAuthority(self.todo, state, workspace=self.work)
        try:
            self.assert_no_model_or_status_change(self.arguments())
        finally:
            owner.close()

    def test_review_resume_survives_real_private_worker_payload(self):
        output = io.StringIO()
        execute = run_todos.TodoRunner._execute_todo_autobuild
        def worker(runner, todo, **kwargs):
            return execute(runner, todo, **dict(kwargs, use_cli_subprocess=True))
        with self.native_worker([passing()]) as workers, \
                patch.object(run_todos.TodoRunner, "_execute_todo_autobuild", worker), \
                redirect_stdout(output), redirect_stderr(output):
            code = arquilo.main(self.arguments(stop="135"))
        self.last_output = output.getvalue()
        self.assertEqual(code, 0, self.last_output)
        self.assertEqual(len(workers), 1)
        requests = list(self.root.glob("*/worker_calls/*/request.json"))
        self.assertEqual(len(requests), 1)
        request = json.loads(requests[0].read_text(encoding="utf-8"))
        self.assertEqual(request["context"]["entry_mode"], "resume-review")
        summary = self.summaries()[0]
        self.assertEqual((summary["auftrag_runs"], summary["review_runs"]), (0, 1))
        self.assertEqual(summary["call_budget"]["used"], 1)
        self.assertEqual([item["phase"] for item in summary["execution_attempts"]], ["review"])
        self.assert_status("135", "DONE")

    def test_parallel_label_on_start_task_does_not_dispatch_peer_before_acceptance(self):
        self.todo.write_text("***CFG workspace=one parallel=pair***\n"
            "135. ***TASK***: Inspect existing result in one.\n"
            "***CFG workspace=two parallel=pair***\n"
            "136. ***TASK***: Produce result in two.\n"
            "137. ***TASK***: Final normal task.\n", encoding="utf-8")
        code = self.invoke([{"events": [FAILED], "exit": 1}])
        self.assertNotEqual(code, 0, self.last_output)
        self.assertEqual(self.phases(), [("135", "review")])
        self.assert_status("135", "TASK")
        self.assert_status("136", "TASK")
        self.assert_status("137", "TASK")


class ClaudeTasklistResumeTests(ClaudeFixture):
    def invoke(self, mode="resume-review", *, stop="137"):
        self.todo = self.work / "tasks.md"
        self.todo.write_text(PLAN, encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = arquilo.main(["tasklist", "run", "--backend", "claude-code",
                "--workdir", str(self.work), "--todo-file", str(self.todo),
                "--state-dir", str(self.base / "state"), "--start", "135", "--stop", stop,
                "--" + mode, "--max-steps", "1", "--max-retries", "1", "--max-calls", "12",
                "--breakdown-policy", "off", "--process-stop-policy", "controller-only",
                "--skip-backend-preflight", "--prompt-config", "en"])
        self.assertEqual(code, 0, output.getvalue())
        return self.rows()

    def test_claude_review_entry_and_follow_on_without_codex(self):
        rows = self.invoke()
        self.assertEqual(len(rows), 5)
        self.assertEqual(["Write" in row["tools"] for row in rows], [False, True, False, True, False])
        self.assertIn("[ARQUILO resume-review]", rows[0]["prompt"])
        self.assertNotIn("[ARQUILO resume-review]", rows[1]["prompt"])
        summaries = list((self.base / "state").glob("*/runs/*/task-135/autobuild_summary.json"))
        self.assertEqual(len(summaries), 1)
        summary = validate_result(json.loads(summaries[0].read_text(encoding="utf-8")))
        self.assertEqual(summary["backend"], "claude-code")
        self.assertEqual((summary["auftrag_runs"], summary["review_runs"]), (0, 1))
        self.assertEqual(summary["call_budget"]["used"], 1)

    def test_claude_review_fail_then_fix_obeys_production_limit(self):
        self.mode("fix_cycle")
        rows = self.invoke(stop="135")
        self.assertEqual(len(rows), 3)
        self.assertEqual(["Write" in row["tools"] for row in rows], [False, True, False])
        statuses = run_todos._todo_line_map(self.todo.read_text(encoding="utf-8"))
        self.assertEqual(statuses["135"][0], "DONE")
        self.assertEqual(statuses["136"][0], "Auftrag")

    def test_claude_task_continuation_only_on_first_selected_task(self):
        rows = self.invoke("resume-task")
        self.assertEqual(len(rows), 6)
        self.assertEqual(["Write" in row["tools"] for row in rows], [True, False, True, False, True, False])
        self.assertIn("[ARQUILO resume-task]", rows[0]["prompt"])
        self.assertNotIn("[ARQUILO resume-task]", rows[2]["prompt"])
        self.assertNotIn("[ARQUILO resume-task]", rows[4]["prompt"])


if __name__ == "__main__":
    unittest.main()
