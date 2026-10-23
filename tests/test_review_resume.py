#!/usr/bin/env python3
"""Public offline regressions: generic Codex retry notices and reviewed continuation."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import review_resume as recovery
import autobuild
import codex_transport
from autobuild_contract import AutoBuildOptions, AutoBuildContext, validate_result
from decision_exec import DecisionCall
from runtime_contracts import DecisionResult, ExecutionResult, ExecutionStatus

OLD = {"type":"error", "message":"Reconnecting... 2/12 (stream disconnected before completion: websocket closed by server before response.completed)"}
NEW = {"type":"error", "message":"Reconnecting... 1/12 (stream disconnected before completion: stream closed before response.completed)"}
BODY = {"type":"error", "message":"Reconnecting... 1/12 (stream disconnected before completion: Transport error: network error: error decoding response body)"}
PASS = {"verdict":"PASS", "short_summary":"Synthetic review accepted the artifacts",
        "blocking_issues":[], "non_blocking_observations":[], "breakdown_recommended":False,
        "breakdown_reason":None}
PROMPT="Synthetic saved production request."
ANSWER="Synthetic final production answer."

def event_bytes(events):
    return b"".join((json.dumps(x,ensure_ascii=False)+"\n").encode() for x in events)

class Fixture(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.work=self.home/"workspace"; self.work.mkdir()
        self.capture=self.work/".codex_runs/run_todos/2026-10-18T15-37-47.993Z/task-2/001-production"
        self.capture.mkdir(parents=True)
        self.dir=self.capture.parent
        (self.dir/"prompt.md").write_text(PROMPT,encoding="utf-8")
        (self.dir/"original_contract.json").write_text(json.dumps({
            "schema_version":"arquilo.review_contract.v1","original_request":PROMPT,
            "task_text":PROMPT, "source":str(self.work/"tasks.md")}),encoding="utf-8")
        self.events=[{"type":"thread.started"},{"type":"turn.started"},NEW,
            {"type":"item.completed","item":{"type":"agent_message","text":ANSWER}},
            {"type":"turn.completed"}]
        self.capture_info={
            "schema_version":"arquilo.codex.io_capture.v1",
            "phase":"auftrag","cwd":str(self.work),
            "status":"failed","completion_seen":True,"process_exit_code":0,
            "process_stop_triggered":False,"error":{"code":"codex_stream_error"},
            "stream_errors":[NEW],"stream_diagnostics":[],
            "stdout":{"complete":True},"stderr":{"complete":True},"stdin":{"complete":True}
        }
        self.write_archive()

    def write_archive(self):
        stdout=event_bytes(self.events)
        prompt_bytes=PROMPT.encode("utf-8")
        self.capture_info["stdout"].update(
            archived_bytes=len(stdout),received_bytes=len(stdout))
        self.capture_info["stdin"].update(
            expected_bytes=len(prompt_bytes),archived_bytes=len(prompt_bytes),
            written_bytes=len(prompt_bytes))
        (self.capture/"capture.json").write_text(json.dumps(self.capture_info),encoding="utf-8")
        (self.capture/"stdout.bin").write_bytes(stdout)
        (self.capture/"prompt.utf8").write_bytes(prompt_bytes)
        (self.capture/"response.txt").write_text(ANSWER,encoding="utf-8")
        (self.dir/"autobuild_summary.json").write_text(json.dumps({
            "completed":False,"auftrag_runs":1,"review_runs":0,
            "execution_error":{"code":"codex_stream_error"},
            "terminal_attempt":{"phase":"task","index":1,
                "capture_directory":str(self.capture)}
        }),encoding="utf-8")

    def recover(self):
        return recovery.load_verified_recovery(self.capture, self.work, "2")

class ClassifierTests(unittest.TestCase):
    def test_all_known_retry_variants_are_diagnostics_only(self):
        for event in (OLD, NEW, BODY):
            with self.subTest(event=event["message"]):
                self.assertTrue(recovery.is_transient_retry_notice(event,terminal_seen=False))
                self.assertFalse(recovery.is_transient_retry_notice(event,terminal_seen=True))

    def test_invalid_or_unrelated_errors_remain_fatal(self):
        invalid=[{},None,[],{"type":"error","message":"401 Unauthorized"},
          {**NEW,"code":500}, {**NEW,"message":NEW["message"]+" malicious"},
          {**NEW,"message":NEW["message"].replace("1/12","12/1")},
          {**NEW,"message":NEW["message"].replace("1/12","0/12")},
          {**NEW,"message":NEW["message"].replace("1/12","1/1001")},
          {**NEW,"message":NEW["message"].replace("Reconnecting","Reconnected")},
          {"type":"turn.failed","message":NEW["message"]},
          {**NEW,"message":"Reconnecting... 1/12 (401 Unauthorized)"}]
        for event in invalid:
            self.assertFalse(recovery.is_transient_retry_notice(event, terminal_seen=False))

    def test_real_collector_does_not_propagate_recovered_notice(self):
        with tempfile.TemporaryDirectory() as d:
            trace=codex_transport.RunResult()
            with patch.object(codex_transport,"is_transient_reconnect",recovery.is_transient_retry_notice):
                for event in (NEW,{"type":"item.completed","item":{"type":"agent_message","text":ANSWER}},
                              {"type":"turn.completed"}):
                    codex_transport.handle_event(event,trace,Path(d)/"pretty.log",Path(d)/"raw.jsonl")
            trace.process_exit_code=0
            self.assertTrue(trace.turn_completed)
            self.assertEqual(trace.stream_errors, [])
            self.assertEqual(len(trace.stream_diagnostics),1)
            self.assertIsNone(codex_transport.fatal_run_error(trace))

    def test_final_failure_overrides_prior_retry(self):
        with tempfile.TemporaryDirectory() as d:
            trace=codex_transport.RunResult()
            with patch.object(codex_transport,"is_transient_reconnect",recovery.is_transient_retry_notice):
                for event in (NEW,{"type":"turn.failed","error":{"message":"real terminal failure"}}):
                    codex_transport.handle_event(event,trace,Path(d)/"pretty.log",Path(d)/"raw.jsonl")
            self.assertEqual(codex_transport.fatal_run_error(trace)["code"],"codex_turn_failed")

class ArchiveTests(Fixture):
    def test_known_false_fatal_is_accepted_only_with_full_evidence(self):
        e=self.recover()
        self.assertEqual(e.task_id,"2")
        self.assertEqual((e.prompt,e.answer),(PROMPT,ANSWER))
        self.assertEqual(len(e.notices),1)
        self.assertIn("stdout",e.sha256)
        self.assertEqual(len(e.sha256["stdout"]),64)

    def test_errors_cannot_be_bypassed(self):
        cases=[
          ("failed_exit",{"process_exit_code":1},None),
          ("no_completion",{"completion_seen":False},None),
          ("has_stop",{"process_stop_triggered":True},None),
          ("unknown_error",{"stream_errors":[{"type":"error","message":"fatal"}]},None),
          ("wrong_category",{"error":{"code":"codex_turn_failed"}},None),
          ("bad_capture",{"stdout":{"complete":False}},None),
          ("claimed_success",{"status":"succeeded"},None),
          ("stdout_turn_failed",{},{"type":"turn.failed","error":{"message":"real failure"}}),
        ]
        for label,mutation,extra in cases:
            with self.subTest(label=label):
                saved=json.loads(json.dumps(self.capture_info))
                self.capture_info.update(mutation)
                self.events=([{"type":"turn.started"},NEW,
                        {"type":"item.completed","item":{"type":"agent_message","text":ANSWER}},
                        {"type":"turn.completed"}]+([extra] if extra else []))
                self.write_archive()
                with self.assertRaises(recovery.RecoveryRefused):
                    self.recover()
                self.capture_info=saved

    def test_mismatched_real_stdin_bytes_are_rejected(self):
        (self.capture/"prompt.utf8").write_text("DIFFERENT",encoding="utf-8")
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_mismatched_task_prompt_is_rejected(self):
        (self.dir/"original_contract.json").write_text(json.dumps({"original_request":"DIFFERENT"}))
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_symlink_and_wrong_task_are_rejected(self):
        with self.assertRaises(recovery.RecoveryRefused):
            recovery.load_verified_recovery(self.capture,self.work,"1")
        linked=self.home/"linked"
        linked.symlink_to(self.capture,target_is_directory=True)
        with self.assertRaises(recovery.RecoveryRefused):
            recovery.load_verified_recovery(linked,self.work,"2")

    def test_missing_or_mismatched_archived_answer_is_rejected(self):
        (self.capture/"response.txt").write_text("wrong output")
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()
        (self.capture/"response.txt").unlink()
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_cli_requires_narrow_review_only_scope(self):
        good=["tasklist","run","--workdir",str(self.work),
            "--todo-file",str(self.work/"tasks.md"),"--start","2","--stop","2",
            "--max-steps","1","--max-retries","1","--breakdown-policy","off"]
        (self.work/"tasks.md").write_text("2. ***Task***: Something")
        self.assertEqual(recovery._validate_recovery_argv(good,"2"),self.work.resolve())
        for bad in (good[:-2],good+["--git"],good+["--accept-plan-changes"],
                    good+["--dry-run"],good+["--allow-todo-modifications"],
                    good[:good.index("--start")+1]+["1"]+good[good.index("--start")+2:]):
            with self.assertRaises(recovery.RecoveryRefused):
                recovery._validate_recovery_argv(bad,"2")

    def test_bad_summary_rejected(self):
        (self.dir/"autobuild_summary.json").write_text(json.dumps({
            "auftrag_runs":1,"review_runs":1,"completed":False,
            "execution_error":{"code":"codex_stream_error"},
            "terminal_attempt":{"phase":"task","index":1,
                "capture_directory":str(self.capture)}}),encoding="utf-8")
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_review_injection_executes_only_real_reviewer(self):
        evidence=self.recover()
        calls=[]
        def fake_model(**kwargs):
            calls.append(kwargs)
            if kwargs["phase"]!="review":
                raise AssertionError("Unexpected real Codex production or correction!")
            return codex_transport.RunResult(assistant_messages=[json.dumps(PASS)],
                                            turn_completed=True,process_exit_code=0)
        logs=self.home/"logs"; logs.mkdir()
        budget=self.home/"private_budget"
        options=AutoBuildOptions(logfile=logs/"pretty.log",rawlog=logs/"raw.jsonl",
                                 summary_json=logs/"summary.json",max_steps=1)
        context=AutoBuildContext(todo_identifier="2",budget_directory=budget,budget_root_id="2")
        with patch.object(autobuild,"run_codex_exec_json",fake_model):
            state=recovery.install_review_injection(evidence,autobuild)
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                summary=autobuild.start(task=PROMPT,workdir=self.work,options=options,context=context)
        self.assertTrue(state["used"])
        self.assertTrue(state["review_seen"])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["phase"],"review")
        self.assertEqual(calls[0]["sandbox"],"read-only")
        self.assertEqual((summary.auftrag_runs,summary.review_runs),(1,1))
        self.assertTrue(summary.completed)
        self.assertTrue(validate_result(autobuild.build_summary_document(summary))["completed"])

    def test_recovered_production_still_requires_a_review_without_blockers(self):
        evidence = self.recover()
        blocker = {"id": "missing", "type": "local_fix", "summary": "Output is missing.",
                   "requirement": "Create the output.", "acceptance_criterion": "Output exists.",
                   "references": [], "fix_suggestion": "Create the output."}
        reviews = ("Must fix: required output is missing.",
                   json.dumps({**PASS, "verdict": "FAIL", "blocking_issues": [blocker],
                               "source_format": "text_legacy"}))
        for index, review in enumerate(reviews):
            calls = []

            def fake_model(**kwargs):
                calls.append(kwargs["phase"])
                self.assertEqual(kwargs["phase"], "review")
                return codex_transport.RunResult(assistant_messages=[review],
                                                turn_completed=True, process_exit_code=0)

            def fake_complete(request, *, settings):
                return DecisionCall(result=DecisionResult(
                    execution=ExecutionResult(status=ExecutionStatus.SUCCEEDED,
                        answer="COMPLETE", process_exit_code=0, completion_seen=True),
                    options=request.options, option="COMPLETE", explanation="Synthetic choice."),
                    directory=None, attempt=None)

            logs = self.home / ("blocked-review-" + str(index))
            logs.mkdir()
            options = AutoBuildOptions(logfile=logs / "pretty.log", rawlog=logs / "raw.jsonl",
                                       summary_json=logs / "summary.json", max_steps=1)
            context = AutoBuildContext(todo_identifier="2", budget_root_id="2",
                                       budget_directory=self.home / ("blocked-budget-" + str(index)))
            with self.subTest(review=review), patch.object(autobuild, "run_codex_exec_json", fake_model), \
                    patch.object(autobuild, "run_semantic_decision", side_effect=fake_complete) as decide, \
                    patch.object(autobuild, "_terminal_beep"), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                state = recovery.install_review_injection(evidence, autobuild)
                summary = autobuild.start(task=PROMPT, workdir=self.work, options=options, context=context)
            self.assertTrue(state["used"])
            self.assertTrue(state["review_seen"])
            self.assertEqual(calls, ["review"])
            self.assertFalse(summary.completed)
            self.assertEqual(summary.review_classification["verdict"], "FAIL")
            self.assertTrue(summary.review_classification["blocking_issues"])
            self.assertFalse(validate_result(autobuild.build_summary_document(summary))["completed"])
            decide.assert_not_called()

    def test_injected_replay_must_match_exact_prompt_before_any_model_call(self):
        evidence=self.recover()
        calls=[]
        def fake_model(**kwargs):
            calls.append(kwargs)
            raise AssertionError("Should never contact model!")
        with patch.object(autobuild,"run_codex_exec_json",fake_model):
            state=recovery.install_review_injection(evidence,autobuild)
            with self.assertRaises(recovery.RecoveryRefused):
                autobuild.run_codex_exec_json(phase="auftrag",console_todo_id="2",
                    cwd=self.work,prompt="changed scope")
        self.assertFalse(state["used"])
        self.assertEqual(calls,[])


class EntrypointTests(unittest.TestCase):
    def test_generic_cli_dispatch(self):
        import arquilo
        from unittest.mock import Mock
        from unittest.mock import patch
        fake=Mock(return_value=125)
        with patch("review_resume.main",fake):
            status=arquilo.main(["tasklist","resume-review","--todo","2"])
        self.assertEqual(status,125)
        fake.assert_called_once_with(["resume-review","--todo","2"])

if __name__=="__main__":
    unittest.main()
