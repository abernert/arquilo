# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline capability negotiation regressions; no installed Codex is needed."""
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
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo_doctor as doctor
import codex_policy as policy
import codex_transport as transport
import decision_exec
from decision_request import DecisionRequest


def config_values(values):
    return tomllib.loads("\n".join(values))


def argv_config(argv):
    return config_values([argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '-c'])


def catalog(*, daemon=False, effective=False):
    data = {name: (value if effective else not value)
            for name, value in policy.DECISION_EXPECTED_FEATURES.items()}
    if not daemon:
        data.pop('daemon_auto_start')
    # Do not derive new configuration overrides from unrelated CLI keys.
    data['future_display_feature'] = True
    return data


def table(data):
    return ''.join(f'{name}\tunder development\t{str(value).lower()}\n' for name, value in data.items())


def probes(*, daemon=False, effective=None, raw=None):
    def probe(**kwargs):
        name = kwargs['probe']
        if name == 'feature_catalog':
            assert kwargs.get('decision_features') is None
            return subprocess.CompletedProcess([], 0, raw if raw is not None else table(catalog(daemon=daemon)), '')
        if name == 'features':
            selected = kwargs['decision_features']
            assert ('daemon_auto_start' in selected) == daemon
            return subprocess.CompletedProcess([], 0, effective if effective is not None else table(catalog(daemon=daemon, effective=True)), '')
        if name == 'version':
            return subprocess.CompletedProcess([], 0, 'codex-cli 0.154.0\n', '')
        if name == 'mcp_catalog':
            return subprocess.CompletedProcess([], 0, '[]', '')
        raise AssertionError(name)
    return probe


class PolicyTests(unittest.TestCase):
    def test_old_catalog_omits_only_optional_override(self):
        selected = policy.select_decision_features(catalog())
        config = policy.decision_config_for_features(selected)
        self.assertNotIn('daemon_auto_start', config_values(config)['features'])
        self.assertFalse(config_values(config)['features']['shell_tool'])
        self.assertTrue(config_values(config)['features']['skip_host_skill_discovery'])

    def test_new_catalog_disables_default_enabled_daemon(self):
        self.assertTrue(catalog(daemon=True)['daemon_auto_start'])
        config = policy.decision_config_for_features(policy.select_decision_features(catalog(daemon=True)))
        self.assertFalse(config_values(config)['features']['daemon_auto_start'])
        self.assertFalse(any('future_display_feature' in value for value in config))

    def test_every_other_missing_control_fails(self):
        for name in policy.DECISION_EXPECTED_FEATURES:
            if name in policy.DECISION_OPTIONAL_FEATURES:
                continue
            with self.subTest(name=name):
                data = catalog(daemon=True); data.pop(name)
                with self.assertRaisesRegex(policy.CodexPolicyError, name):
                    policy.select_decision_features(data)

    def test_invalid_catalogs_do_not_echo_cli_text(self):
        for value in ('', '  \n', 'private-secret', 'shell_tool stable invalid-secret',
                      'shell_tool true', 'shell_tool stable TRUE',
                      'shell_tool stable false\nshell_tool stable false',
                      'shell_tool stable false\nshell_tool stable true',
                      '\x1b[1mshell_tool stable false'):
            with self.subTest(value=value), self.assertRaises(policy.CodexPolicyError) as error:
                policy.parse_feature_catalog(value)
            self.assertNotIn('private-secret', str(error.exception))
            self.assertNotIn('invalid-secret', str(error.exception))

    def test_spaces_crlf_and_multitoken_stage(self):
        self.assertEqual(policy.parse_feature_catalog(' \r\n shell_tool\tunder development\tfalse\r\n'), {'shell_tool': False})

    def test_invalid_selections_fail(self):
        valid = policy.select_decision_features(catalog())
        for names in ((), ('daemon_auto_start',), 'shell_tool', (*valid, valid[0]), (*valid, 'arbitrary_config')):
            with self.subTest(names=names), self.assertRaises(policy.CodexPolicyError):
                policy.decision_config_for_features(names)

    def test_discovery_is_cost_free_and_has_no_feature_overrides(self):
        self.assertEqual(transport.metadata_probe_arguments('feature_catalog'), ['features', 'list'])
        with self.assertRaises(ValueError):
            transport.metadata_probe_arguments('exec')

    def test_old_effective_probe_and_exec_keep_all_other_restrictions(self):
        selected = policy.select_decision_features(catalog())
        args = policy.decision_arguments(network_access=False, config_profile=None, extra_args=(), features=selected)
        self.assertIn('--ephemeral', args)
        self.assertNotIn('--strict-config', args)
        self.assertNotIn('--ignore-user-config', args)
        self.assertFalse(argv_config(args)['features']['shell_tool'])
        self.assertNotIn('daemon_auto_start', argv_config(args)['features'])
        args = transport.metadata_probe_arguments('features', decision_features=selected)
        self.assertEqual(args[-2:], ['features', 'list'])
        self.assertNotIn('daemon_auto_start', argv_config(args)['features'])

    def test_network_profile_and_extra_argument_rejections_unchanged(self):
        for kwargs in ({'network_access': True}, {'config_profile': 'custom'}, {'extra_args': ('--search',)}):
            values = {'network_access': False, 'config_profile': None, 'extra_args': ()}
            values.update(kwargs)
            with self.assertRaises(policy.CodexPolicyError):
                policy.decision_arguments(**values, features=policy.select_decision_features(catalog()))


class NegotiationTests(unittest.TestCase):
    def inspect(self, **kwargs):
        return transport.inspect_decision_features(launcher=('codex',), cwd=ROOT, env={}, **kwargs)

    def test_old_and_new_catalogs(self):
        for daemon in (False, True):
            with self.subTest(daemon=daemon), patch.object(transport, 'probe_cli_metadata', side_effect=probes(daemon=daemon)) as run:
                report = self.inspect()
            self.assertEqual(report['status'], 'PASS', report)
            self.assertEqual(len(run.call_args_list), 2)
            self.assertEqual(report['unavailable_optional'], [] if daemon else ['daemon_auto_start'])
            expected = 'verified' if daemon else 'unavailable_optional'
            self.assertEqual(report['features']['daemon_auto_start']['status'], expected)

    def test_ignored_override_is_not_accepted(self):
        data = catalog(daemon=True, effective=True); data['daemon_auto_start'] = True
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(daemon=True, effective=table(data))):
            report = self.inspect()
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['features']['daemon_auto_start']['status'], 'wrong_value')

    def test_missing_effective_required_feature_is_not_accepted(self):
        data = catalog(effective=True); data.pop('shell_tool')
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(effective=table(data))):
            report = self.inspect()
        self.assertEqual(report['features']['shell_tool']['status'], 'not_confirmed')
        self.assertEqual(report['status'], 'FAIL')

    def test_optional_feature_appearing_between_probes_fails(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(effective=table(catalog(daemon=True, effective=True)))):
            report = self.inspect()
        self.assertEqual(report['features']['daemon_auto_start']['status'], 'catalog_changed')
        self.assertEqual(report['status'], 'FAIL')

    def test_missing_required_does_not_run_effective_probe(self):
        data = catalog(); data.pop('skip_host_skill_discovery')
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(raw=table(data))) as run:
            report = self.inspect()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(report['features']['skip_host_skill_discovery']['status'], 'missing_required')
        self.assertEqual(report['status'], 'FAIL')

    def test_probe_failures_do_not_disclose_output_or_retry(self):
        cases = [subprocess.CompletedProcess([], 1, 'private-secret', 'private-secret'),
                 subprocess.TimeoutExpired('private-secret', 0.01), OSError('private-secret'),
                 UnicodeError('private-secret'), RuntimeError('private-secret')]
        for value in cases:
            with self.subTest(value=type(value).__name__):
                options = {'side_effect': value} if isinstance(value, BaseException) else {'return_value': value}
                with patch.object(transport, 'probe_cli_metadata', **options) as run:
                    report = self.inspect()
                self.assertEqual(report['status'], 'FAIL')
                self.assertEqual(run.call_count, 1)
                self.assertNotIn('private-secret', json.dumps(report))

    def test_duplicate_effective_table_fails(self):
        data = table(catalog(effective=True)) + 'daemon_auto_start stable false\ndaemon_auto_start stable false\n'
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(effective=data)):
            report = self.inspect()
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('Duplicate', report['detail'])

    def test_cancel_between_probes(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()) as run:
            report = self.inspect(cancel_requested=iter([None, 'stop']).__next__)
        self.assertTrue(report['interrupted'])
        self.assertEqual(run.call_count, 1)

    def test_keyboard_interrupt_stops(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=KeyboardInterrupt) as run:
            report = self.inspect()
        self.assertTrue(report['interrupted']); self.assertEqual(run.call_count, 1)

    def test_probe_context_is_identical_and_inputs_unmodified(self):
        env = {'PATH': '/chosen/bin', 'CODEX_HOME': '/chosen/home'}; before = dict(env)
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()) as run:
            transport.inspect_decision_features(launcher=('/chosen/codex',), cwd=ROOT, env=env)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['launcher'], ('/chosen/codex',))
            self.assertEqual(call.kwargs['cwd'], ROOT); self.assertEqual(call.kwargs['env'], env)
        self.assertEqual(env, before)

    def test_capabilities_are_not_cached_across_calls(self):
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()):
            old = self.inspect()
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(daemon=True)):
            new = self.inspect()
        self.assertNotIn('daemon_auto_start', old['selected_features'])
        self.assertIn('daemon_auto_start', new['selected_features'])


class DoctorTests(unittest.TestCase):
    def report(self, *, daemon=False, effective=None, raw=None, check_decide=False):
        fake_launcher = SimpleNamespace(source='codex', metadata=lambda: {})
        def metadata(name, *args, **kwargs):
            text = 'codex-cli 0.154.0' if name == 'version' else '\n'.join(doctor.REQUIRED_EXEC_FLAGS)
            return {'status': 'PASS', 'exit_code': 0}, text
        with patch.object(doctor, 'resolve_launcher', return_value=fake_launcher), \
             patch.object(doctor, '_probe', side_effect=metadata), \
             patch.object(transport, 'probe_cli_metadata', side_effect=probes(daemon=daemon, effective=effective, raw=raw)), \
             patch.object(doctor, '_decision_probe', return_value={'status':'PASS', 'model_calls':1, 'detail':'Simulated'}) as model:
            report = doctor.collect_report(workdir=ROOT, env={}, check_decide=check_decide)
        return report, model.call_count

    def test_metadata_only_stays_cost_free(self):
        report, count = self.report()
        self.assertEqual(report['checks_status'], 'PASS', report)
        self.assertEqual(report['model_calls'], 0); self.assertEqual(count, 0)
        self.assertTrue(report['decision_features']['daemon_auto_start'])
        self.assertEqual(report['unavailable_optional_features'], ['daemon_auto_start'])

    def test_old_and_new_doctor_can_reach_decide(self):
        for daemon in (False, True):
            report, count = self.report(daemon=daemon, check_decide=True)
            self.assertEqual(report['checks_status'], 'PASS', report)
            self.assertEqual(count, 1); self.assertEqual(report['model_calls'], 1)

    def test_doctor_blocks_missing_core_control(self):
        data = catalog(); data.pop('shell_tool')
        report, count = self.report(raw=table(data), check_decide=True)
        self.assertEqual(report['checks_status'], 'FAIL'); self.assertEqual(count, 0)
        self.assertEqual(report['decision_probe']['status'], 'NOT_RUN')

    def test_doctor_blocks_wrong_effective_value(self):
        data = catalog(effective=True); data['skip_host_skill_discovery'] = False
        report, count = self.report(effective=table(data), check_decide=True)
        self.assertEqual(report['checks_status'], 'FAIL'); self.assertEqual(count, 0)

    def test_console_explains_optional_absence_and_failed_control(self):
        report, _ = self.report()
        output = io.StringIO()
        with patch.object(doctor, 'collect_report', return_value=report), redirect_stdout(output):
            self.assertEqual(doctor.main([]), 0)
        self.assertIn('daemon_auto_start', output.getvalue()); self.assertIn('Override entfällt', output.getvalue())
        data = catalog(effective=True); data['shell_tool'] = True
        report, _ = self.report(effective=table(data)); output = io.StringIO()
        with patch.object(doctor, 'collect_report', return_value=report), redirect_stdout(output):
            self.assertEqual(doctor.main([]), 1)
        self.assertIn('[FAIL] shell_tool: wrong_value', output.getvalue())


class TransportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.request = transport.CodexExecRequest(prompt='Choose FOUR.', cwd=self.base, env={},
            raw_log=self.base/'events.jsonl', pretty_log=self.base/'pretty.log', decision_only=True)

    @staticmethod
    def fake_run(request, trace, prompt_bytes, *, decision_features=None):
        trace.capture['argv'] = transport.build_command(request, decision_features=decision_features)
        trace.capture['launcher'] = {'kind': 'fake-exec'}
        trace.capture['stdin'].update(closed=True, written_bytes=len(prompt_bytes))
        for name in ('stdout', 'stderr'):
            trace.capture[name]['eof'] = True
        trace.turn_completed = True; trace.process_exit_code = 0
        trace.assistant_messages.append('{"option":"FOUR","explanation":"2+2=4"}')
        if request.output_last_message is not None:
            request.output_last_message.write_text(trace.end_answer, encoding='utf-8')
        return trace

    def execute(self, *, daemon=False, effective=None, request=None):
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes(daemon=daemon, effective=effective)), \
             patch.object(transport, '_run', side_effect=self.fake_run) as model:
            outcome = transport.execute(request or self.request)
        return outcome, model

    def test_transport_negotiates_without_doctor_and_captures_actual_argv(self):
        for daemon in (False, True):
            outcome, model = self.execute(daemon=daemon)
            self.assertTrue(outcome.execution.succeeded, outcome)
            self.assertEqual(model.call_count, 1)
            args = outcome.trace.capture['argv']
            self.assertEqual('daemon_auto_start' in argv_config(args)['features'], daemon)
            self.assertNotIn('--strict-config', args); self.assertIn('--sandbox', args)
            self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
            saved = json.loads((outcome.trace.capture_dir/'capture.json').read_text())
            self.assertEqual(saved['argv'], args)
            self.assertEqual(saved['decision_feature_compatibility']['status'], 'PASS')

    def test_transport_rejects_wrong_value_before_exec(self):
        data = catalog(effective=True); data['shell_tool'] = True
        outcome, model = self.execute(effective=table(data))
        self.assertFalse(outcome.execution.succeeded); model.assert_not_called()
        self.assertEqual(outcome.execution.failure.code, 'codex_decision_features_failed')
        self.assertNotIn('launcher', outcome.trace.capture)
        self.assertTrue((outcome.trace.capture_dir/'capture.json').exists())

    def test_cancellation_starts_no_metadata_or_exec(self):
        stop = self.base/'process_stop'; stop.write_text('stop', encoding='utf-8')
        with patch.object(transport, 'probe_cli_metadata') as probe, patch.object(transport, '_run') as model:
            outcome = transport.execute(replace(self.request, process_stop_path=stop))
        probe.assert_not_called(); model.assert_not_called()
        self.assertEqual(outcome.execution.status.value, 'cancelled')

    def test_non_decide_transport_does_not_probe_features(self):
        with patch.object(transport, 'probe_cli_metadata') as probe, \
             patch.object(transport, '_run', side_effect=self.fake_run) as model:
            outcome = transport.execute(replace(self.request, decision_only=False))
        probe.assert_not_called(); self.assertEqual(model.call_count, 1)
        self.assertTrue(outcome.execution.succeeded)

    def test_real_decision_archive_records_negotiated_restrictions(self):
        project = self.base/'project'; project.mkdir()
        auth = self.base/'auth'; auth.mkdir()
        temp = self.base/'temp'; temp.mkdir()
        # Resolve the interpreter as a harmless placeholder: _run is mocked, so
        # it is never used to execute Codex or a model.
        settings = decision_exec.DecisionExecSettings(project_root=project, trusted_codex_home=auth,
            temp_root=temp, log_root=project/'logs', env={}, launcher=sys.executable)
        request = DecisionRequest(question='2+2?', options=('FOUR','FIVE'), context=(),
                                  run_id='test', task_id='1', phase='test', attempt_id='1')
        with patch.object(transport, 'probe_cli_metadata', side_effect=probes()), \
             patch.object(transport, '_run', side_effect=self.fake_run):
            call = decision_exec.execute_decision(request, settings=settings)
        self.assertTrue(call.result.valid, call.result)
        saved = json.loads((call.directory/'call.json').read_text())
        self.assertTrue(saved['archive_complete'])
        self.assertNotIn('daemon_auto_start', argv_config(saved['settings']['enforced_cli_arguments'])['features'])
        self.assertNotIn('daemon_auto_start', argv_config(saved['argv'])['features'])
        self.assertEqual(saved['feature_compatibility']['unavailable_optional'], ['daemon_auto_start'])


if __name__ == '__main__':
    unittest.main()
