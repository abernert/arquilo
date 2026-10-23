# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline launcher trust regressions; only synthetic programs and local Git."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import codex_launcher
import codex_transport
import arquilo_doctor
import decision_exec
from decision_request import DecisionRequest
import reviewed_git
import run_todos


class LauncherFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="arquilo-trusted-launcher-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.work = self.base / "project"
        self.host = self.base / "host bin"
        self.work.mkdir()
        self.host.mkdir()
        self.marker = self.base / "workspace-program-ran"

    def executable(self, path, body="print('trusted-version')\n"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return path

    def hostile(self, path):
        return self.executable(path, "from pathlib import Path\n"
            f"Path({str(self.marker)!r}).write_text('synthetic-only')\n"
            "print('workspace-version')\n")


class CodexTrustTests(LauncherFixture):
    def test_unsafe_path_entries_cannot_override_external_installation(self):
        suffix = ".exe" if os.name == "nt" else ""
        good = self.executable(self.host / ("codex" + suffix))
        self.hostile(self.work / ("codex" + suffix))
        self.hostile(self.work / "bin" / ("codex" + suffix))
        for entry in (".", "", "bin", str(self.work), str(self.work / "bin")):
            with self.subTest(entry=entry):
                selected = codex_launcher.resolve_launcher("codex", cwd=self.work,
                    env={"PATH": entry + os.pathsep + str(self.host)})
                self.assertEqual(Path(selected.argv[0]), good)

    def test_workspace_explicit_and_relative_launchers_are_rejected(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        self.hostile(self.work / name)
        for requested in ("./" + name, str(self.work / name)):
            with self.subTest(requested=requested), self.assertRaises(OSError):
                codex_launcher.resolve_launcher(requested, cwd=self.work, env={})

    def test_external_absolute_launcher_is_allowed_without_path(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        good = self.executable(self.host / name)
        selected = codex_launcher.resolve_launcher(str(good), cwd=self.work, env={})
        self.assertEqual(Path(selected.argv[0]), good)

    def test_absolute_native_host_program_starts_on_this_platform(self):
        result = codex_transport.probe_version(launcher=(sys.executable,),
            cwd=self.work, env=dict(os.environ), timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn(sys.version.split()[0], result.stdout + result.stderr)

    def test_external_alias_into_workspace_cannot_select_workspace_code(self):
        suffix = ".exe" if os.name == "nt" else ""
        good = self.executable(self.host / ("codex" + suffix))
        self.hostile(self.work / ("codex" + suffix))
        alias = self.base / "project-alias"
        try:
            alias.symlink_to(self.work, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks unavailable")
        selected = codex_launcher.resolve_launcher("codex", cwd=self.work,
            env={"PATH": str(alias) + os.pathsep + str(self.host)})
        self.assertEqual(Path(selected.argv[0]), good)
        with self.assertRaises(OSError):
            codex_launcher.resolve_launcher(str(alias / ("codex" + suffix)),
                                            cwd=self.work, env={})

    def test_workspace_selector_symlink_to_host_is_still_rejected(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        good = self.executable(self.host / name)
        alias = self.work / name
        try:
            alias.symlink_to(good)
        except (OSError, NotImplementedError):
            self.skipTest("File symlinks unavailable")
        with self.assertRaises(OSError):
            codex_launcher.resolve_launcher(str(alias), cwd=self.work, env={})

    def test_physical_case_alias_does_not_bypass_workspace_boundary(self):
        alias = self.work.with_name("PROJECT")
        if not alias.exists() or not alias.samefile(self.work):
            self.skipTest("Filesystem is case-sensitive")
        name = "codex.exe" if os.name == "nt" else "codex"
        good = self.executable(self.host / name)
        self.hostile(self.work / name)
        selected = codex_launcher.resolve_launcher("codex", cwd=self.work,
            env={"PATH": str(alias) + os.pathsep + str(self.host)})
        self.assertEqual(Path(selected.argv[0]), good)

    @unittest.skipIf(os.name == "nt", "POSIX synthetic executables")
    def test_version_probe_refuses_workspace_program_without_running_it(self):
        self.hostile(self.work / "codex")
        for path in (".", ":", "", str(self.work)):
            with self.subTest(path=path), self.assertRaises(OSError):
                codex_transport.probe_version(launcher=("codex",), cwd=self.work,
                    env={"PATH": path}, timeout=5)
        self.assertFalse(self.marker.exists())

    @unittest.skipIf(os.name == "nt", "POSIX env shebang resolution")
    def test_host_script_cannot_find_workspace_interpreter_through_path(self):
        # A genuine npm POSIX entry point also invokes Node through /usr/bin/env.
        codex = self.host / "codex"
        codex.write_text("#!/usr/bin/env arquilo-test-node\n", encoding="utf-8")
        codex.chmod(0o755)
        self.executable(self.host / "arquilo-test-node")
        self.hostile(self.work / "arquilo-test-node")
        result = codex_transport.probe_version(launcher=(str(codex),), cwd=self.work,
            env={"PATH": "." + os.pathsep + str(self.host),
                 "SYNTHETIC_PROVIDER_TOKEN": "preserve-me"}, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "trusted-version")
        self.assertFalse(self.marker.exists())

    def test_windows_npm_launcher_keeps_installed_node_and_rejects_project_node(self):
        package = self.host / "node_modules" / "@openai" / "codex"
        script = package / "bin" / "codex.js"
        script.parent.mkdir(parents=True)
        script.write_text("// synthetic npm package\n", encoding="utf-8")
        (package / "package.json").write_text(json.dumps({"name": "@openai/codex",
            "bin": {"codex": "bin/codex.js"}}), encoding="utf-8")
        shim = self.host / "codex.cmd"
        shim.write_text(codex_launcher._npm_shim(
            "node_modules\\@openai\\codex\\bin\\codex.js"), encoding="utf-8")
        node = self.executable(self.host / "node.exe")
        self.hostile(self.work / "node.exe")
        selected = codex_launcher.resolve_launcher("codex", cwd=self.work,
            env={"Path": ".;" + str(self.host)}, platform_name="nt")
        self.assertEqual(selected.argv, (str(node), str(script)))
        external_node = self.base / "node installation" / "node.exe"
        self.executable(external_node)
        node.unlink()
        selected = codex_launcher.resolve_launcher(str(shim), cwd=self.work,
            env={"Path": str(self.work) + ";" + str(external_node.parent)}, platform_name="nt")
        self.assertEqual(selected.argv, (str(external_node), str(script)))
        with self.assertRaises(OSError):
            codex_launcher.resolve_launcher(str(shim), cwd=self.work,
                env={"Path": str(self.work)}, platform_name="nt")
        project_script = self.work / "codex.js"
        project_script.write_text("// project code must not be a host entry point", encoding="utf-8")
        script.unlink()
        try:
            script.symlink_to(project_script)
        except (OSError, NotImplementedError):
            self.skipTest("npm controls passed; file symlink check unavailable")
        with self.assertRaises(OSError):
            codex_launcher.resolve_launcher(str(shim), cwd=self.work,
                env={"Path": str(external_node.parent)}, platform_name="nt")

    def test_windows_path_requires_a_local_fully_qualified_drive(self):
        from host_launcher import windows_absolute
        for value in ("C:\\tools\\codex.exe", "c:/Program Files/nodejs/node.exe"):
            with self.subTest(value=value):
                self.assertTrue(windows_absolute(value))
        for value in ("C:codex.exe", "\\codex.exe", "/codex.exe", ".", "", "bin",
                      "\\\\server\\share\\codex.exe", "\\\\?\\C:\\codex.exe",
                      "\\\\.\\C:\\codex.exe"):
            with self.subTest(value=value):
                self.assertFalse(windows_absolute(value))
                with self.assertRaises(OSError):
                    codex_launcher.resolve_launcher(value, cwd=self.work, env={}, platform_name="nt")

    def test_windows_conflicting_path_spellings_fail_closed(self):
        self.executable(self.host / "codex.exe")
        with self.assertRaises(OSError):
            codex_launcher.resolve_launcher("codex", cwd=self.work,
                env={"PATH": str(self.host), "Path": str(self.work)}, platform_name="nt")

    def test_doctor_rejects_workspace_launcher_before_any_probe(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        self.hostile(self.work / name)
        with patch.object(arquilo_doctor, "probe_cli_metadata") as probe:
            report = arquilo_doctor.collect_report(workdir=self.work, env={"PATH": str(self.work)})
        probe.assert_not_called()
        self.assertNotEqual(report["checks_status"], "PASS")
        self.assertEqual(report["model_calls"], 0)

    def test_preflight_binds_host_selection_before_changing_cwd(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        good = self.executable(self.host / name)
        self.hostile(self.work / name)
        environment = {"PATH": "." + os.pathsep + str(self.host),
                       "SYNTHETIC_PROVIDER_TOKEN": "preserve-me"}
        captured = []
        def version(**kwargs):
            captured.append(kwargs)
            return subprocess.CompletedProcess([], 0, "synthetic version", "")
        def execute(request):
            captured.append(request)
            return SimpleNamespace(execution=SimpleNamespace(succeeded=True))
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(Path, "cwd", return_value=self.work), \
             patch.object(codex_transport, "probe_version", side_effect=version), \
             patch.object(codex_transport, "execute", side_effect=execute), \
             redirect_stdout(io.StringIO()):
            run_todos.run_codex_workspace_write_preflight(dry_run=False)
        self.assertEqual(captured[0]["launcher"], (str(good),))
        self.assertEqual(captured[1].launcher, (str(good),))
        self.assertEqual(captured[0]["env"], captured[1].env)
        self.assertEqual(captured[1].env["SYNTHETIC_PROVIDER_TOKEN"], "preserve-me")
        self.assertNotIn(".", captured[1].env["PATH"].split(os.pathsep))

    def test_preflight_uses_requested_project_as_trust_boundary(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        self.hostile(self.work / name)
        with patch.dict(os.environ, {"PATH": str(self.work)}, clear=True), \
             patch.object(Path, "cwd", return_value=self.base), \
             patch.object(codex_transport, "probe_version") as version, \
             patch.object(codex_transport, "execute") as execute:
            with self.assertRaises(run_todos.CodexPreflightError):
                run_todos.run_codex_workspace_write_preflight(dry_run=False, workdir=self.work)
        version.assert_not_called()
        execute.assert_not_called()

    def test_decide_excludes_project_path_before_moving_to_temporary_cwd(self):
        name = "codex.exe" if os.name == "nt" else "codex"
        good = self.executable(self.host / name)
        self.hostile(self.work / name)
        request = DecisionRequest(question="Synthetic?", options=("YES", "NO"), context=(),
                                  run_id="test", task_id="1", phase="test", attempt_id="1")
        with patch.object(codex_transport, "execute", return_value=SimpleNamespace()) as execute:
            attempt = decision_exec.execute_attempt(request, project_root=self.work,
                trusted_codex_home=None, temp_root=self.base,
                env={"PATH": str(self.work) + os.pathsep + str(self.host)},
                raw_log=self.base / "events.jsonl", pretty_log=self.base / "pretty.log")
        self.addCleanup(attempt.cleanup_workdir)
        actual = execute.call_args.args[0]
        self.assertEqual(actual.launcher, (str(good),))
        self.assertEqual(actual.env["PATH"], str(self.host))
        self.assertNotEqual(actual.cwd, self.work)


@unittest.skipIf(os.name == "nt", "POSIX synthetic Git wrappers")
class GitTrustTests(LauncherFixture):
    def setUp(self):
        super().setUp()
        found = shutil.which("git")
        if not found:
            self.skipTest("Local Git unavailable")
        self.git = str(Path(found).resolve())
        self.state = self.base / "state"
        self.state.mkdir()
        self.git_run("init", "-q")
        self.git_run("config", "user.name", "Synthetic Test")
        self.git_run("config", "user.email", "test@example.invalid")
        (self.work / "output.txt").write_text("before\n", encoding="utf-8")
        self.git_run("add", "output.txt")
        self.git_run("commit", "-qm", "fixture")

    def git_run(self, *args):
        return subprocess.run([self.git, *args], cwd=self.work, check=True,
                              capture_output=True)

    def wrapper(self, target, marker):
        return self.executable(target, "import os, sys\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('synthetic-only')\n"
            f"os.execv({self.git!r}, [{self.git!r}, *sys.argv[1:]])\n")

    def test_reviewed_git_does_not_execute_workspace_git(self):
        self.wrapper(self.work / "git", self.marker)
        with patch.dict(os.environ, {"PATH": ".:" + str(Path(self.git).parent)}):
            selection = reviewed_git.ReviewedGit(self.work, ["output.txt"], self.state)
            self.assertTrue(selection.head)
        self.assertFalse(self.marker.exists())

    def test_runner_repository_checks_and_status_do_not_execute_workspace_git(self):
        self.wrapper(self.work / "git", self.marker)
        runner = object.__new__(run_todos.TodoRunner)
        runner.workdir = self.work
        with patch.dict(os.environ, {"PATH": ".:" + str(Path(self.git).parent)}):
            self.assertEqual(runner._assert_git_repository(), self.work)
            runner._run_git_command(["status", "--porcelain"], capture_output=True)
        self.assertFalse(self.marker.exists())

    def test_reviewed_git_keeps_the_selected_host_executable(self):
        first_marker = self.base / "first-host-git-ran"
        second_marker = self.base / "second-host-git-ran"
        self.wrapper(self.host / "git", first_marker)
        second = self.base / "second host"
        self.wrapper(second / "git", second_marker)
        with patch.dict(os.environ, {"PATH": str(self.host)}):
            selection = reviewed_git.ReviewedGit(self.work, ["output.txt"], self.state)
            with patch.dict(os.environ, {"PATH": str(second)}):
                selection.git("status", "--porcelain")
        self.assertTrue(first_marker.exists())
        self.assertFalse(second_marker.exists())


if __name__ == "__main__":
    unittest.main()
