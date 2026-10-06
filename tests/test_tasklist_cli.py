# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline dispatch and subprocess regressions for the tasklist namespace."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import arquilo
from legacy_naming import historical_environment_aliases

ROOT = Path(__file__).resolve().parents[1]


class TasklistDispatchTests(unittest.TestCase):
    def dispatch(self, argv, result=0, error=None):
        runner = Mock(return_value=result, side_effect=error)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {"run_todos": SimpleNamespace(main=runner)}):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = arquilo.main(argv)
        return code, runner, stdout.getvalue(), stderr.getvalue()

    def test_new_command_forwards_arguments_exactly_once(self):
        flags = ["--workdir", "a path", "--todo-file", "t.md", "--stop", "2"]
        code, runner, out, err = self.dispatch(["tasklist", "run", *flags], result=7)
        self.assertEqual(code, 7)
        runner.assert_called_once_with(flags)
        self.assertEqual((out, err), ("", ""))

    def test_old_command_forwards_with_one_stderr_notice(self):
        code, runner, out, err = self.dispatch(["run", "--dry-run"], result=3)
        self.assertEqual(code, 3)
        runner.assert_called_once_with(["--dry-run"])
        self.assertEqual(out, "")
        self.assertEqual(err, arquilo.RUN_MIGRATION_NOTICE + "\n")

    def test_notice_does_not_echo_arguments(self):
        _, _, _, err = self.dispatch(["run", "--secret-example", "do-not-echo"])
        self.assertNotIn("do-not-echo", err)

    def test_tuple_input_is_supported(self):
        _, runner, _, _ = self.dispatch(("tasklist", "run", "--help"))
        runner.assert_called_once_with(["--help"])

    def test_input_sequence_is_not_mutated(self):
        args = ["tasklist", "run", "--dry-run"]
        before = args.copy()
        self.dispatch(args)
        self.assertEqual(args, before)

    def test_none_reads_sys_argv(self):
        with patch.object(sys, "argv", ["arquilo.py", "tasklist", "run", "--help"]):
            _, runner, _, _ = self.dispatch(None)
        runner.assert_called_once_with(["--help"])

    def test_empty_run_arguments_still_delegate(self):
        for prefix in (["tasklist", "run"], ["run"]):
            with self.subTest(prefix=prefix):
                _, runner, _, _ = self.dispatch(prefix)
                runner.assert_called_once_with([])

    def test_separator_and_unknown_flags_are_not_reinterpreted(self):
        flags = ["--unknown-runner-flag", "value", "--", "run"]
        _, runner, _, _ = self.dispatch(["tasklist", "run", *flags])
        runner.assert_called_once_with(flags)

    def test_runner_exit_codes_are_preserved(self):
        for code in (0, 1, 2, 3, 17, 130):
            for prefix in (["tasklist", "run"], ["run"]):
                with self.subTest(code=code, prefix=prefix):
                    actual, _, _, _ = self.dispatch(prefix, result=code)
                    self.assertEqual(actual, code)

    def test_system_exit_is_not_swallowed(self):
        with self.assertRaises(SystemExit) as ctx:
            self.dispatch(["tasklist", "run", "--help"], error=SystemExit(2))
        self.assertEqual(ctx.exception.code, 2)

    def test_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            self.dispatch(["tasklist", "run"], error=KeyboardInterrupt())

    def test_group_without_subcommand_only_shows_help(self):
        code, runner, out, err = self.dispatch(["tasklist"])
        self.assertEqual(code, 0)
        runner.assert_not_called()
        self.assertIn("tasklist run --help", out)
        self.assertEqual(err, "")

    def test_no_command_only_shows_help(self):
        code, runner, out, err = self.dispatch([])
        self.assertEqual(code, 0)
        runner.assert_not_called()
        self.assertIn("tasklist", out)
        self.assertEqual(err, "")

    def test_group_help_does_not_invoke_runner(self):
        runner = Mock()
        with patch.dict(sys.modules, {"run_todos": SimpleNamespace(main=runner)}):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                arquilo.main(["tasklist", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        runner.assert_not_called()

    def test_invalid_commands_fail_without_dispatch(self):
        for args in (["tasklist", "invalid"], ["tasklist", "--workdir", "x"],
                     ["pipeline", "run", "x.yaml"], ["tasklis", "run"],
                     ["tasklist", "--hel"], ["--ver"]):
            with self.subTest(args=args):
                runner = Mock()
                with patch.dict(sys.modules, {"run_todos": SimpleNamespace(main=runner)}):
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                        arquilo.main(args)
                self.assertEqual(ctx.exception.code, 2)
                runner.assert_not_called()

    def test_capabilities_remains_unchanged(self):
        _, runner, out, err = self.dispatch(["capabilities"])
        runner.assert_called_once_with(["--print-capabilities"])
        self.assertEqual((out, err), ("", ""))

    def test_doctor_and_package_dispatch_remain_unchanged(self):
        for command, module in (("doctor", "arquilo_doctor"),
                                ("package", "scripts.build_runtime_zip")):
            with self.subTest(command=command):
                runner = Mock(return_value=4)
                with patch.dict(sys.modules, {module: SimpleNamespace(main=runner)}):
                    self.assertEqual(arquilo.main([command, "--help"]), 4)
                runner.assert_called_once_with(["--help"])


class TasklistSubprocessTests(unittest.TestCase):
    def invoke(self, *args):
        # No user configuration, provider credentials or model calls are needed.
        prefixes = ("ARQUILO_", "AGENT_SYSTEM_",
                    *historical_environment_aliases("ARQUILO_"))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(prefixes)}
        return subprocess.run([sys.executable, "-B", str(ROOT / "arquilo.py"), *args],
                              cwd=ROOT, env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=30, check=False)

    def test_new_and_legacy_help_have_identical_stdout(self):
        new = self.invoke("tasklist", "run", "--help")
        old = self.invoke("run", "--help")
        self.assertEqual((new.returncode, old.returncode), (0, 0))
        self.assertEqual(new.stdout, old.stdout)
        self.assertIn("--todo-file", new.stdout)
        self.assertEqual(new.stderr, "")
        self.assertEqual(old.stderr, arquilo.RUN_MIGRATION_NOTICE + "\n")

    def test_json_capabilities_stays_parseable_for_all_entrypoints(self):
        results = [self.invoke(*args) for args in
                   (("capabilities",), ("tasklist", "run", "--print-capabilities"),
                    ("run", "--print-capabilities"))]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        payloads = [json.loads(result.stdout) for result in results]
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[0], payloads[2])
        self.assertEqual(results[0].stderr, "")
        self.assertEqual(results[1].stderr, "")
        self.assertEqual(results[2].stderr, arquilo.RUN_MIGRATION_NOTICE + "\n")

    def test_real_dry_run_without_codex(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "workspace"
            work.mkdir()
            todo = work / "tasks.md"
            todo.write_text("1. Task: Create an empty hello.txt.\n", encoding="utf-8")
            report = root / "preview.md"
            result = self.invoke("tasklist", "run", "--workdir", str(work),
                                 "--todo-file", str(todo), "--state-dir", str(root / "state"),
                                 "--dry-run", "--dry-run-file", str(report),
                                 "--process-stop-policy", "controller-only")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(report.is_file())
            self.assertFalse((work / "hello.txt").exists())
            self.assertNotIn("DONE", todo.read_text(encoding="utf-8"))
            self.assertNotIn("compatibility alias", result.stderr)

    def test_yolo_remains_rejected(self):
        result = self.invoke("tasklist", "run", "--allow-yolo")
        self.assertEqual(result.returncode, 2)
        self.assertIn("entfernt", result.stderr)

    def test_version_unchanged(self):
        result = self.invoke("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), f"ARQUILO {arquilo.__version__}")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
