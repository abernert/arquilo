# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""A passed review must not be mistaken for controller acceptance after a plan edit."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_todos
import safe_io
from controller_state import PlanIntegrityError
from review_contract import parse_review_classification
from runtime_failure import execution_error, EXIT_EXECUTION_ERROR

PLAN = '7. ***TASK***: Create seven.txt.\n8. ***TASK***: Create eight.txt.\n'
STOP_PLAN = PLAN.replace('8. ***TASK***', '***STOP***\n8. ***TASK***')
PASS = {
    'verdict': 'PASS', 'short_summary': 'The original bounded assignment passed.',
    'blocking_issues': [], 'non_blocking_observations': [
        {'summary': 'This does not certify other tasks or full integration.'}],
    'breakdown_recommended': False, 'breakdown_reason': None,
}


class ReviewHintTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'
        self.work.mkdir()
        self.todo = self.work / 'tasks.md'
        self.todo.write_text(PLAN, encoding='utf-8')
        self.runner = run_todos.TodoRunner(
            self.todo, self.work, 5, 1, None, None, False,
            run_todos.DryRunRecorder(None), set(), 3, 'workspace-write', None,
            process_stop_policy='controller-only', state_dir=self.base / 'private')
        self.addCleanup(self.runner.close)

    def passed(self, **kwargs):
        values = dict(completed=True, message='Finished',
                      review_classification=parse_review_classification(json.dumps(PASS)))
        values.update(kwargs)
        return run_todos.TaskOutcome(**values)

    def reject_after(self, outcome, *, identifier='7', changed=STOP_PLAN, copied=False):
        active = self.todo
        kwargs = {}
        if copied:
            folder = self.work / 'worker'
            folder.mkdir()
            active = folder / 'tasks.md'
            active.write_text(PLAN, encoding='utf-8')
            kwargs['todo_file_override'] = active
        def execute(*args, **options):
            active.write_text(changed, encoding='utf-8')
            return outcome
        with patch.object(self.runner, '_run_autobuild_impl', side_effect=execute):
            return self.runner._run_autobuild(identifier, 'Original task', **kwargs)

    def test_stop_edit_after_pass_stays_open_and_prints_conditional_recovery(self):
        output = io.StringIO()
        original_journal = self.runner.plan_authority.path.read_bytes()
        original_review = deepcopy(self.passed().review_classification)
        def execute(identifier, *args, **kwargs):
            self.assertEqual(identifier, '7')
            (self.work / 'seven.txt').write_text('reviewed output', encoding='utf-8')
            self.todo.write_text(STOP_PLAN, encoding='utf-8')
            return self.passed()
        with patch.object(self.runner, '_run_autobuild_impl', side_effect=execute) as calls, \
                patch.object(self.runner, '_maybe_git_commit') as git_commit, redirect_stdout(output):
            self.runner.run()
        text = output.getvalue()
        self.assertIn('Review für ToDo 7: PASS', text)
        self.assertIn('nach manueller Prüfung auf ***DONE***', text)
        self.assertIn('keine weiteren Planänderungen', text)
        self.assertIn('geprüfte Ergebnisse unverändert', text)
        self.assertIn('ARQUILO hat diese Voraussetzungen nicht bestätigt', text)
        self.assertIn('--accept-plan-changes', text)
        self.assertIn('Ein STOP vor dem nächsten ToDo bleibt wirksam', text)
        self.assertIn('ToDo bleibt offen', text)
        self.assertEqual(calls.call_count, 1)
        git_commit.assert_not_called()
        self.assertEqual(self.runner.exit_code, EXIT_EXECUTION_ERROR)
        self.assertFalse(self.runner.completed)
        self.assertFalse(self.runner.reviewed_this_run)
        self.assertEqual(self.runner.incomplete, {'7'})
        self.assertEqual(self.todo.read_text(encoding='utf-8'), STOP_PLAN)
        self.assertEqual(self.runner.plan_authority.path.read_bytes(), original_journal)
        self.assertFalse((self.work / 'eight.txt').exists())
        self.assertEqual((self.work / 'seven.txt').read_text(), 'reviewed output')
        self.assertFalse(self.runner.process_stop_path.exists())
        for name in ('run.json', 'run_log.json'):
            log = json.loads((self.runner.run_dir / name).read_text(encoding='utf-8'))
            error = log['execution_error']
            self.assertEqual(error['code'], 'unapproved_plan_mutation')
            self.assertEqual(error['phase'], 'controller_acceptance')
            self.assertFalse(error['automatic_task_retry'])
            self.assertIn('Review für ToDo 7: PASS', error['message'])
            self.assertNotIn('7', log['completed'])
        # Normalized review evidence remains unchanged; the hint is not a new verdict.
        self.assertEqual(self.passed().review_classification, original_review)

    def test_no_hint_for_incomplete_failed_or_invalid_review(self):
        malformed = {**PASS, 'breakdown_reason': 'Contradictory with false'}
        for classification in (None, {}, {'verdict': 'PASS'}, malformed,
                               {**PASS, 'verdict': 'FAIL'}):
            with self.subTest(classification=classification):
                self.todo.write_text(PLAN, encoding='utf-8')
                result = self.reject_after(self.passed(review_classification=classification))
                self.assertNotIn('nach manueller Prüfung', result.message)
                self.assertFalse(result.completed)
        self.todo.write_text(PLAN, encoding='utf-8')
        result = self.reject_after(self.passed(completed=False))
        self.assertNotIn('nach manueller Prüfung', result.message)

    def test_prose_pass_is_not_review_evidence(self):
        result = self.reject_after(self.passed(
            review_classification=None, review_findings='PASS', message='Review passed'))
        self.assertNotIn('Review für ToDo', result.message)

    def test_no_hint_after_technical_failure_abort_stop_or_budget_failure(self):
        for override in ({'execution_error': execution_error('network failed')},
                         {'abort': True}, {'process_stop_triggered': True},
                         {'budget_exhausted': {'reason': 'exhausted'}}):
            with self.subTest(override=override):
                self.todo.write_text(PLAN, encoding='utf-8')
                result = self.reject_after(self.passed(**override))
                self.assertNotIn('nach manueller Prüfung', result.message)
                self.assertFalse(result.completed)

    def test_no_hint_for_worker_copy(self):
        result = self.reject_after(self.passed(), copied=True)
        self.assertNotIn('Review für ToDo', result.message)
        self.assertEqual(result.execution_error['code'], 'unapproved_plan_mutation')

    def test_no_hint_for_breakdown_or_parent_review_subtask(self):
        for ident in ('7-breakdown', '7-review'):
            with self.subTest(ident=ident):
                self.todo.write_text(PLAN, encoding='utf-8')
                result = self.reject_after(self.passed(), identifier=ident)
                self.assertNotIn('nach manueller Prüfung', result.message)

    def test_no_hint_for_unreadable_or_unsafe_paths(self):
        for error in (PermissionError('unreadable'), safe_io.UnsafePathError('redirected')):
            with self.subTest(error=error), \
                    patch.object(self.runner.plan_authority, 'check', side_effect=[None, error]), \
                    patch.object(self.runner, '_run_autobuild_impl', return_value=self.passed()):
                result = self.runner._run_autobuild('7', 'Original task')
                self.assertNotIn('nach manueller Prüfung', result.message)

    def test_does_not_suppress_early_plan_rejection(self):
        self.todo.write_text(STOP_PLAN, encoding='utf-8')
        with patch.object(self.runner, '_run_autobuild_impl') as execute:
            with self.assertRaises(PlanIntegrityError):
                self.runner._run_autobuild('7', 'Original task')
        execute.assert_not_called()

    def test_unchanged_plan_and_pass_do_not_emit_recovery_hint(self):
        passed = self.passed()
        with patch.object(self.runner, '_run_autobuild_impl', return_value=passed):
            outcome = self.runner._run_autobuild('7', 'Original task')
        self.assertIs(outcome, passed)
        self.assertTrue(outcome.completed)
        self.assertNotIn('nach manueller Prüfung', outcome.message)

    def test_changed_requirements_are_not_certified_as_unchanged(self):
        result = self.reject_after(self.passed(), changed=PLAN.replace('seven.txt', 'easier.txt'))
        self.assertIn('wenn außer Ihrer beabsichtigten', result.message)
        self.assertIn('ARQUILO hat diese Voraussetzungen nicht bestätigt', result.message)
        self.assertFalse(result.completed)
        self.assertEqual(self.runner.plan_authority.text, PLAN)

    def test_valid_nonblocking_observations_are_preserved(self):
        reviewed = self.passed()
        expected = deepcopy(reviewed.review_classification)
        result = self.reject_after(reviewed)
        self.assertIn('Review für ToDo 7: PASS', result.message)
        self.assertEqual(result.review_classification, expected)
        self.assertFalse(result.completed)

    def test_documentation_describes_narrow_recovery_without_changing_stop_policy(self):
        doc = (Path(__file__).resolve().parents[1] / 'docs/troubleshooting.md').read_text(encoding='utf-8')
        for fragment in ('Review passed, but an edited task plan blocks DONE',
                         '--accept-plan-changes', 'sole plan',
                         'ARQUILO has not', 'Existing run logs are not rewritten'):
            self.assertIn(fragment, doc)


if __name__ == '__main__':
    unittest.main()
