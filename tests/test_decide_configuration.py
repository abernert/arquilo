# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Configured Decide: inherited provisioning, minimal argv and fail-closed results.

These offline fakes verify ARQUILO, not connectivity to an actual Databricks tenant.
Real upstream CLI metadata/config parsing is covered by the opt-in CI script.
"""
from __future__ import annotations
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo_doctor as doctor
import codex_policy as policy
import codex_transport as transport
import decide
import decision_exec
import decision_archive
from decision_request import DecisionRequest

HELP = '\n'.join(policy.DECISION_REQUIRED_EXEC_FLAGS + ('--model', '--profile'))
SECRET = 'synthetic-secret-MUST-NOT-APPEAR-IN-ARCHIVES'


def request(model=None, effort=None):
    return DecisionRequest(question='2+2?', options=('FOUR', 'FIVE'), context=(),
        run_id='test', task_id='1', phase='test', attempt_id='1', model=model,
        reasoning_effort=effort)


def metadata(**kwargs):
    assert kwargs['probe'] in ('version', 'help'), 'No feature overrides or config dumps allowed'
    return subprocess.CompletedProcess([], 0,
        'codex-cli 0.154.0' if kwargs['probe'] == 'version' else HELP, '')


def fake_run(req, trace, prompt_bytes):
    trace.capture['argv'] = transport.build_command(req)
    trace.capture['launcher'] = {'kind': 'fake-exec'}
    trace.capture['stdin'].update(closed=True, written_bytes=len(prompt_bytes))
    for name in ('stdout', 'stderr'):
        trace.capture[name]['eof'] = True
    trace.turn_completed = True
    trace.process_exit_code = 0
    trace.assistant_messages.append('{"option":"FOUR","explanation":"2+2=4"}')
    if req.output_last_message is not None:
        req.output_last_message.write_text(trace.end_answer, encoding='utf-8')
    return trace


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.base = Path(t.name).resolve()
        self.project = self.base/'project'; self.project.mkdir()
        self.home = self.base/'corporate-config'; self.home.mkdir()
        self.tmp = self.base/'scratch'; self.tmp.mkdir()
        self.env = {'CODEX_HOME': str(self.home), 'DATABRICKS_TOKEN': SECRET,
                    'HTTPS_PROXY': 'http://proxy.example.invalid:8080',
                    'SSL_CERT_FILE': str(self.base/'company-ca.pem'),
                    'CUSTOM_PROVIDER_ENV': 'unchanged'}
        self.settings = decision_exec.DecisionExecSettings(project_root=self.project,
            log_root=self.base/'logs', env=self.env, temp_root=self.tmp, launcher=sys.executable)
        self.transport_request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project,
            env=self.env, raw_log=self.base/'events.jsonl', pretty_log=self.base/'pretty.log',
            output_schema=self.base/'schema.json', output_last_message=self.base/'response.json',
            sandbox='read-only', decision_only=True)

    def call(self, **kwargs):
        with patch.object(transport, 'probe_cli_metadata', side_effect=metadata), \
             patch.object(transport, '_run', side_effect=fake_run) as run:
            call = decide.run_decision(kwargs.pop('request', request()),
                                      settings=kwargs.pop('settings', self.settings), **kwargs)
        return call, run


class ArgumentTests(Base):
    def test_default_argv_is_small_and_exact(self):
        self.assertEqual(transport.build_command(self.transport_request), [
            'codex', 'exec', '--json', '--output-schema', str(self.base/'schema.json'),
            '--output-last-message', str(self.base/'response.json'), '--skip-git-repo-check',
            '--sandbox', 'read-only', '-c', 'approval_policy="never"', '-'])

    def test_no_provider_or_model_default_even_with_provider_environment(self):
        cmd = transport.build_command(self.transport_request)
        self.assertNotIn('--model', cmd)
        self.assertFalse(any(v.startswith(('model_provider=', 'model_reasoning_effort=')) for v in cmd))
        self.assertNotIn(SECRET, repr(cmd))

    def test_no_ignored_user_config_rules_or_experimental_overrides(self):
        cmd = transport.build_command(self.transport_request)
        for flag in ('--ignore-user-config', '--ignore-rules', '--strict-config', '--ephemeral'):
            self.assertNotIn(flag, cmd)
        self.assertFalse(any(v.startswith(('features.', 'mcp_servers', 'shell_environment_policy',
                                          'web_search', 'model_providers.')) for v in cmd))

    def test_explicit_model_does_not_select_provider(self):
        cmd = transport.build_command(replace(self.transport_request, model='my-deployment'))
        self.assertEqual(cmd[cmd.index('--model')+1], 'my-deployment')
        self.assertFalse(any(v.startswith('model_provider=') for v in cmd))

    def test_explicit_provider_does_not_select_model(self):
        cmd = transport.build_command(replace(self.transport_request, model_provider='databricks'))
        self.assertIn('model_provider="databricks"', cmd)
        self.assertNotIn('--model', cmd)

    def test_explicit_profile_does_not_change_other_defaults(self):
        cmd = transport.build_command(replace(self.transport_request, config_profile='corporate'))
        self.assertEqual(cmd[cmd.index('--profile')+1], 'corporate')
        self.assertNotIn('--model', cmd)
        self.assertFalse(any(v.startswith('model_provider=') for v in cmd))

    def test_reasoning_is_only_set_explicitly(self):
        self.assertIn('model_reasoning_effort=low', transport.build_command(
            replace(self.transport_request, reasoning_effort='low')))

    def test_cannot_broaden_decide_sandbox_or_grant_network(self):
        for values in ({'sandbox':'workspace-write'}, {'sandbox':'danger-full-access'},
                       {'network_access':True}, {'extra_args':('--ephemeral',)}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(self.transport_request, **values)

    def test_provider_selector_rejects_urls_and_config_fragments(self):
        for value in ('https://example.invalid', 'db"\nsandbox_mode="danger-full-access"', '', [], SECRET+'\0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(self.transport_request, model_provider=value)

    def test_production_write_policy_unchanged(self):
        req = replace(self.transport_request, decision_only=False, sandbox='workspace-write')
        cmd = transport.build_command(req)
        self.assertIn('sandbox_workspace_write.writable_roots=[]', cmd)
        self.assertIn('sandbox_workspace_write.network_access=false', cmd)
        self.assertIn('--ignore-rules', cmd)


class EnvironmentTests(Base):
    def test_host_environment_is_preserved_as_copy(self):
        env = decision_exec.decision_environment(self.env, project_root=self.project)
        self.assertEqual(env, self.env); self.assertIsNot(env, self.env)
        env['DATABRICKS_TOKEN'] = 'changed'
        self.assertEqual(self.env['DATABRICKS_TOKEN'], SECRET)

    def test_proxy_ca_arbitrary_auth_names_and_case_are_preserved(self):
        source = dict(self.env, https_proxy='http://lowercase.invalid',
                      REQUESTS_CA_BUNDLE='custom.pem', NO_PROXY='localhost',
                      CORPORATE_TOKEN=SECRET, TMP=str(self.tmp))
        if os.name == 'nt':
            source['https_proxy'] = source['HTTPS_PROXY']
        self.assertEqual(decision_exec.decision_environment(source, project_root=self.project), source)

    def test_no_auth_json_or_config_parsing_is_required(self):
        (self.home/'config.toml').write_text('deliberately-not-parsed-by-ARQUILO', encoding='utf-8')
        self.assertFalse((self.home/'auth.json').exists())
        with patch.object(Path, 'read_text', side_effect=AssertionError('No config/auth read')):
            self.assertEqual(decision_exec.decision_environment(self.env, project_root=self.project), self.env)

    def test_custom_codex_home_is_respected(self):
        self.assertEqual(decision_exec.configured_codex_home(self.env), self.home)

    def test_explicit_trusted_home_wins_without_changing_caller(self):
        other = self.base/'explicit'; other.mkdir()
        env = decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=other)
        self.assertEqual(env['CODEX_HOME'], str(other))
        self.assertEqual(self.env['CODEX_HOME'], str(self.home))

    def test_no_codex_home_added_when_not_explicit(self):
        env = {'HOME':str(self.base), 'USERPROFILE':str(self.base), 'DATABRICKS_TOKEN':SECRET}
        self.assertEqual(decision_exec.decision_environment(env, project_root=self.project), env)

    def test_project_cannot_be_used_as_config_home(self):
        with self.assertRaises(ValueError):
            decision_exec.decision_environment(dict(self.env, CODEX_HOME=str(self.project)),
                                               project_root=self.project)

    def test_bad_environment_fails_without_echoing_values(self):
        with self.assertRaises(ValueError) as exc:
            decision_exec.decision_environment({'KEY':SECRET+'\0'}, project_root=self.project)
        self.assertNotIn(SECRET, str(exc.exception))

    def test_missing_default_home_is_not_assumed_bad_chatgpt_login(self):
        env = {'HOME':str(self.base/'other'), 'USERPROFILE':str(self.base/'other')}
        self.assertEqual(decision_exec.decision_environment(env, project_root=self.project), env)

    def test_project_dotenv_is_never_loaded(self):
        (self.project/'.env').write_text('DATABRICKS_TOKEN=untrusted\nCODEX_HOME=untrusted', encoding='utf-8')
        self.assertEqual(decision_exec.decision_environment(self.env, project_root=self.project), self.env)


class ApiAndArchiveTests(Base):
    def test_full_decision_preserves_env_and_does_not_edit_config(self):
        config = self.home/'config.toml'
        text = 'model="my-deployment"\nmodel_provider="databricks"\n'
        config.write_text(text, encoding='utf-8')
        call, run = self.call()
        self.assertTrue(call.result.valid, call.result)
        self.assertEqual(run.call_args.args[0].env, self.env)
        self.assertIsNone(run.call_args.args[0].model)
        self.assertIsNone(run.call_args.args[0].model_provider)
        self.assertEqual(config.read_text(encoding='utf-8'), text)

    def test_custom_config_home_with_default_home_codex_and_nested_temp(self):
        user_home = self.base/'user'
        (user_home/'.codex').mkdir(parents=True)
        nested_temp = user_home/'AppData'/'Local'/'Temp'
        nested_temp.mkdir(parents=True)
        env = dict(self.env, HOME=str(user_home), USERPROFILE=str(user_home))
        call, run = self.call(settings=replace(self.settings, env=env, temp_root=nested_temp))
        self.assertTrue(call.result.valid, call.result)
        self.assertEqual(run.call_args.args[0].env['CODEX_HOME'], str(self.home))

    def test_explicit_selectors_pass_through_and_settings_stay_immutable(self):
        call, run = self.call(request=request('explicit-model', 'low'),
                              model_provider='named-provider', config_profile='named-profile')
        self.assertTrue(call.result.valid)
        req = run.call_args.args[0]
        self.assertEqual((req.model,req.model_provider,req.config_profile,req.reasoning_effort),
                         ('explicit-model','named-provider','named-profile','low'))
        self.assertIsNone(self.settings.model_provider)

    def test_none_keeps_explicit_settings_selectors(self):
        call, run = self.call(settings=replace(self.settings, model_provider='databricks', config_profile='corp'))
        self.assertEqual(run.call_args.args[0].model_provider, 'databricks')
        self.assertEqual(run.call_args.args[0].config_profile, 'corp')

    def test_archive_records_only_explicit_selectors_not_effective_guesses(self):
        call, _ = self.call()
        manifest = json.loads((call.directory/'call.json').read_text())
        self.assertTrue(manifest['archive_complete'])
        self.assertIsNone(manifest['settings']['model'])
        self.assertIsNone(manifest['settings']['model_provider'])
        self.assertEqual(manifest['settings']['sandbox'], 'read-only')
        self.assertEqual(manifest['cli_compatibility']['status'], 'PASS')
        self.assertEqual(manifest['settings']['enforced_cli_arguments'],
                         policy.decision_arguments(network_access=False, config_profile=None, extra_args=()))

    def test_environment_secret_not_archived_by_controller(self):
        call, _ = self.call()
        for f in call.directory.rglob('*'):
            if f.is_file():
                self.assertNotIn(SECRET.encode(), f.read_bytes(), str(f))

    def test_transport_failure_keeps_provider_and_does_not_fallback_or_retry(self):
        def fail(req, trace, data):
            self.assertEqual(req.model_provider, 'databricks')
            from runtime_failure import execution_error
            trace.execution_error = execution_error('Provider refused request.', code='codex_turn_failed')
            return trace
        with patch.object(transport, 'probe_cli_metadata', side_effect=metadata), \
             patch.object(transport, '_run', side_effect=fail) as run:
            call = decide.run_decision(request(), settings=replace(self.settings, max_attempts=2),
                                       model_provider='databricks')
        self.assertFalse(call.result.valid); self.assertEqual(run.call_count, 1)

    def test_format_retry_keeps_same_provider_environment_and_profile(self):
        calls = []
        def first_invalid(req, trace, data):
            calls.append(req)
            fake_run(req, trace, data)
            if len(calls) == 1:
                req.output_last_message.write_text('{}', encoding='utf-8')
            return trace
        with patch.object(transport, 'probe_cli_metadata', side_effect=metadata), \
             patch.object(transport, '_run', side_effect=first_invalid):
            call = decide.run_decision(request(), settings=replace(self.settings,max_attempts=2),
                                       model_provider='databricks', config_profile='corp')
        self.assertTrue(call.result.valid, call.result); self.assertEqual(len(calls), 2)
        for req in calls:
            self.assertEqual(req.env, self.env)
            self.assertEqual((req.model_provider,req.config_profile,req.model), ('databricks','corp',None))

    def test_convenience_choice_selectors(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=metadata), \
             patch.object(transport, '_run', side_effect=fake_run) as run:
            answer, _ = decide.decide('2+2?', ('FOUR','FIVE'), settings=self.settings,
                                      model_provider='databricks', config_profile='corp')
        self.assertEqual(answer, 'FOUR'); self.assertEqual(run.call_args.args[0].config_profile, 'corp')


class CapabilityTests(Base):
    def test_only_help_probe_is_needed_no_features_or_version_pin(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=metadata) as probe:
            report = transport.inspect_decision_cli(launcher=('codex',), cwd=self.project, env=self.env)
        self.assertEqual(report['status'], 'PASS'); self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.kwargs['probe'], 'help')
        self.assertEqual(probe.call_args.kwargs['env'], self.env)

    def test_each_required_flag_missing_fails_closed(self):
        for flag in policy.DECISION_REQUIRED_EXEC_FLAGS:
            help_text = '\n'.join(f for f in policy.DECISION_REQUIRED_EXEC_FLAGS if f != flag)
            with self.subTest(flag=flag), patch.object(transport,'probe_cli_metadata',
                return_value=subprocess.CompletedProcess([],0,help_text,'')):
                r = transport.inspect_decision_cli(launcher=('codex',),cwd=self.project,env=self.env)
                self.assertEqual(r['status'],'FAIL'); self.assertIn(flag,r['detail'])

    def test_optional_model_profile_flags_only_required_when_used(self):
        help_text = '\n'.join(policy.DECISION_REQUIRED_EXEC_FLAGS)
        with patch.object(transport,'probe_cli_metadata',return_value=subprocess.CompletedProcess([],0,help_text,'')):
            for overrides in ({},{'model':'named'},{'config_profile':'corp'}):
                r = transport.inspect_decision_cli(launcher=('codex',),cwd=self.project,env=self.env,**overrides)
                self.assertEqual(r['status'], 'FAIL' if overrides else 'PASS')

    def test_malformed_help_stderr_and_exceptions_do_not_leak_secrets(self):
        for value in (subprocess.CompletedProcess([],1,SECRET,SECRET), OSError(SECRET),
                      subprocess.TimeoutExpired('cmd',1,SECRET), UnicodeError(SECRET)):
            with self.subTest(value=type(value).__name__), patch.object(transport,'probe_cli_metadata') as p:
                if isinstance(value,BaseException): p.side_effect=value
                else: p.return_value=value
                r = transport.inspect_decision_cli(launcher=('codex',),cwd=self.project,env=self.env)
                self.assertEqual(r['status'],'FAIL'); self.assertNotIn(SECRET,json.dumps(r))
                self.assertEqual(p.call_count,1)

    def test_cancellation_before_and_after_probe(self):
        for seq, count in ((['cancel'],0),([None,'cancel'],1)):
            with patch.object(transport,'probe_cli_metadata',side_effect=metadata) as p, \
                 patch('builtins.input',side_effect=AssertionError('No input')):
                cb = unittest.mock.Mock(side_effect=seq)
                r = transport.inspect_decision_cli(launcher=('codex',),cwd=self.project,env=self.env,cancel_requested=cb)
                self.assertTrue(r['interrupted']);self.assertEqual(p.call_count,count)

    def test_keyboard_interrupt_cannot_certify_a_decision(self):
        with patch.object(transport,'probe_cli_metadata',side_effect=KeyboardInterrupt):
            r=transport.inspect_decision_cli(launcher=('codex',),cwd=self.project,env=self.env)
        self.assertTrue(r['interrupted']);self.assertEqual(r['status'],'FAIL')

    def test_actual_transport_checks_help_before_model_and_archives_failure(self):
        with patch.object(transport,'probe_cli_metadata',return_value=subprocess.CompletedProcess([],0,'','')), \
             patch.object(transport,'_run') as run:
            result=transport.execute(self.transport_request)
        run.assert_not_called();self.assertFalse(result.execution.succeeded)
        self.assertEqual(result.execution.failure.code,'codex_decision_cli_failed')
        self.assertTrue((result.trace.capture_dir/'capture.json').exists())

    def test_existing_process_stop_starts_no_probe_or_model(self):
        stop=self.base/'stop';stop.write_text('stop')
        with patch.object(transport,'probe_cli_metadata') as probe,patch.object(transport,'_run') as run:
            result=transport.execute(replace(self.transport_request,process_stop_path=stop))
        probe.assert_not_called();run.assert_not_called()
        self.assertEqual(result.execution.status.value,'cancelled')

    def test_non_decide_transport_policy_and_probes_are_unchanged(self):
        with patch.object(transport,'probe_cli_metadata') as probe, \
             patch.object(transport,'_run',side_effect=fake_run):
            result=transport.execute(replace(self.transport_request,decision_only=False))
        probe.assert_not_called();self.assertTrue(result.execution.succeeded)

    def test_unknown_metadata_command_cannot_run_login_or_dump_config(self):
        for name in ('features','feature_catalog','config','login','doctor'):
            with self.assertRaises(ValueError):transport.metadata_probe_arguments(name)


class DoctorTests(Base):
    def collect(self, **kwargs):
        from codex_launcher import CodexLauncher
        launcher = CodexLauncher('codex',sys.executable,'fake',(sys.executable,))
        with patch.object(doctor,'resolve_launcher',return_value=launcher), \
             patch.object(doctor,'probe_cli_metadata',side_effect=metadata):
            return doctor.collect_report(workdir=self.project,env=self.env,**kwargs)

    def test_metadata_only_has_two_probes_no_config_values_or_model_calls(self):
        r=self.collect()
        self.assertEqual(r['checks_status'],'PASS');self.assertEqual(r['model_calls'],0)
        self.assertEqual([p['name'] for p in r['probes']],['version','help'])
        self.assertNotIn(SECRET,json.dumps(r));self.assertNotIn('decision_features',r)

    def test_doctor_selectors_are_explicit_and_forwarded(self):
        with patch.object(doctor,'_decision_probe',return_value={'status':'PASS','model_calls':1,'detail':'Fake'}) as p:
            r=self.collect(check_decide=True,model_provider='databricks',config_profile='corp',model='deployment')
        self.assertEqual(r['checks_status'],'PASS')
        for k,v in (('model_provider','databricks'),('config_profile','corp'),('model','deployment')):
            self.assertEqual(p.call_args.kwargs[k],v)

    def test_doctor_default_probe_does_not_force_home_or_selectors(self):
        call=SimpleNamespace(directory=None,request=request(),attempts=(),result=SimpleNamespace(valid=True,option='FOUR'))
        with patch.object(decide,'run_decision',return_value=call) as run:
            r=doctor._decision_probe(workspace=self.project,launcher=SimpleNamespace(source=sys.executable),
                env=self.env,model=None,reasoning_effort=None,timeout=10)
        settings=run.call_args.kwargs['settings']
        self.assertIsNone(settings.trusted_codex_home)
        self.assertIsNone(settings.model_provider);self.assertIsNone(settings.config_profile)
        self.assertEqual(settings.env,self.env);self.assertEqual(r['status'],'PASS')

    def test_doctor_override_without_live_opt_in_is_rejected(self):
        for kwargs in ({'model_provider':'databricks'},{'config_profile':'corp'}):
            with self.assertRaises(ValueError):self.collect(**kwargs)

    def test_console_explains_config_inheritance_not_feature_flags(self):
        output=io.StringIO(); report=self.collect()
        with patch.object(doctor,'collect_report',return_value=report),redirect_stdout(output):
            self.assertEqual(doctor.main([]),0)
        self.assertIn('Hostkonfiguration',output.getvalue())
        self.assertNotIn('daemon_auto_start',output.getvalue())


if __name__ == '__main__': unittest.main()
