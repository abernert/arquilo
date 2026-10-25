# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent acceptance/publication boundaries with real local state and Git.

Model answers are explicit synthetic fixtures. Tests inspect controller journals,
artifact bytes and Git objects independently. No external provider or remote is
used. The native-looking Claude executable below is a local Python fixture.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adversarial.harness import IsolatedControllerCase
import arquilo
import autobuild
from autobuild_contract import AutoBuildResultError, validate_result
from agent_types import RunResult
import git_snapshot
import reviewed_git
from reviewed_git import ReviewedGitError
from review_contract import parse_review_classification
from runtime_contracts import ExitCode
from test_claude_backend import Fixture as ClaudeFixture
from test_review_completion_integrity import COMPLETE, LEGACY_PASS, completed_document


PLAN = '1. ***Task***: Create proof.txt containing exactly RIGHT.\n'
RIGHT = b'RIGHT'
PASS = {'verdict': 'PASS', 'short_summary': 'Inspected the requested bytes.',
        'blocking_issues': [], 'non_blocking_observations': [],
        'breakdown_recommended': False, 'breakdown_reason': None}
FAIL = {**PASS, 'verdict': 'FAIL', 'blocking_issues': [
    {'id': 'wrong', 'type': 'local_fix', 'summary': 'Output does not satisfy task.',
     'requirement': 'Create proof.txt containing RIGHT.',
     'acceptance_criterion': 'Exact required bytes.', 'references': ['proof.txt'],
     'fix_suggestion': 'Repair the output.'}]}


def answer(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


class PublicationWorkflow:
    """Run identical controller invariants through either selected backend."""

    backend = None

    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Publication Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'gc.auto', '0')
        self.git('config', 'maintenance.auto', 'false')
        self.git('add', '--', 'tasks.md')
        self.git('commit', '-qm', 'owner task')
        self.original_head = self.git('rev-parse', 'HEAD')
        self.phases = []

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work,
                                       stderr=subprocess.PIPE, timeout=20)

    def new_runner(self, **overrides):
        options = dict(backend=self.backend, git_enabled=True, git_paths=['proof.txt'],
                       max_steps=1, breakdown_policy='off')
        options.update(overrides)
        return self.runner(**options)

    @contextmanager
    def dispatch(self, callback):
        chosen = 'run_claude_exec_json' if self.backend == 'claude-code' else 'run_codex_exec_json'
        other = 'run_codex_exec_json' if self.backend == 'claude-code' else 'run_claude_exec_json'
        with patch.object(autobuild, chosen, side_effect=callback), \
             patch.object(autobuild, other, side_effect=AssertionError('Wrong backend selected')), \
             patch.object(autobuild, 'run_semantic_decision', side_effect=AssertionError('Unexpected Decide')), \
             patch.object(autobuild, '_terminal_beep'), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield

    def success(self, **kw):
        self.phases.append(kw['phase'])
        self.assertEqual(Path(kw['cwd']), self.work)
        self.assertEqual(kw['launcher_workspace'], self.work)
        if kw['phase'] == 'auftrag':
            (self.work / 'proof.txt').write_bytes(RIGHT)
            return answer('Created the requested output.')
        self.assertEqual(kw['phase'], 'review')
        self.assertEqual(kw['sandbox'], 'read-only')
        if self.backend == 'claude-code':
            self.assertNotIn('--skip-git-repo-check', kw['extra_args'])
            self.assertEqual(kw['extra_args'], [])
        self.assertEqual((self.work / 'proof.txt').read_bytes(), RIGHT)
        return answer(json.dumps(PASS))

    def assert_plan(self, runner, *, done):
        expected = PLAN.replace('***Task***', '***DONE***') if done else PLAN
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], expected)

    def record(self, runner):
        return json.loads((runner.run_dir / 'run.json').read_text())

    def test_commit_error_preserves_reviewed_done_and_records_pending_publication(self):
        runner = self.new_runner()
        with patch.object(runner.git_selection, 'commit', side_effect=ReviewedGitError('Synthetic Git unavailable')), \
             self.dispatch(self.success):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(self.phases, ['auftrag', 'review'])
        self.assert_plan(runner, done=True)
        self.assertEqual((self.work / 'proof.txt').read_bytes(), RIGHT)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        record = self.record(runner)
        self.assertEqual(record['publication_status'], 'pending')
        self.assertTrue(record['publication_records'])

    def test_required_publication_failure_changes_run_exit_but_not_accepted_task(self):
        runner = self.new_runner(git_required=True)
        with patch.object(runner.git_selection, 'commit', side_effect=ReviewedGitError('Synthetic Git unavailable')), \
             self.dispatch(self.success):
            runner.run()
        self.assertEqual(runner.exit_code, int(ExitCode.INCOMPLETE))
        self.assert_plan(runner, done=True)
        self.assertEqual(self.record(runner)['publication_status'], 'pending')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def _two_task_publication_failure(self, *, required):
        plan = PLAN + '2. ***Task***: Create second.txt containing exactly SECOND.\n'
        self.write_plan(plan)
        self.git('add', '--', 'tasks.md')
        self.git('commit', '-qm', 'owner followup task')
        self.original_head = self.git('rev-parse', 'HEAD')
        runner = self.new_runner(git_required=required, max_steps=3,
                                 git_paths=['proof.txt', 'second.txt'])
        real_git = runner.git_selection.git
        def failed_prepare(*args, **kw):
            if args[0] == 'read-tree' and kw.get('private'):
                raise ReviewedGitError('Synthetic publication preparation failure')
            return real_git(*args, **kw)
        def successful(**kw):
            result = self.success(**kw)
            if self.phases.count('auftrag') == 2:
                if kw['phase'] == 'auftrag':
                    (self.work / 'second.txt').write_bytes(b'SECOND')
                else:
                    self.assertEqual((self.work / 'second.txt').read_bytes(), b'SECOND')
            return result
        with patch.object(runner.git_selection, 'git', side_effect=failed_prepare), self.dispatch(successful):
            runner.run()
        expected = plan.replace('***Task***', '***DONE***', 1 if required else 2)
        self.assertEqual(self.todo.read_text(), expected)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], expected)
        self.assertEqual(self.phases, ['auftrag', 'review'] * (1 if required else 2))
        self.assertEqual(runner.exit_code, int(ExitCode.INCOMPLETE) if required else 0)
        self.assertEqual(self.record(runner)['publication_status'], 'pending')
        self.assertIsNone(self.record(runner)['execution_error'])
        self.assertEqual((self.work / 'proof.txt').read_bytes(), RIGHT)
        if required:
            self.assertFalse((self.work / 'second.txt').exists())
        else:
            self.assertEqual((self.work / 'second.txt').read_bytes(), b'SECOND')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        self.assertFalse((self.work / 'process_stop').exists())

    def test_required_publication_failure_blocks_next_task_after_acceptance(self):
        self._two_task_publication_failure(required=True)

    def test_optional_publication_failure_allows_next_task(self):
        self._two_task_publication_failure(required=False)

    def test_capture_failure_uses_actual_separate_review_without_publishing(self):
        runner = self.new_runner()
        with patch.object(git_snapshot, 'capture', side_effect=git_snapshot.GitSnapshotUnavailable('Synthetic capture failure')), \
             patch.object(runner.git_selection, 'commit', side_effect=AssertionError('No accepted publication binder')), \
             self.dispatch(self.success):
            runner.run()
        self.assertEqual(self.phases, ['auftrag', 'review'])
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        self.assertEqual(self.record(runner)['publication_status'], 'pending')

    def test_capture_failure_cannot_turn_failed_factual_review_into_done(self):
        runner = self.new_runner()
        def failed(**kw):
            result = self.success(**kw)
            return answer(json.dumps(FAIL)) if kw['phase'] == 'review' else result
        with patch.object(git_snapshot, 'capture', side_effect=git_snapshot.GitSnapshotUnavailable('Synthetic capture failure')), \
             patch.object(runner.git_selection, 'commit', side_effect=AssertionError('Failed review cannot publish')), \
             self.dispatch(failed):
            runner.run()
        self.assertEqual(self.phases, ['auftrag', 'review'])
        self.assertNotEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=False)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_selected_output_drift_during_review_still_blocks_done(self):
        runner = self.new_runner()
        def drift(**kw):
            result = self.success(**kw)
            if kw['phase'] == 'review':
                (self.work / 'proof.txt').write_bytes(b'UNREVIEWED')
            return result
        with self.dispatch(drift):
            runner.run()
        self.assert_plan(runner, done=False)
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_private_snapshot_mutation_is_not_demoted_to_publication_warning(self):
        runner = self.new_runner()
        def tamper(**kw):
            result = self.success(**kw)
            if kw['phase'] == 'review':
                copies = list((runner.state_dir / 'git-reviews').glob('*/review-*/workspace/proof.txt'))
                self.assertEqual(len(copies), 1)
                copies[0].chmod(0o600)
                copies[0].write_bytes(b'FORGED')
            return result
        with self.dispatch(tamper):
            runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=False)
        self.assertEqual((self.work / 'proof.txt').read_bytes(), RIGHT)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_output_drift_after_worker_acceptance_but_before_done_is_rechecked(self):
        runner = self.new_runner()
        original_finalize = runner._finalize_post_todo_log
        def late_edit(outcome):
            original_finalize(outcome)
            self.assertIsNotNone(outcome.git_candidate)
            (self.work / 'proof.txt').write_bytes(b'CHANGED AT ACCEPTANCE BOUNDARY')
        with patch.object(runner, '_finalize_post_todo_log', side_effect=late_edit), self.dispatch(self.success):
            try:
                runner.run()
            except git_snapshot.GitSnapshotError:
                pass  # Explicit fail-closed refusal is also an acceptable boundary.
            else:
                self.assertNotEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=False)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_worker_success_without_token_or_capture_error_is_not_authority(self):
        runner = self.new_runner()
        def false_summary(*args, **kw):
            (self.work / 'proof.txt').write_bytes(RIGHT)
            options = kw['options']
            return autobuild.AutoBuildSummary(last_answer='Claimed success', completed=True,
                auftrag_runs=1, review_runs=1, workspace=self.work,
                pretty_log=options.logfile, raw_log=options.rawlog, readonly_result_path=None,
                review_classification=parse_review_classification(json.dumps(PASS)))
        with patch('run_todos.autobuild_start', side_effect=false_summary), \
             self.dispatch(lambda **kw: self.fail('No model invocation expected')):
            runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=False)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)

    def test_unselected_large_and_linked_context_does_not_enter_snapshot(self):
        outside = self.base / 'outside-secret'; outside.write_bytes(b'PRIVATE TARGET')
        link = self.work / 'linked-context'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Native link fixture unavailable: ' + type(exc).__name__)
        large = self.work / 'oversized-context.bin'; large.write_bytes(b'x' * 4097)
        runner = self.new_runner()
        original_read = git_snapshot.read_regular
        def bounded(path, *args, **kw):
            self.assertNotIn(Path(path), (outside, link, large), 'Unselected context was read for publication')
            return original_read(path, *args, **kw)
        with patch.object(git_snapshot, 'MAX_FILE_BYTES', 4096), \
             patch.object(git_snapshot, 'read_regular', side_effect=bounded), self.dispatch(self.success):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=True)
        self.assertEqual(self.git('show', 'HEAD:proof.txt'), RIGHT)
        self.assertEqual(outside.read_bytes(), b'PRIVATE TARGET')
        self.assertNotIn(b'linked-context', self.git('ls-tree', '--name-only', 'HEAD'))
        self.assertNotIn(b'oversized-context.bin', self.git('ls-tree', '--name-only', 'HEAD'))

    def test_cli_retry_after_reopen_uses_receipt_without_model_or_budget_reset(self):
        runner = self.new_runner()
        real_git = runner.git_selection.git
        def failed_prepare(*args, **kw):
            if args[0] == 'read-tree' and kw.get('private'):
                raise ReviewedGitError('Synthetic publication preparation failure')
            return real_git(*args, **kw)
        with patch.object(runner.git_selection, 'git', side_effect=failed_prepare), self.dispatch(self.success):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=True)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        receipts = reviewed_git.list_publications(runner.state_dir, self.work)
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual(receipt['status'], 'preparing')
        self.assertRegex(receipt['id'], r'^publication-[a-f0-9]{32}$')
        budget_files = list((runner.state_dir / 'call_budgets').rglob('*.json'))
        self.assertTrue(budget_files)
        budget_before = {p: p.read_bytes() for p in budget_files}
        runner.close()
        arguments = ['--workdir', str(self.work), '--todo-file', str(self.todo),
                     '--state-dir', str(self.state_root)]
        with patch.object(autobuild, 'run_codex_exec_json', side_effect=AssertionError('Retry called Codex')), \
             patch.object(autobuild, 'run_claude_exec_json', side_effect=AssertionError('Retry called Claude')), \
             patch.object(autobuild, 'run_semantic_decision', side_effect=AssertionError('Retry called Decide')), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(arquilo.main(['git', 'status', *arguments]), 0)
            self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
            self.assertEqual(arquilo.main(['git', 'retry', *arguments, '--publication', receipt['id']]), 0)
            committed_head = self.git('rev-parse', 'HEAD')
            self.assertNotEqual(committed_head, self.original_head)
            # Retrying an already complete receipt must not create a second commit.
            self.assertEqual(arquilo.main(['git', 'retry', *arguments, '--publication', receipt['id']]), 0)
            self.assertEqual(self.git('rev-parse', 'HEAD'), committed_head)
        self.assertEqual(self.git('show', 'HEAD:proof.txt'), RIGHT)
        self.assertEqual(self.git('rev-parse', 'HEAD^'), self.original_head)
        self.assert_plan(runner, done=True)
        for path, data in budget_before.items():
            self.assertEqual(path.read_bytes(), data)
        updated = reviewed_git.list_publications(runner.state_dir, self.work)
        self.assertEqual(updated[0]['status'], 'published')

    def test_required_reopen_does_not_hide_previously_pending_publication(self):
        runner = self.new_runner()
        real_git = runner.git_selection.git
        def failed_prepare(*args, **kw):
            if args[0] == 'read-tree' and kw.get('private'):
                raise ReviewedGitError('Synthetic publication preparation failure')
            return real_git(*args, **kw)
        with patch.object(runner.git_selection, 'git', side_effect=failed_prepare), self.dispatch(self.success):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assert_plan(runner, done=True)
        state = runner.state_dir
        budget_before = {p: p.read_bytes() for p in (state / 'call_budgets').rglob('*.json')}
        self.assertTrue(budget_before)
        receipts = reviewed_git.list_publications(state, self.work)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['status'], 'preparing')
        runner.close()
        resumed = self.new_runner(git_required=True)
        with self.dispatch(lambda **kw: self.fail('Accepted task must not run again')):
            resumed.run()
        self.assertEqual(resumed.exit_code, int(ExitCode.INCOMPLETE))
        self.assert_plan(resumed, done=True)
        self.assertEqual(self.record(resumed)['publication_status'], 'pending')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.original_head)
        for path, data in budget_before.items():
            self.assertEqual(path.read_bytes(), data)


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class CodexPublicationSeparation(PublicationWorkflow, IsolatedControllerCase):
    backend = 'codex'


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class ClaudePublicationSeparation(PublicationWorkflow, IsolatedControllerCase):
    backend = 'claude-code'


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class ClaudePublicationWorker(ClaudeFixture):
    runner = IsolatedControllerCase.runner

    def setUp(self):
        super().setUp()
        self.todo = self.work / 'tasks.md'
        self.todo.write_text('1. ***Task***: Create empty hello.txt.\n', encoding='utf-8', newline='')
        self.state_root = self.base / 'controller-state'; self.state_root.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Claude Worker')
        self.git('config', 'user.email', 'worker@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'gc.auto', '0')
        self.git('config', 'maintenance.auto', 'false')
        self.git('add', '--', 'tasks.md'); self.git('commit', '-qm', 'owner task')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work,
                                       stderr=subprocess.PIPE, timeout=20)

    def private_worker(self, *, mode='success'):
        self.mode(mode)
        runner = self.runner(backend='claude-code', git_enabled=True, git_paths=['hello.txt'], max_calls=4)
        outcome, _, _ = runner._execute_todo_autobuild(runner._parse_todo_file()[0], use_cli_subprocess=True)
        self.assertTrue(outcome.completed, outcome.message)
        self.assertIsNotNone(outcome.git_candidate)
        rows = self.rows()
        review = [row for row in rows if row['tools'] and 'Write' not in row['tools']]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['cwd'], str(self.work))
        self.assertNotIn('--skip-git-repo-check', review[0]['argv'])
        self.assertNotIn('Bash', review[0]['tools'])
        candidate = outcome.git_candidate
        frozen = Path(candidate.request['directory']) / candidate.token['candidate'] / 'workspace' / 'hello.txt'
        self.assertEqual(frozen.read_bytes(), b'')
        self.assertIn(str(frozen.parent), review[0]['prompt'])
        self.assertEqual(candidate.contents()['hello.txt'][0], b'')
        result = runner.git_selection.commit('reviewed Claude worker result', candidate=candidate)
        self.assertEqual(self.git('show', result['commit'] + ':hello.txt'), b'')
        requests = list((runner.state_dir / 'worker_calls').glob('*/request.json'))
        self.assertEqual(len(requests), 1)
        request = json.loads(requests[0].read_text())
        self.assertEqual(request['options']['backend'], 'claude-code')
        self.assertEqual(request['context']['git_review'], candidate.request)
        self.assertFalse((self.base / 'CODEX_WAS_STARTED').exists())
        return rows

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixture; native Windows cannot execute Python shebang')
    def test_real_private_claude_worker_preserves_snapshot_and_backend_boundaries(self):
        rows = self.private_worker()
        self.assertEqual(len(rows), 2)

    @unittest.skipIf(os.name == 'nt', 'POSIX executable fixture; native Windows cannot execute Python shebang')
    def test_real_private_claude_worker_accepts_matching_legacy_decision_source(self):
        rows = self.private_worker(mode='legacy_review')
        self.assertEqual(len(rows), 3)
        decisions = [row for row in rows if '--json-schema' in row['argv']]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['tools'], [])


class DecisionBackendProvenance(unittest.TestCase):
    def document(self, backend, source):
        payload = completed_document(parse_review_classification(LEGACY_PASS),
                                     decision={**deepcopy(COMPLETE), 'source': source})
        payload['backend'] = backend
        return payload

    def test_legacy_decision_source_must_match_selected_backend(self):
        for backend, correct, wrong in [('codex', 'codex_exec', 'claude_code'),
                                        ('claude-code', 'claude_code', 'codex_exec')]:
            with self.subTest(backend=backend):
                self.assertTrue(validate_result(self.document(backend, correct))['completed'])
                with self.assertRaises(AutoBuildResultError):
                    validate_result(self.document(backend, wrong))

    def test_unknown_backend_does_not_inherit_codex_decision_authority(self):
        with self.assertRaises((AutoBuildResultError, ValueError)):
            validate_result(self.document('unrecognized-backend', 'codex_exec'))


if __name__ == '__main__':
    unittest.main()
