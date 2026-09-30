# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Synthetic regressions: no providers; push tests use only disposable local bare repos."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import safe_io
from controller_state import PlanAuthority, PlanIntegrityError, state_directory
from execution_budget import CallBudget, BudgetExhausted
from reviewed_git import ReviewedGit, ReviewedGitError
from runtime_files import atomic_write_text, unique_directory
import run_todos
from runtime_profile import _parse_preflight, RuntimeProfileError

PLAN = '1. ***TASK***: Create first.txt.\n2. ***TASK***: Create second.txt.\n'


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.workspace = self.base / 'workspace'
        self.workspace.mkdir()
        self.state = self.base / 'state'
        self.todo = self.workspace / 'tasks.md'
        self.todo.write_text(PLAN, encoding='utf-8')

    def authority(self, **kwargs):
        d = state_directory(self.workspace, self.todo, self.state)
        authority = PlanAuthority(self.todo, d, **kwargs)
        self.addCleanup(authority.close)
        return authority

    def runner(self, **kwargs):
        value = run_todos.TodoRunner(self.todo, self.workspace, 5, 1, None, None, False,
            run_todos.DryRunRecorder(None), set(), 3, 'workspace-write', None,
            process_stop_policy='controller-only', state_dir=self.state, **kwargs)
        self.addCleanup(value.close)
        return value

    def link(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Host does not grant symlink creation: {exc}')


class PlanTests(Fixture):
    @unittest.skipUnless(os.name == 'nt', 'Windows registered user folders')
    def test_windows_state_root_without_environment(self):
        from controller_state import default_state_root
        with patch.dict(os.environ, {}, clear=True):
            root = default_state_root()
        self.assertTrue(root.is_absolute())
        self.assertEqual(root.parts[-2:], ('ARQUILO', 'controller'))

    def test_doctor_reports_external_default_state_root(self):
        import arquilo_doctor
        with patch('arquilo_doctor.resolve_launcher', side_effect=OSError('Not needed')):
            report = arquilo_doctor.collect_report(workdir=self.workspace, env={})
        self.assertIn('runner_state_root', report['paths'])
        self.assertNotIn('runner_logs', report['paths'])

    def test_unauthorized_done_removed_obsolete_and_hidden_tasks_fail(self):
        authority = self.authority()
        for text in (PLAN.replace('2. ***TASK***', '2. ***DONE***'),
                     PLAN.splitlines()[0] + '\n',
                     PLAN.replace('2. ***TASK***', '2. ***OBSOLETE***'),
                     '```\n' + PLAN + '```\n', PLAN + '3. ***DONE***: Forged\n',
                     PLAN.replace('first.txt', 'easier.txt')):
            with self.subTest(text=text):
                self.todo.write_text(text, encoding='utf-8')
                with self.assertRaises(PlanIntegrityError):
                    authority.check()
        self.todo.write_text(PLAN, encoding='utf-8')
        authority.check()

    def test_unapproved_mutation_survives_restart_as_failure(self):
        a = self.authority()
        self.todo.write_text(PLAN.replace('2. ***TASK***', '2. ***DONE***'), encoding='utf-8')
        a.close()
        with self.assertRaises(PlanIntegrityError):
            self.authority()

    def test_approved_transition_and_restart(self):
        a = self.authority()
        new = PLAN.replace('1. ***TASK***', '1. ***DONE***')
        a.replace_approved(new)
        a.close()
        b = self.authority()
        self.assertEqual(b.text, new)
        b.check()

    def test_first_owner_baseline_can_contain_done(self):
        self.todo.write_text(PLAN.replace('1. ***TASK***', '1. ***DONE***'), encoding='utf-8')
        self.authority().check()

    def test_explicit_owner_adoption_is_archived(self):
        a = self.authority(); a.close()
        self.todo.write_text(PLAN + '3. ***TASK***: New owner task\n', encoding='utf-8')
        b = self.authority(accept_changes=True)
        self.assertIn('New owner task', b.text)
        self.assertEqual(len(list(b.directory.glob('owner-adoptions/*/previous-plan.md'))), 1)

    def test_valid_open_children_require_explicit_controller_acceptance(self):
        a = self.authority()
        new = PLAN.replace('2. ***TASK***', '1.1. ***TASK***: Child\n2. ***TASK***')
        self.todo.write_text(new, encoding='utf-8')
        self.assertEqual(a.verify_children('1'), ['1.1'])
        with self.assertRaises(PlanIntegrityError): a.check()
        a.accept_children('1', 2)
        a.check()
        a.close()
        self.authority().check()

    def test_breakdown_cannot_change_old_work_or_create_done(self):
        a = self.authority()
        for text in (PLAN.replace('2. ***TASK***', '1.1. ***DONE***: Forged\n2. ***TASK***'),
                     PLAN + '1.1. ***TASK***: Outside parent\n',
                     PLAN.replace('2. ***TASK***', '1.1. ***TASK***: Child\n2. ***DONE***')):
            self.todo.write_text(text, encoding='utf-8')
            with self.assertRaises(PlanIntegrityError): a.verify_children('1')

    def test_pending_approved_write_recovers_after_crash(self):
        a = self.authority()
        new = PLAN.replace('1. ***TASK***', '1. ***DONE***')
        a._save(a.text, pending=new)
        a.close()
        b = self.authority()
        self.assertEqual(self.todo.read_text(), new)
        b.check()

    def test_pending_write_rejects_a_third_unapproved_value(self):
        a = self.authority()
        a._save(a.text, pending=PLAN.replace('1. ***TASK***', '1. ***DONE***'))
        a.close()
        self.todo.write_text(PLAN.replace('2. ***TASK***', '2. ***DONE***'))
        with self.assertRaises(PlanIntegrityError): self.authority()

    def test_dispatch_failure_cannot_become_done(self):
        r = self.runner()
        def producer(*args, **kwargs):
            self.todo.write_text(PLAN.replace('2. ***TASK***', '2. ***DONE***'))
            (self.workspace / 'first.txt').touch()
            return run_todos.TaskOutcome(completed=True, message='Simulated separate review PASS')
        with patch.object(r, '_run_autobuild_impl', side_effect=producer):
            result = r._run_autobuild('1', 'First task')
        self.assertFalse(result.completed)
        self.assertEqual(result.execution_error['code'], 'unapproved_plan_mutation')
        self.assertFalse((self.workspace / 'second.txt').exists())
        with self.assertRaises(PlanIntegrityError): r._next_todo()

    def test_real_run_rejects_fake_done_without_accepting_either_task(self):
        r = self.runner()
        def producer(*args, **kwargs):
            self.todo.write_text(PLAN.replace('2. ***TASK***', '2. ***DONE***'))
            (self.workspace / 'first.txt').touch()
            return run_todos.TaskOutcome(completed=True, message='Simulated review PASS')
        with patch.object(r, '_run_autobuild_impl', side_effect=producer), redirect_stdout(io.StringIO()):
            r.run()
        self.assertNotEqual(r.exit_code, 0)
        self.assertEqual(r.completed, set())
        self.assertFalse((self.workspace / 'second.txt').exists())

    def test_real_run_and_noop_restart_accept_only_completed_tasks(self):
        r = self.runner()
        def producer(identifier, *args, **kwargs):
            (self.workspace / ('first.txt' if identifier == '1' else 'second.txt')).touch()
            return run_todos.TaskOutcome(completed=True, message='Simulated review PASS')
        with patch.object(r, '_run_autobuild_impl', side_effect=producer), redirect_stdout(io.StringIO()):
            r.run()
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.completed, {'1', '2'})
        r2 = self.runner()
        with patch.object(r2, '_run_autobuild_impl', side_effect=AssertionError('No replay')), redirect_stdout(io.StringIO()):
            r2.run()
        self.assertEqual(r2.exit_code, 0)

    def test_crlf_and_bom_approved_status_is_stable(self):
        self.todo.write_bytes(('\ufeff' + PLAN.replace('\n', '\r\n')).encode())
        r = self.runner()
        task = r._parse_todo_file()[0]
        r._mark_todo_as_done(task)
        r.plan_authority.check()
        data = self.todo.read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'\r\n', data)
        r.close()
        self.runner().plan_authority.check()

    def test_parallel_workspace_copy_is_checked(self):
        r = self.runner()
        child = self.workspace / 'worker'; child.mkdir()
        copy = child / 'tasks.md'; copy.write_text(PLAN)
        def producer(*args, **kwargs):
            copy.write_text(PLAN.replace('2. ***TASK***', '2. ***DONE***'))
            return run_todos.TaskOutcome(completed=True, message='fake')
        with patch.object(r, '_run_autobuild_impl', side_effect=producer):
            result = r._run_autobuild('1', 'task', todo_file_override=copy, workdir_override=child)
        self.assertFalse(result.completed)

    def test_breakdown_restart_executes_children_then_mandatory_parent_review(self):
        r = self.runner()
        parent = r._parse_todo_file()[0]
        classification = {
            "verdict": "FAIL", "short_summary": "Local repair needed",
            "blocking_issues": [{"id":"LOCAL-1", "type":"local_fix", "summary":"Missing output",
                "requirement":"Create first.txt", "acceptance_criterion":"File exists", "references":[],
                "fix_suggestion":"Create it"}],
            "non_blocking_observations":[], "breakdown_recommended":False, "breakdown_reason":None,
        }
        def breakdown(identifier, *args, **kwargs):
            self.assertEqual(identifier, '1-breakdown')
            self.todo.write_text(PLAN.replace('2. ***TASK***',
                '1.1. ***TASK***: Create first.txt and verify existence.\n2. ***TASK***'), encoding='utf-8')
            return run_todos.TaskOutcome(completed=True, message='Validated child plan')
        with patch.object(r, '_run_autobuild_impl', side_effect=breakdown), redirect_stdout(io.StringIO()):
            result = r._request_minimal_breakdown(todo=parent, result_file=self.workspace/'todo_result_1.md',
                outcome=run_todos.TaskOutcome(completed=False, message="Local fix", review_classification=classification))
        self.assertIsNone(result)
        r.plan_authority.check()
        r.close()  # simulated deliberate restart, before any child executes
        calls=[]
        r2=self.runner()
        def worker(identifier, *args, **kwargs):
            calls.append(identifier)
            self.assertNotEqual(identifier, '1', 'Do not replay parent production')
            if identifier == '1-review':
                self.assertTrue((self.workspace/'first.txt').exists())
                self.assertEqual(kwargs.get('sandbox_override'), 'read-only')
                return run_todos.TaskOutcome(completed=True, message=json.dumps({
                    "verdict":"PASS", "short_summary":"Checked child output",
                    "blocking_issues":[], "non_blocking_observations":[],
                    "breakdown_recommended":False, "breakdown_reason":None}))
            (self.workspace/('first.txt' if identifier=='1.1' else 'second.txt')).touch()
            return run_todos.TaskOutcome(completed=True, message='Simulated task review PASS')
        with patch.object(r2, '_run_autobuild_impl', side_effect=worker), redirect_stdout(io.StringIO()):
            r2.run()
        self.assertEqual(r2.exit_code, 0)
        self.assertEqual(r2.completed, {'1', '1.1', '2'})
        self.assertLess(calls.index('1.1'), calls.index('1-review'))

    def test_two_controllers_cannot_share_plan(self):
        a = self.authority()
        with self.assertRaises((OSError, PlanIntegrityError)):
            self.authority()
        a.check()

    def test_state_and_budget_are_outside_model_workspace(self):
        r = self.runner()
        self.assertFalse(r.run_dir.is_relative_to(self.workspace))
        self.assertFalse(r._call_budget_for('1.1').directory.is_relative_to(self.workspace))
        with self.assertRaises(PlanIntegrityError):
            state_directory(self.workspace, self.todo, self.workspace / 'state')


class FileTests(Fixture):
    def test_atomic_write_rejects_leaf_symlink_and_preserves_target(self):
        other = self.base / 'outside.txt'; other.write_text('keep')
        link = self.workspace / 'process_stop'; self.link(other, link)
        with self.assertRaises(safe_io.UnsafePathError): atomic_write_text(link, 'overwrite')
        self.assertEqual(other.read_text(), 'keep')

    def test_atomic_write_rejects_hardlink(self):
        other = self.base / 'outside.txt'; other.write_text('keep')
        alias = self.workspace / 'alias'; os.link(other, alias)
        with self.assertRaises(safe_io.UnsafePathError): atomic_write_text(alias, 'overwrite')
        self.assertEqual(other.read_text(), 'keep')

    def test_linked_parent_rejected_before_directory_creation(self):
        other = self.base / 'outside'; other.mkdir()
        self.link(other, self.workspace / '.codex_runs', True)
        with self.assertRaises(safe_io.UnsafePathError):
            unique_directory(self.workspace / '.codex_runs' / 'run_todos', prefix='run')
        self.assertEqual(list(other.iterdir()), [])

    def test_real_runner_rejects_legacy_log_link(self):
        other = self.base / 'outside'; other.mkdir()
        self.link(other, self.workspace / '.codex_runs', True)
        with self.assertRaises(safe_io.UnsafePathError): self.runner()
        self.assertEqual(list(other.iterdir()), [])

    def test_link_swapped_after_runner_init_does_not_overwrite(self):
        r = self.runner()
        other = self.base / 'outside.txt'; other.write_text('keep')
        self.link(other, r.process_stop_path)
        with self.assertRaises(safe_io.UnsafePathError): r._append_process_stop_details('unsafe')
        self.assertEqual(other.read_text(), 'keep')

    @unittest.skipIf(os.name == 'nt', 'POSIX directory-descriptor race test')
    def test_parent_replaced_between_staging_and_replace_does_not_follow_link(self):
        parent = self.workspace / 'reports'; parent.mkdir()
        outside = self.base / 'outside'; outside.mkdir()
        victim = outside / 'x'; victim.write_text('keep')
        original = os.replace
        moved = self.workspace / 'old_reports'
        def race(src, dst, **kw):
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
            return original(src, dst, **kw)
        with patch('safe_io.os.replace', side_effect=race):
            atomic_write_text(parent / 'x', 'new')
        self.assertEqual(victim.read_text(), 'keep')
        self.assertEqual((moved / 'x').read_text(), 'new')

    @unittest.skipUnless(os.name == 'nt', 'native Windows junction test')
    def test_windows_junction_parent_is_rejected(self):
        outside = self.base / 'outside'; outside.mkdir()
        link = self.workspace / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        with self.assertRaises(safe_io.UnsafePathError): atomic_write_text(link / 'file', 'unsafe')
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_atomic_replace_preserves_original_and_recovery_file(self):
        target=self.workspace/'normal'; target.write_text('keep')
        with patch('safe_io.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(OSError) as failure: atomic_write_text(target,'replacement')
        self.assertEqual(target.read_text(),'keep')
        recovery=failure.exception.recovery_path
        self.assertEqual(recovery.read_text(),'replacement')

    @unittest.skipUnless(os.name == 'nt', 'Windows parent-handle lease')
    def test_windows_parent_cannot_be_renamed_during_replace(self):
        parent=self.workspace/'reports'; parent.mkdir()
        original=os.replace
        def try_rename(src,dst,**kwargs):
            with self.assertRaises(OSError): parent.rename(self.workspace/'moved')
            return original(src,dst,**kwargs)
        with patch('safe_io.os.replace',side_effect=try_rename):
            atomic_write_text(parent/'file','normal')
        self.assertEqual((parent/'file').read_text(),'normal')

    @unittest.skipUnless(os.name == 'nt', 'Windows alias validation')
    def test_windows_ambiguous_components_are_rejected(self):
        for name in ('trailing.', 'trailing ', 'file:stream', 'NUL', 'CON.txt', '.. '):
            with self.subTest(name=name), self.assertRaises(safe_io.UnsafePathError):
                safe_io.lexical_path(self.workspace/name)

    def test_regular_atomic_write_and_append(self):
        target = self.workspace / 'normal'
        atomic_write_text(target, 'Ünicode')
        with safe_io.open_file(target, 'a') as stream: stream.write(' more')
        self.assertEqual(target.read_text(encoding='utf-8'), 'Ünicode more')

    def test_dry_run_same_input_and_output_preserves_input(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.object(run_todos, '_beep'):
            code = run_todos.main(['--todo-file', str(self.todo), '--workdir', str(self.workspace),
                                   '--dry-run', '--dry-run-file', str(self.todo)])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.todo.read_text(), PLAN)

    def test_dry_run_refuses_existing_output_and_aliases(self):
        alias = self.workspace / 'alias'; os.link(self.todo, alias)
        for target in (self.todo, alias):
            with self.assertRaises((OSError, ValueError)): run_todos.DryRunRecorder(target)
        self.assertEqual(self.todo.read_text(), PLAN)

    def test_dry_run_writes_only_new_report(self):
        target = self.workspace / 'preview.md'
        report = run_todos.DryRunRecorder(target)
        report.record('one', 'not executed')
        self.assertIn('not executed', target.read_text())
        self.assertEqual(self.todo.read_text(), PLAN)

    def test_existing_policy_directory_is_not_silently_empty(self):
        target = self.workspace / 'config' / 'policy.md'; target.mkdir(parents=True)
        with self.assertRaises((RuntimeError, ValueError, OSError)): self.runner()

    def test_policy_deleted_or_unreadable_after_start_fails(self):
        r = self.runner(); r.policy_workspace_file.unlink()
        with self.assertRaises(RuntimeError): r._read_policy_text()
        with patch('run_todos.read_utf8', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, 'Cannot read required policy'): r._read_policy_text()

    def test_empty_default_policy_remains_valid(self):
        r = self.runner()
        self.assertEqual(r._read_policy_text(), '')


class BudgetTests(Fixture):
    def test_deleting_diagnostic_claim_does_not_refund_budget(self):
        b = CallBudget(self.base / 'budget', 1, '1')
        b.consume('1', 'production')
        (b.directory / 'call_000001.json').unlink()
        with self.assertRaises(BudgetExhausted): b.consume('1', 'review')
        restored = CallBudget(b.directory, 1, '1')
        self.assertEqual(restored.snapshot()['used'], 1)

    def test_failed_claim_write_is_reserved(self):
        b = CallBudget(self.base / 'budget', 1, '1')
        with patch('execution_budget.safe_io.write_text', side_effect=OSError('disk')):
            with self.assertRaises(OSError): b.consume('1', 'production')
        self.assertEqual(b.snapshot()['remaining'], 0)

    def test_concurrent_processes_reserve_at_most_the_shared_limit(self):
        limit=4
        directory=self.base/'budget'
        CallBudget(directory,limit,'1')
        code="""from pathlib import Path
import sys
from execution_budget import CallBudget, BudgetExhausted
b=CallBudget(Path(sys.argv[1]),4,'1')
try:
    print(b.consume('1','test')['number'])
except BudgetExhausted:
    print('exhausted')
"""
        processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(directory)],
                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
        answers=[]
        for child in processes:
            out,err=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,err.decode('utf-8','replace'))
            answers.append(out.decode().strip())
        self.assertEqual(sorted(a for a in answers if a!='exhausted'),['1','2','3','4'])
        self.assertEqual(CallBudget(directory,limit,'1').snapshot()['used'],limit)

    def test_counter_corruption_is_not_reset(self):
        b = CallBudget(self.base / 'budget', 1, '1')
        (b.directory / 'reservations.json').write_text('NaN')
        with self.assertRaises(ValueError): CallBudget(b.directory, 1, '1')

    def test_legacy_claims_migrate_without_reset(self):
        d = self.base / 'budget'; d.mkdir()
        (d / 'budget.json').write_text(json.dumps({'schema_version':'arquilo.call_budget.v1','root_id':'1','limit':2}))
        (d / 'call_000001.json').write_text('partial diagnostic')
        b = CallBudget(d, 2, '1')
        self.assertEqual(b.consume('1', 'review')['number'], 2)
        with self.assertRaises(BudgetExhausted): b.consume('1', 'production')


class PreflightTests(unittest.TestCase):
    def test_argv_preserves_repetitions_spaces_and_empty_arguments(self):
        argv = [sys.executable, 'script.py', '--include', 'a', '--include', 'b', ' padded ', '']
        self.assertEqual(_parse_preflight({'command':argv}).command, tuple(argv))

    def test_invalid_argv_is_rejected(self):
        for argv in (None, '', [], [''], [' '], ['python', None], ['python', '\0']):
            with self.subTest(argv=argv), self.assertRaises(RuntimeProfileError):
                _parse_preflight({'command':argv})

    def test_nonfinite_and_invalid_timeouts_fail(self):
        for timeout in (float('nan'), float('inf'), float('-inf'), 'NaN', 'Infinity', 0, -1, 3601, True):
            with self.subTest(timeout=timeout), self.assertRaises(RuntimeProfileError):
                _parse_preflight({'command':['python'], 'timeout_seconds':timeout})
        self.assertEqual(_parse_preflight({'command':['python'], 'timeout_seconds':1.5}).timeout_seconds, 1.5)


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class GitTests(Fixture):
    def setUp(self):
        super().setUp()
        self.state.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Test')
        self.git('config', 'user.email', 'test@example.invalid')
        for name in ('first.txt', 'second.txt', 'staged-note', 'unstaged-note'):
            (self.workspace / name).write_text('initial')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')

    def git(self, *args):
        proc = subprocess.run(['git', *args], cwd=self.workspace, capture_output=True, check=True)
        return proc.stdout

    def test_commit_only_explicit_paths_preserves_other_changes_and_logs(self):
        (self.workspace / 'staged-note').write_text('private staged')
        self.git('add', 'staged-note')
        (self.workspace / 'unstaged-note').write_text('private unstaged')
        (self.workspace / 'untracked-private').write_text('private untracked')
        g = ReviewedGit(self.workspace, ['first.txt', 'new.txt'], self.state)
        (self.workspace / 'first.txt').write_text('reviewed output')
        (self.workspace / 'new.txt').write_text('new reviewed')
        logs = self.workspace / '.codex_runs'; logs.mkdir()
        (logs / 'raw-prompts.jsonl').write_text('sensitive synthetic content')
        result = g.commit('Reviewed task')
        self.assertFalse(result['pushed'])
        changed = set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').decode().splitlines())
        self.assertEqual(changed, {'first.txt', 'new.txt'})
        self.assertEqual(self.git('diff', '--cached', '--name-only').decode().strip(), 'staged-note')
        self.assertEqual((self.workspace / 'unstaged-note').read_text(), 'private unstaged')
        self.assertIn(b'untracked-private', self.git('ls-files', '--others', '--exclude-standard'))

    def test_dirty_selected_file_is_rejected_at_launch(self):
        (self.workspace / 'first.txt').write_text('user work')
        with self.assertRaises(ReviewedGitError): ReviewedGit(self.workspace, ['first.txt'], self.state)

    def test_internal_paths_even_tracked_are_never_selected(self):
        for name in ('.codex_runs/raw', '.git/config', '../outside', 'process_stop'):
            with self.subTest(name=name), self.assertRaises(ReviewedGitError):
                ReviewedGit(self.workspace, [name], self.state)

    def test_selection_required(self):
        with self.assertRaises(ReviewedGitError): ReviewedGit(self.workspace, [], self.state)

    def test_concurrent_index_edit_stops_before_commit(self):
        g = ReviewedGit(self.workspace, ['first.txt'], self.state)
        before = self.git('rev-parse', 'HEAD')
        (self.workspace / 'first.txt').write_text('result')
        (self.workspace / 'staged-note').write_text('late user edit'); self.git('add', 'staged-note')
        with self.assertRaises(ReviewedGitError): g.commit('must not commit')
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))

    def test_symlink_selected_after_review_is_rejected(self):
        g = ReviewedGit(self.workspace, ['first.txt'], self.state)
        other = self.base / 'secret'; other.write_text('keep')
        (self.workspace / 'first.txt').unlink(); self.link(other, self.workspace / 'first.txt')
        with self.assertRaises(safe_io.UnsafePathError): g.commit('must not include outside')

    def test_literal_pathspec_special_characters_and_deletion(self):
        # No shell expansion or pathspec globbing; [a] is an ordinary filename.
        g = ReviewedGit(self.workspace, ['[a].txt', 'first.txt'], self.state)
        (self.workspace / '[a].txt').write_text('literal')
        (self.workspace / 'a.txt').write_text('not selected')
        (self.workspace / 'first.txt').unlink()
        g.commit('Selected creation and deletion')
        self.assertIn(b'[a].txt\0', self.git('ls-files', '-z'))
        self.assertNotIn(b'a.txt\0', self.git('ls-files', '-z'))
        self.assertNotIn(b'first.txt\0', self.git('ls-files', '-z'))

    def test_explicit_push_uses_only_local_bare_remote(self):
        remote=self.base/'remote.git'
        subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
        self.git('remote','add','origin',str(remote))
        self.git('push','-qu','origin','HEAD')
        g=ReviewedGit(self.workspace,['first.txt'],self.state,push=True)
        (self.workspace/'first.txt').write_text('reviewed')
        result=g.commit('Explicit local test push')
        self.assertTrue(result['pushed'])
        remote_head=subprocess.check_output(['git','--git-dir',str(remote),'rev-parse',g.remote_branch])
        self.assertEqual(remote_head.strip().decode(),result['commit'])

    def test_push_refuses_unrelated_unpushed_commits(self):
        remote=self.base/'remote.git'
        subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
        self.git('remote','add','origin',str(remote)); self.git('push','-qu','origin','HEAD')
        self.git('commit','--allow-empty','-qm','Unrelated owner commit')
        with self.assertRaises(ReviewedGitError):
            ReviewedGit(self.workspace,['first.txt'],self.state,push=True)

    def test_push_is_never_implicit(self):
        g = ReviewedGit(self.workspace, ['first.txt'], self.state)
        (self.workspace / 'first.txt').write_text('output')
        original = g.git
        seen = []
        def record(*args, **kwargs):
            seen.append(args[0])
            if args[0] == 'push': self.fail('Unexpected network push')
            return original(*args, **kwargs)
        with patch.object(g, 'git', side_effect=record): g.commit('Reviewed')
        self.assertNotIn('push', seen)


if __name__ == '__main__':
    unittest.main()
