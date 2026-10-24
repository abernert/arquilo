# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Primary workspace launcher authority survives task cwd and worker changes."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from test_public_runtime import PASS, result
import autobuild
import codex_launcher
import codex_transport
import decision_exec
from autobuild_contract import AutoBuildContext, AutoBuildOptions, call_payload, decode_call
from codex_launcher import resolve_launcher
from decision_exec import DecisionExecSettings
from decision_request import DecisionRequest
from host_launcher import launcher_environment


class LauncherWorkspaceTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.host = self.base / 'host-bin'
        self.host.mkdir()
        self.project_bin = self.work / 'bin'
        self.project_bin.mkdir()
        self.calls = self.base / 'launcher-calls.jsonl'

    def synthetic_codex(self, directory, label):
        code = f'''#!{sys.executable}
import json, os, pathlib, sys
if '--version' in sys.argv:
    print('codex-cli 0.159.1')
    raise SystemExit(0)
sandbox = sys.argv[sys.argv.index('--sandbox') + 1]
with pathlib.Path({str(self.calls)!r}).open('a', encoding='utf-8') as stream:
    stream.write(json.dumps({{'launcher': {label!r}, 'cwd': os.getcwd(), 'sandbox': sandbox}}) + '\\n')
sys.stdin.buffer.read()
answer = {json.dumps(PASS)!r} if sandbox == 'read-only' else 'Synthetic result.'
for event in ({{'type': 'turn.started'}},
              {{'type': 'item.completed', 'item': {{'type': 'agent_message', 'text': answer}}}},
              {{'type': 'turn.completed'}}):
    print(json.dumps(event), flush=True)
'''
        executable = directory / 'codex'
        executable.write_text(code, encoding='utf-8', newline='')
        executable.chmod(0o755)
        return executable

    def run_cfg(self, *, worker):
        self.write_plan('***CFG workspace=child***\n1. ***Task***: Synthetic boundary check.\n')
        trusted = self.synthetic_codex(self.host, 'host')
        self.synthetic_codex(self.project_bin, 'project')
        environment = {'PATH': str(self.project_bin) + os.pathsep + str(self.host)}
        with patch.dict(os.environ, environment), redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()), patch.object(autobuild, '_terminal_beep'):
            self.assertEqual(resolve_launcher('codex', cwd=self.work, env=os.environ).source, str(trusted))
            runner = self.runner()
            outcome, context, _ = runner._execute_todo_autobuild(
                runner._parse_todo_file()[0], use_cli_subprocess=worker)
        self.assertTrue(outcome.completed, outcome.message)
        rows = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([row['sandbox'] for row in rows], ['workspace-write', 'read-only'])
        self.assertEqual([row['launcher'] for row in rows], ['host', 'host'])
        self.assertEqual({row['cwd'] for row in rows}, {str(context.workdir)})
        if worker:
            requests = list((runner.state_dir / 'worker_calls').glob('*/request.json'))
            self.assertEqual(len(requests), 1)
            payload = json.loads(requests[0].read_text())
            self.assertEqual(payload['context']['launcher_workspace'], str(self.work))

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixtures; worker serialization also tested separately')
    def test_cfg_in_process_production_and_review_exclude_primary_workspace(self):
        self.run_cfg(worker=False)

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixtures; worker serialization also tested separately')
    def test_cfg_private_worker_preserves_primary_workspace_boundary(self):
        self.run_cfg(worker=True)

    def run_symlink_cfg(self, *, worker):
        self.write_plan('***CFG workspace=child***\n1. ***Task***: Synthetic symlink boundary.\n')
        project = self.synthetic_codex(self.project_bin, 'project')
        self.synthetic_codex(self.host, 'host')
        alias = self.base / 'alias-bin'
        alias.mkdir()
        try:
            (alias / 'codex').symlink_to(project)
        except (OSError, NotImplementedError):
            self.skipTest('File symlinks unavailable')
        with patch.dict(os.environ, {'PATH': str(alias) + os.pathsep + str(self.host)}), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
             patch.object(autobuild, '_terminal_beep'):
            runner = self.runner()
            outcome, _, _ = runner._execute_todo_autobuild(
                runner._parse_todo_file()[0], use_cli_subprocess=worker)
        self.assertFalse(outcome.completed)
        self.assertEqual(outcome.execution_error['code'], 'codex_launch_failed')
        self.assertFalse(self.calls.exists(), 'No workspace-linked executable may start')

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixture')
    def test_cfg_in_process_rejects_external_file_link_to_primary_root(self):
        self.run_symlink_cfg(worker=False)

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixture')
    def test_cfg_private_worker_rejects_external_file_link_to_primary_root(self):
        self.run_symlink_cfg(worker=True)

    def test_context_is_absolute_and_survives_private_worker_serialization(self):
        for value in ('relative', '', 'bad\0path', 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AutoBuildContext(launcher_workspace=value)
        context = AutoBuildContext(launcher_workspace=self.work)
        payload = call_payload(task='synthetic', workdir=self.work / 'child',
                               options=AutoBuildOptions(), context=context)
        restored = decode_call(json.loads(json.dumps(payload)))['context']
        self.assertEqual(restored.launcher_workspace, str(self.work))

    def test_sanitize_only_empty_path_does_not_restore_project_lookup(self):
        child = self.work / 'child'
        child.mkdir()
        name = 'codex.exe' if os.name == 'nt' else 'codex'
        executable = self.project_bin / name
        executable.write_text('synthetic-only')
        executable.chmod(0o755)
        source = {'PATH': str(self.project_bin), 'SYNTHETIC_PROVIDER_TOKEN': 'preserved'}
        cleaned = launcher_environment(source, workspace=self.work)
        self.assertEqual(cleaned, {**source, 'PATH': ''})
        self.assertEqual(source['PATH'], str(self.project_bin))
        with self.assertRaises(OSError):
            resolve_launcher('codex', cwd=child, env=cleaned)

    def test_windows_npm_targets_preserve_primary_and_active_workspace_boundaries(self):
        active = self.base / 'separate-task'
        active.mkdir()
        package = self.host / 'node_modules' / '@openai' / 'codex'
        script = package / 'bin' / 'codex.js'
        script.parent.mkdir(parents=True)
        script.write_text('// synthetic host script', encoding='utf-8')
        (package / 'package.json').write_text(json.dumps({'name': '@openai/codex',
            'bin': {'codex': 'bin/codex.js'}}), encoding='utf-8')
        shim = self.host / 'codex.cmd'
        shim.write_text(codex_launcher._npm_shim('node_modules\\@openai\\codex\\bin\\codex.js'),
                        encoding='utf-8', newline='')
        node = self.host / 'node.exe'
        node.write_bytes(b'synthetic host interpreter')
        def resolve():
            return resolve_launcher(str(shim), cwd=active, additional_workspace=self.work,
                                    env={'Path': str(self.host)}, platform_name='nt')
        self.assertEqual(resolve().argv, (str(node), str(script)))
        for boundary in (self.work, active):
            for selected in (node, script):
                with self.subTest(boundary=boundary.name, target=selected.name):
                    target = boundary / selected.name
                    target.write_bytes(b'synthetic project-owned target')
                    original = selected.read_bytes()
                    selected.unlink()
                    try:
                        selected.symlink_to(target)
                    except (OSError, NotImplementedError):
                        selected.write_bytes(original)
                        self.skipTest('File symlinks unavailable; external npm positive control passed')
                    try:
                        with self.assertRaises(OSError):
                            resolve()
                    finally:
                        selected.unlink()
                        selected.write_bytes(original)
        selector = self.project_bin / 'codex.cmd'
        selector.symlink_to(shim)
        with self.assertRaises(OSError):
            resolve_launcher(str(selector), cwd=active, additional_workspace=self.work,
                             env={'Path': str(self.host)}, platform_name='nt')

    def test_metadata_and_mcp_probes_reject_primary_workspace_file_alias(self):
        child = self.work / 'child'
        child.mkdir()
        name = 'codex.exe' if os.name == 'nt' else 'codex'
        target = self.project_bin / name
        target.write_bytes(b'synthetic executable; must never start')
        target.chmod(0o755)
        try:
            (self.host / name).symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('File symlinks unavailable')
        request = codex_transport.CodexExecRequest(prompt='Synthetic only.', cwd=child,
            env={'PATH': str(self.host)}, raw_log=self.base / 'events.jsonl',
            pretty_log=self.base / 'pretty.log', launcher_workspace=self.work,
            sandbox='read-only', decision_only=True)
        with patch.object(codex_transport.subprocess, 'Popen') as popen:
            with self.assertRaises(OSError):
                codex_transport.probe_cli_metadata(probe='version', launcher=request.launcher,
                    cwd=child, env=request.env, timeout=1, launcher_workspace=self.work)
            with self.assertRaises(OSError):
                codex_transport.probe_mcp_inventory(('mcp', 'list', '--json'), request=request)
            outcome = codex_transport.execute(request)
        popen.assert_not_called()
        self.assertEqual(outcome.trace.execution_error['code'], 'codex_decision_cli_failed')

    def test_decide_attempt_preserves_primary_boundary_after_temporary_cwd_change(self):
        child = self.work / 'child'
        child.mkdir()
        request = DecisionRequest(question='Synthetic?', options=('YES', 'NO'), context=(),
            run_id='synthetic', task_id='1', phase='decide', attempt_id='1')
        with patch.object(codex_transport, 'execute', return_value=None) as execute:
            attempt = decision_exec.execute_attempt(request, project_root=child,
                launcher_workspace=self.work, trusted_codex_home=None, temp_root=self.base,
                env={'PATH': str(self.project_bin) + os.pathsep + str(self.host)},
                launcher=sys.executable, raw_log=self.base / 'events.jsonl',
                pretty_log=self.base / 'pretty.log')
        self.addCleanup(attempt.cleanup_workdir)
        actual = execute.call_args.args[0]
        self.assertEqual(actual.launcher_workspace, self.work)
        self.assertFalse(actual.cwd.is_relative_to(self.work))
        self.assertEqual(actual.env['PATH'], str(self.host))

    def legacy_attempt(self, *, explicit_settings, launcher='codex'):
        active = self.base / 'separate-task'
        active.mkdir(exist_ok=True)
        active_bin = active / 'bin'
        active_bin.mkdir(exist_ok=True)
        path = os.pathsep.join(map(str, (self.project_bin, active_bin, self.host)))
        environment = {'PATH': path, 'SYNTHETIC_PROVIDER_TOKEN': 'original'}
        settings = (DecisionExecSettings(project_root=active, log_root=self.base / 'logs',
                    env={**environment, 'SYNTHETIC_PROVIDER_TOKEN': 'override'}, launcher=launcher)
                    if explicit_settings else None)
        captured = []
        def invoke(**kwargs):
            captured.append(kwargs)
            return result('No issues remain.' if kwargs['phase'] == 'review' else 'Synthetic result.')
        with patch.dict(os.environ, environment), \
             patch.object(autobuild, 'run_codex_exec_json', side_effect=invoke), \
             patch.object(autobuild, 'run_semantic_decision', side_effect=RuntimeError('synthetic-stop')) as decide, \
             patch.object(autobuild, '_terminal_beep'), redirect_stdout(io.StringIO()):
            summary = autobuild.start(task='Synthetic boundary check.', workdir=active,
                options=AutoBuildOptions(logfile=self.base / 'logs' / 'pretty.log',
                    rawlog=self.base / 'logs' / 'raw.jsonl', max_steps=1),
                context=AutoBuildContext(launcher_workspace=self.work,
                    budget_directory=self.state_root / ('override' if explicit_settings else 'default')),
                decision_settings=settings)
            self.assertEqual(os.environ['PATH'], path)
        for invocation in captured:
            self.assertEqual(invocation['env']['PATH'], str(self.host))
            self.assertEqual(invocation['env']['SYNTHETIC_PROVIDER_TOKEN'], 'original')
            self.assertEqual(invocation['launcher_workspace'], self.work)
        return summary, decide

    def test_legacy_decide_default_and_override_keep_both_workspace_boundaries(self):
        for explicit in (False, True):
            with self.subTest(explicit_settings=explicit):
                _, decide = self.legacy_attempt(explicit_settings=explicit)
                decide.assert_called_once()
                env = decide.call_args.kwargs['settings'].env
                self.assertEqual(env['PATH'], str(self.host))
                self.assertEqual(env['SYNTHETIC_PROVIDER_TOKEN'], 'override' if explicit else 'original')
                self.assertEqual(decide.call_args.kwargs['settings'].launcher_workspace, self.work)

    def test_explicit_legacy_decide_launcher_in_primary_workspace_is_rejected(self):
        name = 'codex.exe' if os.name == 'nt' else 'codex'
        launcher = self.project_bin / name
        launcher.write_text('synthetic-only')
        summary, decide = self.legacy_attempt(explicit_settings=True, launcher=str(launcher))
        decide.assert_not_called()
        self.assertFalse(summary.completed)
        self.assertEqual(summary.execution_error['code'], 'decision_invalid_input')
