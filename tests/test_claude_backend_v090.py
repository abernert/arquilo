# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""0.9 integration regressions: synthetic subprocesses; never real model calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import agent_backend
import arquilo_doctor
import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload, decode_call
import claude_transport as ct
from prompt_config import load_prompt_config, PromptConfigError
import run_todos
from task_resources import ResourceError, SkillCatalog
from test_claude_backend import Fixture, ROOT


class Claude090Tests(Fixture):
    def catalog(self, language='en'):
        text = (ROOT / 'prompts' / f'{language}.toml').read_text(encoding='utf-8')
        for name in ('reviewer_role', 'fix_assignment', 'decision_system', 'doctor_question'):
            pattern = r'(\[prompts\.' + name + r'\]\n(?:#[^\n]*\n)*text = """\n)'
            text, count = re.subn(pattern, lambda m: m[1] + f'CATALOG-{language}-{name}\n', text)
            self.assertEqual(count, 1)
        path = self.base / f'{language}.toml'
        path.write_text(text, encoding='utf-8')
        return path

    def skill(self, root=None):
        root = root or self.work / '.claude' / 'skills'
        path = root / 'proof' / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text('---\nname: proof\n---\nFROZEN-SKILL-INSTRUCTIONS\n', encoding='utf-8')
        return root, path

    def test_all_builtin_catalogs_and_worker_options_roundtrip(self):
        for language in ('default', 'de', 'en'):
            with self.subTest(language=language):
                options = AutoBuildOptions(backend='claude-code', prompt_config=language,
                                           mcp=(), review_mcp=(), skills=())
                payload = call_payload(options=options, context=AutoBuildContext(), task='Test', workdir=self.work)
                restored = decode_call(json.loads(json.dumps(payload)))['options']
                self.assertEqual(restored.backend, 'claude-code')
                self.assertEqual(restored.mcp, ())
                self.assertEqual(restored.prompt_config, load_prompt_config(language))
        self.assertEqual(self.rows(), [])

    def test_explicit_none_and_custom_catalog_survive_correction_loop(self):
        self.mode('fix_cycle')
        path = self.catalog('de')
        options = AutoBuildOptions(backend='claude-code', prompt_config=path,
                                   mcp=(), review_mcp=(), max_calls=8, max_steps=2)
        path.unlink()  # Worker/backend must use the frozen catalog, not reopen it.
        summary = autobuild.start(task='Create empty hello.txt.', workdir=self.work, options=options)
        self.assertTrue(summary.completed, str(summary.execution_error))
        rows = self.rows()
        self.assertEqual(len(rows), 4)
        for index in (1, 3):
            self.assertIn('CATALOG-de-reviewer_role', rows[index]['prompt'])
            self.assertEqual(set(rows[index]['tools']), set(ct.READ_TOOLS))
        self.assertIn('CATALOG-de-fix_assignment', rows[2]['prompt'])
        for row in rows:
            self.assertEqual(json.loads(row['argv'][row['argv'].index('--mcp-config') + 1]), {'mcpServers': {}})
            self.assertNotIn('--model', row['argv'])

    def test_legacy_review_decide_uses_custom_catalog_and_no_codex_model(self):
        self.mode('legacy_review')
        summary = autobuild.start(task='Create empty hello.txt.', workdir=self.work,
            options=AutoBuildOptions(backend='claude-code', prompt_config=self.catalog(),
                                     mcp=(), review_mcp=(), max_calls=4))
        self.assertTrue(summary.completed, str(summary.execution_error))
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]['tools'], [])
        self.assertIn('CATALOG-en-decision_system', rows[-1]['prompt'])
        self.assertNotIn('--model', rows[-1]['argv'])

    def test_doctor_honors_prompt_catalog_and_invalid_catalog_precedes_probe(self):
        path = self.catalog()
        report = arquilo_doctor.collect_report(backend='claude-code', workdir=self.work,
            env=self.env, prompt_config=path, check_decide=True)
        self.assertEqual(report['checks_status'], 'PASS')
        self.assertEqual(report['prompt_config'], load_prompt_config(path).metadata())
        self.assertIn('CATALOG-en-doctor_question', self.rows()[0]['prompt'])
        path.write_text('not a valid catalog', encoding='utf-8')
        with patch.object(ct, 'probe_cli', side_effect=AssertionError('must not probe')), self.assertRaises(PromptConfigError):
            arquilo_doctor.collect_report(backend='claude-code', workdir=self.work, env=self.env, prompt_config=path)

    def test_named_mcp_and_codex_profile_rejected_before_task_execution(self):
        for selection in ({'mcp': ('server',)}, {'review_mcp': ('server',)}):
            with self.subTest(selection=selection), self.assertRaisesRegex(ResourceError, 'Named MCP'):
                AutoBuildOptions(backend='claude-code', **selection)
        with self.assertRaisesRegex(ResourceError, 'Named MCP'):
            ct.run_claude_exec_json('Test', self.work, sandbox='read-only',
                output_last_message_path=None, raw_log=self.logs/'r', pretty_log=self.logs/'p', mcp_servers=('server',))
        with self.assertRaises(ValueError):
            AutoBuildOptions(backend='claude-code', config_profile='codex-profile')
        self.assertEqual(self.rows(), [])
        self.assertFalse((self.work/'hello.txt').exists())

    def test_skill_discovery_never_consults_codex_home(self):
        _, path = self.skill()
        class NoCodexEnvironment(dict):
            def get(self, key, default=None):
                if key == 'CODEX_HOME':
                    raise AssertionError('Claude must not consult CODEX_HOME')
                return super().get(key, default)
        env = NoCodexEnvironment(HOME=str(self.base/'home'), USERPROFILE=str(self.base/'home'))
        catalog = SkillCatalog(workdir=self.work, backend='claude-code', env=env)
        self.assertEqual(catalog.get(('proof',))[0].path, str(path))
        self.assertFalse(any('.codex' in root for root in catalog.roots))

    def test_selected_skill_instructions_reach_production_and_review(self):
        root, path = self.skill()
        summary = autobuild.start(task='Create empty hello.txt.', workdir=self.work,
            options=AutoBuildOptions(backend='claude-code', skills=('proof',),
                                     skill_dirs=(str(root),), mcp=(), max_calls=4))
        self.assertTrue(summary.completed, str(summary.execution_error))
        for row in self.rows():
            self.assertIn('FROZEN-SKILL-INSTRUCTIONS', row['prompt'])
            self.assertIn('sha256', row['prompt'])
            self.assertNotIn('Skill', row['tools'])
            self.assertIn('--disable-slash-commands', row['argv'])

    @unittest.skipIf(os.name == 'nt', 'Executable subprocess fixture is POSIX')
    def test_real_worker_uses_frozen_catalog_and_none_resources(self):
        path = self.catalog()
        options = AutoBuildOptions(backend='claude-code', prompt_config=path, mcp=(), skills=(), max_calls=4)
        payload = call_payload(options=options, context=AutoBuildContext(), task='Create empty hello.txt.', workdir=self.work)
        path.unlink()
        request = self.base/'worker.json'
        request.write_text(json.dumps(payload), encoding='utf-8')
        out = subprocess.run([sys.executable, '-B', str(ROOT/'autobuild.py'), '--request-json', str(request)],
            cwd=self.work, env=self.env, capture_output=True, timeout=40)
        self.assertEqual(out.returncode, 0, out.stderr.decode(errors='replace') + out.stdout.decode(errors='replace'))
        self.assertIn('CATALOG-en-reviewer_role', self.rows()[1]['prompt'])

    @unittest.skipIf(os.name == 'nt', 'Executable subprocess fixture is POSIX')
    def test_tasklist_defaults_skills_and_catalog_finish_with_mandatory_review(self):
        root, _ = self.skill()
        todo = self.work/'tasks.md'
        todo.write_text('***DEFAULTS mcp=none review_mcp=none skills=proof***\n'
                        '1. ***TASK***: Create empty hello.txt.\n', encoding='utf-8')
        args = [sys.executable, '-B', str(ROOT/'arquilo.py'), 'tasklist', 'run', '--backend', 'claude-code',
                '--workdir', str(self.work), '--todo-file', str(todo), '--state-dir', str(self.base/'state'),
                '--prompt-config', str(self.catalog()), '--skill-dir', str(root),
                '--process-stop-policy', 'controller-only', '--max-calls', '4']
        out = subprocess.run(args, cwd=self.work, env=self.env, capture_output=True, timeout=40)
        self.assertEqual(out.returncode, 0, out.stderr.decode(errors='replace') + out.stdout.decode(errors='replace'))
        self.assertIn('***DONE***', todo.read_text())
        self.assertEqual(len(self.rows()), 2)
        self.assertIn('CATALOG-en-reviewer_role', self.rows()[1]['prompt'])
        for row in self.rows():
            self.assertIn('FROZEN-SKILL-INSTRUCTIONS', row['prompt'])
        snapshots = list((self.base/'state').rglob('prompt_config_snapshot.json'))
        self.assertTrue(snapshots)
        self.assertEqual(load_prompt_config(json.loads(snapshots[0].read_text())).language, 'en')

    @unittest.skipIf(os.name == 'nt', 'Executable subprocess fixture is POSIX')
    def test_named_mcp_in_later_task_fails_before_any_model_call(self):
        todo = self.work/'tasks.md'
        original = ('1. ***TASK***: Create empty hello.txt.\n\n'
                    '***CFG mcp=server***\n2. ***TASK***: Another task.\n')
        todo.write_text(original, encoding='utf-8')
        out = subprocess.run([sys.executable, '-B', str(ROOT/'arquilo.py'), 'tasklist', 'run',
            '--backend', 'claude-code', '--workdir', str(self.work), '--todo-file', str(todo),
            '--state-dir', str(self.base/'state')], env=self.env, capture_output=True, timeout=20)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('Named MCP', out.stderr.decode(errors='replace'))
        self.assertEqual(todo.read_text(), original)
        self.assertEqual(self.rows(), [])

    def test_missing_review_with_none_resources_and_custom_catalog_never_completes(self):
        self.mode('review_missing_result')
        summary = autobuild.start(task='Create empty hello.txt.', workdir=self.work,
            options=AutoBuildOptions(backend='claude-code', prompt_config=self.catalog('de'),
                                     mcp=(), review_mcp=(), max_calls=4))
        self.assertFalse(summary.completed)
        self.assertIsNotNone(summary.execution_error)
        self.assertEqual(len(self.rows()), 2)
        self.assertIn('CATALOG-de-reviewer_role', self.rows()[1]['prompt'])

    def test_capabilities_do_not_claim_named_claude_mcp_support(self):
        result = run_todos.arquilo_capabilities_payload()
        self.assertEqual(result['backends']['default'], 'codex')
        self.assertEqual(result['features']['claude_code.mcp_selection'], 0)
        self.assertEqual(result['features']['claude_code.prompt_config'], 1)


if __name__ == '__main__':
    unittest.main()
