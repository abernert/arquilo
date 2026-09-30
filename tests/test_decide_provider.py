# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral Decide regressions. All keys/endpoints are synthetic."""
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
from types import SimpleNamespace
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo_doctor as doctor
import codex_policy as policy
import codex_transport as transport
import decide
import decision_archive
import decision_exec
from decision_request import DecisionRequest, DecisionInputError
from runtime_config import resolve_codex_home
from test_codex_features import probes
import test_codex_features


def config(argv):
    return tomllib.loads('\n'.join(argv[i + 1] for i, a in enumerate(argv[:-1]) if a == '-c'))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root/'project'; self.project.mkdir()
        self.home = self.root/'codex-home'; self.home.mkdir()
        self.temp = self.root/'temp'; self.temp.mkdir()
        self.env = {'CODEX_HOME': str(self.home), 'CUSTOM_CORP_KEY': 'synthetic-key',
                    'HTTPS_PROXY': 'http://proxy.invalid:443', 'http_proxy': 'http://proxy.invalid:80',
                    'NO_PROXY': '127.0.0.1', 'SSL_CERT_FILE': str(self.root/'corp-ca.pem'),
                    'REQUESTS_CA_BUNDLE': str(self.root/'corp-ca.pem'),
                    'DATABRICKS_HOST': 'https://gateway.invalid', 'DATABRICKS_TOKEN': 'synthetic-token'}
        self.request = DecisionRequest(question='2+2?', options=('FOUR','FIVE'), context=(),
            run_id='provider-test', task_id='1', phase='test', attempt_id='1')
        self.settings = decision_exec.DecisionExecSettings(project_root=self.project,
            trusted_codex_home=self.home, env=self.env, log_root=self.root/'logs',
            temp_root=self.temp, launcher=sys.executable)

    def command(self, **kwargs):
        request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project, env=self.env,
            raw_log=self.root/'raw.jsonl', pretty_log=self.root/'pretty.log', decision_only=True, **kwargs)
        return transport.build_command(request)

    def test_default_argv_has_no_routing_auth_or_config_suppression(self):
        argv = self.command(); values = config(argv)
        self.assertNotIn('--model', argv)
        for key in ('model', 'model_provider', 'model_providers', 'model_reasoning_effort',
                    'openai_base_url', 'mcp_servers', 'shell_environment_policy'):
            self.assertNotIn(key, values)
        for flag in ('--ignore-user-config', '--ignore-rules', '--strict-config'):
            self.assertNotIn(flag, argv)
        self.assertEqual(argv[argv.index('--sandbox')+1], 'read-only')
        self.assertEqual(values['approval_policy'], 'never')
        self.assertEqual(values['web_search'], 'disabled')
        self.assertEqual(values['notify'], [])

    def test_features_compact_without_changing_restrictions(self):
        argv = self.command(); values = config(argv)
        self.assertEqual(values['features'], policy.DECISION_EXPECTED_FEATURES)
        self.assertEqual(sum(a.startswith('features=') for a in argv), 1)
        self.assertLessEqual(argv.count('-c'), 6)

    def test_model_override_does_not_change_provider(self):
        argv = self.command(model='corporate-deployment')
        self.assertEqual(argv[argv.index('--model')+1], 'corporate-deployment')
        self.assertNotIn('model_provider', config(argv))

    def test_provider_override_does_not_change_model(self):
        argv = self.command(model_provider='databricks-test')
        self.assertNotIn('--model', argv)
        self.assertEqual(config(argv)['model_provider'], 'databricks-test')

    def test_provider_is_one_quoted_toml_string(self):
        provider = 'name"with\\characters'
        self.assertEqual(config(self.command(model_provider=provider))['model_provider'], provider)

    def test_provider_override_and_reasoning_forwarded_only_when_explicit(self):
        argv = self.command(model='my-model', model_provider='company', reasoning_effort='low')
        self.assertEqual(config(argv)['model_reasoning_effort'], 'low')
        self.assertEqual(config(argv)['model_provider'], 'company')

    def test_environment_retains_custom_keys_proxy_certificates_without_mutation(self):
        before = dict(self.env)
        env = decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=self.home)
        for key, value in before.items():
            self.assertEqual(env[key.upper() if os.name == 'nt' else key], value)
        self.assertEqual(self.env, before)

    def test_host_env_has_no_project_dotenv_lookup(self):
        (self.project/'.env').write_text('NEW_KEY=must-not-be-loaded\n')
        env = decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=self.home)
        self.assertNotIn('NEW_KEY', env)

    def test_explicit_trusted_home_wins(self):
        other = self.root/'another'; other.mkdir()
        env = decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=other)
        self.assertEqual(env['CODEX_HOME'], str(other))
        self.assertEqual(self.env['CODEX_HOME'], str(self.home))

    def test_config_home_inside_workspace_rejected(self):
        home = self.project/'.codex'; home.mkdir()
        with self.assertRaises(policy.CodexPolicyError):
            decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=home)

    def test_config_home_can_work_without_auth_json(self):
        self.assertFalse((self.home/'auth.json').exists())
        self.assertEqual(resolve_codex_home(environ=self.env), self.home)
        env = decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=self.home)
        self.assertIn('CUSTOM_CORP_KEY', env)

    def test_missing_config_home_does_not_fallback(self):
        with self.assertRaises(policy.CodexPolicyError):
            decision_exec.decision_environment(self.env, project_root=self.project, trusted_codex_home=self.root/'missing')

    def test_relative_and_invalid_home_rejected_without_disclosing_value(self):
        for value in ('relative', 'secret\0value', []):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                resolve_codex_home(environ={'CODEX_HOME': value})

    def test_settings_omitted_honors_codex_home(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(decide, 'execute_decision') as call:
            decide.run_decision(self.request)
        self.assertEqual(call.call_args.kwargs['settings'].trusted_codex_home, self.home)
        self.assertIsNone(call.call_args.args[0].model)
        self.assertIsNone(call.call_args.args[0].model_provider)

    def test_public_choice_and_boolean_api_forward_provider(self):
        for name, args, option in [('decide', ('2+2?', ['FOUR','FIVE']), 'FOUR'),
                                   ('decide_bool', ('Is 2+2=4?',), 'true')]:
            with self.subTest(name=name), patch.object(decide, '_decide_with_options', return_value=(option,'ok')) as call:
                getattr(decide, name)(*args, model='deployment', model_provider='corp', settings=self.settings)
            self.assertEqual(call.call_args.args[0].model, 'deployment')
            self.assertEqual(call.call_args.args[0].model_provider, 'corp')

    def test_request_provider_conflicts_fail_before_execution(self):
        with patch.object(decide, 'execute_decision') as execute:
            with self.assertRaises(DecisionInputError):
                decide.decide(self.request.question, self.request.options, request=self.request,
                              model_provider='different', settings=self.settings)
        execute.assert_not_called()

    def test_doctor_cli_provider_reaches_report(self):
        with patch.object(doctor, 'collect_report', return_value={'checks_status':'PASS'}) as call, redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(['--check-decide','--model-provider','corp','--json']), 0)
        self.assertEqual(call.call_args.kwargs['model_provider'], 'corp')
        self.assertIsNone(call.call_args.kwargs['model'])

    def test_doctor_probe_preserves_provider_config_home(self):
        outcome = SimpleNamespace(directory=None, request=self.request, attempts=(),
                                  result=SimpleNamespace(valid=True,option='FOUR'))
        with patch.object(decide, 'run_decision', return_value=outcome) as call:
            report = doctor._decision_probe(workspace=self.project, launcher=SimpleNamespace(source=sys.executable),
                env=self.env, model=None, model_provider=None, reasoning_effort=None, timeout=5)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(call.call_args.kwargs['settings'].trusted_codex_home, self.home)
        self.assertEqual(call.call_args.kwargs['settings'].env['CUSTOM_CORP_KEY'], 'synthetic-key')

    def test_full_decide_preserves_configuration_and_no_env_dumps(self):
        configfile = self.home/'config.toml'
        contents = 'model="corp-deployment"\nmodel_provider="company-gateway"\n'
        configfile.write_text(contents, encoding='utf-8')
        before = configfile.read_bytes()
        def fake(request, trace, prompt_bytes, **kwargs):
            self.assertIsNone(request.model); self.assertIsNone(request.model_provider)
            self.assertEqual(request.env['CUSTOM_CORP_KEY'], 'synthetic-key')
            self.assertEqual(Path(request.env['CODEX_HOME']), self.home)
            return test_codex_features.TransportTests.fake_run(request, trace, prompt_bytes, **kwargs)
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()), patch.object(transport, '_run', side_effect=fake):
            result = decide.run_decision(self.request, settings=self.settings)
        self.assertTrue(result.result.valid, result.result)
        self.assertEqual(configfile.read_bytes(), before)
        manifest = json.loads((result.directory/'call.json').read_text())
        self.assertEqual(manifest['settings']['provider_selection'], 'codex_config')
        self.assertIsNone(manifest['settings']['model'])
        for p in (self.root/'logs').rglob('*'):
            if p.is_file():
                self.assertNotIn(b'synthetic-key', p.read_bytes())
                self.assertNotIn(b'synthetic-token', p.read_bytes())

    def test_failed_provider_has_no_alternate_model_or_provider_retry(self):
        def fail(request, trace, prompt_bytes, **kwargs):
            trace.execution_error = {'code':'codex_turn_failed','phase':'test', 'message':'Provider rejected request'}
            trace.process_exit_code = 1
            return trace
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()), patch.object(transport, '_run', side_effect=fail) as run:
            result = decide.run_decision(self.request, settings=self.settings, max_attempts=2)
        self.assertFalse(result.result.valid)
        self.assertEqual(run.call_count, 1)
        self.assertIsNone(run.call_args.args[0].model_provider)

    def test_mcp_raw_values_not_logged_or_reused(self):
        request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project, env=self.env,
            raw_log=self.root/'raw.jsonl', pretty_log=self.root/'pretty.log', decision_only=True)
        rows = [{'name':'corp-test', 'enabled':True, 'transport':{'env':{'KEY':'secret-mcp-test'}}}]
        responses = [subprocess.CompletedProcess([],0,json.dumps(rows),''),
                     subprocess.CompletedProcess([],0,json.dumps([dict(rows[0],enabled=False)]),'')]
        with patch.object(transport, 'probe_cli_metadata', side_effect=responses) as call:
            names = transport.inspect_decision_mcp(request=request, decision_features=tuple(policy.DECISION_EXPECTED_FEATURES))
        self.assertEqual(names, ('corp-test',))
        argv = transport.build_command(replace(request,disabled_mcp_servers=names))
        self.assertEqual(config(argv)['mcp_servers'], {'corp-test':{'enabled':False}})
        self.assertNotIn('secret-mcp-test', repr(argv))
        self.assertEqual(call.call_count, 2)

    def test_mcp_ambiguity_or_failed_disable_stops(self):
        request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project, env=self.env,
            raw_log=self.root/'raw.jsonl', pretty_log=self.root/'pretty.log', decision_only=True)
        for raw in ('secret-value', '{}', '[{"name":"a","name":"b","enabled":true}]',
                    '[{"name":"a","enabled":"false"}]', '[{"name":"a","enabled":true}]'):
            with self.subTest(raw=raw), patch.object(transport,'probe_cli_metadata',return_value=subprocess.CompletedProcess([],0,raw,'')):
                with self.assertRaises(policy.CodexPolicyError) as error:
                    transport.inspect_decision_mcp(request=request, decision_features=tuple(policy.DECISION_EXPECTED_FEATURES))
                self.assertNotIn('secret-value', str(error.exception))

    def test_mcp_failure_exceptions_do_not_echo_secret_diagnostics(self):
        request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project, env=self.env,
            raw_log=self.root/'raw.jsonl', pretty_log=self.root/'pretty.log', decision_only=True)
        for exc in (OSError('secret-value'), subprocess.TimeoutExpired('secret-value',10), UnicodeError('secret-value')):
            with self.subTest(exc=type(exc).__name__), patch.object(transport,'probe_cli_metadata',side_effect=exc):
                with self.assertRaises(policy.CodexPolicyError) as error:
                    transport.inspect_decision_mcp(request=request, decision_features=tuple(policy.DECISION_EXPECTED_FEATURES))
                self.assertNotIn('secret-value', str(error.exception))

    def test_no_mcp_uses_one_inspection(self):
        request = transport.CodexExecRequest(prompt='2+2?', cwd=self.project, env=self.env,
            raw_log=self.root/'raw.jsonl', pretty_log=self.root/'pretty.log', decision_only=True)
        with patch.object(transport,'probe_cli_metadata',return_value=subprocess.CompletedProcess([],0,'[]','')) as call:
            self.assertEqual(transport.inspect_decision_mcp(request=request, decision_features=tuple(policy.DECISION_EXPECTED_FEATURES)), ())
        self.assertEqual(call.call_count,1)

if __name__ == '__main__':
    unittest.main()
