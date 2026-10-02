# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Owner controls: no billed models; real controller, budgets, files and reviews."""
from __future__ import annotations

from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autobuild
from autobuild_contract import AutoBuildContext, AutoBuildOptions, call_payload, decode_call, validate_result
import codex_transport
from controller_state import PlanAuthority, PlanIntegrityError, state_directory
from execution_budget import CallBudget, BudgetExhausted, DEFAULT_MAX_CALLS, positive_limit
import run_todos
import safe_io

PASS = {'verdict':'PASS', 'short_summary':'Checked the requested artifacts.', 'blocking_issues':[],
        'non_blocking_observations':[], 'breakdown_recommended':False, 'breakdown_reason':None}
FAIL = {**PASS, 'verdict':'FAIL', 'short_summary':'Fix the output.', 'blocking_issues':[
    {'id':'F1', 'type':'local_fix', 'summary':'Output missing.', 'requirement':'Create output',
     'acceptance_criterion':'Output exists', 'references':[], 'fix_suggestion':'Create it.'}]}
PLAN = '1. ***DONE***: Previously checked input.\n2. ***TASK***: Append open tasks 3 and 4 to this same tasks.md; do not execute them.\n'
NEW = '3. ***TASK***: Create third.txt.\n4. ***TASK***: Create fourth.txt.\n'


def result(text):
    return codex_transport.RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.work = self.base/'work'; self.work.mkdir()
        self.root = self.base/'private'
        self.todo = self.work/'tasks.md'; self.todo.write_text(PLAN, encoding='utf-8')

    def runner(self, **kwargs):
        options = dict(todo_file=self.todo, workdir=self.work, max_depth=5, max_retries=1,
                       start_id=None, stop_id=None, dry_run=False,
                       dry_run_recorder=run_todos.DryRunRecorder(None), simulated_incomplete=set(),
                       max_steps=3, sandbox='workspace-write', run_id=None, state_dir=self.root,
                       process_stop_policy='controller-only')
        options.update(kwargs)
        runner = run_todos.TodoRunner(**options); self.addCleanup(runner.close)
        return runner

    def authority(self, **kwargs):
        a = PlanAuthority(self.todo, state_directory(self.work, self.todo, self.root), **kwargs)
        self.addCleanup(a.close); return a

    def run_fake(self, runner, production):
        calls = []
        def invoke(**kwargs):
            calls.append((kwargs['phase'], kwargs.get('console_todo_id'), kwargs['prompt']))
            if kwargs['phase'] == 'review':
                return result(json.dumps(PASS))
            production(kwargs)
            return result('Requested output is ready for separate review.')
        with patch.object(autobuild, 'run_codex_exec_json', side_effect=invoke), redirect_stdout(io.StringIO()):
            runner.run()
        return calls

    def link(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(str(exc))


class UnlimitedBudgetTests(Fixture):
    def test_defaults_and_zero_validation(self):
        self.assertEqual(DEFAULT_MAX_CALLS, 0)
        self.assertEqual(AutoBuildOptions().max_calls, 0)
        self.assertEqual(run_todos.parse_args(['--todo-file', str(self.todo)]).max_calls, 0)
        for value in (0, 1, 1000): self.assertEqual(positive_limit(value), value)
        for value in (-1, True, None, 1.5, '0'):
            with self.subTest(value=value), self.assertRaises(ValueError): positive_limit(value)

    def test_unlimited_keeps_counting_beyond_old_default(self):
        b = CallBudget(self.base/'budget', 0, '2')
        for n in range(125): self.assertEqual(b.consume('2', 'production')['number'], n+1)
        self.assertEqual(b.snapshot()['used'], 125)
        self.assertIsNone(b.snapshot()['remaining'])
        self.assertTrue(b.snapshot()['unlimited'])
        self.assertEqual(CallBudget(b.directory, 0, '2').consume('2','review')['number'], 126)

    def test_old_exhausted_budget_is_migrated_by_runner_without_losing_claims(self):
        state = state_directory(self.work, self.todo, self.root)
        b = CallBudget(state/'call_budgets/task_2', 2, '2')
        b.consume('2','production'); b.consume('2','review')
        before = {p.name:p.read_bytes() for p in b.directory.glob('call_*.json')}
        runner = self.runner(stop_id='2')
        self.assertEqual(runner._call_budget_for('2').limit, 0)
        self.assertEqual(runner._call_budget_for('2').snapshot()['used'], 2)
        calls = self.run_fake(runner, lambda _: None)
        self.assertEqual([c[0] for c in calls], ['auftrag','review'])
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(CallBudget(b.directory,0,'2').snapshot()['used'],4)
        self.assertEqual({n:(b.directory/n).read_bytes() for n in before},before)
        changes = list((b.directory/'limit_changes').glob('*/change.json'))
        self.assertEqual(len(changes),1)
        self.assertEqual(json.loads(changes[0].read_text())['previous_limit'],2)

    def test_zero_is_propagated_to_worker_payload(self):
        payload = call_payload(task='test',workdir=self.work,options=AutoBuildOptions(),context=AutoBuildContext())
        self.assertEqual(decode_call(payload)['options'].max_calls,0)

    def test_only_owner_can_change_existing_limit(self):
        b = CallBudget(self.base/'budget',1,'2'); b.consume('2','test')
        with self.assertRaises(ValueError): CallBudget(b.directory,0,'2')
        continued = CallBudget(b.directory,0,'2',allow_limit_change=True)
        self.assertEqual(continued.snapshot()['used'],1)
        with self.assertRaises(ValueError): b.consume('2','stale worker')

    def test_raising_or_lowering_limit_keeps_consumed_count(self):
        b=CallBudget(self.base/'budget',2,'2');b.consume('2','a');b.consume('2','b')
        more=CallBudget(b.directory,3,'2',allow_limit_change=True);more.consume('2','c')
        with self.assertRaises(BudgetExhausted):more.consume('2','d')
        with self.assertRaises(ValueError):CallBudget(b.directory,2,'2',allow_limit_change=True)
        self.assertEqual(json.loads((b.directory/'budget.json').read_text())['limit'],3)
        self.assertEqual(json.loads((b.directory/'reservations.json').read_text()),3)

    def test_old_claim_only_budget_uses_highest_not_number_of_files(self):
        d=self.base/'budget';d.mkdir()
        (d/'budget.json').write_text(json.dumps({'schema_version':'arquilo.call_budget.v1','root_id':'2','limit':100}))
        (d/'call_000057.json').write_text('partial')
        b=CallBudget(d,0,'2',allow_limit_change=True)
        self.assertEqual(b.consume('2','next')['number'],58)

    def test_corrupt_counter_not_reset_in_unlimited_mode(self):
        b=CallBudget(self.base/'budget',0,'2')
        for value in ('true','-1','NaN','null','"0"'):
            (b.directory/'reservations.json').write_text(value)
            with self.subTest(value=value), self.assertRaises(ValueError):CallBudget(b.directory,0,'2')

    def test_root_cannot_change_even_when_owner_changes_limit(self):
        b=CallBudget(self.base/'budget',2,'2')
        with self.assertRaises(ValueError):CallBudget(b.directory,0,'9',allow_limit_change=True)

    def test_failed_claim_write_still_counts_without_limit(self):
        b=CallBudget(self.base/'budget',0,'2')
        with patch.object(safe_io,'write_text',side_effect=OSError('disk')):
            with self.assertRaises(OSError):b.consume('2','test')
        self.assertEqual(b.snapshot()['used'],1)
        self.assertEqual(b.consume('2','next')['number'],2)

    def test_parallel_unlimited_reservations_are_unique(self):
        b=CallBudget(self.base/'budget',0,'2')
        with ThreadPoolExecutor(max_workers=4) as pool:
            numbers=list(pool.map(lambda _:b.consume('2','parallel')['number'],range(12)))
        self.assertEqual(sorted(numbers),list(range(1,13)))

    def test_existing_done_roots_also_adopt_unlimited_default(self):
        d=state_directory(self.work,self.todo,self.root)/'call_budgets/task_1'
        b=CallBudget(d,1,'1');b.consume('1','old')
        r=self.runner()
        self.assertEqual(r.call_budgets['1'].snapshot()['used'],1)
        self.assertEqual(r.call_budgets['1'].limit,0)

    def test_dry_run_does_not_migrate_budget(self):
        d=state_directory(self.work,self.todo,self.root)/'call_budgets/task_2'
        b=CallBudget(d,1,'2');old=(d/'budget.json').read_bytes()
        self.runner(dry_run=True)
        self.assertEqual((d/'budget.json').read_bytes(),old)


class MutablePlanTests(Fixture):
    def test_generating_same_file_stops_after_review_then_resumes_strict(self):
        runner=self.runner(allow_todo_modifications=True,stop_id='2')
        def generate(_): self.todo.write_text(PLAN+NEW,encoding='utf-8')
        calls=self.run_fake(runner,generate)
        self.assertEqual([c[0] for c in calls],['auftrag','review'])
        self.assertEqual(runner.exit_code,0)
        self.assertIn('2. ***DONE***',self.todo.read_text())
        self.assertIn('3. ***TASK***',self.todo.read_text())
        self.assertFalse((self.work/'third.txt').exists())
        self.assertFalse((self.work/'process_stop').exists())
        manifest=json.loads((runner.run_dir/'run.json').read_text())
        self.assertEqual(manifest['status'],'stopped')
        self.assertEqual(manifest['reviewed_this_run'],['2'])
        self.assertTrue(manifest['plan_mutations'])
        self.assertIn('Append open tasks',calls[1][2])
        self.assertNotIn('"task_text": "Create third.txt',calls[1][2])
        next_runner=self.runner()
        def build(kw):
            task=kw.get('console_todo_id')
            (self.work/('third.txt' if task=='3' else 'fourth.txt')).write_text('done')
        next_calls=self.run_fake(next_runner,build)
        self.assertEqual(len(next_calls),4)
        self.assertTrue((self.work/'third.txt').exists())
        self.assertTrue((self.work/'fourth.txt').exists())
        self.assertEqual(next_runner.exit_code,0)
        self.assertEqual(next_runner.reviewed_this_run,{'3','4'})

    def test_owner_can_edit_generated_plan_before_next_guarded_run(self):
        first=self.runner(allow_todo_modifications=True,stop_id='2')
        self.run_fake(first,lambda _: self.todo.write_text(PLAN+NEW))
        self.todo.write_text(self.todo.read_text().replace('Create third.txt','Create reviewed-third.txt'))
        with self.assertRaises(PlanIntegrityError):self.runner()
        r=self.runner(accept_plan_changes=True,start_id='3',stop_id='3')
        self.run_fake(r,lambda _:None)
        self.assertEqual(r.exit_code,0)
        self.assertEqual(r.reviewed_this_run,{'3'})

    def test_default_still_rejects_generated_tasks(self):
        r=self.runner(stop_id='2')
        self.run_fake(r,lambda _:self.todo.write_text(PLAN+NEW))
        self.assertNotEqual(r.exit_code,0)
        self.assertNotIn('2. ***DONE***',self.todo.read_text())

    def test_stop_at_one_also_prevents_generated_work(self):
        self.todo.write_text('1. ***TASK***: Generate future tasks.\n')
        r=self.runner(allow_todo_modifications=True,stop_id='1')
        self.run_fake(r,lambda _:self.todo.write_text('1. ***TASK***: Generate future tasks.\n2. ***TASK***: Later.\n'))
        self.assertEqual(r.reviewed_this_run,{'1'})
        self.assertEqual(r.exit_code,0)

    def test_new_ids_inserted_before_stop_are_not_scheduled(self):
        self.todo.write_text('1. ***TASK***: Generate plan.\n2. ***TASK***: Present plan for approval.\n')
        r=self.runner(allow_todo_modifications=True,stop_id='2')
        def generate(kw):
            if kw.get('console_todo_id')=='1':
                self.todo.write_text('1. ***TASK***: Generate plan.\n1.1. ***TASK***: New child for later.\n2. ***TASK***: Present plan for approval.\n3. ***TASK***: Later.\n')
        self.run_fake(r,generate)
        self.assertEqual(r.reviewed_this_run,{'1','2'})
        self.assertIn('1.1. ***TASK***',self.todo.read_text())

    def test_removed_stop_boundary_cannot_allow_later_work(self):
        self.todo.write_text('1. ***TASK***: Change plan.\n2. ***TASK***: Stop here.\n')
        r=self.runner(allow_todo_modifications=True,stop_id='2')
        def mutate(_):self.todo.write_text('1. ***TASK***: Change plan.\n3. ***TASK***: Must not execute.\n')
        with self.assertRaises(RuntimeError):self.run_fake(r,mutate)
        self.assertNotIn('3',r.attempted)

    def test_done_markers_are_not_reported_as_independent_review(self):
        r=self.runner(allow_todo_modifications=True,stop_id='2')
        self.run_fake(r,lambda _:self.todo.write_text(PLAN+NEW.replace('3. ***TASK***','3. ***DONE***')))
        manifest=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(manifest['reviewed_this_run'],['2'])
        self.assertNotIn('3',r.attempted)
        self.assertFalse(manifest['plan_mutations'][0]['independently_verified'])

    def test_changed_current_requirements_are_not_marked_done(self):
        r=self.runner(allow_todo_modifications=True)
        self.run_fake(r,lambda _:self.todo.write_text(PLAN.replace('Append open tasks 3 and 4 to this same tasks.md; do not execute them.','A different future requirement.')))
        self.assertIn('2. ***TASK***',self.todo.read_text())
        self.assertNotEqual(r.exit_code,0)
        self.assertIn('2',r.reviewed_this_run)

    def test_duplicates_still_fail(self):
        a=self.authority(allow_modifications=True)
        self.todo.write_text(PLAN+'2. ***TASK***: Duplicate.\n')
        with self.assertRaises(PlanIntegrityError):a.check()

    def test_mutations_are_archived_and_next_guarded_run_uses_new_plan(self):
        a=self.authority(allow_modifications=True);self.todo.write_text(PLAN+NEW);a.check()
        self.assertEqual(len(a.mutations),1)
        archive=Path(a.mutations[0]['archive'])
        self.assertEqual((archive/'before.md').read_text(),PLAN)
        self.assertEqual((archive/'after.md').read_text(),PLAN+NEW)
        a.close();b=self.authority();b.check()
        self.assertFalse(b.allow_modifications)
        self.todo.write_text(PLAN)
        with self.assertRaises(PlanIntegrityError):b.check()

    def test_parallel_batch_honors_stop_even_without_mutable_mode(self):
        self.todo.write_text('***CFG parallel=g workspace=a***\n1. ***TASK***: A.\n***CFG parallel=g workspace=b***\n2. ***TASK***: B.\n***CFG parallel=g workspace=c***\n3. ***TASK***: C.\n')
        r=self.runner(stop_id='2')
        batch=r._collect_parallel_group_batch(r._next_todo())
        self.assertEqual([t.identifier for t in batch],['1','2'])

    def test_owner_flags_are_not_accepted_from_task_directives(self):
        import codex_policy
        for name in ('allow_todo_modifications','logs_in_workdir','max_calls'):
            # Values must not be used as a second owner-control channel.
            self.todo.write_text(f'***CFG {name}=true***\n1. ***TASK***: Test.\n')
            r=self.runner(accept_plan_changes=True)
            with self.assertRaises(ValueError):r._parse_todo_file()
            r.close()

    def test_explicit_mutable_context_freezes_decide_input_across_correction(self):
        snapshots=[]
        def invoke(**kw):
            if kw['phase']=='auftrag':
                self.todo.write_text(PLAN.replace('Append open tasks 3 and 4 to this same tasks.md; do not execute them.','Weaker requirement.'))
                return result('Needs correction')
            if kw['phase']=='fix':return result('Corrected')
            return result(json.dumps(FAIL if len(snapshots)==0 else PASS))
        original=autobuild.evaluate_completion_decision
        def record(**kw):
            snapshots.append(kw['task_snapshot'].task_text)
            return original(**kw)
        state=state_directory(self.work,self.todo,self.root)
        with patch.object(autobuild,'run_codex_exec_json',side_effect=invoke),patch.object(autobuild,'evaluate_completion_decision',side_effect=record),redirect_stdout(io.StringIO()):
            summary=autobuild.start(task='Execute original task 2',workdir=self.work,
                options=AutoBuildOptions(logfile=state/'pretty.log',rawlog=state/'raw.jsonl'),
                context=AutoBuildContext(task_source='todo',todo_identifier='2',decision_todo_file=self.todo,
                    budget_directory=state/'budget',budget_root_id='2',allow_todo_modifications=True))
        self.assertTrue(summary.completed)
        self.assertEqual(len(snapshots),2)
        self.assertEqual(snapshots[0],snapshots[1])
        self.assertIn('Append open tasks',snapshots[1])


class WorkdirLogsTests(Fixture):
    def test_default_logs_remain_external(self):
        r=self.runner(project_id='pilot')
        self.assertFalse(r.run_dir.is_relative_to(self.work))

    def test_log_switch_does_not_move_state_or_budget(self):
        first=self.runner(project_id='pilot');state=first.state_dir;oldplan=(state/'plan.json').read_bytes();first.close()
        r=self.runner(logs_in_workdir=True)
        self.assertEqual(r.state_dir,state)
        self.assertEqual(r.run_dir.parent,self.work/'.codex_runs/run_todos')
        self.assertEqual((state/'plan.json').read_bytes(),oldplan)
        self.assertFalse(r._call_budget_for('2').directory.is_relative_to(self.work))
        self.assertEqual(r.project_id,'pilot')

    def test_workspace_logs_are_available_during_run_and_terminal_status_after_stop(self):
        r=self.runner(logs_in_workdir=True,allow_todo_modifications=True,stop_id='2')
        def create(_):
            self.assertTrue((r.run_dir/'run.json').exists())
            self.assertTrue((r.run_dir/'run_log.json').exists())
            self.assertTrue((r.run_dir/'run_config.json').exists())
            self.assertEqual(json.loads((r.run_dir/'run.json').read_text())['status'],'running')
            self.todo.write_text(PLAN+NEW)
        self.run_fake(r,create)
        doc=json.loads((r.run_dir/'run.json').read_text())
        self.assertEqual(doc['logs_location'],'workdir')
        self.assertEqual(doc['status'],'stopped')
        self.assertTrue((r.run_dir/'task-2/autobuild_summary.json').exists())
        self.assertEqual((r.run_dir.parent/'latest-run.txt').read_text().strip(),r.run_dir.name)

    def test_changing_back_to_external_does_not_reset_state(self):
        r=self.runner(logs_in_workdir=True,stop_id='2');self.run_fake(r,lambda _:None)
        n=self.runner()
        self.assertFalse(n.run_dir.is_relative_to(self.work))
        self.assertEqual(n._call_budget_for('2').snapshot()['used'],2)

    def test_dry_run_does_not_create_workdir_log_tree(self):
        r=self.runner(dry_run=True,logs_in_workdir=True,allow_todo_modifications=True)
        self.assertFalse((self.work/'.codex_runs').exists())
        self.assertFalse(self.root.exists())

    def test_workdir_log_junction_or_symlink_is_not_followed(self):
        elsewhere=self.base/'elsewhere';elsewhere.mkdir()
        self.link(elsewhere,self.work/'.codex_runs',True)
        with self.assertRaises((OSError,ValueError)):self.runner(logs_in_workdir=True)
        self.assertEqual(list(elsewhere.iterdir()),[])

    def test_runtime_flags_do_not_weaken_codex_policy(self):
        import codex_policy
        before=codex_policy.sandbox_arguments(sandbox='workspace-write',network_access=False)
        r=self.runner(logs_in_workdir=True,allow_todo_modifications=True)
        self.assertEqual(before,codex_policy.sandbox_arguments(sandbox=r.sandbox,network_access=r.network_access))


class MoreControlTests(Fixture):
    def test_unlimited_summary_validation_and_invalid_variants(self):
        r=self.runner(stop_id='2');self.run_fake(r,lambda _:None)
        summary=next(r.run_dir.rglob('autobuild_summary.json'))
        value=json.loads(summary.read_text())
        validate_result(value)
        self.assertEqual(value['call_budget']['limit'],0)
        self.assertIsNone(value['call_budget']['remaining'])
        for key,bad in [('remaining',0),('remaining',float('inf')),('limit',True),('used',-1),('unlimited',False)]:
            clone=json.loads(summary.read_text());clone['call_budget'][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):validate_result(clone)
        clone=json.loads(summary.read_text());del clone['call_budget']['remaining']
        with self.assertRaises(ValueError):validate_result(clone)
        clone=json.loads(summary.read_text());clone['budget_exhausted']={'root_id':'2','blocked_phase':'review'}
        with self.assertRaises(ValueError):validate_result(clone)

    def test_explicit_finite_runner_limit_still_stops_before_review(self):
        r=self.runner(stop_id='2',max_calls=1)
        calls=self.run_fake(r,lambda _:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(r.exit_code,6)
        self.assertTrue((self.work/'process_stop').exists())
        self.assertIn('2. ***TASK***',self.todo.read_text())

    def test_old_budget_stop_is_not_automatically_removed_or_ignored(self):
        r=self.runner(stop_id='2',max_calls=1);self.run_fake(r,lambda _:None)
        stop=self.work/'process_stop';old=stop.read_bytes()
        n=self.runner(stop_id='2')
        self.assertEqual(n._call_budget_for('2').limit,0)
        self.assertEqual(self.run_fake(n,lambda _:None),[])
        self.assertEqual(stop.read_bytes(),old)
        stop.unlink()  # Deliberate owner action after inspection, never library behavior.
        last=self.runner(stop_id='2');self.run_fake(last,lambda _:None)
        self.assertEqual(last.exit_code,0)
        self.assertEqual(last._call_budget_for('2').snapshot()['used'],3)

    def test_malformed_mutable_plan_is_not_adopted_even_at_stop(self):
        r=self.runner(stop_id='2',allow_todo_modifications=True)
        old=(r.state_dir/'plan.json').read_bytes()
        self.run_fake(r,lambda _:self.todo.write_text(PLAN+'3. ***BOGUS***: Bad task.\n'))
        self.assertNotEqual(r.exit_code,0)
        self.assertEqual((r.state_dir/'plan.json').read_bytes(),old)

    def test_mutable_mode_is_not_sticky_and_human_edits_are_explicit(self):
        a=self.authority(allow_modifications=True);self.todo.write_text(PLAN+NEW);a.check();a.close()
        self.todo.write_text(PLAN+NEW+'5. ***TASK***: Human edit.\n')
        with self.assertRaises(PlanIntegrityError):self.authority()
        b=self.authority(accept_changes=True);b.check()
        self.assertFalse(b.allow_modifications)

    def test_active_task_can_be_removed_but_original_review_and_stop_still_apply(self):
        r=self.runner(stop_id='2',allow_todo_modifications=True)
        calls=self.run_fake(r,lambda _:self.todo.write_text('1. ***DONE***: Previously checked input.\n'+NEW))
        self.assertEqual([c[0] for c in calls],['auftrag','review'])
        self.assertEqual(r.exit_code,0)
        self.assertIn('2',r.reviewed_this_run)
        self.assertNotIn('3',r.attempted)

    def test_stop_already_done_never_runs_later_tasks(self):
        self.todo.write_text(PLAN.replace('2. ***TASK***','2. ***DONE***')+NEW)
        r=self.runner(stop_id='2',allow_todo_modifications=True)
        calls=self.run_fake(r,lambda _:self.fail('Must not execute beyond stop'))
        self.assertEqual(calls,[])
        self.assertEqual(r.exit_code,0)

    def test_cli_exposes_only_explicit_opt_ins(self):
        args=run_todos.parse_args(['--todo-file',str(self.todo)])
        self.assertFalse(args.allow_todo_modifications);self.assertFalse(args.logs_in_workdir)
        args=run_todos.parse_args(['--todo-file',str(self.todo),'--allow-todo-modifications','--logs-in-workdir','--stop','2'])
        self.assertTrue(args.allow_todo_modifications);self.assertTrue(args.logs_in_workdir)
        self.assertEqual(args.stop_id,'2')

    def test_owner_bool_inputs_are_strict(self):
        for name in ('logs_in_workdir','allow_todo_modifications'):
            for value in (1,'true',None):
                with self.subTest(name=name,value=value),self.assertRaises(ValueError):self.runner(**{name:value})

    def test_policy_flags_do_not_weaken_decide_options(self):
        import codex_policy
        self.runner(logs_in_workdir=True,allow_todo_modifications=True)
        self.assertEqual(codex_policy.decision_arguments(network_access=False,config_profile=None,extra_args=[]),
                         ['--sandbox','read-only','-c','approval_policy="never"'])

    def test_workspace_log_mode_still_has_live_capture_and_exact_error_path(self):
        from runtime_failure import execution_error
        r=self.runner(logs_in_workdir=True)
        def failed(**kw):
            capture=codex_transport.numbered_directory(Path(kw['raw_log']).parent,'production')
            safe_io.write_bytes(capture/'stderr.bin',b'Synthetic failure')
            return codex_transport.RunResult(execution_error={**execution_error('Synthetic failure',code='codex_turn_failed',phase='production'),
                'capture_directory':str(capture),'stderr_file':str(capture/'stderr.bin')})
        with patch.object(autobuild,'run_codex_exec_json',side_effect=failed),redirect_stdout(io.StringIO()):r.run()
        self.assertNotEqual(r.exit_code,0)
        manifest=json.loads((r.run_dir/'run.json').read_text())
        stderr=Path(manifest['execution_error']['stderr_file'])
        self.assertTrue(stderr.is_relative_to(self.work/'.codex_runs'))
        self.assertEqual(stderr.read_bytes(),b'Synthetic failure')

    def test_worker_request_and_return_are_private_not_workspace_authority(self):
        r=self.runner(logs_in_workdir=True)
        log=r.run_dir/'task-2';safe_io.mkdir(log)
        summary=log/'autobuild_summary.json'
        options=AutoBuildOptions(logfile=log/'pretty.log',rawlog=log/'raw.jsonl',summary_json=summary)
        ctx=AutoBuildContext(budget_directory=r._call_budget_for('2').directory,budget_root_id='2')
        from runtime_failure import execution_error
        error=execution_error('Private synthetic failure',code='codex_turn_failed',phase='production')
        payload={'completed':False,'process_stop_triggered':False,'review_required':True,'exit_code':7,
                 'status':'failed','last_answer':'','execution_error':error}
        def subprocess_fake(command,**kwargs):
            request=Path(command[-1]);self.assertFalse(request.is_relative_to(self.work))
            data=json.loads(request.read_text())
            private=Path(data['options']['summary_json']);self.assertFalse(private.is_relative_to(self.work))
            self.assertEqual(data['options']['max_calls'],0)
            self.assertFalse(Path(data['context']['budget_directory']).is_relative_to(self.work))
            summary.write_text('{"completed":true}')  # Model-edited public log must not be accepted.
            private.write_text(json.dumps(payload))
            return subprocess.CompletedProcess(command,7,b'',b'Synthetic stderr')
        with patch.object(run_todos.subprocess,'run',side_effect=subprocess_fake):
            returned=r._autobuild_python_attempt('test',self.work,options,ctx)
        self.assertFalse(returned.completed)
        self.assertEqual(returned.execution_error['message'],'Private synthetic failure')
        self.assertEqual(json.loads(summary.read_text()),payload)

    def test_independent_processes_share_unlimited_counter(self):
        directory=self.base/'budget';CallBudget(directory,0,'2')
        code="from execution_budget import CallBudget; from pathlib import Path; import sys; print(CallBudget(Path(sys.argv[1]),0,'2').consume('2','test')['number'])"
        children=[subprocess.Popen([sys.executable,'-B','-c',code,str(directory)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(6)]
        numbers=[]
        for child in children:
            out,err=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,err.decode('utf-8','replace'))
            numbers.append(int(out))
        self.assertEqual(sorted(numbers),list(range(1,7)))

    def test_new_logs_do_not_overwrite_previous_workdir_runs(self):
        a=self.runner(logs_in_workdir=True);a.close()
        (a.run_dir/'marker').write_text('retain')
        b=self.runner(logs_in_workdir=True)
        self.assertNotEqual(a.run_dir,b.run_dir)
        self.assertEqual((a.run_dir/'marker').read_text(),'retain')
        self.assertEqual((b.run_dir.parent/'latest-run.txt').read_text().strip(),b.run_dir.name)

class VersionedBudgetTests(Fixture):
    def test_v2_unlimited_records_and_claims(self):
        b=CallBudget(self.base/'budget',0,'2')
        self.assertEqual(b.snapshot()['schema_version'],'arquilo.call_budget.v2')
        self.assertEqual(json.loads((b.directory/'budget.json').read_text())['schema_version'],'arquilo.call_budget.v2')
        self.assertEqual(b.consume('2','test')['schema_version'],'arquilo.call_claim.v2')

    def test_invalid_legacy_unlimited_record_is_not_silently_adopted(self):
        d=self.base/'budget';d.mkdir()
        for schema in ('arquilo.call_budget.v1','arquilo.call_budget.v99'):
            (d/'budget.json').write_text(json.dumps({'schema_version':schema,'root_id':'2','limit':0}))
            with self.subTest(schema=schema),self.assertRaises(ValueError):
                CallBudget(d,0,'2',allow_limit_change=True)
            self.assertFalse((d/'reservations.json').exists())

    def test_old_finite_record_changes_only_with_owner_limit_update(self):
        d=self.base/'budget';d.mkdir()
        old=json.dumps({'schema_version':'arquilo.call_budget.v1','root_id':'2','limit':100})
        (d/'budget.json').write_text(old)
        b=CallBudget(d,100,'2');b.consume('2','old');self.assertEqual((d/'budget.json').read_text(),old)
        new=CallBudget(d,0,'2',allow_limit_change=True)
        self.assertEqual(new.snapshot()['used'],1)
        self.assertEqual(json.loads((d/'budget.json').read_text())['schema_version'],'arquilo.call_budget.v2')

    def test_single_file_example_lints_without_network_or_other_files(self):
        from todo_lint import lint_todo_file
        self.todo.write_bytes((ROOT/'examples/planning_todo.md').read_bytes())
        self.assertEqual(lint_todo_file(self.todo,workdir=self.work),[])

if __name__ == '__main__': unittest.main()
