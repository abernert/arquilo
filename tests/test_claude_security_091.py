# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Claude-specific execution-path checks on the shared 0.9.1 safety basis."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload
import claude_launcher as launcher
import claude_transport as ct
from host_launcher import launcher_environment
from runtime_contracts import ExecutionStatus
from decision_request import DecisionRequest
import claude_decision
from test_claude_backend import Fixture, ROOT


class ClaudeHostLauncher091(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='arquilo-claude-host-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.work = self.base / 'workspace'; self.work.mkdir()
        self.active = self.work / 'child'; self.active.mkdir()
        self.host = self.base / 'host'; self.host.mkdir()
        self.name = 'claude.exe' if os.name == 'nt' else 'claude'

    def executable(self, path):
        path.write_bytes(b'synthetic host executable; never executed by resolver tests')
        path.chmod(0o755)
        return path

    def test_relative_empty_workspace_path_entries_cannot_select_host_tool(self):
        bad = self.executable(self.work / self.name)
        good = self.executable(self.host / self.name)
        env = {'PATH': os.pathsep.join(('', '.', str(self.work), str(self.host)))}
        chosen = launcher.resolve_launcher('claude', cwd=self.active, env=env,
                                          workspace=self.work, additional_workspace=self.active)
        self.assertEqual(chosen.argv[0], str(good))
        for explicit in (str(bad), './' + self.name, '../' + self.name):
            with self.subTest(explicit=explicit), self.assertRaises(OSError):
                launcher.resolve_launcher(explicit, cwd=self.active, env=env, workspace=self.work)
        self.assertEqual(launcher_environment(env, workspace=self.work)['PATH'], str(self.host))

    def test_symlink_host_entry_to_primary_workspace_is_not_authorized(self):
        bad = self.executable(self.work / self.name)
        link = self.host / self.name
        try: link.symlink_to(bad)
        except (OSError, NotImplementedError): self.skipTest('File symlinks unavailable')
        with self.assertRaises(OSError):
            launcher.resolve_launcher(str(link), cwd=self.active, env={'PATH': str(self.host)}, workspace=self.work)

    def test_alias_to_codex_is_still_prohibited(self):
        codex = self.executable(self.host / ('codex.exe' if os.name == 'nt' else 'codex'))
        link = self.host / self.name
        try: link.symlink_to(codex)
        except (OSError, NotImplementedError): self.skipTest('File symlinks unavailable')
        with self.assertRaisesRegex(OSError, 'Codex'):
            launcher.resolve_launcher(str(link), cwd=self.work, env={'PATH': str(self.host)})

    def test_windows_standard_npm_layout_checks_node_and_script_boundaries(self):
        package = self.host / 'node_modules' / '@anthropic-ai' / 'claude-code'
        package.mkdir(parents=True)
        script = self.executable(package / 'cli.js')
        (package / 'package.json').write_text(json.dumps({'name':'@anthropic-ai/claude-code', 'bin':{'claude':'cli.js'}}))
        shim = self.host / 'claude.cmd'
        shim.write_text(launcher._npm_shim('node_modules\\@anthropic-ai\\claude-code\\cli.js'), encoding='utf-8', newline='')
        node = self.executable(self.host / 'node.exe')
        def resolve():
            return launcher.resolve_launcher(str(shim), cwd=self.active, env={'Path':str(self.host)},
                platform_name='nt', workspace=self.work, additional_workspace=self.active)
        self.assertEqual(resolve().argv, (str(node), str(script)))
        for component in (node, script):
            saved = component.read_bytes(); component.unlink()
            bad = self.executable(self.work / component.name)
            try: component.symlink_to(bad)
            except (OSError, NotImplementedError):
                component.write_bytes(saved); self.skipTest('Symlinks unavailable; standard shim verified')
            try:
                with self.assertRaises(OSError): resolve()
            finally:
                component.unlink(); component.write_bytes(saved)

    def test_decide_preserves_primary_boundary_when_active_task_is_nested(self):
        bad = self.executable(self.work / self.name)
        request = DecisionRequest(question='Choose A', options=('A','B'), context=(),
            run_id='r', task_id='1', phase='decide', attempt_id='a')
        with patch.object(ct, '_start', side_effect=AssertionError('No CLI may be started')), self.assertRaises(OSError):
            claude_decision.execute_attempt(request, project_root=self.active,
                env={'PATH':str(self.host), 'ARQUILO_CLAUDE_CODE_COMMAND':str(bad)},
                raw_log=self.base/'r.jsonl', pretty_log=self.base/'p.log', temp_root=self.base,
                launcher_workspace=self.work)


class ClaudeExecutionSecurity091(Fixture):
    def test_opaque_stop_prevents_even_metadata_probes(self):
        for kind in ('directory', 'invalid-text', 'linked'):
            with self.subTest(kind=kind):
                path = self.work / 'process_stop'
                if kind == 'directory': path.mkdir()
                elif kind == 'invalid-text': path.write_bytes(b'\xff\xfe')
                else:
                    outside = self.base / 'stop-victim'; outside.write_text('DO NOT READ')
                    try: path.symlink_to(outside)
                    except (OSError, NotImplementedError): self.skipTest('File symlinks unavailable')
                try:
                    with patch.object(ct, 'probe_cli', side_effect=AssertionError('Must not probe')):
                        result = ct.execute(self.request(process_stop_path=path))
                    self.assertEqual(result.execution.status, ExecutionStatus.CANCELLED)
                    self.assertFalse(result.trace.turn_completed)
                    self.assertNotIn('DO NOT READ', result.trace.process_stop_details or '')
                finally:
                    if path.is_symlink() or path.is_file(): path.unlink()
                    else: path.rmdir()
        self.assertEqual(self.rows(), [])

    def test_terminal_after_invalid_stream_cannot_start_review_or_complete(self):
        self.mode('thinking_tokens_extra_field')
        summary = autobuild.start(task='Create hello.txt', workdir=self.work,
            options=AutoBuildOptions(backend='claude-code', max_steps=1, max_calls=4))
        self.assertFalse(summary.completed)
        self.assertEqual(summary.review_runs, 0)
        self.assertIsNotNone(summary.execution_error)
        self.assertEqual(len(self.rows()), 1)

    def test_ambiguous_prose_does_not_override_shared_fail_gate(self):
        self.mode('ambiguous_legacy_review')
        summary = autobuild.start(task='Create hello.txt', workdir=self.work,
            options=AutoBuildOptions(backend='claude-code', max_steps=1, max_calls=4))
        self.assertFalse(summary.completed)
        self.assertEqual(summary.review_classification['verdict'], 'FAIL')
        self.assertEqual(len(self.rows()), 2)  # No permissive Decide call.

    def test_request_rejects_relative_primary_workspace(self):
        with self.assertRaises(ValueError): self.request(launcher_workspace=Path('relative'))

    @unittest.skipIf(os.name == 'nt', 'POSIX host executable fixture; Windows resolver covered separately')
    def test_real_python_worker_keeps_external_launcher_and_peer_stops(self):
        child = self.work / 'child'; child.mkdir()
        # Project-local executable would succeed if selected, but must never run.
        bad = self.work / 'claude'
        bad.write_text('#!' + sys.executable + '\nfrom pathlib import Path\nPath(' + repr(str(self.base/'BAD_HOST')) + ').touch()\nraise SystemExit(101)\n')
        bad.chmod(0o700)
        environment = {**self.env, 'PATH': str(self.work)+os.pathsep+str(self.base)+os.pathsep+self.env['PATH']}
        environment.pop('ARQUILO_CLAUDE_CODE_COMMAND', None)
        context = AutoBuildContext(launcher_workspace=self.work,
            process_stop_paths=(str(self.work/'process_stop'),str(self.work/'peer'/'process_stop')))
        payload = call_payload(task='Create empty hello.txt', workdir=child,
            options=AutoBuildOptions(backend='claude-code', max_calls=4), context=context)
        path = self.base/'private-request.json'; path.write_text(json.dumps(payload))
        result = subprocess.run([sys.executable,'-B',str(ROOT/'autobuild.py'),'--request-json',str(path)],
            cwd=child, env=environment, capture_output=True, timeout=45)
        self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
        self.assertFalse((self.base/'BAD_HOST').exists())
        self.assertEqual(len(self.rows()),2)
        self.assertEqual({row['cwd'] for row in self.rows()}, {str(child)})
        self.assertTrue((child/'hello.txt').is_file())
        # A peer/root stop preserved in serialized context forbids a new call.
        (self.work/'peer').mkdir(); (self.work/'peer'/'process_stop').mkdir()
        again = subprocess.run([sys.executable,'-B',str(ROOT/'autobuild.py'),'--request-json',str(path)],
            cwd=child,env=environment,capture_output=True,timeout=20)
        self.assertNotEqual(again.returncode,0)
        self.assertEqual(len(self.rows()),2)

    def test_version_help_and_execution_pin_one_external_launcher(self):
        original = ct.resolve_launcher
        seen = []
        def resolve(*args, **kwargs):
            seen.append(args[0]); return original(*args, **kwargs)
        with patch.object(ct, 'resolve_launcher', side_effect=resolve):
            result = ct.execute(self.request())
        self.assertTrue(result.execution.succeeded, str(result.execution))
        self.assertEqual(len(seen), 1)
