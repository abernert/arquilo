# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Combined documentation/state/Git acceptance with synthetic model answers.

No provider credentials or external push. Runtime code is unchanged by this
integration. These tests also record the *existing* late-context-refusal limit;
they are not claims of a new preflight implementation.
"""
from __future__ import annotations

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
from codex_transport import RunResult
import git_snapshot
from reviewed_git import ReviewedGitError

PASS = {'verdict': 'PASS', 'short_summary': 'Checked synthetic artifact against source.',
        'blocking_issues': [], 'non_blocking_observations': [],
        'breakdown_recommended': False, 'breakdown_reason': None}
CALCULATOR = b'def add(a, b):\n    return a + b\n'
UNITTEST = (b'import unittest\nfrom calculator import add\n\n'
            b'class Addition(unittest.TestCase):\n'
            b'    def test_positive(self): self.assertEqual(add(2, 3), 5)\n'
            b'    def test_negative(self): self.assertEqual(add(-2, 3), 1)\n'
            b'    def test_zero(self): self.assertEqual(add(0, 0), 0)\n')
SUMMARY = (b'# Atlas summary\n\nRequirements draft: 2030-01-10.\n'
           b'Internal prototype: 2030-01-24.\nAcceptance review: 2030-02-07.\n'
           b'The prototype uses local synthetic data.\n\n'
           b'## Open questions\nThe acceptance owner is unassigned.\n')


def answer(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class IntegratedWorkflowTests(IsolatedControllerCase):
    def git(self, *args):
        return subprocess.check_output(['git', '-c', 'core.longpaths=true', *args],
                                      cwd=self.work, stderr=subprocess.PIPE, timeout=20)

    def prepare(self, example='document_review_todo.md'):
        plan = (ROOT / 'examples' / example).read_text(encoding='utf-8')
        self.write_plan(plan)
        (self.work / 'brief.md').write_bytes((ROOT / 'examples/brief.md').read_bytes())
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Integration')
        self.git('config', 'user.email', 'integration@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        self.git('add', '--', 'tasks.md', 'brief.md')
        self.git('commit', '-qm', 'owner inputs')
        return plan

    def test_document_guide_run_binds_source_summary_and_retains_other_staging(self):
        plan = self.prepare()
        (self.work / 'owners-note.txt').write_bytes(b'UNRELATED STAGING\n')
        self.git('add', '--', 'owners-note.txt')
        staged = self.git('rev-parse', ':owners-note.txt')
        runner = self.runner(git_enabled=True, git_paths=['summary.md'])
        phases = []
        def dispatch(**kw):
            cwd = Path(kw['cwd']); phases.append(kw['phase'])
            if kw['phase'] == 'auftrag':
                self.assertEqual(cwd, self.work)
                (cwd / 'summary.md').write_bytes(SUMMARY)
                return answer('Summary created; owner remains unassigned.')
            self.assertNotEqual(cwd, self.work)
            self.assertEqual(kw['sandbox'], 'read-only')
            self.assertEqual((cwd / 'summary.md').read_bytes(), SUMMARY)
            self.assertEqual((cwd / 'brief.md').read_bytes(), (self.work / 'brief.md').read_bytes())
            for date in (b'2030-01-10', b'2030-01-24', b'2030-02-07'):
                self.assertIn(date, SUMMARY)
            self.assertLess(len(SUMMARY.split()), 250)
            return answer(json.dumps(PASS))
        with self.fake_codex(dispatch): runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(len(phases), 2)
        self.assertEqual(self.git('show', 'HEAD:summary.md'), SUMMARY)
        self.assertEqual(self.git('show', 'HEAD:tasks.md'), plan.encode())
        self.assertEqual(self.git('rev-parse', ':owners-note.txt'), staged)
        self.assertNotIn(b'owners-note.txt', self.git('ls-tree', '--name-only', 'HEAD'))
        self.assert_accepted_artifact(runner, plan=plan.replace('***Task***', '***DONE***'),
                                     artifact='summary.md', data=SUMMARY)

    def test_two_task_software_example_runs_tests_on_review_copy(self):
        plan = self.prepare('python_function_todo.md')
        runner = self.runner(git_enabled=True, git_paths=['calculator.py', 'test_calculator.py'])
        phases = []
        def dispatch(**kw):
            cwd = Path(kw['cwd']); phases.append(kw['phase'])
            if kw['phase'] == 'auftrag':
                (cwd / 'calculator.py').write_bytes(CALCULATOR)
                (cwd / 'test_calculator.py').write_bytes(UNITTEST)
                return answer('Three synthetic checks recorded.')
            self.assertNotEqual(cwd, self.work)
            # This is known synthetic code owned by the test, not unreviewed
            # output from a live model. -B avoids changing the reviewed copy.
            tested = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover',
                                     '-s', str(cwd), '-p', 'test_calculator.py', '-v'],
                                    cwd=cwd, capture_output=True, timeout=20)
            self.assertEqual(tested.returncode, 0, tested.stderr.decode('utf-8', 'replace'))
            self.assertIn(b'Ran 3 tests', tested.stderr)
            self.assertEqual((cwd / 'calculator.py').read_bytes(), CALCULATOR)
            return answer(json.dumps(PASS))
        with self.fake_codex(dispatch): runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(len(phases), 4)
        for path, content in [('calculator.py', CALCULATOR), ('test_calculator.py', UNITTEST)]:
            self.assertEqual(self.git('show', 'HEAD:' + path), content)
        self.assertEqual(self.todo.read_text(encoding='utf-8'), plan.replace('***Task***', '***DONE***'))
        for p in ('tasks.md', 'todo_result_1.md', 'todo_result_2.md'):
            self.assertNotIn(p.encode(), self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'))

    def test_without_git_uses_live_review_without_snapshot_machinery(self):
        plan = self.prepare()
        runner = self.runner()
        def dispatch(**kw):
            self.assertEqual(Path(kw['cwd']), self.work)
            if kw['phase'] == 'auftrag':
                (self.work / 'summary.md').write_bytes(SUMMARY)
                return answer('Created summary.')
            return answer(json.dumps(PASS))
        before = self.git('rev-parse', 'HEAD')
        with patch('git_snapshot.capture', side_effect=AssertionError('No Git snapshot without opt-in')), self.fake_codex(dispatch):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertFalse((runner.state_dir / 'git-reviews').exists())
        self.assertEqual(self.todo.read_text(encoding='utf-8'), plan.replace('***Task***', '***DONE***'))

    def _context_failure(self, *, small_limit=False):
        original = self.todo.read_bytes()
        before = self.git('rev-parse', 'HEAD')
        runner = self.runner(git_enabled=True, git_paths=['summary.md'])
        phases = []
        def dispatch(**kw):
            phases.append(kw['phase'])
            self.assertEqual(kw['phase'], 'auftrag', 'An invalid context must not reach review')
            (self.work / 'summary.md').write_bytes(SUMMARY)
            return answer('Production completed before context capture.')
        from contextlib import nullcontext
        limit = patch.object(git_snapshot, 'MAX_FILE_BYTES', 4096) if small_limit else nullcontext()
        with limit, self.fake_codex(dispatch): runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(phases, ['auftrag'])
        self.assertEqual(self.todo.read_bytes(), original)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual((self.work / 'summary.md').read_bytes(), SUMMARY)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text(encoding='utf-8'))['text'],
                         original.decode('utf-8'))

    def test_linked_environment_is_rejected_after_production_not_before(self):
        self.prepare()
        outside = self.base / 'external-environment'; outside.mkdir()
        try:
            (self.work / '.venv').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Native link fixture unavailable: ' + type(exc).__name__)
        self._context_failure()
        self.assertEqual(list(outside.iterdir()), [])

    def test_large_unselected_context_is_rejected_after_production(self):
        self.prepare()
        (self.work / 'oversized-context.bin').write_bytes(b'x' * 4097)
        self.assertEqual(git_snapshot.MAX_FILE_BYTES, 32 * 1024 * 1024)
        # Exercise the same quota path with small synthetic data; this is not
        # a 32 MiB throughput benchmark.
        self._context_failure(small_limit=True)

    def test_parallel_git_refusal_precedes_any_model_in_first_batch(self):
        self.prepare()
        self.write_plan('***CFG parallel=group workspace=child***\n1. ***Task***: Create summary.md.\n')
        self.git('add', '--', 'tasks.md'); self.git('commit', '-qm', 'parallel owner plan')
        runner = self.runner(git_enabled=True, git_paths=['summary.md'])
        before = self.todo.read_bytes()
        with self.fake_codex(lambda **kw: self.fail('No model may start')), self.assertRaisesRegex(ReviewedGitError, 'serial tasks'):
            runner.run()
        self.assertEqual(self.todo.read_bytes(), before)

    def test_task_plan_selection_is_rejected_at_setup(self):
        self.prepare()
        with self.assertRaisesRegex(ReviewedGitError, 'task plan'):
            self.runner(git_enabled=True, git_paths=['tasks.md'])


class IntegrationDocumentationTests(unittest.TestCase):
    def test_manifest_records_code_docs_and_release_separately(self):
        manifest = json.loads((ROOT / 'docs/guides/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['status'], 'unreleased-integration')
        self.assertEqual(manifest['source_commit'], manifest['integrated_pull_requests']['36'])
        self.assertEqual(manifest['documentation_base_commit'], manifest['integrated_pull_requests']['33'])
        self.assertNotEqual(manifest['source_commit'], manifest['release_baseline'])
        for guide in manifest['guides']:
            text = (ROOT / guide['path']).read_text(encoding='utf-8')
            self.assertIn('../integration-status.md', text)
            self.assertIn('0.9.1', text)
        self.assertEqual((ROOT / 'VERSION').read_text().strip(), '0.9.1')

    def test_combined_package_keeps_both_pr_additions(self):
        package = json.loads((ROOT / 'documents/lean_package.json').read_text(encoding='utf-8'))
        required = {'git_snapshot.py', 'docs/guides/cli-reference.json', 'docs/integration-status.md',
                    'docs/guides/user-guide.de.md', 'docs/guides/user-guide.en.md',
                    'docs/guides/operator-guide.en.md', 'docs/guides/technical-guide.en.md',
                    'docs/guides/manifest.json', 'docs/README.md',
                    'examples/python_function_todo.md'}
        self.assertTrue(required.issubset(package['runtime_files']))
        self.assertEqual(len(set(package['runtime_files'])), package['runtime_file_count'])
        self.assertNotIn('tests/test_integration_091.py', package['runtime_files'])
        self.assertFalse(any(p.startswith('maintenance/') for p in package['runtime_files']))

    def test_guides_do_not_recommend_publishing_controller_plan_or_old_gap(self):
        operator = (ROOT / 'docs/guides/operator-guide.en.md').read_text(encoding='utf-8')
        self.assertNotIn('--git-path tasks.md', operator)
        self.assertNotIn('--git-path todo_result_1.md', operator)
        self.assertIn('after production', operator)
        self.assertIn('serial only', operator)
        technical = (ROOT / 'docs/guides/technical-guide.en.md').read_text(encoding='utf-8')
        self.assertIn('git_snapshot.py', technical)
        self.assertNotIn('This is design intent, **not current behavior**', technical)
        self.assertNotIn('Windows registry race still under investigation', technical)


if __name__ == '__main__':
    unittest.main()
