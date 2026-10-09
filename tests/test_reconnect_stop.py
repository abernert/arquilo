# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Synthetic event sequences through the actual transport, pipes and cleanup.

No recorded prompts, user logs, credentials or application data are used.
The only child is a temporary Python CLI stub; no Codex/model is contacted.
"""
from __future__ import annotations
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, validate_result, AutoBuildResultError
import codex_transport as transport
from runtime_contracts import ExecutionStatus
from runtime_failure import execution_error, stop_reason

RECONNECT = {"type": "error", "message": "Reconnecting... 2/5 (stream disconnected before completion: websocket closed by server before response.completed)"}
ANSWER = {"type": "item.completed", "item": {"type": "agent_message", "text": "Synthetic answer."}}
COMPLETE = {"type": "turn.completed"}
FAILED = {"type": "turn.failed", "error": {"message": "Synthetic terminal failure."}}
WORK = {"type": "item.completed", "item": {"type": "command_execution", "command": "synthetic-test",
        "status": "completed", "exit_code": 0, "aggregated_output": "ok"}}
STOP = "Synthetic operator pause: inspect the result."
PASS = {"verdict": "PASS", "short_summary": "Synthetic artifact inspected.", "blocking_issues": [],
        "non_blocking_observations": [], "breakdown_recommended": False, "breakdown_reason": None}
FAIL = {**PASS, "verdict": "FAIL", "blocking_issues": [{"id": "X1", "type": "local_fix", "summary": "Missing output.",
        "requirement": "Create output.", "acceptance_criterion": "Output exists.", "references": [], "fix_suggestion": "Create output."}]}

def answer(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}

# Waits are bounded watchdogs, not assumptions about OS scheduling. Sentinel,
# queue injection and process.poll() order the cancellation tests explicitly.
STUB = r'''
import json, os, sys, time
from pathlib import Path
s = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sys.stdin.buffer.read()
for event in s["events"]:
    sys.stdout.buffer.write((json.dumps(event) + "\n").encode("utf-8"))
if s.get("bad_utf8"):
    sys.stdout.buffer.write(b"\xff\n")
sys.stdout.buffer.flush()
sys.stderr.buffer.write(b"synthetic stderr\n")
sys.stderr.buffer.flush()
Path(s["ready"]).write_text("ready", encoding="utf-8")
if s.get("stop"):
    Path(s["stop"]).write_text(s["reason"], encoding="utf-8")
mode = s.get("mode", "exit")
if mode in ("wait", "activity"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if mode == "activity":
            print(json.dumps({"type":"item.updated", "item":{"type":"reasoning", "text":"synthetic activity"}}), flush=True)
        time.sleep(.025)
sys.exit(s.get("exit", 0))
'''

class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="arquilo-reconnect-test-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.work = self.base / "workspace"; self.work.mkdir()
        self.logs = self.base / "logs"; self.logs.mkdir()
        self.stub = self.base / "cli_stub.py"; self.stub.write_text(STUB, encoding="utf-8")
        self.stop = self.work / "process_stop"
        self.processes = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for proc in self.processes:
            if proc.poll() is None:
                transport._terminate_process_group(proc, grace_seconds=.05, reason="test_cleanup")
            proc.arquilo_process_tree.close()

    @contextmanager
    def launch(self, scenarios):
        original = transport._start_process
        count = 0
        def start(command, *, cwd, env):
            nonlocal count
            if count >= len(scenarios):
                raise AssertionError("An unapproved additional phase/retry was started")
            spec = {"ready": str(self.base / f"ready-{count}"), **scenarios[count]}
            count += 1
            if spec.get("stop") is True:
                spec.update(stop=str(self.stop), reason=STOP)
            path = self.base / f"scenario-{count}.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            proc = original([sys.executable, "-B", str(self.stub), str(path)], cwd=cwd, env=env)
            self.processes.append(proc)
            return proc
        with patch.object(transport, "_start_process", side_effect=start) as mock:
            yield mock

    def request(self, **kwargs):
        return transport.CodexExecRequest(prompt="Synthetic task.", cwd=self.work, env=dict(os.environ),
            raw_log=self.logs / "events.jsonl", pretty_log=self.logs / "pretty.log", process_stop_path=self.stop,
            timeouts=transport.TransportTimeouts(total=4, stall=2, post_turn_grace=1, kill_grace=.05), **kwargs)

    def execute(self, spec, req=None):
        with self.launch([spec]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return transport.execute(req or self.request())

    def assert_archive(self, result, spec, *, healthy=True):
        trace = result.trace
        capture = json.loads((trace.capture_dir / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(capture["process_stop_triggered"], trace.process_stop_triggered)
        self.assertEqual(capture["stream_diagnostics"], trace.stream_diagnostics)
        self.assertEqual(capture["process_exit_code"], trace.process_exit_code)
        self.assertEqual(capture["status"], result.execution.status.value)
        if healthy:
            for source in ("stdout", "stderr"):
                self.assertTrue(capture[source]["complete"], capture)
            self.assertTrue(capture["stdin"]["complete"])
        raw = (trace.capture_dir / "stdout.bin").read_bytes()
        for ev in spec["events"]:
            self.assertIn((json.dumps(ev)+"\n").encode(), raw)
        self.assertEqual((trace.capture_dir / "stderr.bin").read_bytes(), b"synthetic stderr\n")
        self.assertTrue(all(p.poll() is not None for p in self.processes))
        self.assertFalse(any(t.is_alive() and t.name.startswith("autobuild-codex-") for t in threading.enumerate()))
        return capture

    def build(self, scenarios, *, max_steps=3):
        options = AutoBuildOptions(logfile=self.logs / "pretty.log", rawlog=self.logs / "events.jsonl",
            summary_json=self.logs / "summary.json", process_stop_path=self.stop, max_steps=max_steps)
        context = AutoBuildContext(budget_directory=self.base / "budget", budget_root_id="1")
        fast = transport.TransportTimeouts(total=4, stall=2, post_turn_grace=1, kill_grace=.05)
        original = autobuild.run_codex_exec_json
        def invoke(**kwargs):
            return original(**{**kwargs, "timeouts": fast})
        with self.launch(scenarios) as calls, patch.object(autobuild, "run_codex_exec_json", side_effect=invoke), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            summary = autobuild.start(task="Create a synthetic output.", workdir=self.work, options=options, context=context)
        payload = validate_result(autobuild.build_summary_document(summary))
        return summary, payload, calls.call_count

class SequenceTests(Fixture):
    def test_plain_stop_and_reconnect_stop_archive_and_cleanup(self):  # T101-01/02/09
        for events in ([WORK], [RECONNECT, WORK], [RECONNECT]):
            with self.subTest(events=events):
                self.stop.unlink(missing_ok=True)
                spec = {"events": events, "mode": "wait", "stop": True}
                result = self.execute(spec)
                self.assertEqual(result.execution.status, ExecutionStatus.CANCELLED)
                self.assertTrue(result.trace.process_stop_triggered)
                self.assertEqual(result.trace.process_stop_details, STOP)
                self.assertIsNone(result.trace.execution_error)
                self.assertEqual(len(result.trace.stream_diagnostics), int(RECONNECT in events))
                capture = self.assert_archive(result, spec)
                self.assertTrue(capture["process_tree"]["forced_parent_exit"])
                self.assertFalse(capture["process_tree"]["errors"])
                if os.name == "posix":
                    self.assertEqual(result.trace.process_exit_code, -15)

    def test_completed_with_and_without_reconnect(self):  # T101-03/04
        for events in ([ANSWER, COMPLETE], [RECONNECT, WORK, ANSWER, COMPLETE]):
            result = self.execute({"events": events})
            self.assertEqual(result.execution.status, ExecutionStatus.SUCCEEDED)
            self.assertIsNone(result.trace.execution_error)
            self.assertEqual(result.trace.process_exit_code, 0)
            self.assert_archive(result, {"events": events})

    def test_failure_missing_completion_and_missing_answer(self):  # T101-05/06/17/18
        for events, code, expected in (([RECONNECT, FAILED], 1, "codex_turn_failed"),
                ([RECONNECT, ANSWER], 0, "codex_missing_completion"),
                ([RECONNECT, ANSWER], 1, "codex_missing_completion"),
                ([RECONNECT, ANSWER, COMPLETE], 1, "codex_process_failed"),
                ([RECONNECT, COMPLETE], 0, "codex_missing_answer")):
            with self.subTest(expected=expected, code=code):
                spec = {"events": events, "exit": code}
                result = self.execute(spec)
                self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
                self.assertEqual(result.trace.execution_error["code"], expected)
                self.assertFalse(result.trace.execution_error["automatic_task_retry"])
                self.assertEqual(len(result.trace.stream_diagnostics), 1)
                self.assert_archive(result, spec)

    def test_stall_and_total_timeouts_remain_failures(self):  # T101-07/08
        for mode, timeouts, expected in (("wait", transport.TransportTimeouts(stall=.4, total=4, kill_grace=.05), "codex_stalled"),
                ("activity", transport.TransportTimeouts(stall=2, total=.6, kill_grace=.05), "codex_timeout")):
            with self.subTest(mode=mode):
                spec = {"events": [RECONNECT], "mode": mode}
                result = self.execute(spec, replace(self.request(), timeouts=timeouts))
                self.assertEqual(result.trace.execution_error["code"], expected)
                self.assertFalse(result.trace.process_stop_triggered)
                self.assert_archive(result, spec)

    def test_unknown_errors_remain_fatal_even_with_completion(self):  # T101-10
        for message in ("Fatal", "401 unauthorized", "quota exceeded", "429 rate limit"):
            result = self.execute({"events": [{"type": "error", "message": message}, ANSWER, COMPLETE]})
            self.assertEqual(result.trace.execution_error["code"], "codex_stream_error")
            self.assertFalse(result.trace.stream_diagnostics)

    def test_fatal_and_failed_turn_keep_stop(self):  # T101-11
        for tail, expected in (([], "codex_stream_error"), ([FAILED], "codex_turn_failed")):
            self.stop.unlink(missing_ok=True)
            result = self.execute({"events": [RECONNECT, {"type": "error", "message": "Fatal"}, *tail],
                                   "mode": "wait", "stop": True})
            self.assertEqual(result.trace.execution_error["code"], expected)
            self.assertEqual(result.trace.process_stop_details, STOP)
            self.assertTrue(result.trace.process_stop_triggered)
            self.assertEqual(len(result.trace.stream_diagnostics), 1)

    def test_natural_nonzero_exit_before_stop_not_excused(self):  # T101-31
        for complete in (False, True):
            def stop_after_exit():
                return STOP if self.processes and self.processes[-1].poll() == 1 else None
            self.processes.clear()
            spec = {"events": [ANSWER] + ([COMPLETE] if complete else []), "exit": 1}
            result = self.execute(spec, self.request(cancel_requested=stop_after_exit))
            self.assertEqual(result.trace.execution_error["code"], "codex_process_failed")
            self.assertEqual(result.trace.process_stop_details, STOP)
            tree = result.trace.capture["process_tree"]
            self.assertEqual(tree["parent_exit_before"], 1)
            self.assertFalse(tree["forced_parent_exit"])

    def test_post_turn_cleanup_exception_is_preserved(self):  # T101-19
        spec = {"events": [RECONNECT, ANSWER, COMPLETE], "mode": "wait"}
        result = self.execute(spec)
        self.assertEqual(result.execution.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(result.trace.post_turn_cleanup)
        self.assert_archive(result, spec)
        real_cleanup = transport._terminate_process_group
        def faulty(*args, **kwargs):
            value = real_cleanup(*args, **kwargs)
            if not value.errors:
                value.errors.append("Synthetic cleanup error")
            return value
        with patch.object(transport, "_terminate_process_group", side_effect=faulty):
            result = self.execute(spec)
        self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
        self.assertTrue(result.trace.stream_diagnostics)

    def test_item_error_and_failed_tool_remain_nonfatal(self):  # T101-21
        failed_tool = deepcopy(WORK); failed_tool["item"].update(exit_code=1, status="failed")
        spec = {"events": [{"type":"item.completed", "item":{"type":"error", "message":"Synthetic warning"}},
                           failed_tool, WORK, ANSWER, COMPLETE]}
        result = self.execute(spec)
        self.assertEqual(result.execution.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual([c.exit_code for c in result.trace.commands], [1, 0])

    def test_stop_before_start_starts_no_child(self):  # T101-22
        self.stop.write_text(STOP, encoding="utf-8")
        with patch.object(transport, "_start_process") as start:
            result = transport.execute(self.request())
        start.assert_not_called()
        self.assertEqual(result.execution.status, ExecutionStatus.CANCELLED)
        self.assertEqual(result.trace.process_stop_details, STOP)
        self.assertTrue(result.trace.capture["process_stop_triggered"])
        self.assertIsNone(result.trace.process_exit_code)

class ClassifierTests(Fixture):
    def test_exact_scope_ascii_attempts_and_terminal_boundaries(self):  # T101-20
        for fraction in ("1/5", "2/5", "5/5"):
            event = {**RECONNECT, "message": " \t" + RECONNECT["message"].replace("2/5", fraction) + " \n"}
            self.assertTrue(transport.is_transient_reconnect(event, terminal_seen=False))
            self.assertFalse(transport.is_transient_reconnect(event, terminal_seen=True))
        invalid = [None, {}, [], {**RECONNECT, "code": "unknown"}, {**RECONNECT, "message": None}]
        for fraction in ("0/5", "6/5", "1/0", "-1/5", "01/5", "１/５", "1/"+"9"*5000):
            invalid.append({**RECONNECT, "message": RECONNECT["message"].replace("2/5", fraction)})
        invalid += [{**RECONNECT, "message": x} for x in (
            "prefix " + RECONNECT["message"], RECONNECT["message"] + " trailing", "Reconnecting... 2/5 (401 unauthorized)",
            "Reconnecting... 2/5 (stream disconnected before completion: Transport error: network error: error decoding response body)")]
        for event in invalid:
            self.assertFalse(transport.is_transient_reconnect(event, terminal_seen=False), str(event)[:100])

    def test_diagnostic_index_raw_preservation_and_single_display(self):
        trace = transport.RunResult()
        events = [{"type": "thread.started"}, WORK, RECONNECT, ANSWER, COMPLETE, RECONNECT]
        with redirect_stdout(io.StringIO()) as out:
            for event in events:
                transport.handle_event(event, trace, self.logs / "pretty.log", self.logs / "raw.jsonl")
        self.assertEqual(trace.stream_diagnostics, [{"kind":"codex_reconnect", "event_index":3, "event":RECONNECT}])
        self.assertEqual(trace.stream_errors, [RECONNECT])
        self.assertEqual(out.getvalue().count("[reconnect]"), 1)
        self.assertEqual([json.loads(x) for x in (self.logs / "raw.jsonl").read_text().splitlines()], events)
        other = transport.RunResult(turn_failed={})
        with redirect_stdout(io.StringIO()):
            transport.handle_event(RECONNECT, other, self.logs / "pretty2.log", self.logs / "raw2.jsonl")
        self.assertEqual(other.stream_errors, [RECONNECT])

    def test_shared_fatal_precedence_and_custom_runners(self):  # T101-25/34
        violation = {"type":"decision_policy_violation", "message":"Synthetic forbidden tool"}
        for stopped in (False, True):
            trace = transport.RunResult(turn_failed=FAILED, stream_errors=[violation], process_stop_triggered=stopped,
                                        process_stop_details=STOP if stopped else None)
            self.assertEqual(autobuild.run_result_error(trace, "review")["code"], "codex_decision_policy_violation")
            trace.execution_error = execution_error("prior I/O failure", code="codex_io_failed")
            self.assertEqual(autobuild.run_result_error(trace, "review")["code"], "codex_io_failed")
        trace = transport.RunResult(stream_diagnostics=[{"kind":"codex_reconnect", "event_index":1, "event":RECONNECT}])
        self.assertIsNone(autobuild.run_result_error(trace, "task"))
        trace.stream_errors.append(RECONNECT)  # No reclassification of legacy runner lists.
        self.assertEqual(autobuild.run_result_error(trace, "task")["code"], "codex_stream_error")
        trace.turn_failed = FAILED
        self.assertEqual(autobuild.run_result_error(trace, "task")["code"], "codex_turn_failed")

    def test_first_stop_reason_and_positional_compatibility(self):
        trace = transport.RunResult([], [], [], {}, None, True, STOP)
        transport.observe_stop(trace, "KeyboardInterrupt")
        self.assertEqual(trace.process_stop_details, STOP)
        self.assertEqual(stop_reason(None), "Stop details unavailable (legacy result).")
        a, b = transport.RunResult(), transport.RunResult()
        a.stream_diagnostics.append({})
        self.assertEqual(b.stream_diagnostics, [])

class AutoBuildTests(Fixture):
    def test_stop_and_reconnect_stop_propagate_without_review(self):  # T101-23
        for reconnect in (False, True):
            self.stop.unlink(missing_ok=True)
            summary, payload, calls = self.build([{"events": ([RECONNECT] if reconnect else [])+[WORK], "stop":True, "mode":"wait"}])
            self.assertEqual((payload["status"], payload["exit_code"], calls), ("cancelled", 6, 1))
            self.assertEqual((summary.auftrag_runs, summary.review_runs), (1, 0))
            self.assertEqual(payload["process_stop_details"], STOP)
            self.assertFalse(payload["completed"])
            self.assertIsNone(payload["execution_error"])
            self.assertEqual(payload["terminal_attempt"]["phase"], "task")
            self.assertEqual(payload["execution_attempts"][0]["process_stop_details"], STOP)

    def test_reconnect_success_still_runs_actual_review(self):  # T101-24
        summary, payload, calls = self.build([{"events":[RECONNECT, ANSWER, COMPLETE]},
                                             {"events":[answer(json.dumps(PASS)), COMPLETE]}])
        self.assertEqual((payload["status"], payload["exit_code"], calls), ("complete", 0, 2))
        self.assertEqual(summary.review_runs, 1)
        self.assertEqual(len(payload["execution_attempts"][0]["stream_diagnostics"]), 1)
        self.assertEqual(payload["terminal_attempt"]["phase"], "review")

    def test_stop_plus_error_in_production_review_and_fix(self):  # T101-25
        for phase in ("task", "review", "fix"):
            self.stop.unlink(missing_ok=True)
            bad = {"events":[RECONNECT, {"type":"error","message":"Synthetic fatal"}], "mode":"wait", "stop":True}
            scenarios = []
            if phase in ("review", "fix"):
                scenarios.append({"events":[ANSWER, COMPLETE]})
            if phase == "fix":
                scenarios.append({"events":[answer(json.dumps(FAIL)), COMPLETE]})
            scenarios.append(bad)
            summary, payload, calls = self.build(scenarios)
            self.assertEqual(calls, len(scenarios))
            self.assertEqual((payload["status"], payload["exit_code"]), ("failed", 7))
            self.assertEqual(payload["process_stop_details"], STOP)
            self.assertEqual(payload["execution_error"]["code"], "codex_stream_error")
            terminal = payload["terminal_attempt"]
            expected = "review" if phase == "review" else "task"
            self.assertEqual(terminal["phase"], expected)
            self.assertEqual(terminal["capture_directory"], payload["execution_error"]["capture_directory"])
            if phase == "fix":
                self.assertNotEqual(terminal["capture_directory"], payload["execution_attempts"][-1]["capture_directory"])

    def test_pure_stop_in_fix_has_explicit_terminal_identity(self):  # T101-33
        summary, payload, calls = self.build([{"events":[ANSWER, COMPLETE]},
            {"events":[answer(json.dumps(FAIL)), COMPLETE]}, {"events":[RECONNECT, WORK], "mode":"wait", "stop":True}])
        self.assertEqual((payload["exit_code"], calls), (6, 3))
        self.assertEqual(payload["terminal_attempt"], {"phase":"task", "index":2,
                          "capture_directory":str(summary.run_history[-1].capture_dir)})
        self.assertEqual(payload["execution_attempts"][-1]["phase"], "review")
        self.assertNotEqual(payload["terminal_attempt"]["capture_directory"], payload["execution_attempts"][-1]["capture_directory"])

    def test_empty_review_maps_to_existing_exit_eight(self):  # T101-18
        _, payload, calls = self.build([{"events":[ANSWER, COMPLETE]}, {"events":[RECONNECT, COMPLETE]}])
        self.assertEqual((payload["exit_code"], calls), (8, 2))
        self.assertEqual(payload["execution_error"]["code"], "invalid_review")

if __name__ == "__main__":
    unittest.main()
