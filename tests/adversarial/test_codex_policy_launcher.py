# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline task-to-argv and launcher checks; no installed Codex is started."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from test_public_runtime import PASS, result
import autobuild
import codex_launcher
import codex_policy
import codex_transport
import runtime_profile


OPEN = ("***SYNTAX marked-en***\n"
        "***CFG agent=yolo model='named deployment' web_search=disabled network_access=false***\n"
        "1. ***Task***: Create proof.txt containing verified.\n")
DONE = OPEN.replace("***Task***", "***DONE***")


class PolicyLauncherTests(IsolatedControllerCase):
    def test_task_producer_and_reviewer_keep_profile_model_and_fixed_policy(self):
        self.write_plan(OPEN)
        runner = self.runner(stop_id="1", network_access=True)
        seen = []

        def dispatch(**kwargs):
            phase = kwargs["phase"]
            self.assertEqual(kwargs["config_profile"], "yolo")
            self.assertEqual(kwargs["model"], "named deployment")
            self.assertFalse(kwargs["network_access"])
            request = codex_transport.CodexExecRequest(
                prompt=kwargs["prompt"], cwd=kwargs["cwd"], env={},
                raw_log=self.base / f"{phase}.jsonl",
                pretty_log=self.base / f"{phase}.log",
                sandbox=kwargs["sandbox"], network_access=kwargs["network_access"],
                config_profile=kwargs["config_profile"], model=kwargs["model"],
                extra_args=tuple(kwargs["extra_args"]),
            )
            command = codex_transport.build_command(request)
            seen.append((phase, command))
            self.assertEqual(command[command.index("--sandbox") + 1],
                             "workspace-write" if phase == "auftrag" else "read-only")
            self.assertEqual(command[command.index("--profile") + 1], "yolo")
            self.assertEqual(command[command.index("--model") + 1], "named deployment")
            self.assertIn('approval_policy="never"', command)
            self.assertIn('web_search="disabled"', command)
            self.assertIn("sandbox_workspace_write.network_access=false", command)
            self.assertFalse(any("writable_roots" in part or "exclude_tmpdir" in part
                                 or "ignore-rules" in part for part in command))
            if phase == "auftrag":
                (self.work / "proof.txt").write_bytes(b"verified\n")
                return result("Created proof.txt")
            self.assertEqual((self.work / "proof.txt").read_bytes(), b"verified\n")
            return result(json.dumps(PASS))

        with self.fake_codex(dispatch):
            runner.run()
        self.assertEqual([phase for phase, _ in seen], ["auftrag", "review"])
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(runner.reviewed_this_run, {"1"})
        self.assert_accepted_artifact(runner, plan=DONE,
                                      artifact="proof.txt", data=b"verified\n")

    def test_transport_adapter_preserves_synthetic_host_env_and_argv_boundaries(self):
        home = self.base / "codex home"
        home.mkdir()
        configured_root = self.base / "operator writable root"
        config = home / "config.toml"
        original = ('model_provider = "synthetic"\n'
                    '[sandbox_workspace_write]\n'
                    f'writable_roots = ["{configured_root}"]\n').encode()
        config.write_bytes(original)
        env = {"CODEX_HOME": str(home), "SYNTHETIC_PROVIDER_TOKEN": "canary-only",
               "HTTPS_PROXY": "http://proxy.invalid", "NO_PROXY": "localhost",
               "SSL_CERT_FILE": str(self.base / "ca.pem"), "TMPDIR": str(self.base / "tmp")}
        captured = []

        def fake_execute(request):
            captured.append((request, codex_transport.build_command(request)))
            return SimpleNamespace(trace=result("synthetic answer"))

        with patch.object(codex_transport, "execute", side_effect=fake_execute):
            answer = autobuild.run_codex_exec_json(
                "synthetic prompt", self.work, sandbox="workspace-write",
                output_last_message_path=None, raw_log=self.base / "events.jsonl",
                pretty_log=self.base / "pretty.log", extra_args=[], env=env,
                model="named deployment", config_profile="dev")
        self.assertEqual(answer.end_answer, "synthetic answer")
        request, command = captured[0]
        self.assertEqual(dict(request.env), env)
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(command[command.index("--model") + 1], "named deployment")
        self.assertEqual(command[command.index("--profile") + 1], "dev")
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertNotIn("canary-only", repr(command))
        self.assertFalse(any("writable_roots" in part for part in command))

    def test_option_injection_and_removed_yolo_switch_fail_while_names_work(self):
        for name in ("dev", "yolo"):
            self.assertEqual(codex_policy.validate_config_profile(name), name)
        for value in ("dev --sandbox danger-full-access", "-c", "../profile", "dev\n-c"):
            with self.subTest(value=value), self.assertRaises(codex_policy.CodexPolicyError):
                codex_policy.validate_config_profile(value)
        for extra in (("--sandbox", "danger-full-access"),
                      ("-c", 'approval_policy="on-request"'),
                      ("--add-dir", str(self.base)),
                      ("-c", "sandbox_workspace_write.writable_roots=[]")):
            with self.subTest(extra=extra), self.assertRaises(codex_policy.CodexPolicyError):
                codex_policy.validate_extra_args(extra)
        for key in ("allow_yolo", "yolo", "full_auto", "approval_policy"):
            with self.subTest(key=key), self.assertRaises(codex_policy.CodexPolicyError):
                codex_policy.reject_policy_keys({key: False}, source="CFG")
        with self.assertRaises(codex_policy.CodexPolicyError):
            codex_policy.validate_launcher(("codex", "--sandbox", "danger-full-access"))

    def test_model_and_output_paths_are_single_argv_values(self):
        model = 'deployment " -c approval_policy="on-request"'
        output = self.base / 'answer -c approval_policy=on-request.json'
        request = codex_transport.CodexExecRequest(
            prompt="synthetic", cwd=self.work, env={}, model=model,
            output_schema=self.base / "schema with spaces.json",
            output_last_message=output,
            raw_log=self.base / "events.jsonl", pretty_log=self.base / "pretty.log")
        command = codex_transport.build_command(request)
        self.assertEqual(command[command.index("--model") + 1], model)
        self.assertEqual(command[command.index("--output-schema") + 1],
                         str(self.base / "schema with spaces.json"))
        self.assertEqual(command[command.index("--output-last-message") + 1], str(output))
        self.assertEqual(command.count("-c"), 2)
        self.assertNotIn('approval_policy="on-request"', command)
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")

    def test_unavailable_selected_model_does_not_fallback_or_complete_task(self):
        self.write_plan(OPEN)
        runner = self.runner(stop_id="1")
        attempts = []

        def unavailable(**kwargs):
            attempts.append((kwargs["phase"], kwargs["model"]))
            return codex_transport.RunResult(process_exit_code=1, execution_error={
                "category": "technical", "code": "codex_turn_failed",
                "message": "synthetic model unavailable", "phase": kwargs["phase"]})

        with self.fake_codex(unavailable):
            runner.run()
        self.assertEqual(attempts, [("auftrag", "named deployment")])
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(runner.reviewed_this_run, set())
        self.assertEqual(self.todo.read_text(), OPEN)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text())["text"], OPEN)
        self.assertFalse((self.work / "proof.txt").exists())

    def test_shell_network_web_search_and_provider_paths_stay_separate(self):
        request = codex_transport.CodexExecRequest(
            prompt="synthetic", cwd=self.work, env={},
            raw_log=self.base / "events.jsonl", pretty_log=self.base / "pretty.log",
            extra_args=("-c", 'web_search="live"'), network_access=False,
            model_provider="corporate")
        command = codex_transport.build_command(request)
        self.assertIn('web_search="live"', command)
        self.assertIn("sandbox_workspace_write.network_access=false", command)
        self.assertIn('model_provider="corporate"', command)
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(codex_policy.decision_event_violation(
            {"type": "item.started", "item": {"type": "mcp_tool_call"}}),
            "Forbidden or unknown decision item: ['mcp_tool_call']")

    def test_windows_npm_shim_resolves_node_without_shell_or_extra_flags(self):
        bin_dir = self.base / "npm bin with spaces"
        package = bin_dir / "node_modules" / "@openai" / "codex"
        (package / "bin").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({
            "name": "@openai/codex", "bin": {"codex": "bin/codex.js"}}), newline="")
        script = package / "bin" / "codex.js"
        script.write_text("// synthetic fixture\n", newline="")
        node = bin_dir / "node.exe"
        node.write_bytes(b"synthetic")
        shim = bin_dir / "codex.cmd"
        shim.write_text(codex_launcher._npm_shim(
            "node_modules\\@openai\\codex\\bin\\codex.js"), encoding="utf-8", newline="")
        selected = codex_launcher.resolve_launcher(
            "codex", cwd=self.work, env={"PATH": str(bin_dir)}, platform_name="nt")
        self.assertEqual(selected.kind, "windows-npm-node")
        self.assertEqual(selected.argv, (str(node), str(script)))
        shim.write_text(shim.read_text() + "\n& unwanted-command\n", newline="")
        with self.assertRaises(codex_launcher.CodexLauncherError):
            codex_launcher.resolve_launcher(
                "codex", cwd=self.work, env={"PATH": str(bin_dir)}, platform_name="nt")
        native = bin_dir / "codex.exe"
        native.write_bytes(b"synthetic")
        selected = codex_launcher.resolve_launcher(
            "codex", cwd=self.work, env={"PATH": str(bin_dir)}, platform_name="nt")
        self.assertEqual(selected.argv, (str(native),))
        self.assertEqual(selected.kind, "windows-native")

    def test_process_start_uses_resolved_argv_and_exact_environment_without_shell(self):
        launcher = codex_launcher.CodexLauncher(
            "codex", str(self.base / "codex.exe"), "synthetic-native",
            (str(self.base / "codex.exe"),))
        process = SimpleNamespace()
        tree = SimpleNamespace(popen_options={}, bind=lambda _: None,
                               abort_start=lambda _: None)
        env = {"PATH": str(self.base), "SYNTHETIC_PROVIDER_TOKEN": "canary-only"}
        with patch.object(codex_transport, "resolve_launcher", return_value=launcher), \
             patch.object(codex_transport, "ProcessTree", return_value=tree), \
             patch.object(codex_transport.subprocess, "Popen", return_value=process) as popen:
            started = codex_transport._start_process(
                ["codex", "exec", "--model", "model with spaces", "-"],
                cwd=self.work, env=env)
        self.assertIs(started, process)
        self.assertEqual(popen.call_args.args[0],
                         [str(self.base / "codex.exe"), "exec", "--model",
                          "model with spaces", "-"])
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(popen.call_args.kwargs["env"], env)
        self.assertEqual(started.arquilo_argv, popen.call_args.args[0])

    def test_owner_runtime_profile_preflight_is_explicit_argv_and_env_overlay(self):
        todo = self.work / "tasks.md"
        todo.write_text("1. ***Task***: Synthetic profile probe.\n", newline="")
        profile = runtime_profile.RuntimeProfile(preflight=runtime_profile.PreflightSpec(
            command=("synthetic-check", "--input", "{todo_file}", " spaced value ", ""),
            environment={"PROFILE_WORKDIR": "{workdir}"}))
        base_env = {"PATH": str(self.base), "SYNTHETIC_PROVIDER_TOKEN": "canary-only"}
        with patch.object(runtime_profile.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
            runtime_profile.run_runtime_profile_preflight(
                profile, workdir=self.work, todo_file=todo, environ=base_env)
        self.assertEqual(run.call_args.args[0],
                         ["synthetic-check", "--input", str(todo), " spaced value ", ""])
        self.assertEqual(run.call_args.kwargs["env"],
                         {**base_env, "PROFILE_WORKDIR": str(self.work)})
        self.assertIs(run.call_args.kwargs["check"], False)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(base_env["SYNTHETIC_PROVIDER_TOKEN"], "canary-only")


if __name__ == "__main__":
    import unittest
    unittest.main()
