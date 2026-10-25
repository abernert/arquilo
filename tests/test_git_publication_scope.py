# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Publication scope excludes planning helpers and respects parent task bounds.

All agent answers are synthetic. Git repositories and controller state are local
temporary fixtures; ordinary production and review pass through AutoBuild.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adversarial.harness import IsolatedControllerCase
from agent_types import RunResult
import autobuild
from reviewed_git import list_publications


PLAN = ('1. ***Task***: Create proof.txt containing RIGHT.\n'
        '2. ***Task***: Create second.txt containing SECOND.\n'
        '3. ***Task***: Create third.txt containing THIRD.\n')
PASS = {'verdict': 'PASS', 'short_summary': 'Inspected the requested result.',
        'blocking_issues': [], 'non_blocking_observations': [],
        'breakdown_recommended': False, 'breakdown_reason': None}


def answer(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class GitPublicationScopeTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Scope Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'gc.auto', '0')
        self.git('config', 'maintenance.auto', 'false')
        self.git('add', '--', 'tasks.md')
        self.git('commit', '-qm', 'owner task scope')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work,
                                       stderr=subprocess.PIPE, timeout=20)

    def new_runner(self, **overrides):
        options = dict(git_enabled=True, git_paths=['proof.txt'],
                       max_steps=1, breakdown_policy='off')
        options.update(overrides)
        return self.runner(**options)

    def test_reviewed_breakdown_does_not_create_task_publication_receipt(self):
        runner = self.new_runner()
        initial_head = self.git('rev-parse', 'HEAD')
        child_plan = PLAN.replace('2. ***Task***',
            '1.1. ***Task***: Create proof.txt and verify the exact bytes.\n2. ***Task***')
        phases = []
        def planner(**kw):
            phases.append(kw['phase'])
            if kw['phase'] == 'auftrag':
                self.write_plan(child_plan)
                return answer('Added an open direct child without accepting the parent task.')
            self.assertEqual(kw['phase'], 'review')
            self.assertEqual(self.todo.read_text(), child_plan)
            return answer(json.dumps(PASS))
        with patch.object(runner.git_selection, 'begin_review',
                          side_effect=AssertionError('A planner must not create an output publication')) as begin, \
             patch.object(autobuild, '_terminal_beep'), self.fake_codex(planner):
            outcome = runner._run_autobuild('1-breakdown',
                'Add one open direct child for task 1. Preserve every existing task and status.')
        begin.assert_not_called()
        self.assertTrue(outcome.completed, outcome.message)
        self.assertEqual(phases, ['auftrag', 'review'])
        self.assertEqual(outcome.review_classification['verdict'], 'PASS')
        self.assertIsNone(outcome.git_candidate)
        self.assertEqual(list_publications(runner.state_dir, self.work), [])
        self.assertEqual(runner.publication_records, [])
        self.assertEqual(runner.completed, set())
        self.assertEqual(runner.reviewed_this_run, set())
        self.assertEqual(self.todo.read_text(), child_plan)
        self.assertNotIn('***DONE***', self.todo.read_text())
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], PLAN)
        self.assertEqual(self.git('rev-parse', 'HEAD'), initial_head)

    def test_pending_parent_review_outside_start_scope_does_not_block_selected_task(self):
        runner = self.new_runner()
        phases = []
        def parent_review(**kw):
            phases.append(kw['phase'])
            if kw['phase'] == 'auftrag':
                (self.work / 'proof.txt').write_bytes(b'RIGHT')
                return answer('Parent output is ready for the separate review.')
            self.assertEqual(kw['phase'], 'review')
            self.assertEqual((self.work / 'proof.txt').read_bytes(), b'RIGHT')
            return answer(json.dumps(PASS))
        with patch.object(autobuild, '_terminal_beep'), self.fake_codex(parent_review):
            outcome = runner._run_autobuild('1-review', 'Review the original requirements for task 1.')
        self.assertTrue(outcome.completed, outcome.message)
        self.assertIsNotNone(outcome.git_candidate)
        receipts = list_publications(runner.state_dir, self.work)
        self.assertEqual([(row['task'], row['status']) for row in receipts], [('1-review', 'accepted')])
        self.assertEqual(phases, ['auftrag', 'review'])
        runner.close()

        selected = self.new_runner(start_id='3', git_required=True, git_paths=['third.txt'])
        self.assertEqual(selected.publication_records, [])
        phases.clear()
        def third_task(**kw):
            phases.append(kw['phase'])
            if kw['phase'] == 'auftrag':
                (self.work / 'third.txt').write_bytes(b'THIRD')
                return answer('Created the selected task output.')
            self.assertEqual(kw['phase'], 'review')
            self.assertEqual((self.work / 'third.txt').read_bytes(), b'THIRD')
            return answer(json.dumps(PASS))
        with patch.object(autobuild, '_terminal_beep'), self.fake_codex(third_task):
            selected.run()
        self.assertEqual(selected.exit_code, 0)
        self.assertEqual(phases, ['auftrag', 'review'])
        self.assertEqual(self.todo.read_text(), PLAN.replace('3. ***Task***', '3. ***DONE***'))
        record = json.loads((selected.run_dir / 'run.json').read_text())
        self.assertEqual(record['publication_status'], 'complete')
        self.assertEqual(self.git('show', 'HEAD:third.txt'), b'THIRD')
        self.assertNotIn(b'proof.txt', self.git('ls-tree', '--name-only', 'HEAD'))
        self.assertEqual((self.work / 'proof.txt').read_bytes(), b'RIGHT')
        pending = [row for row in list_publications(selected.state_dir, self.work)
                   if row['id'] == receipts[0]['id']]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()
