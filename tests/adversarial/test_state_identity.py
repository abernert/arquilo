# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""State aliases retain the established journal/counter key or fail closed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from adversarial.harness import IsolatedControllerCase
from controller_state import PlanAuthority, PlanIntegrityError, state_directory, state_directory_path
from execution_budget import BudgetExhausted, CallBudget
import safe_io


PLAN = '1. ***Task***: Create first.txt.\n'


class StateIdentityTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)

    def alias(self):
        # The native filesystem resolves this ordinary spelling to the same
        # file on every platform; it does not require links or case emulation.
        return self.work / '..' / self.work.name / self.todo.name

    def plan_directories(self):
        return [p for p in self.state_root.iterdir()
                if len(p.name) == 64 and all(c in '0123456789abcdef' for c in p.name)]

    def test_alias_does_not_allocate_a_second_budget_or_journal(self):
        original = state_directory(self.work, self.todo, self.state_root)
        budget = CallBudget(original / 'call_budgets' / 'task_1', 1, '1')
        budget.consume('1', 'production')
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.alias(), self.state_root)
        with self.assertRaises(PlanIntegrityError):
            state_directory_path(self.work, self.alias(), self.state_root)
        self.assertEqual(self.plan_directories(), [original])
        self.assertEqual(budget.snapshot()['used'], 1)
        with self.assertRaises(BudgetExhausted):
            budget.consume('1', 'review')

    def test_legacy_key_and_spent_budget_survive_identity_upgrade_and_atomic_replace(self):
        key = hashlib.sha256((str(self.work.resolve()) + '\0' + str(self.todo)).encode()).hexdigest()
        original = self.state_root / key
        safe_io.mkdir(original)
        safe_io.write_text(original / 'plan.json', json.dumps({
            'schema_version': 'arquilo.plan_authority.v1', 'todo': str(self.todo),
            'text': PLAN, 'pending': None,
        }))
        budget = CallBudget(original / 'call_budgets' / 'task_1', 2, '1')
        budget.consume('1', 'production')
        # Legacy journals identify an alias even before the new marker exists.
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.alias(), self.state_root)
        self.assertEqual(state_directory(self.work, self.todo, self.state_root), original)
        authority = PlanAuthority(self.todo, original)
        self.addCleanup(authority.close)
        authority.replace_approved(PLAN.replace('***Task***', '***DONE***'))
        authority.close()
        self.assertEqual(state_directory(self.work, self.todo, self.state_root), original)
        self.assertEqual(CallBudget(budget.directory, 2, '1').consume('1', 'review')['number'], 2)
        self.assertEqual(self.plan_directories(), [original])

    def test_missing_task_alias_is_registered_before_a_plan_journal_exists(self):
        self.todo.unlink()
        original = state_directory(self.work, self.todo, self.state_root)
        self.assertFalse((original / 'plan.json').exists())
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.alias(), self.state_root)
        self.assertEqual(self.plan_directories(), [original])

    def test_private_run_metadata_identifies_legacy_state_without_plan(self):
        key = hashlib.sha256((str(self.work.resolve()) + '\0' + str(self.todo)).encode()).hexdigest()
        original = self.state_root / key
        run = original / 'runs' / '2026-10-23T01-02-03.004Z'
        safe_io.mkdir(run)
        safe_io.write_text(original / 'latest-run.txt', 'runs/' + run.name + '\n')
        safe_io.write_text(run / 'run.json', json.dumps({
            'schema_version': 'arquilo.run_log.v2', 'workspace': str(self.work),
            'todo_file': str(self.todo), 'controller_state': str(original),
        }))
        budget = CallBudget(original / 'call_budgets' / 'task_1', 1, '1')
        budget.consume('1', 'production')
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.alias(), self.state_root)
        self.assertEqual(self.plan_directories(), [original])
        self.assertEqual(budget.snapshot()['used'], 1)
        self.assertFalse((original / 'plan.json').exists())

    def test_private_project_metadata_identifies_legacy_state_without_plan(self):
        key = hashlib.sha256((str(self.work.resolve()) + '\0' + str(self.todo)).encode()).hexdigest()
        original = self.state_root / key
        safe_io.mkdir(original)
        project = self.state_root / 'example'
        safe_io.mkdir(project)
        safe_io.write_text(self.state_root / 'projects.json', json.dumps({
            'schema_version': 'arquilo.projects.v1', 'projects': {'example': str(self.work)},
            'plans': {key: 'example'},
        }))
        safe_io.write_text(project / 'project.json', json.dumps({
            'schema_version': 'arquilo.project.v1', 'project_id': 'example',
            'workspace': str(self.work), 'plans': {key: {
                'todo_file': str(self.todo), 'controller_state': str(original),
            }},
        }))
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.alias(), self.state_root)
        self.assertEqual(self.plan_directories(), [original])
        self.assertFalse((original / 'plan.json').exists())

    def test_distinct_native_case_sensitive_files_keep_separate_state(self):
        other = self.todo.with_name('TASKS.md')
        if other.exists():
            self.skipTest('Volume aliases this case spelling')
        other.write_bytes(PLAN.encode('utf-8'))
        first = state_directory(self.work, self.todo, self.state_root)
        second = state_directory(self.work, other, self.state_root)
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.plan_directories()), 2)

    def test_native_case_alias_of_state_workspace_overlap_is_rejected(self):
        alias = self.work.with_name(self.work.name.upper())
        if not alias.exists() or not alias.samefile(self.work):
            self.skipTest('Volume does not expose native case aliases')
        # Missing descendants still have a physically aliased workspace parent.
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.work, self.todo, alias / 'new-controller')
        self.assertFalse((self.work / 'new-controller').exists())
        with self.assertRaises(PlanIntegrityError):
            state_directory(alias / 'child', alias / 'child' / 'tasks.md', self.work)

    def test_native_case_alias_cannot_fork_consumed_budget(self):
        original = state_directory(self.work, self.todo, self.state_root)
        budget = CallBudget(original / 'call_budgets' / 'task_1', 1, '1')
        budget.consume('1', 'production')
        alias = self.todo.with_name(self.todo.name.upper())
        if not alias.exists() or not alias.samefile(self.todo):
            self.skipTest('Volume does not expose native case aliases')
        try:
            selected = state_directory(self.work, alias, self.state_root)
        except PlanIntegrityError:
            selected = original
        self.assertTrue(selected.samefile(original))
        self.assertEqual(CallBudget(selected / 'call_budgets' / 'task_1', 1, '1').snapshot()['used'], 1)
        self.assertEqual(self.plan_directories(), [original])

    def test_native_unicode_alias_cannot_fork_state(self):
        todo = self.work / 'caf\u00e9.md'
        todo.write_bytes(PLAN.encode('utf-8'))
        alias = self.work / 'cafe\u0301.md'
        if not alias.exists() or not alias.samefile(todo):
            self.skipTest('Volume does not expose native Unicode normalization aliases')
        original = state_directory(self.work, todo, self.state_root)
        try:
            selected = state_directory(self.work, alias, self.state_root)
        except PlanIntegrityError:
            selected = original
        self.assertTrue(selected.samefile(original))
        self.assertEqual(self.plan_directories(), [original])

    def test_concurrent_process_alias_allocation_creates_only_one_identity(self):
        script = '''
import json, pathlib, sys, time
from controller_state import state_directory, PlanIntegrityError
workspace, todo, root, ready, start = map(pathlib.Path, sys.argv[1:])
ready.write_text('ready')
deadline = time.monotonic() + 10
while not start.exists():
    if time.monotonic() > deadline:
        raise RuntimeError('Parent did not release allocation barrier')
    time.sleep(0.01)
try:
    result = {'state': str(state_directory(workspace, todo, root))}
except PlanIntegrityError as exc:
    result = {'error': str(exc)}
print(json.dumps(result))
'''
        start = self.base / 'allocate-now'
        processes = []
        ready_files = []
        try:
            for index, todo in enumerate((self.todo, self.alias())):
                ready = self.base / f'ready-{index}'
                ready_files.append(ready)
                processes.append(subprocess.Popen(
                    [sys.executable, '-B', '-c', script, str(self.work), str(todo),
                     str(self.state_root), str(ready), str(start)],
                    cwd=Path(__file__).resolve().parents[2],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 10
            while not all(path.exists() for path in ready_files):
                self.assertLess(time.monotonic(), deadline, 'Allocation children did not become ready')
                time.sleep(0.01)
            start.touch()
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                results.append(json.loads(stdout))
            self.assertEqual(sum('state' in result for result in results), 1, results)
            self.assertEqual(sum('error' in result for result in results), 1, results)
            self.assertEqual(len(self.plan_directories()), 1)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
