# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Synthetic controller and private Python-worker return tests (no original logs)."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, AutoBuildResultError, validate_result
import codex_transport as transport
import run_todos
from runtime_failure import execution_error, stop_reason
from test_reconnect_stop import Fixture, RECONNECT, ANSWER, COMPLETE, WORK, STOP, PASS, FAIL, answer

PLAN = "1. ***TASK***: Create a synthetic output.\n2. ***TASK***: Inspect the next output.\n"
# This wrapper substitutes only the model CLI inside a real, separately spawned
# AutoBuild worker. Its request and response still cross the private JSON boundary.
WORKER = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import autobuild, codex_transport as transport
from dataclasses import replace
script, config, request = map(Path, sys.argv[2:5])
settings = json.loads(config.read_text(encoding="utf-8"))
call = json.loads(request.read_text(encoding="utf-8"))
original_start = transport._start_process
index = 0
def start(command, *, cwd, env):
    global index
    if index >= len(settings):
        raise AssertionError("Unexpected worker phase")
    scenario = dict(settings[index])
    scenario["ready"] = str(config.parent / ("ready-"+str(os.getpid())+"-"+str(index)))
    if scenario.get("stop") is True:
        scenario.update(stop=call["options"]["process_stop_path"], reason="Synthetic operator pause: inspect the result.")
    index += 1
    path = config.parent / ("worker-scenario-"+str(os.getpid())+"-"+str(index)+".json")
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return original_start([sys.executable,"-B",str(script),str(path)],cwd=cwd,env=env)
transport._start_process = start
original_run = autobuild.run_codex_exec_json
def invoke(**kwargs):
    return original_run(**dict(kwargs, timeouts=transport.TransportTimeouts(total=8,stall=4,post_turn_grace=1,kill_grace=.05)))
autobuild.run_codex_exec_json = invoke
raise SystemExit(autobuild.main(["--request-json",str(request)]))
'''

class ControllerFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.todo = self.work/'tasks.md'; self.todo.write_text(PLAN, encoding='utf-8')
        self.repo = Path(run_todos.__file__).parent

    def runner(self, **kwargs):
        options = dict(todo_file=self.todo, workdir=self.work, max_depth=5, max_retries=1, start_id=None,
            stop_id=None, dry_run=False, dry_run_recorder=run_todos.DryRunRecorder(None), simulated_incomplete=set(),
            max_steps=3, sandbox='workspace-write', run_id=None, state_dir=self.base/'private',
            process_stop_policy='controller-only')
        options.update(kwargs)
        result = run_todos.TodoRunner(**options)
        self.addCleanup(result.close)
        return result

    @contextmanager
    def native_worker(self, scenarios):
        wrapper = self.base/'worker_wrapper.py'; wrapper.write_text(WORKER,encoding='utf-8')
        spec = self.base/'worker_scenarios.json'; spec.write_text(json.dumps(scenarios),encoding='utf-8')
        original = subprocess.run
        calls = []
        def launch(command, *args, **kwargs):
            if isinstance(command,list) and '--request-json' in command:
                calls.append(command)
                request = Path(command[-1])
                self.assertFalse(request.is_relative_to(self.work))
                command = [sys.executable, '-B', str(wrapper), str(self.repo), str(self.stub), str(spec), str(request)]
                kwargs['timeout'] = 25
            return original(command, *args, **kwargs)
        with patch.object(run_todos.subprocess, 'run', side_effect=launch):
            yield calls

    def run_scenarios(self, scenarios, *, worker=False, parallel=False):
        runner = self.runner(logs_in_workdir=True)
        if worker:
            execute = runner._execute_todo_autobuild
            def worker_execute(todo, **kwargs):
                return execute(todo, **{**kwargs, 'use_cli_subprocess':True})
            with self.native_worker(scenarios) as workers, \
                 patch.object(runner, '_execute_todo_autobuild', side_effect=worker_execute), \
                 redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                runner.run()
            count = len(workers)
        else:
            original = autobuild.run_codex_exec_json
            def invoke(**kwargs):
                return original(**{**kwargs,'timeouts':transport.TransportTimeouts(total=6,stall=3,post_turn_grace=1,kill_grace=.05)})
            with self.launch(scenarios) as calls, patch.object(autobuild,'run_codex_exec_json',side_effect=invoke), \
                 redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
                runner.run()
            count = calls.call_count
        return runner, out.getvalue(), count

    def verify_logs(self, runner, *, code, terminal_phase, index, next_id='2'):
        stopped = code == 6
        for filename in ('run.json', 'run_log.json'):
            value = json.loads((runner.run_dir/filename).read_text(encoding='utf-8'))
            self.assertEqual(value['exit_code'],code)
            self.assertEqual(value['status'],'stopped' if stopped else 'failed')
            self.assertEqual(value['termination_status'],'cancelled' if stopped else 'failed')
            self.assertTrue(value['process_stop_triggered'])
            self.assertEqual(value['process_stop_details'],STOP)
        for record in runner.task_log_records.values():
            task = json.loads((record.log_dir/'task_log.json').read_text(encoding='utf-8'))
            summary = json.loads((record.log_dir/'autobuild_summary.json').read_text(encoding='utf-8'))
            validate_result(summary)
            for obj in (task, summary):
                self.assertFalse(obj['completed'])
                self.assertEqual(obj['exit_code'],code)
                self.assertEqual(obj['process_stop_details'], STOP)
                self.assertTrue(obj['process_stop_triggered'])
            self.assertEqual(task['status'],'incomplete' if stopped else 'failed')
            self.assertEqual(task['termination_status'],'cancelled' if stopped else 'failed')
            terminal = summary['terminal_attempt']
            self.assertEqual((terminal['phase'],terminal['index']),(terminal_phase,index))
            self.assertEqual(task['capture_directory'], terminal['capture_directory'])
            capture = json.loads((Path(terminal['capture_directory'])/'capture.json').read_text(encoding='utf-8'))
            self.assertTrue(capture['process_stop_triggered'])
            self.assertEqual(capture['cancellation_reason'],STOP)
        self.assertNotIn(next_id, runner.attempted)
        self.assertFalse(runner.completed)
        self.assertNotIn('DONE', self.todo.read_text(encoding='utf-8'))

class ControllerTests(ControllerFixture):
    def test_complete_controller_stop_and_single_diagnostic_block(self):  # T101-27/29
        runner, out, calls = self.run_scenarios([{'events':[RECONNECT, WORK], 'mode':'wait','stop':True}])
        self.assertEqual(calls,1)
        self.verify_logs(runner,code=6,terminal_phase='task',index=1)
        self.assertIsNone(runner.terminal_execution_error)
        for field in ('capture_directory','stderr_file','pretty_log','raw_log'):
            self.assertEqual(out.count('[diagnose] '+field+':'),1,out)
        self.assertNotIn('codex_stream_error',out)
        self.assertTrue(all(p.poll() is not None for p in self.processes))

    def test_controller_failure_and_stop_are_both_preserved(self):  # T101-28
        runner,out,calls = self.run_scenarios([{'events':[RECONNECT,{'type':'error','message':'Synthetic fatal'}],
                                               'mode':'wait','stop':True}])
        self.assertEqual(calls,1)
        self.verify_logs(runner,code=7,terminal_phase='task',index=1)
        self.assertEqual(runner.terminal_execution_error['code'],'codex_stream_error')
        for field in ('capture_directory','stderr_file','pretty_log','raw_log'):
            self.assertEqual(out.count('[diagnose] '+field+':'),1,out)

    def test_fix_stop_keeps_correct_archive_in_process_and_real_worker(self):  # T101-33
        for worker in (False, True):
            self.stop.unlink(missing_ok=True)
            runner,out,calls = self.run_scenarios([{'events':[ANSWER,COMPLETE]},
                {'events':[answer(json.dumps(FAIL)),COMPLETE]}, {'events':[RECONNECT,WORK],'mode':'wait','stop':True}],worker=worker)
            self.assertEqual(calls,1 if worker else 3)
            self.verify_logs(runner,code=6,terminal_phase='task',index=2)
            self.assertIn('003-fix',out)
            # Diagnostics identify the terminal fix, not the older last-listed review.
            diagnostic = [s for s in out.splitlines() if s.startswith('[diagnose] capture_directory:')]
            self.assertEqual(len(diagnostic),1)
            self.assertIn('003-fix',diagnostic[0])
            runner.close()

    def test_parallel_worker_error_preserves_stop_and_blocks_next_task(self):  # T101-28/30
        self.todo.write_text('***CFG workspace=one parallel=pair***\n1. ***TASK***: Synthetic parallel one.\n'
                            '***CFG workspace=two parallel=pair***\n2. ***TASK***: Synthetic parallel two.\n'
                            '3. ***TASK***: Must not run.\n',encoding='utf-8')
        runner,_,calls = self.run_scenarios([{'events':[RECONNECT,{'type':'error','message':'Synthetic fatal'}],
                                            'mode':'wait','stop':True}],worker=True,parallel=True)
        self.assertEqual(calls,2)
        self.verify_logs(runner,code=7,terminal_phase='task',index=1,next_id='3')

    def test_dedup_is_per_attempt_and_thread_safe(self):  # T101-29
        runner = self.runner()
        outcome = run_todos.TaskOutcome(False,'Synthetic stop',process_stop_triggered=True,
            process_stop_details=STOP,capture_directory=self.logs/'001-production',pretty_log=self.logs/'pretty.log',
            raw_log=self.logs/'raw.jsonl',log_dir=self.logs,task_log_id='1',session_stamp='synthetic',attempt=1)
        with redirect_stdout(io.StringIO()) as out:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda _: runner._show_failure_logs(outcome), range(6)))
            outcome.capture_directory=self.logs/'003-fix'
            runner._show_failure_logs(outcome)
        for field in ('capture_directory','stderr_file','pretty_log','raw_log'):
            self.assertEqual(out.getvalue().count('[diagnose] '+field+':'),2)
        self.assertIsNone(outcome.execution_error)

    def test_missing_legacy_details_are_not_taken_from_error_message(self):
        runner=self.runner()
        outcome=run_todos.TaskOutcome(False,'UNRELATED TECHNICAL ERROR',True,execution_error=execution_error('Synthetic error'))
        with redirect_stdout(io.StringIO()):
            runner._stop_for_execution_error('1',outcome)
        self.assertEqual(runner.process_stop_details,stop_reason(None))
        self.assertEqual(runner.exit_code,7)

class ResultBoundaryTests(ControllerFixture):
    def payload(self,code=6):
        trace=transport.RunResult(process_stop_triggered=True,process_stop_details=STOP,capture_dir=self.logs/'003-fix',
            stream_diagnostics=[{'kind':'codex_reconnect','event_index':1,'event':RECONNECT}])
        error=execution_error('Synthetic failure',code='codex_stream_error') if code==7 else None
        summary=autobuild.AutoBuildSummary('Synthetic last answer',False,1,0,self.work,self.logs/'pretty.log',
            self.logs/'raw.jsonl',None,run_history=[trace],process_stop_triggered=True,process_stop_details=STOP,
            execution_error=error,terminal_attempt={'phase':'task','index':1,'capture_directory':str(trace.capture_dir)})
        return autobuild.build_summary_document(summary)

    def test_old_and_new_payloads_and_status_invariants(self):  # T101-30
        for code in (6,7):
            value=self.payload(code); validate_result(value)
            for field in ('terminal_attempt','execution_attempts','process_stop_details'):
                value.pop(field)
            validate_result(value)
        for changes in ({'exit_code':0,'completed':True,'status':'complete'},
                        {'process_stop_triggered':False}, {'execution_error':execution_error('Synthetic error')}):
            value={**self.payload(),**changes}
            with self.assertRaises(AutoBuildResultError): validate_result(value)

    def test_additive_fields_are_validated_not_trusted_blindly(self):  # T101-30
        cases=[]
        for name,value in (('process_stop_details',42),('process_stop_details',''),('execution_attempts',{}),
                           ('terminal_attempt',{'phase':'task','index':True,'capture_directory':None}),
                           ('terminal_attempt',{'phase':'task','index':9,'capture_directory':None})):
            cases.append({**self.payload(),name:value})
        for field,value in (('stream_diagnostics',{}),('stream_diagnostics',[{'kind':'codex_reconnect','event_index':True,'event':RECONNECT}]),
                            ('process_stop_triggered',1),('process_stop_details',{}),('capture_directory',10),('stderr_file','x\0y')):
            case=self.payload();case['execution_attempts'][0][field]=value;cases.append(case)
        mismatch=self.payload(); mismatch['terminal_attempt']['capture_directory']='different';cases.append(mismatch)
        for case in cases:
            with self.assertRaises(AutoBuildResultError): validate_result(case)

    def test_worker_exit_mismatch_retains_only_validated_stop(self):  # T101-32
        runner=self.runner(logs_in_workdir=True)
        for invalid,external_stop in ((False,False),(True,False),(True,True)):
            self.stop.unlink(missing_ok=True)
            payload=self.payload()
            if invalid: payload['process_stop_triggered']='forged'
            if external_stop: self.stop.write_text(STOP,encoding='utf-8')
            log=runner.run_dir/f'worker-{invalid}-{external_stop}';log.mkdir()
            options=AutoBuildOptions(summary_json=log/'public.json',logfile=log/'pretty.log',rawlog=log/'raw.jsonl',process_stop_path=self.stop)
            context=AutoBuildContext(budget_directory=self.base/'budget',budget_root_id='1')
            def fake(command,**kwargs):
                request=json.loads(Path(command[-1]).read_text(encoding='utf-8'))
                private=Path(request['options']['summary_json'])
                self.assertFalse(private.is_relative_to(self.work))
                private.write_text(json.dumps(payload),encoding='utf-8')
                Path(options.summary_json).write_text('{"completed":true}',encoding='utf-8')
                return subprocess.CompletedProcess(command,1,b'',b'Synthetic worker stderr')
            with patch.object(run_todos.subprocess,'run',side_effect=fake):
                result=runner._autobuild_python_attempt('Synthetic task',self.work,options,context)
            validated=validate_result(vars(result))
            self.assertEqual(validated['exit_code'],7)
            self.assertEqual(validated['execution_error']['code'],'invalid_autobuild_summary' if invalid else 'autobuild_exit_mismatch')
            self.assertEqual(validated['process_stop_triggered'],not invalid or external_stop)
            if not invalid or external_stop:
                self.assertEqual(validated['process_stop_details'],STOP)
            if invalid:
                self.assertNotIn('terminal_attempt',validated)
            else:
                self.assertEqual(validated['terminal_attempt'],payload['terminal_attempt'])
            self.assertEqual(json.loads(Path(options.summary_json).read_text(encoding='utf-8')),payload)

if __name__ == '__main__':
    unittest.main()
