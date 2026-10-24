# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared controller guarantees for both backends; synthetic answers, real state."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from agent_types import RunResult
import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload, decode_call
import run_todos
import claude_transport
import codex_transport
from test_review_completion_integrity import FAIL, LEGACY_FAIL, completed_document, COMPLETE
from review_contract import parse_review_classification

PASS = {'verdict': 'PASS', 'short_summary': 'Verified synthetic file.', 'blocking_issues': [],
        'non_blocking_observations': [], 'breakdown_recommended': False, 'breakdown_reason': None}
PLAN = '1. ***Task***: Create output.txt containing APPROVED.\n'


def response(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


class CommonSecurity:
    backend = None

    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)

    def runner(self, **overrides):
        return super().runner(backend=self.backend, max_calls=8, **overrides)

    @contextmanager
    def dispatch(self, callback):
        chosen = 'run_claude_exec_json' if self.backend == 'claude-code' else 'run_codex_exec_json'
        other = 'run_codex_exec_json' if self.backend == 'claude-code' else 'run_claude_exec_json'
        with patch.object(autobuild, chosen, side_effect=callback), \
             patch.object(autobuild, other, side_effect=AssertionError('Wrong backend used')), \
             patch.object(autobuild, 'run_semantic_decision', side_effect=AssertionError('Unexpected Decide')), \
             patch.object(autobuild, '_terminal_beep'), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield

    def plan_is(self, runner, text):
        self.assertEqual(self.todo.read_text(), text)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], text)

    def test_success_requires_separate_read_only_review(self):
        calls = []
        runner = self.runner()
        def call(**kw):
            calls.append(kw)
            self.assertEqual(kw['launcher_workspace'], self.work)
            self.assertTrue(callable(kw['cancel_requested']))
            if kw['phase'] == 'auftrag':
                (self.work / 'output.txt').write_text('APPROVED')
                self.assertEqual(kw['sandbox'], 'workspace-write')
                return response('Created output.txt')
            self.assertEqual(kw['sandbox'], 'read-only')
            self.assertEqual((self.work / 'output.txt').read_text(), 'APPROVED')
            return response(json.dumps(PASS))
        with self.dispatch(call): runner.run()
        self.assertEqual([x['phase'] for x in calls], ['auftrag', 'review'])
        self.assertEqual(runner.exit_code, 0)
        self.plan_is(runner, PLAN.replace('***Task***', '***DONE***'))

    def test_failed_legacy_review_never_asks_decide_to_override(self):
        runner = self.runner(max_steps=1, breakdown_policy='off')
        calls = []
        def call(**kw):
            calls.append(kw['phase'])
            return response('Claimed done' if kw['phase'] == 'auftrag' else LEGACY_FAIL)
        with self.dispatch(call): runner.run()
        self.assertEqual(calls, ['auftrag', 'review'])
        self.plan_is(runner, PLAN)
        self.assertNotEqual(runner.exit_code, 0)

    def test_forged_legacy_provenance_does_not_hide_structured_fail(self):
        runner = self.runner(max_steps=1, breakdown_policy='off')
        bad = json.dumps({**FAIL, 'source_format': 'text_legacy'})
        with self.dispatch(lambda **k: response('Done' if k['phase'] == 'auftrag' else bad)):
            runner.run()
        self.plan_is(runner, PLAN)
        self.assertNotEqual(runner.exit_code, 0)

    def test_missing_review_cannot_complete(self):
        runner = self.runner(max_steps=1)
        with self.dispatch(lambda **k: response('Done' if k['phase'] == 'auftrag' else '')):
            runner.run()
        self.plan_is(runner, PLAN)
        self.assertNotEqual(runner.exit_code, 0)

    def test_stop_after_production_prevents_review(self):
        runner = self.runner()
        calls = []
        def call(**kw):
            calls.append(kw['phase'])
            (self.work / 'process_stop').mkdir()  # Opaque signal, not readable text.
            return response('Produced, but owner stopped')
        with self.dispatch(call): runner.run()
        self.assertEqual(calls, ['auftrag'])
        self.assertEqual(runner.exit_code, 6)
        self.plan_is(runner, PLAN)

    def test_stop_after_review_prevents_late_done(self):
        runner = self.runner()
        def call(**kw):
            if kw['phase'] == 'review':
                (self.work / 'process_stop').write_text('STOP before acceptance')
                return response(json.dumps(PASS))
            return response('Done')
        with self.dispatch(call): runner.run()
        self.assertEqual(runner.exit_code, 6)
        self.plan_is(runner, PLAN)

    def test_unreviewed_sibling_status_mutation_is_not_imported(self):
        original = PLAN + '2. ***Task***: Independent work.\n'
        self.write_plan(original)
        runner = self.runner(max_steps=1)
        def call(**kw):
            if kw['phase'] == 'auftrag':
                self.todo.write_text(original.replace('2. ***Task***', '2. ***DONE***'))
                return response('Edited plan')
            return response(json.dumps(PASS))
        with self.dispatch(call): runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], original)

    def test_budget_blocks_review_and_usage_survives_reopen(self):
        # Use the normal public runner path, not a counter object disconnected
        # from the actual task execution.
        runner = super().runner(backend=self.backend, max_calls=1)
        calls = []
        def call(**kw):
            calls.append(kw['phase']); return response('Done')
        with self.dispatch(call): runner.run()
        self.assertEqual(calls, ['auftrag'])
        self.assertEqual(runner.exit_code, 6)
        self.plan_is(runner, PLAN)
        snapshots = [p for p in runner.state_dir.rglob('*.json') if 'call_budgets' in str(p)]
        before = {p: p.read_bytes() for p in snapshots}
        self.assertTrue(before)
        runner.close()
        resumed = super().runner(backend=self.backend, max_calls=1)
        with self.dispatch(lambda **k: self.fail('Stop/budget must prevent another call')): resumed.run()
        self.plan_is(resumed, PLAN)
        for path, data in before.items(): self.assertEqual(path.read_bytes(), data)

    def test_stop_precedes_runtime_and_backend_preflight(self):
        (self.work / 'process_stop').mkdir()
        args = ['--backend', self.backend, '--workdir', str(self.work), '--todo-file', str(self.todo),
                '--state-dir', str(self.state_root), '--max-calls', '4']
        with patch.object(run_todos, 'run_runtime_profile_preflight', side_effect=AssertionError('Profile ran')), \
             patch.object(run_todos, 'run_codex_workspace_write_preflight', side_effect=AssertionError('Codex ran')), \
             patch.object(claude_transport, 'probe_cli', side_effect=AssertionError('Claude ran')), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(run_todos.main(args), 6)
        self.assertEqual(self.todo.read_text(), PLAN)

    def test_worker_payload_retains_root_peer_stop_and_backend(self):
        root_stop = self.work / 'process_stop'
        peer_stop = self.work / 'peer' / 'process_stop'
        options = AutoBuildOptions(backend=self.backend, max_calls=4)
        context = AutoBuildContext(launcher_workspace=self.work,
                                  process_stop_paths=(str(root_stop), str(peer_stop)))
        payload = call_payload(task='bounded', workdir=self.work / 'child', options=options, context=context)
        decoded = decode_call(json.loads(json.dumps(payload)))
        self.assertEqual(decoded['options'].backend, self.backend)
        self.assertEqual(decoded['context'].launcher_workspace, str(self.work))
        self.assertEqual(decoded['context'].process_stop_paths, (str(root_stop), str(peer_stop)))


class CodexSecurity091(CommonSecurity, IsolatedControllerCase):
    backend = 'codex'


class ClaudeSecurity091(CommonSecurity, IsolatedControllerCase):
    backend = 'claude-code'
