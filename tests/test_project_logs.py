# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Project IDs, timestamped logs, restart integrity and no-follow regressions."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, contextmanager
from datetime import datetime, UTC, timedelta
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autobuild
import codex_transport as transport
import project_logs as logs
import run_todos
import safe_io
from controller_state import PlanIntegrityError, state_directory
from execution_budget import BudgetExhausted
from runtime_failure import execution_error


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base/'work'; self.work.mkdir()
        self.root = self.base/'private'
        self.todo = self.work/'tasks.md'
        self.todo.write_text('1. ***TASK***: Create hello.txt.\n', encoding='utf-8')
        self.state = state_directory(self.work, self.todo, self.root)

    def runner(self, *, todo=None, project_id=None, dry_run=False, **kwargs):
        runner = run_todos.TodoRunner(todo or self.todo, self.work, 5, 1, None, None,
            dry_run, run_todos.DryRunRecorder(None), set(), 3, 'workspace-write', None,
            state_dir=self.root, project_id=project_id, process_stop_policy='controller-only', **kwargs)
        self.addCleanup(runner.close)
        return runner

    def project(self, project_id='pilot', todo=None):
        todo = todo or self.todo
        state = state_directory(self.work, todo, self.root)
        return logs.project_logs(state, self.work, todo, project_id)

    def link(self, target, source, directory=False):
        try:
            source.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Host does not permit symlinks: {exc}')


class NamingTests(Fixture):
    def test_portable_lowercase_project_ids(self):
        self.assertEqual(logs.validate_project_id('Migration-Pilot_2'), 'migration-pilot_2')
        self.assertIsNone(logs.validate_project_id(None))

    def test_reject_paths_devices_controls_and_ambiguous_names(self):
        for value in ('', '..', '../x', '/x', 'C:\\x', 'CON', 'LPT9', 'NUL.txt',
                      'foo/bar', 'foo\\bar', 'project.', ' x', 'x ', 'x\n', 'x'*49,
                      'dry-run', 'Ä', '-name', {}, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                logs.validate_project_id(value)

    def test_utc_timestamp_and_sorting(self):
        date = datetime(2026,10,2,12,3,4,123456,tzinfo=UTC)
        self.assertEqual(logs.timestamp_name(date), '2026-10-02T12-03-04.123Z')
        self.assertLess(logs.timestamp_name(date), logs.timestamp_name(date+timedelta(seconds=1)))
        with self.assertRaises(ValueError): logs.timestamp_name(date.replace(tzinfo=None))

    def test_collision_suffix_is_exclusive_not_overwrite(self):
        first = logs.reserve_directory(self.root/'runs', '2026-10-02T12-03-04.123Z')
        sentinel = first/'sentinel'; sentinel.write_text('keep')
        second = logs.reserve_directory(first.parent, first.name)
        self.assertEqual(second.name, first.name+'-0002')
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_numbered_roles_share_monotonic_sequence(self):
        parent = self.root/'task-1'
        paths = [logs.numbered_directory(parent, role) for role in ('production','review','fix','review')]
        self.assertEqual([p.name for p in paths], ['001-production','002-review','003-fix','004-review'])

    def test_parallel_allocations_use_distinct_ordinals(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda i: logs.numbered_directory(self.root/'task', str(i)), range(12)))
        self.assertEqual(len({p.name.split('-')[0] for p in paths}), 12)

    def test_index_lock_serializes_threads_before_open(self):
        original = safe_io.open_file
        mutex = threading.Lock()
        active = 0
        high_water = 0
        @contextmanager
        def observed(*args, **kwargs):
            nonlocal active, high_water
            with mutex:
                active += 1
                high_water = max(high_water, active)
            try:
                time.sleep(0.01)
                with original(*args, **kwargs) as stream:
                    yield stream
            finally:
                with mutex:
                    active -= 1
        def enter(_):
            with logs.index_lock(self.root):
                pass
        with patch.object(safe_io, 'open_file', side_effect=observed):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(enter, range(8)))
        self.assertEqual(high_water, 1)

    def test_parallel_timestamp_allocations_are_distinct(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda _: logs.reserve_directory(self.root/'runs','same'), range(12)))
        self.assertEqual(len(set(paths)), 12)


class RegistryTests(Fixture):
    def test_named_path_and_unchanged_authority_location(self):
        project = self.project()
        self.assertEqual(project.directory, self.root/'pilot')
        self.assertEqual(project.state_directory, self.state)
        record = json.loads(safe_io.read_text(project.directory/'project.json'))
        self.assertEqual(record['plans'][self.state.name]['controller_state'], str(self.state))

    def test_without_flag_remains_compatible_and_binding_is_sticky(self):
        old = logs.project_logs(self.state,self.work,self.todo)
        self.assertEqual(old.directory,self.state)
        named = self.project()
        self.assertEqual(logs.project_logs(self.state,self.work,self.todo),named)

    def test_same_plan_cannot_silently_change_id(self):
        self.project()
        with self.assertRaisesRegex(ValueError,'already belongs'):
            self.project('other')
        self.assertFalse((self.root/'other').exists())

    def test_same_project_cannot_bind_different_workspace(self):
        self.project()
        other=self.base/'other';other.mkdir()
        todo=other/'tasks.md';todo.write_text('1. ***TASK***: Other.')
        state=state_directory(other,todo,self.root)
        with self.assertRaisesRegex(ValueError,'different workspace'):
            logs.project_logs(state,other,todo,'pilot')

    def test_multiple_plans_share_logs_but_not_state(self):
        one=self.project()
        todo=self.work/'second.md';todo.write_text('1. ***TASK***: Other.')
        two=self.project(todo=todo)
        self.assertEqual(one.directory,two.directory)
        self.assertNotEqual(one.state_directory,two.state_directory)
        self.assertEqual(len(json.loads(safe_io.read_text(one.directory/'project.json'))['plans']),2)

    def test_corrupt_registry_fails_closed(self):
        self.project()
        (self.root/'projects.json').write_text('{}')
        with self.assertRaises(ValueError):self.project()
        self.assertEqual((self.root/'projects.json').read_text(),'{}')

    def test_existing_foreign_directory_is_not_reused(self):
        d=self.root/'pilot';d.mkdir();(d/'private.txt').write_text('unchanged')
        with self.assertRaisesRegex(ValueError,'not empty'):self.project()
        self.assertEqual((d/'private.txt').read_text(),'unchanged')

    def test_broken_marker_is_not_overwritten(self):
        p=self.project();(p.directory/'project.json').write_text('{broken')
        with self.assertRaises(ValueError):self.project()
        self.assertEqual((p.directory/'project.json').read_text(),'{broken')

    def test_parallel_plan_registration_preserves_all_entries(self):
        todos=[]
        for n in range(4):
            p=self.work/f'{n}.md';p.write_text('1. ***TASK***: Other.');todos.append(p)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda todo:self.project(todo=todo),todos))
        record=json.loads(safe_io.read_text(self.root/'pilot'/'project.json'))
        self.assertEqual(len(record['plans']),4)


class RunTests(Fixture):
    def test_legacy_plan_budget_survive_named_project_and_omitted_flag(self):
        old=self.runner(max_calls=2)
        budget=old._call_budget_for('1');budget.consume('1','test')
        plan=(self.state/'plan.json').read_bytes();old.close()
        new=self.runner(project_id='pilot',max_calls=2)
        self.assertEqual(new.state_dir,self.state)
        self.assertEqual((self.state/'plan.json').read_bytes(),plan)
        self.assertEqual(new._call_budget_for('1').snapshot()['used'],1)
        new._call_budget_for('1').consume('1','test');new.close()
        resumed=self.runner(max_calls=2)
        self.assertEqual(resumed.project_id,'pilot')
        self.assertEqual(resumed._call_budget_for('1').snapshot()['used'],2)
        with self.assertRaises(BudgetExhausted):resumed._call_budget_for('1').consume('1','test')

    def test_changed_todo_still_rejected_when_adding_project_id(self):
        r=self.runner();r.close()
        self.todo.write_text('1. ***DONE***: Create hello.txt.\n')
        with self.assertRaises(PlanIntegrityError): self.runner(project_id='pilot')
        self.assertFalse((self.root/'pilot'/'latest-run.txt').exists())

    def test_same_project_separate_plans_do_not_share_budget(self):
        a=self.runner(project_id='pilot',max_calls=2);a._call_budget_for('1').consume('1','test')
        todo=self.work/'other.md';todo.write_text('1. ***TASK***: Other.')
        b=self.runner(todo=todo,project_id='pilot',max_calls=2)
        self.assertEqual(b._call_budget_for('1').snapshot()['used'],0)

    def test_timestamp_layout_and_initial_status(self):
        r=self.runner(project_id='pilot')
        self.assertEqual(r.run_dir.parent,self.root/'pilot'/'runs')
        self.assertRegex(r.run_dir.name,r'^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z')
        data=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(data['status'],'preparing');self.assertIsNone(data['finished_at'])
        self.assertEqual((r.project_logs.directory/'latest-run.txt').read_text().strip(),'runs/'+r.run_dir.name)

    def test_latest_started_is_not_last_finished(self):
        p=self.project();date=datetime(2026,10,2,12,tzinfo=UTC)
        a=p.new_run(date,run_id='a',workspace=self.work,todo=self.todo)
        b=p.new_run(date+timedelta(seconds=1),run_id='b',workspace=self.work,todo=self.todo)
        # A late completion changes only that run's manifest, not the latest pointer.
        (a/'run.json').write_text('{"status":"completed"}')
        self.assertEqual((p.directory/'latest-run.txt').read_text().strip(),'runs/'+b.name)
        self.assertEqual(json.loads((b/'run.json').read_text())['status'],'preparing')

    def test_complete_run_and_backward_compatible_run_log(self):
        self.todo.write_text('1. ***DONE***: Create hello.txt.\n')
        r=self.runner(project_id='pilot')
        with redirect_stdout(io.StringIO()):r.run()
        data=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(data['status'],'completed');self.assertIsNotNone(data['finished_at'])
        self.assertEqual(data['exit_code'],0)
        self.assertEqual(json.loads((r.run_dir/'run_log.json').read_text())['schema_version'],'arquilo.run_log.v1')

    def test_failed_run_has_direct_stderr_reference(self):
        r=self.runner(project_id='pilot')
        stderr=r.run_dir/'task-1'/'001-production'/'stderr.bin'
        error=execution_error('failed',code='codex_turn_failed',phase='auftrag')
        error['stderr_file']=str(stderr)
        outcome=run_todos.TaskOutcome(completed=False,message='failed',execution_error=error)
        output=io.StringIO()
        with patch.object(r,'_handle_todo',return_value=outcome),redirect_stdout(output):r.run()
        self.assertIn(str(stderr),output.getvalue())
        data=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(data['status'],'failed')
        self.assertEqual(data['execution_error']['stderr_file'],str(stderr))
        self.assertIn('Failure logs:',(r.run_dir/'overview.log').read_text())

    def test_cancellation_leaves_terminal_manifest(self):
        r=self.runner(project_id='pilot')
        with patch.object(r,'_next_todo',side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):r.run()
        data=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(data['status'],'cancelled');self.assertEqual(data['exit_code'],130)

    def test_task_logs_are_flat_and_repeated_attempts_do_not_overwrite(self):
        r=self.runner(project_id='pilot')
        _,_,a=r._prepare_task_log('1','long-old-stamp',self.work,self.todo)
        _,_,b=r._prepare_task_log('1-review','another-stamp',self.work,self.todo)
        self.assertEqual(a,r.run_dir/'task-1');self.assertEqual(b,r.run_dir/'task-1-0002')
        pretty,raw,_=r._attempt_log_paths(a,1,ensure_directories=True)
        self.assertEqual(pretty.parent,a);self.assertEqual(raw.parent,a)

    def test_dry_run_does_not_register_or_write_run_files(self):
        before=set(self.root.rglob('*'))
        r=self.runner(project_id='preview',dry_run=True)
        with redirect_stdout(io.StringIO()):r.run()
        self.assertEqual(set(self.root.rglob('*')),before)

    def test_invalid_id_cannot_write_into_workspace(self):
        with self.assertRaises(ValueError): self.runner(project_id='../work')
        self.assertFalse((self.work/'project.json').exists())

    def test_successive_runs_keep_old_archives_and_latest_is_new(self):
        a=self.runner(project_id='pilot');path=a.run_dir
        sentinel=path/'sentinel.txt';sentinel.write_text('retain');a.close()
        b=self.runner()
        self.assertNotEqual(b.run_dir,path)
        self.assertEqual(sentinel.read_text(),'retain')
        self.assertEqual((self.root/'pilot'/'latest-run.txt').read_text().strip(),'runs/'+b.run_dir.name)

    def test_real_autobuild_failure_carries_capture_to_runner_manifest(self):
        r=self.runner(project_id='pilot')
        def failed(**kwargs):
            directory=logs.numbered_directory(kwargs['raw_log'].parent,'production')
            safe_io.write_text(directory/'stderr.bin','synthetic process failure')
            safe_io.write_text(directory/'capture.json','{}')
            error=execution_error('synthetic failure',code='codex_turn_failed',phase='auftrag')
            trace=transport.RunResult(execution_error=error,capture_dir=directory)
            raise autobuild.CodexExecutionError(trace,error)
        output=io.StringIO()
        with patch.object(autobuild,'run_codex_exec_json',side_effect=failed),redirect_stdout(output):r.run()
        data=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(data['status'],'failed')
        stderr=Path(data['execution_error']['stderr_file'])
        self.assertTrue(stderr.is_file());self.assertTrue(stderr.is_relative_to(r.run_dir))
        self.assertIn(str(stderr),output.getvalue())

    def test_provider_policy_is_unchanged_by_project_registration(self):
        env=dict(os.environ)
        from codex_policy import DECISION_CONFIG
        before=DECISION_CONFIG
        self.runner(project_id='pilot')
        self.assertEqual(dict(os.environ),env)
        self.assertEqual(DECISION_CONFIG,before)
        self.assertEqual(DECISION_CONFIG,('approval_policy="never"',))

    def test_cli_accepts_new_parameter(self):
        outcome=subprocess.run([sys.executable,'-B',str(ROOT/'arquilo.py'),'run','--help'],capture_output=True,text=True)
        self.assertEqual(outcome.returncode,0)
        self.assertIn('--project-id',outcome.stdout)


class CaptureTests(Fixture):
    def test_capture_is_direct_numbered_phase_folder(self):
        parent=self.root/'pilot'/'runs'/'2026-10-02T12-00-00.000Z'/'task-2'
        request=transport.CodexExecRequest(prompt='synthetic',cwd=self.work,env={},
            raw_log=parent/'autobuild_raw.jsonl',pretty_log=parent/'autobuild_pretty.log',phase='auftrag')
        one=transport.RunResult();transport._prepare_capture(request,one)
        from dataclasses import replace
        two=transport.RunResult();transport._prepare_capture(replace(request,phase='review'),two)
        self.assertEqual(one.capture_dir,parent/'001-production')
        self.assertEqual(two.capture_dir,parent/'002-review')
        self.assertTrue((one.capture_dir/'stderr.bin').exists())
        self.assertFalse(any(part.endswith('.calls') for part in one.capture_dir.parts))

    def test_error_propagates_actual_capture_not_latest_guess(self):
        trace=transport.RunResult(execution_error=execution_error('oops',code='codex_turn_failed'),
                                  capture_dir=self.root/'task-2'/'002-review')
        error=autobuild.run_result_error(trace,'review')
        self.assertEqual(error['stderr_file'],str(trace.capture_dir/'stderr.bin'))


class BoundaryTests(Fixture):
    def test_symlink_project_directory_rejected(self):
        outside=self.base/'outside';outside.mkdir()
        self.link(outside,self.root/'pilot',True)
        with self.assertRaises((ValueError,OSError)):self.project()
        self.assertFalse((outside/'project.json').exists())

    def test_symlink_latest_pointer_is_not_followed(self):
        p=self.project();target=self.base/'target';target.write_text('unchanged')
        self.link(target,p.directory/'latest-run.txt')
        with self.assertRaises((ValueError,OSError)):
            p.new_run(datetime.now(UTC),run_id='test',workspace=self.work,todo=self.todo)
        self.assertEqual(target.read_text(),'unchanged')

    def test_hardlinked_registry_is_not_overwritten(self):
        self.project();outside=self.base/'copy';os.link(self.root/'projects.json',outside)
        before=outside.read_bytes()
        with self.assertRaises(ValueError):self.project()
        self.assertEqual(outside.read_bytes(),before)

    def test_corrupt_latest_pointer_is_never_used_as_authority(self):
        p=self.project();(p.directory/'latest-run.txt').write_text('../../outside')
        with self.assertRaisesRegex(ValueError,'latest-run'):
            p.new_run(datetime.now(UTC),run_id='x',workspace=self.work,todo=self.todo)
        self.assertFalse((self.base/'outside').exists())

    @unittest.skipUnless(os.name=='nt','Windows native junction')
    def test_windows_project_junction_rejected(self):
        outside=self.base/'outside';outside.mkdir();link=self.root/'pilot'
        result=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(outside)],capture_output=True)
        if result.returncode:self.skipTest('Host does not permit junction creation')
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        with self.assertRaises((ValueError,OSError)):self.project()
        self.assertFalse((outside/'project.json').exists())


if __name__=='__main__':unittest.main()
