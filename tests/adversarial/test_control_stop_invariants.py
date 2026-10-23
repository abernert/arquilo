# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Control-stop regressions with real plan/journal transitions and no model calls."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
import autobuild
from autobuild_contract import AutoBuildContext, AutoBuildOptions, call_payload, decode_call
from codex_transport import RunResult
import run_todos


PASS = {"verdict": "PASS", "short_summary": "Physical output checked.",
        "blocking_issues": [], "non_blocking_observations": [],
        "breakdown_recommended": False, "breakdown_reason": None}


class ControlStopInvariants(IsolatedControllerCase):
    def run_with_dispatch(self, runner, dispatch):
        with patch.object(runner, "_run_autobuild_impl", side_effect=dispatch), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner.run()

    def assert_plan(self, runner, expected):
        self.assertEqual(self.todo.read_text(encoding="utf-8"), expected)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text(
            encoding="utf-8"))["text"], expected)

    def test_stop_before_depth_filtered_task_blocks_later_dispatch(self):
        plan = "1. ***DONE***: Earlier.\n***STOP***\n1.1. ***Task***: Deep.\n2. ***Task***: Later.\n"
        self.write_plan(plan)
        runner = self.runner(max_depth=1)
        self.run_with_dispatch(runner, lambda *a, **k: self.fail("Dispatch crossed STOP"))
        self.assertTrue(runner.stop_marker_triggered)
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, plan)

    def test_stop_before_terminal_task_is_still_a_barrier(self):
        for status in ("DONE", "OBSOLETE"):
            with self.subTest(status=status):
                plan = f"***STOP***\n1. ***{status}***: Earlier.\n2. ***Task***: Later.\n"
                self.write_plan(plan)
                runner = self.runner(accept_plan_changes=True)
                self.run_with_dispatch(runner, lambda *a, **k: self.fail("Dispatch crossed STOP"))
                self.assertTrue(runner.stop_marker_triggered)
                self.assert_plan(runner, plan)
                runner.close()

    def test_explicit_start_after_earlier_stop_preserves_owner_scope(self):
        plan = "***STOP***\n1. ***Task***: Earlier.\n2. ***Task***: Selected.\n"
        self.write_plan(plan)
        runner = self.runner(start_id="2")
        calls = []
        def dispatch(identifier, *args, **kwargs):
            calls.append(identifier)
            return run_todos.TaskOutcome(completed=True, message="Reviewed selected output")
        self.run_with_dispatch(runner, dispatch)
        self.assertEqual(calls, ["2"])
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, plan.replace("2. ***Task***", "2. ***DONE***"))

    def test_parallel_batch_cannot_skip_deep_stop(self):
        plan = ("***CFG parallel=g workspace=a***\n1. ***Task***: First.\n"
                "***STOP***\n1.1. ***Task***: Deep.\n"
                "***CFG parallel=g workspace=b***\n2. ***Task***: Later.\n")
        self.write_plan(plan)
        runner = self.runner(max_depth=1)
        calls = []
        def dispatch(identifier, *args, **kwargs):
            calls.append(identifier)
            return run_todos.TaskOutcome(completed=True, message="Reviewed first output")
        self.run_with_dispatch(runner, dispatch)
        self.assertEqual(calls, ["1"])
        self.assertTrue(runner.stop_marker_triggered)
        self.assert_plan(runner, plan.replace("1. ***Task***", "1. ***DONE***", 1))

    def test_wait_continue_cannot_override_file_stop(self):
        plan = ("1. ***OBSOLETE***: Earlier.\n"
                "***WAIT on=todo:1 timeout=1s on_timeout=continue***\n"
                "2. ***Task***: Later.\n")
        self.write_plan(plan)
        runner = self.runner()
        def stop(_seconds):
            (self.work / "process_stop").write_text("Owner stopped during WAIT", encoding="utf-8")
        with patch.object(run_todos.time, "sleep", side_effect=stop):
            self.run_with_dispatch(runner, lambda *a, **k: self.fail("Dispatch after WAIT stop"))
        self.assertEqual(runner.exit_code, 6)
        self.assertTrue(runner.process_stop_detected)
        self.assertIn("Owner stopped", runner.process_stop_details)
        self.assert_plan(runner, plan)

    def test_unreadable_stop_content_still_latches_cancellation(self):
        plan = "1. ***Task***: Work.\n"
        self.write_plan(plan)
        for kind in ("invalid-utf8", "directory", "symlink"):
            with self.subTest(kind=kind):
                runner = self.runner()
                stop = self.work / "process_stop"
                if kind == "invalid-utf8":
                    stop.write_bytes(b"\xff\xfe")
                elif kind == "directory":
                    stop.mkdir()
                else:
                    target = self.victims / "stop-text"
                    target.write_text("External contents must not be read", encoding="utf-8")
                    try:
                        stop.symlink_to(target)
                    except (OSError, NotImplementedError):
                        self.skipTest("Creating a local symbolic link is unavailable")
                self.run_with_dispatch(runner, lambda *a, **k: self.fail("Dispatch after physical stop"))
                self.assertEqual(runner.exit_code, 6)
                self.assertTrue(runner.process_stop_detected)
                self.assertNotIn("External contents", runner.process_stop_details)
                self.assert_plan(runner, plan)
                runner.close()
                if kind == "directory":
                    stop.rmdir()
                else:
                    stop.unlink()

    def cli(self):
        with patch.object(run_todos, "_beep"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return run_todos.main(["--todo-file", str(self.todo), "--workdir", str(self.work),
                                   "--state-dir", str(self.state_root)])

    def assert_subworkspace_stop(self, kind):
        plan = "***CFG workspace=a***\n1. ***Task***: Work.\n"
        self.write_plan(plan)
        runner = self.runner()
        work = self.work / "a"
        work.mkdir()
        stop = work / "process_stop"
        if kind == "invalid-utf8":
            stop.write_bytes(b"\xff\xfe")
        elif kind == "directory":
            stop.mkdir()
        else:
            target = self.victims / "stop-text"
            target.write_text("External contents must not be read", encoding="utf-8")
            try:
                stop.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Creating a local symbolic link is unavailable")
        with self.fake_codex(lambda **kwargs: self.fail("Dispatch after subworkspace stop")):
            runner.run()
        self.assertEqual(runner.exit_code, 6)
        self.assertTrue(runner.process_stop_detected)
        self.assertTrue((self.work / "process_stop").is_file())
        self.assertNotIn("External contents", (self.work / "process_stop").read_text(encoding="utf-8"))
        self.assertFalse(runner.completed)
        self.assert_plan(runner, plan)

    def test_invalid_utf8_subworkspace_stop_propagates(self):
        self.assert_subworkspace_stop("invalid-utf8")

    def test_directory_subworkspace_stop_propagates(self):
        self.assert_subworkspace_stop("directory")

    def test_symlink_subworkspace_stop_propagates(self):
        self.assert_subworkspace_stop("symlink")

    def test_existing_stop_blocks_profile_and_codex_preflight(self):
        self.write_plan("1. ***Task***: Work.\n")
        (self.work / "process_stop").write_text("Owner stop", encoding="utf-8")
        with patch.object(run_todos, "run_runtime_profile_preflight") as profile, \
                patch.object(run_todos, "run_codex_workspace_write_preflight") as codex:
            self.assertEqual(self.cli(), 6)
        profile.assert_not_called()
        codex.assert_not_called()

    def test_stop_created_by_profile_preflight_blocks_codex_preflight(self):
        self.write_plan("1. ***Task***: Work.\n")
        def profile(*args, **kwargs):
            (self.work / "process_stop").write_text("Preflight requested stop", encoding="utf-8")
        with patch.object(run_todos, "run_runtime_profile_preflight", side_effect=profile), \
                patch.object(run_todos, "run_codex_workspace_write_preflight") as codex:
            self.assertEqual(self.cli(), 6)
        codex.assert_not_called()

    def test_stop_created_during_runner_setup_blocks_profile_preflight(self):
        self.write_plan("1. ***Task***: Work.\n")
        runner_type = run_todos.TodoRunner
        def create_runner(*args, **kwargs):
            runner = runner_type(*args, **kwargs)
            (self.work / "process_stop").write_text("Stop during setup", encoding="utf-8")
            return runner
        with patch.object(run_todos, "TodoRunner", side_effect=create_runner), \
                patch.object(run_todos, "run_runtime_profile_preflight") as profile, \
                patch.object(run_todos, "run_codex_workspace_write_preflight") as codex:
            self.assertEqual(self.cli(), 6)
        profile.assert_not_called()
        codex.assert_not_called()

    def test_stop_created_with_review_result_prevents_done(self):
        plan = "1. ***Task***: Produce output.\n"
        self.write_plan(plan)
        runner = self.runner()
        def codex(**kwargs):
            if kwargs["phase"] == "review":
                (self.work / "process_stop").write_text("Stop at review boundary", encoding="utf-8")
                return RunResult(assistant_messages=[json.dumps(PASS)], turn_completed=True, process_exit_code=0)
            return RunResult(assistant_messages=["Produced"], turn_completed=True, process_exit_code=0)
        with self.fake_codex(codex):
            runner.run()
        self.assertEqual(runner.exit_code, 6)
        self.assertFalse(runner.completed)
        self.assert_plan(runner, plan)

    def test_stop_after_final_log_prevents_plan_and_journal_done(self):
        plan = "1. ***Task***: Produce output.\n"
        self.write_plan(plan)
        runner = self.runner()
        finalize = runner._finalize_post_todo_log
        def stop_after_log(outcome):
            finalize(outcome)
            (self.work / "process_stop").write_text("Stop before DONE", encoding="utf-8")
        def codex(**kwargs):
            text = json.dumps(PASS) if kwargs["phase"] == "review" else "Produced"
            return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)
        with self.fake_codex(codex), \
                patch.object(runner, "_finalize_post_todo_log", side_effect=stop_after_log):
            runner.run()
        self.assertEqual(runner.exit_code, 6)
        self.assertFalse(runner.completed)
        self.assertFalse(runner.reviewed_this_run)
        self.assert_plan(runner, plan)

    def test_parallel_peer_stop_prevents_batch_acceptance(self):
        plan = ("***CFG parallel=g workspace=a***\n1. ***Task***: First.\n"
                "***CFG parallel=g workspace=b***\n2. ***Task***: Second.\n")
        self.write_plan(plan)
        runner = self.runner()
        peer_stopped = threading.Event()
        def dispatch(identifier, *args, **kwargs):
            if identifier == "1":
                Path(kwargs["process_stop_override"]).write_text("Worker requested stop", encoding="utf-8")
                peer_stopped.set()
                return run_todos.TaskOutcome(completed=False, message="Stop", process_stop_triggered=True,
                                             process_stop_details="Worker requested stop")
            self.assertTrue(peer_stopped.wait(3))
            return run_todos.TaskOutcome(completed=True, message="Late completion must not be adopted")
        self.run_with_dispatch(runner, dispatch)
        self.assertEqual(runner.exit_code, 6)
        self.assertFalse(runner.completed)
        self.assert_plan(runner, plan)

    def test_real_python_workers_observe_peer_stop_before_followup(self):
        self.run_real_workers(reported_stop=False)

    def test_worker_return_stop_is_published_before_output_copying(self):
        self.run_real_workers(reported_stop=True)

    def run_real_workers(self, *, reported_stop):
        """Keep the private request/return boundary; simulate only model output."""
        plan = ("***CFG parallel=g workspace=a***\n1. ***Task***: First.\n"
                "***CFG parallel=g workspace=b***\n2. ***Task***: Second.\n")
        self.write_plan(plan)
        runner = self.runner()
        helper = self.base / "isolated_worker.py"
        helper.write_text('''import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import autobuild
from codex_transport import RunResult
request = Path(sys.argv[2])
work = Path(json.loads(request.read_text(encoding="utf-8"))["workdir"])
reported_stop = sys.argv[3] == "reported"
ready = work.parent / "peer-ready"
peer_stop = work.parent / "a" / "process_stop"
def wait_for(path):
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError("Worker rendezvous timed out")
        time.sleep(0.01)
def model(**kwargs):
    if kwargs["phase"] == "auftrag":
        if work.name == "a":
            wait_for(ready)
            if not reported_stop:
                peer_stop.write_text("Peer worker stopped", encoding="utf-8")
            return RunResult(process_stop_triggered=True,
                             process_stop_details="Peer worker stopped")
        ready.write_text("ready", encoding="utf-8")
        wait_for(work.parent / "parent-observed-stop" if reported_stop else peer_stop)
        reason = kwargs.get("cancel_requested", lambda: None)()
        (work.parent / "peer-observation.json").write_text(json.dumps({"reason":reason}), encoding="utf-8")
        if reason:
            return RunResult(process_stop_triggered=True, process_stop_details=reason)
        (work / "late-artifact.txt").write_text("incorrect continuation", encoding="utf-8")
        return RunResult(assistant_messages=["Produced"], turn_completed=True, process_exit_code=0)
    (work / "review-started.txt").write_text("review", encoding="utf-8")
    return RunResult(assistant_messages=[json.dumps({"verdict":"PASS",
        "short_summary":"Checked output", "blocking_issues":[],
        "non_blocking_observations":[], "breakdown_recommended":False,
        "breakdown_reason":None})], turn_completed=True, process_exit_code=0)
with patch.object(autobuild, "run_codex_exec_json", side_effect=model), \\
     patch.object(autobuild, "_terminal_beep"):
    raise SystemExit(autobuild.main(["--request-json", str(request)]))
''', encoding="utf-8")
        real_run = subprocess.run
        requests = []
        observations = {}
        original_record = runner._record_task_io
        def record(outcome, *, log_record):
            if reported_stop and log_record.identifier == "1" and outcome.process_stop_triggered:
                runner._observe_outcome_stop(outcome)
                observations["published"] = runner.process_stop_path.exists()
                (self.work / "parent-observed-stop").write_text("observed", encoding="utf-8")
                deadline = time.monotonic() + 5
                while not (self.work / "peer-observation.json").exists():
                    if time.monotonic() >= deadline:
                        raise AssertionError("Controller output-copy rendezvous timed out")
                    time.sleep(0.01)
            return original_record(outcome, log_record=log_record)
        def run_worker(command, **kwargs):
            self.assertIn("--request-json", command)
            request = Path(command[-1])
            requests.append(request)
            return real_run([sys.executable, "-B", str(helper), str(runner.repo_root), str(request),
                             "reported" if reported_stop else "file"],
                            **kwargs, timeout=15)
        with patch.object(run_todos.subprocess, "run", side_effect=run_worker), \
                patch.object(runner, "_record_task_io", side_effect=record), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner.run()
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(set(requests)), 2)
        if reported_stop:
            self.assertTrue(observations["published"], "The stop must be shared before output copying")
        self.assertFalse((self.work / "b" / "late-artifact.txt").exists())
        self.assertFalse((self.work / "b" / "review-started.txt").exists())
        self.assertTrue(json.loads((self.work / "peer-observation.json").read_text(encoding="utf-8"))["reason"])
        for request in requests:
            payload = json.loads(request.read_text(encoding="utf-8"))
            self.assertIn(str(self.work / "a" / "process_stop"),
                          payload["context"]["process_stop_paths"])
            self.assertTrue((request.parent / "summary.json").is_file())
        self.assertEqual(runner.exit_code, 6)
        self.assert_plan(runner, plan)

    def test_parallel_overlapping_workspaces_fail_before_dispatch(self):
        for second in ("a/b", "."):
            with self.subTest(second=second):
                plan = ("***CFG parallel=g workspace=a***\n1. ***Task***: First.\n"
                        f"***CFG parallel=g workspace={second}***\n2. ***Task***: Second.\n")
                self.write_plan(plan)
                runner = self.runner(accept_plan_changes=True)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.run_with_dispatch(runner, lambda *a, **k: self.fail("Overlapping workers started"))
                self.assert_plan(runner, plan)
                runner.close()

    def test_worker_stop_paths_survive_request_serialization(self):
        paths = (self.work / "process_stop", self.work / "peer" / "process_stop")
        context = AutoBuildContext(process_stop_paths=paths)
        payload = json.loads(json.dumps(call_payload(task="Work", workdir=self.work,
                            options=AutoBuildOptions(), context=context)))
        restored = decode_call(payload)["context"]
        self.assertEqual(tuple(map(str, restored.process_stop_paths)), tuple(map(str, paths)))

    def test_peer_stop_prevents_followup_model_phase(self):
        peer_stop = self.work / "peer-stop"
        calls = []
        def codex(**kwargs):
            calls.append(kwargs["phase"])
            peer_stop.write_text("Peer stopped", encoding="utf-8")
            return RunResult(assistant_messages=["Produced"], turn_completed=True, process_exit_code=0)
        with self.fake_codex(codex):
            summary = autobuild.start(task="Produce output", workdir=self.work,
                options=AutoBuildOptions(), context=AutoBuildContext(
                    budget_directory=self.state_root / "budget", process_stop_paths=(peer_stop,)))
        self.assertEqual(calls, ["auftrag"])
        self.assertFalse(summary.completed)
        self.assertTrue(summary.process_stop_triggered)
        self.assertIn("Peer stopped", summary.process_stop_details)
