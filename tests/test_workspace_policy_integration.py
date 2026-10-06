# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline argv boundaries; these tests do not certify native Codex isolation."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_policy as policy
from codex_transport import CodexExecRequest, build_command


class WorkspacePolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.work = self.base / 'work'
        self.work.mkdir()
        self.home = self.base / 'configured-home'
        self.home.mkdir()
        self.env = {'CODEX_HOME': str(self.home), 'PROVIDER_TOKEN': 'synthetic-secret',
                    'HTTPS_PROXY': 'https://proxy.example.invalid',
                    'TMPDIR': str(self.base / 'operator-temp')}
        self.request = CodexExecRequest(prompt='Synthetic command-construction test.',
            cwd=self.work, env=self.env, raw_log=self.base / 'raw.jsonl',
            pretty_log=self.base / 'pretty.log')

    def assert_selected_policy(self, command, sandbox, network):
        self.assertEqual(command.count('--sandbox'), 1)
        self.assertEqual(command[command.index('--sandbox') + 1], sandbox)
        self.assertEqual(command.count('approval_policy="never"'), 1)
        self.assertIn('sandbox_workspace_write.network_access=' + str(network).lower(), command)
        for flag in ('--ignore-rules', '--ignore-user-config', '--full-auto',
                     '--dangerously-bypass-approvals-and-sandbox', '--add-dir'):
            self.assertNotIn(flag, command)
        for key in ('sandbox_workspace_write.writable_roots=',
                    'sandbox_workspace_write.exclude_tmpdir_env_var=',
                    'sandbox_workspace_write.exclude_slash_tmp='):
            self.assertFalse(any(arg.startswith(key) for arg in command))

    def test_normal_production_and_review_keep_explicit_mode_with_named_profiles(self):
        for sandbox in ('workspace-write', 'read-only'):
            for name in (None, 'corporate', 'dev', 'yolo', 'unsandboxed',
                         'danger-full-access', 'full-access'):
                with self.subTest(sandbox=sandbox, profile=name):
                    cmd = build_command(replace(self.request, sandbox=sandbox, config_profile=name))
                    self.assert_selected_policy(cmd, sandbox, False)
                    if name is None:
                        self.assertNotIn('--profile', cmd)
                    else:
                        self.assertEqual(cmd[cmd.index('--profile') + 1], name)
                    self.assertNotIn('--model', cmd)
                    self.assertFalse(any(arg.startswith('model_provider=') for arg in cmd))

    def test_network_remains_an_explicit_grant_independent_of_profile_name(self):
        for network in (False, True):
            for sandbox in ('workspace-write', 'read-only'):
                cmd = build_command(replace(self.request, sandbox=sandbox,
                    config_profile='dev', network_access=network))
                self.assert_selected_policy(cmd, sandbox, network)
        self.assertFalse(policy.effective_network_access(True, 'false'))
        with self.assertRaises(policy.CodexPolicyError):
            policy.effective_network_access(False, 'true')

    def test_decide_retains_minimal_read_only_contract(self):
        for name in (None, 'dev', 'yolo'):
            req = replace(self.request, decision_only=True, sandbox='read-only',
                          config_profile=name)
            cmd = build_command(req)
            expected = ['codex', 'exec', '--json']
            if name is not None:
                expected += ['--profile', name]
            expected += ['--skip-git-repo-check', '--sandbox', 'read-only',
                         '-c', 'approval_policy="never"', '-']
            self.assertEqual(cmd, expected)
        for values in ({'sandbox': 'workspace-write'}, {'network_access': True}):
            with self.subTest(values=values), self.assertRaises(policy.CodexPolicyError):
                replace(req, **values)
        event = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call'}}
        self.assertIsNotNone(policy.decision_event_violation(event))

    def test_extra_arguments_cannot_replace_selected_policy(self):
        for args in (('--sandbox', 'danger-full-access'), ('--profile', 'dev'),
                     ('--add-dir', str(self.base)), ('--ignore-rules',),
                     ('-c', 'approval_policy="on-request"'),
                     ('-c', 'sandbox_workspace_write.writable_roots=[]'),
                     ('-c', 'sandbox_workspace_write.network_access=true')):
            with self.subTest(args=args), self.assertRaises(policy.CodexPolicyError):
                replace(self.request, extra_args=args)
        cmd = build_command(replace(self.request, extra_args=('--color', 'never')))
        self.assert_selected_policy(cmd, 'workspace-write', False)

    def test_task_policy_fields_and_unsafe_profile_syntax_remain_rejected(self):
        for key in ('sandbox', 'sandbox_mode', 'writable_roots', 'approval_policy',
                    'extra_args', 'skip_review', 'permissions', 'allow_yolo'):
            with self.subTest(key=key), self.assertRaises(policy.CodexPolicyError):
                policy.reject_policy_keys({key: False}, source='CFG task')
        for name in ('../dev', 'a..b', 'dev --sandbox read-only', '', 'dev\nprofile'):
            with self.subTest(name=name), self.assertRaises(policy.CodexPolicyError):
                replace(self.request, config_profile=name)
        with self.assertRaises(policy.CodexPolicyError):
            replace(self.request, sandbox='danger-full-access')

    def test_command_building_preserves_host_config_and_environment(self):
        config = self.home / 'config.toml'
        original = b'[sandbox_workspace_write]\nwritable_roots = ["operator-chosen"]\n'
        config.write_bytes(original)
        before_env = dict(self.env)
        with patch.object(Path, 'read_text', side_effect=AssertionError('No config reads')):
            cmd = build_command(replace(self.request, config_profile='corporate'))
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(self.env, before_env)
        self.assertEqual(dict(self.request.env), before_env)
        self.assertNotIn('synthetic-secret', repr(cmd))
        self.assertNotIn('proxy.example.invalid', repr(cmd))


if __name__ == '__main__':
    unittest.main()
