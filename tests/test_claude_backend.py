# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline backend regressions. The fake executable is NOT native Claude Code.

Real subprocesses test orchestration, protocol, pipes and cancellation, not a
model or native sandbox. Codex starts/config reads are poisoned in Claude tests.
"""
from __future__ import annotations
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import agent_backend
import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload, decode_call
import claude_launcher
import claude_transport as ct
import codex_transport
import codex_launcher
import decision_exec
from decision_exec import DecisionExecSettings, execute_decision
from decision_request import DecisionRequest
import decide
import run_todos
import arquilo_doctor
from agent_types import RunResult, TransportTimeouts
from runtime_contracts import ExecutionStatus


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='arquilo-claude-test-')
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name).resolve()
        self.work=self.base/'workspace with spaces';self.work.mkdir()
        self.logs=self.base/'logs';self.logs.mkdir()
        self.audit=self.base/'audit.jsonl'
        self.script=self.base/'claude'
        self.script.write_text('#!'+sys.executable+'\n'+(ROOT/'tests/fixtures/claude_cli_fixture.py').read_text(),encoding='utf-8')
        self.script.chmod(0o700)
        self.poison=self.base/'codex'
        self.poison.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nPath('+repr(str(self.base/'CODEX_WAS_STARTED'))+').write_text(\"forbidden\")\nraise SystemExit(101)\n')
        self.poison.chmod(0o700)
        self.env=dict(os.environ,PATH=str(self.base)+os.pathsep+os.environ.get('PATH',''),ARQUILO_CLAUDE_CODE_COMMAND=str(self.script),CLAUDE_FIXTURE_AUDIT=str(self.audit),
                      CLAUDE_FIXTURE_MODE='success',ARQUILO_CODEX_MODEL='DO_NOT_INHERIT_CODEX_MODEL',
                      ARQUILO_CODEX_REASONING_EFFORT='minimal',ARQUILO_DECISION_MODEL='DO_NOT_INHERIT_DECISION_MODEL')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,self.env,clear=True))
        # This must catch *any* accidentally reused Codex process or auth path.
        for module,name in ((codex_transport,'_start_process'),(codex_transport,'execute'),
                            (codex_transport,'probe_version'),(codex_launcher,'resolve_launcher'),
                            (decision_exec,'configured_codex_home'),(autobuild,'run_codex_exec_json')):
            self.stack.enter_context(patch.object(module,name,side_effect=AssertionError('Codex is forbidden in this test')))
        if os.name=='nt':
            # A .py file is not a Windows executable. Launch Python through the
            # same service-neutral owned process boundary; no .cmd / shell=True.
            launcher=claude_launcher.ClaudeCodeLauncher(str(self.script),str(self.script),'test-python',
                                                     (sys.executable,str(self.script)))
            self.stack.enter_context(patch.object(ct,'resolve_launcher',return_value=launcher))
            import claude_decision
            self.stack.enter_context(patch.object(claude_decision,'resolve_launcher',return_value=launcher))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))

    def request(self,**kwargs):
        return ct.ClaudeRequest(prompt='Write an empty hello.txt. Prüfung.',cwd=self.work,env=self.env,
                raw_log=self.logs/'raw.jsonl',pretty_log=self.logs/'pretty.log',
                timeouts=TransportTimeouts(total=10,stall=5,kill_grace=.1,post_turn_grace=2),**kwargs)

    def rows(self):
        self.assertFalse((self.base/'CODEX_WAS_STARTED').exists(),'A subprocess launched Codex')
        return [json.loads(s) for s in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def mode(self,mode):
        self.env['CLAUDE_FIXTURE_MODE']=mode
        os.environ['CLAUDE_FIXTURE_MODE']=mode

    def settings(self,**kw):
        return DecisionExecSettings(project_root=self.work,env=self.env,log_root=self.logs,
                    backend='claude-code',temp_root=self.base,**kw)

    def decision(self,**kw):
        req=DecisionRequest(question='What is 2 + 2?',options=('FOUR','FIVE'),context=(),
                run_id='test',task_id='one',phase='decision',attempt_id='1',**kw)
        return execute_decision(req,settings=self.settings())


class SelectionTests(Fixture):
    def test_default_and_serialized_worker(self):
        self.assertEqual(AutoBuildOptions().backend,'codex')
        call=call_payload(options=AutoBuildOptions(backend='claude-code'),context=AutoBuildContext(),
                          workdir=self.work,task='Create file')
        self.assertEqual(decode_call(json.loads(json.dumps(call)))['options'].backend,'claude-code')

    def test_unsupported_future_and_codex_specific_options(self):
        for value in ('open-code','opencode','claude',None,42):
            with self.subTest(value=value),self.assertRaises(ValueError):
                AutoBuildOptions(backend=value)
        for kwargs in ({'config_profile':'personal'},{'extra_arg':('-c','foo=true')}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                AutoBuildOptions(backend='claude-code',**kwargs)
        for kwargs in ({'model_provider':'azure'},{'trusted_codex_home':self.base/'codex'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                self.settings(**kwargs)
        self.assertFalse(self.rows())

    def test_model_effort_inherit_only_selected_backend(self):
        self.assertIsNone(agent_backend.resolve_model(None,backend='claude-code',environ=self.env))
        self.assertIsNone(agent_backend.resolve_effort(None,backend='claude-code',environ=self.env))
        env={**self.env,'ARQUILO_CLAUDE_CODE_MODEL':'native-model','ARQUILO_CLAUDE_CODE_REASONING_EFFORT':'high'}
        self.assertEqual(agent_backend.resolve_model(None,backend='claude-code',environ=env),'native-model')
        self.assertEqual(agent_backend.resolve_model('explicit',backend='claude-code',environ=env),'explicit')
        with self.assertRaises(ValueError): agent_backend.resolve_effort('minimal',backend='claude-code')

    def test_codex_command_never_even_probed(self):
        for executable in ('codex','codex.exe','/example/codex','C:\\tools\\codex.exe'):
            with self.subTest(executable=executable),self.assertRaises(claude_launcher.ClaudeCodeLauncherError):
                claude_launcher.resolve_launcher(executable,cwd=self.work,env=self.env)
        with patch.object(ct, 'resolve_launcher', claude_launcher.resolve_launcher), \
                patch.object(subprocess,'Popen',side_effect=AssertionError('No process allowed')):
            report=ct.probe_cli(cwd=self.work,env={**self.env,'ARQUILO_CLAUDE_CODE_COMMAND':'codex'})
        self.assertEqual(report['status'],'FAIL')

    def test_mismatched_decision_backend_rejected_before_run(self):
        with self.assertRaises(ValueError):
            autobuild.start(task='Test',workdir=self.work,options=AutoBuildOptions(backend='claude-code'),
                decision_settings=DecisionExecSettings(project_root=self.work,env=self.env,log_root=self.logs))
        self.assertFalse(self.rows())

    def test_command_role_boundaries(self):
        for request,expected in ((self.request(),set(ct.WRITE_TOOLS)),
            (self.request(sandbox='read-only'),set(ct.READ_TOOLS)),
            (self.request(sandbox='read-only',decision_only=True),set())):
            command=ct.build_command(request)
            self.assertEqual(set(command[command.index('--tools')+1].split(','))-{''},expected)
            self.assertEqual(command[command.index('--permission-mode')+1],'dontAsk')
            self.assertNotIn('--dangerously-skip-permissions',command)
            self.assertNotIn('--fallback-model',command)
            self.assertIn('--safe-mode',command)
            self.assertEqual(command[command.index('--setting-sources')+1],'user')
        settings=ct.policy_settings(self.request())['sandbox']
        self.assertTrue(settings['failIfUnavailable'])
        self.assertFalse(settings['allowUnsandboxedCommands'])
        self.assertEqual(settings['network']['deniedDomains'],['*'])


class ProtocolTests(Fixture):
    def init(self,request,**kwargs):
        return dict(type='system',subtype='init',session_id=request.session_id,
                    tools=list(ct.selected_tools(request)),mcp_servers=[],permissionMode='dontAsk',**kwargs)

    def test_unverified_or_wrong_tools_are_not_accepted(self):
        request=self.request(sandbox='read-only',decision_only=True)
        for field,val in (('tools',['Bash']),('mcp_servers',[{'name':'x'}]),
                          ('permissionMode','bypassPermissions'),('plugins',[{'name':'x'}]),('session_id','wrong')):
            event=self.init(request);event[field]=val
            with self.subTest(field=field),self.assertRaises(ValueError):
                ct.ClaudeProtocol(request).accept(json.dumps(event),RunResult())

    def test_duplicate_init_and_post_terminal_fail(self):
        request=self.request();trace=RunResult();p=ct.ClaudeProtocol(request)
        p.accept(json.dumps(self.init(request)),trace)
        with self.assertRaises(ValueError):p.accept(json.dumps(self.init(request)),trace)
        event=dict(type='result',session_id=request.session_id,subtype='success',is_error=False,result='done')
        self.assertTrue(p.accept(json.dumps(event),trace))
        with self.assertRaises(ValueError):p.accept(json.dumps(event),trace)

    def test_only_schema_output_operation_allowed_for_decide(self):
        schema=self.logs/'schema.json';schema.write_text('{}')
        request=self.request(sandbox='read-only',decision_only=True,output_schema=schema)
        p=ct.ClaudeProtocol(request);trace=RunResult()
        init=self.init(request);init['tools']=['StructuredOutput'];p.accept(json.dumps(init),trace)
        p.accept(json.dumps(dict(type='assistant',session_id=request.session_id,message={'content':[
            {'type':'tool_use','name':'StructuredOutput','input':{'option':'A'}}]})),trace)
        with self.assertRaises(ValueError):p.accept(json.dumps(dict(type='assistant',session_id=request.session_id,
            message={'content':[{'type':'tool_use','name':'Read','input':{'file_path':'secret'}}]})),trace)


class TransportTests(Fixture):
    def test_success_captures_raw_bytes_and_exclusive_answer(self):
        request=self.request(output_last_message=self.logs/'answer.json')
        out=ct.execute(request)
        self.assertTrue(out.execution.succeeded,str(out.execution))
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(out.trace.capture['stdin']['written_bytes'],len(request.prompt.encode()))
        for name in ('stdin','stdout','stderr'):
            self.assertTrue(out.trace.capture[name]['complete'],out.trace.capture)
        self.assertEqual(request.output_last_message.read_text(),out.execution.answer)
        self.assertEqual(out.trace.capture['backend'],'claude-code')
        self.assertNotIn('--model',self.rows()[0]['argv'])
        self.assertNotIn('--effort',self.rows()[0]['argv'])
        with self.assertRaises(ValueError):ct.execute(request)

    def test_native_like_failures_never_succeed(self):
        for mode in ('foreign','invalid_json','duplicate_key','tool_violation','missing_result','bad_utf8',
                     'nonzero','result_error','truncated','denied','after_result'):
            self.mode(mode)
            with self.subTest(mode=mode):
                out=ct.execute(self.request())
                self.assertEqual(out.execution.status,ExecutionStatus.FAILED,str(out.execution))
                self.assertIsNotNone(out.execution.failure)
        self.assertEqual(len(self.rows()),11)

    def test_oversize_unterminated_stdout_is_bounded_failure(self):
        self.mode('long_line')
        out=ct.execute(self.request())
        self.assertEqual(out.execution.status,ExecutionStatus.FAILED)

    def test_missing_binary_and_old_cli_no_model_no_fallback(self):
        for env in ({**self.env,'ARQUILO_CLAUDE_CODE_COMMAND':str(self.base/'missing')},
                    {**self.env,'CLAUDE_FIXTURE_MODE':'old_cli'}):
            if os.name=='nt' and 'missing' in env['ARQUILO_CLAUDE_CODE_COMMAND']:
                continue  # Windows executable resolution is intentionally replaced by the fixture.
            out=ct.execute(replace(self.request(),env=env))
            self.assertEqual(out.execution.status,ExecutionStatus.FAILED)
        self.assertEqual(self.rows(),[])

    def test_cancel_before_model_and_during_running_process(self):
        out=ct.execute(self.request(cancel_requested=lambda:'owner stop'))
        self.assertEqual(out.execution.status,ExecutionStatus.CANCELLED)
        self.assertEqual(self.rows(),[])
        self.mode('hang')
        out=ct.execute(self.request(cancel_requested=lambda:'owner stop' if self.audit.exists() else None))
        self.assertEqual(out.execution.status,ExecutionStatus.CANCELLED,str(out.execution))
        self.assertEqual(len(self.rows()),1)
        self.assertNotEqual(out.execution.process_exit_code,None)

    def test_timeouts_and_hanging_terminal_are_failures(self):
        for mode in ('hang','terminal_hang'):
            self.mode(mode)
            with self.subTest(mode=mode):
                out=ct.execute(replace(self.request(),timeouts=TransportTimeouts(total=.5,stall=.5,
                                                                                 post_turn_grace=.1,kill_grace=.1)))
                self.assertEqual(out.execution.status,ExecutionStatus.FAILED,str(out.execution))

    def test_archive_failure_prevents_success(self):
        with patch.object(ct,'atomic_write_text',side_effect=OSError('fixture disk full')):
            out=ct.execute(self.request())
        self.assertEqual(out.execution.status,ExecutionStatus.FAILED)
        self.assertEqual(out.execution.failure.code,'claude_archive_failed')


class DecisionTests(Fixture):
    def test_real_subprocess_decide_uses_claude_and_no_tools(self):
        call=self.decision()
        self.assertTrue(call.result.valid,str(call.result))
        self.assertEqual(call.result.option,'FOUR')
        self.assertTrue(call.attempts[0].archive_complete,str(call.attempts[0].archive_error))
        self.assertEqual(self.rows()[0]['tools'],[])
        self.assertNotIn('--model',self.rows()[0]['argv'])
        self.assertFalse(Path(self.rows()[0]['cwd']).is_relative_to(self.work))
        manifest=json.loads((call.directory/'call.json').read_text())
        self.assertEqual(manifest['settings']['backend'],'claude-code')
        call.cleanup_workdirs()

    def test_wrong_option_is_invalid_not_a_completed_decision(self):
        self.mode('wrong_option');call=self.decision()
        self.assertFalse(call.result.valid)
        self.assertEqual(call.result.failure.code,'decision_invalid_response')
        self.assertEqual(len(self.rows()),1)

    def test_direct_default_launcher_and_explicit_model(self):
        call=self.decision(model='selected-claude')
        self.assertTrue(call.result.valid,str(call.result))
        args=self.rows()[0]['argv'];self.assertEqual(args[args.index('--model')+1],'selected-claude')

    def test_doctor_checks_and_optional_decide_never_call_codex(self):
        report=arquilo_doctor.collect_report(workdir=self.work,env=self.env,backend='claude-code')
        self.assertEqual(report['status'],'QUALIFIED',str(report))
        self.assertEqual(self.rows(),[])
        report=arquilo_doctor.collect_report(workdir=self.work,env=self.env,backend='claude-code',check_decide=True)
        self.assertEqual(report['status'],'QUALIFIED',str(report))
        self.assertEqual(report['model_calls'],1)


class OrchestrationTests(Fixture):
    def run_task(self,**kw):
        return autobuild.start(task='Create an empty hello.txt.',workdir=self.work,
            options=AutoBuildOptions(backend='claude-code',max_steps=3,max_calls=8,auto_continue=True,**kw))

    def test_production_review_completed_and_separate_sessions(self):
        summary=self.run_task()
        self.assertTrue(summary.completed,str(summary.execution_error))
        self.assertEqual((summary.auftrag_runs,summary.review_runs),(1,1))
        self.assertEqual(summary.backend,'claude-code')
        rows=self.rows();self.assertEqual(len(rows),2)
        self.assertIn('Write',rows[0]['tools']);self.assertEqual(set(rows[1]['tools']),set(ct.READ_TOOLS))
        self.assertNotEqual(rows[0]['session_id'],rows[1]['session_id'])
        self.assertFalse((self.work/'.codex_runs').exists())
        self.assertTrue((self.work/'hello.txt').exists())
        for row in rows:self.assertNotIn('--model',row['argv'])

    def test_fix_cycle_uses_claude_in_each_phase(self):
        self.mode('fix_cycle');summary=self.run_task()
        self.assertTrue(summary.completed,str(summary.execution_error))
        self.assertEqual(len(self.rows()),4)
        self.assertEqual([('Write' in row['tools']) for row in self.rows()],[True,False,True,False])

    def test_missing_review_never_completes(self):
        self.mode('review_missing_result');summary=self.run_task()
        self.assertFalse(summary.completed)
        self.assertIsNotNone(summary.execution_error)
        self.assertEqual(len(self.rows()),2)

    def test_plaintext_review_routes_decide_to_claude_without_codex_model(self):
        self.mode('legacy_review');summary=self.run_task()
        self.assertTrue(summary.completed,str(summary.execution_error))
        rows=self.rows();self.assertEqual(len(rows),3)
        self.assertEqual(rows[-1]['tools'],[])
        self.assertNotIn('--model',rows[-1]['argv'])
        self.assertEqual(summary.decision['source'],'claude_code')

    @unittest.skipIf(os.name=='nt','Subprocess shell fixture is POSIX; Windows protocol/process tests above use Python')
    def test_standalone_autobuild_worker_payload_without_codex(self):
        payload=call_payload(options=AutoBuildOptions(backend='claude-code',max_calls=4),
                             context=AutoBuildContext(),task='Create empty hello.txt.',workdir=self.work)
        file=self.base/'request.json';file.write_text(json.dumps(payload))
        out=subprocess.run([sys.executable,'-B',str(ROOT/'autobuild.py'),'--request-json',str(file)],
                           cwd=self.work,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(out.returncode,0,out.stderr.decode()+out.stdout.decode())
        self.assertEqual(len(self.rows()),2)

    @unittest.skipIf(os.name=='nt','End-to-end executable fixture is POSIX')
    def test_tasklist_cli_done_and_review_failure_not_done(self):
        todo=self.work/'tasks.md';todo.write_text('1. ***TASK***: Create an empty hello.txt.\n')
        args=[sys.executable,'-B',str(ROOT/'arquilo.py'),'tasklist','run','--backend','claude-code',
              '--workdir',str(self.work),'--todo-file',str(todo),'--state-dir',str(self.base/'state'),
              '--process-stop-policy','controller-only','--max-calls','6']
        out=subprocess.run(args,cwd=self.work,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(out.returncode,0,out.stderr.decode()+out.stdout.decode())
        self.assertIn('***DONE***',todo.read_text())
        self.assertEqual(len(self.rows()),2)
        other=self.base/'other';other.mkdir();failed=other/'tasks.md';failed.write_text('1. ***TASK***: Create empty hello.txt.\n')
        args=[v.replace(str(self.work),str(other)) for v in args]
        self.mode('review_missing_result')
        out=subprocess.run(args,cwd=other,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertNotEqual(out.returncode,0)
        self.assertNotIn('***DONE***',failed.read_text())

    @unittest.skipIf(os.name=='nt','End-to-end executable fixture is POSIX')
    def test_dry_run_without_any_cli(self):
        todo=self.work/'tasks.md';todo.write_text('1. ***TASK***: Create an empty hello.txt.\n')
        env={**self.env,'ARQUILO_CLAUDE_CODE_COMMAND':str(self.base/'missing')}
        out=subprocess.run([sys.executable,'-B',str(ROOT/'arquilo.py'),'tasklist','run','--backend','claude-code',
            '--workdir',str(self.work),'--todo-file',str(todo),'--dry-run','--dry-run-file',str(self.base/'dry-run.md'),'--state-dir',str(self.base/'state')],
            env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(out.returncode,0,out.stderr.decode())
        self.assertEqual(self.rows(),[])


if __name__=='__main__':unittest.main()
