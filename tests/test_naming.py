# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline naming and historical DORA input-compatibility regressions."""
from __future__ import annotations
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo
import arquilo_doctor
from autobuild_contract import validate_result, core_status
from execution_budget import CallBudget, BudgetExhausted
from legacy_naming import historical_environment_aliases, schema_matches
from removed_features import check_removed_environment, check_removed_fields
from runtime_config import environment_value, resolve_model, resolve_reasoning_effort, transport_timeout_values
from runtime_profile import load_runtime_profile, resolve_runtime_profile_path, RuntimeProfileError
from scripts.check_naming import check_naming
from scripts.stage_lean import package_files, stage_package


class DoctorNamingTests(unittest.TestCase):
    def test_only_current_doctor_is_shipped(self):
        names = package_files(ROOT)
        self.assertIn('arquilo_doctor.py', names)
        self.assertNotIn('dora_doctor.py', names)
        self.assertFalse((ROOT / 'dora_doctor.py').exists())

    def test_wrapper_dispatches_to_current_doctor(self):
        with patch('arquilo_doctor.main', return_value=7) as call:
            self.assertEqual(arquilo.main(['doctor', '--json']), 7)
        call.assert_called_once_with(['--json'])

    def test_report_schema_and_version_key_are_current(self):
        with patch('arquilo_doctor.resolve_launcher', side_effect=OSError('CLI unavailable')):
            report = arquilo_doctor.collect_report(workdir=ROOT, env={})
        self.assertEqual(report['schema_version'], 'arquilo.doctor.v2')
        self.assertEqual(report['arquilo_version'], arquilo.__version__)
        self.assertNotIn('dora_version', report)
        self.assertEqual(report['model_calls'], 0)

    def test_console_banner_is_current(self):
        output = io.StringIO()
        with patch('arquilo_doctor.resolve_launcher', side_effect=OSError('CLI unavailable')), redirect_stdout(output):
            self.assertEqual(arquilo_doctor.main(['--workdir', str(ROOT)]), 1)
        self.assertIn('ARQUILO Doctor:', output.getvalue())
        self.assertNotIn('DORA', output.getvalue())

    def test_smoke_logs_use_current_doctor_directory(self):
        call = SimpleNamespace(directory=None, request=SimpleNamespace(model='test'), attempts=(),
                               result=SimpleNamespace(valid=True, option='FOUR'))
        with tempfile.TemporaryDirectory() as t, patch('decide.run_decision', return_value=call) as run:
            workspace = Path(t).resolve()
            probe = arquilo_doctor._decision_probe(workspace=workspace,
                launcher=SimpleNamespace(source='codex'), env={}, model=None,
                reasoning_effort=None, timeout=5)
            self.assertEqual(probe['status'], 'PASS')
            self.assertEqual(run.call_args.kwargs['settings'].log_root,
                             workspace / '.codex_runs' / 'arquilo_doctor')

    def test_all_public_help_and_capabilities_use_current_names(self):
        for filename, args in [('arquilo_doctor.py', ['--help']), ('run_todos.py', ['--help']),
                               ('arquilo.py', ['--help']), ('arquilo.py', ['capabilities'])]:
            with self.subTest(filename=filename, args=args):
                with patch.dict(os.environ, {}, clear=True):
                    p = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / filename), *args],
                        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertNotIn('DORA', p.stdout)
                self.assertNotIn('dora_', p.stdout)
                self.assertNotIn('dora.', p.stdout)
        self.assertEqual(json.loads(p.stdout)['schema_version'], 'arquilo.capabilities.v1')


class HistoricalEnvironmentTests(unittest.TestCase):
    SUFFIXES = ('CODEX_MODEL', 'CODEX_REASONING_EFFORT', 'DECISION_MODEL', 'DECISION_SYSTEM_PROMPT',
                'CODEX_POST_TURN_EXIT_GRACE_SECONDS', 'CODEX_STALL_TIMEOUT_SECONDS',
                'CODEX_KILL_GRACE_SECONDS', 'TODO_SYNTAX', 'TODO_PREAMBLE', 'RUNTIME_PROFILE')

    def test_canonical_names_are_quiet_and_take_precedence(self):
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix), warnings.catch_warnings(record=True) as found:
                warnings.simplefilter('always')
                name = 'ARQUILO_' + suffix
                self.assertEqual(environment_value(name, environ={name: ' current '}), 'current')
                self.assertEqual(found, [])
                self.assertEqual(environment_value(name, environ={name: 'current', 'DORA_' + suffix: 'old'}), 'current')
                self.assertTrue(found)

    def test_historical_aliases_warn_without_disclosing_values(self):
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix), warnings.catch_warnings(record=True) as found:
                warnings.simplefilter('always')
                self.assertEqual(environment_value('ARQUILO_' + suffix,
                    environ={'DORA_' + suffix: 'SECRET-test-value'}), 'SECRET-test-value')
                self.assertTrue(found)
                self.assertIn('deprecated', str(found[0].message))
                self.assertNotIn('SECRET-test-value', str(found[0].message))

    def test_empty_canonical_value_falls_back(self):
        env = {'ARQUILO_CODEX_MODEL': ' ', 'DORA_CODEX_MODEL': 'old'}
        before = dict(env)
        with self.assertWarns(FutureWarning):
            self.assertEqual(resolve_model(None, environ=env), 'old')
        self.assertEqual(env, before)

    def test_cli_value_wins_without_using_aliases(self):
        with warnings.catch_warnings(record=True) as found:
            self.assertEqual(resolve_model('explicit', environ={'DORA_CODEX_MODEL': 'old'}), 'explicit')
            self.assertEqual(resolve_reasoning_effort('LOW', environ={'DORA_CODEX_REASONING_EFFORT': 'high'}), 'low')
        self.assertEqual(found, [])

    def test_older_aliases_keep_original_order(self):
        with self.assertWarns(FutureWarning):
            self.assertEqual(environment_value('ARQUILO_DECISION_MODEL', environ={
                'DORA_DECISION_MODEL': 'old', 'AUTOBUILD_DECISION_MODEL': 'older',
                'METACODEX_DECISION_MODEL': 'oldest'}), 'old')
        with self.assertWarns(FutureWarning):
            self.assertEqual(environment_value('ARQUILO_DECISION_MODEL', environ={
                'AUTOBUILD_DECISION_MODEL': 'older', 'METACODEX_DECISION_MODEL': 'oldest'}), 'older')

    def test_legacy_timeouts_are_still_validated(self):
        with self.assertWarns(FutureWarning):
            self.assertEqual(transport_timeout_values(environ={'DORA_CODEX_KILL_GRACE_SECONDS': '2'})['kill_grace'], 2)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FutureWarning)
            with self.assertRaises(ValueError):
                transport_timeout_values(environ={'DORA_CODEX_KILL_GRACE_SECONDS': 'nan'})

    def test_profile_path_precedence(self):
        with tempfile.TemporaryDirectory() as t:
            old, new, explicit = [str(Path(t) / n) for n in ('old.json', 'new.json', 'explicit.json')]
            with self.assertWarns(FutureWarning):
                self.assertEqual(resolve_runtime_profile_path(environ={
                    'DORA_RUNTIME_PROFILE': old, 'ARQUILO_RUNTIME_PROFILE': new}), Path(new).resolve())
            with warnings.catch_warnings(record=True) as found:
                self.assertEqual(resolve_runtime_profile_path(explicit, environ={'DORA_RUNTIME_PROFILE': old}), Path(explicit).resolve())
                self.assertEqual(found, [])

    def test_task_options_retain_legacy_environment_defaults(self):
        from run_todos import parse_args
        with patch.dict(os.environ, {'DORA_TODO_SYNTAX': 'legacy', 'DORA_TODO_PREAMBLE': 'off'}, clear=True):
            with self.assertWarns(FutureWarning):
                args = parse_args(['--todo-file', 'tasks.md', '--dry-run'])
        self.assertEqual(args.todo_syntax, 'legacy')
        self.assertEqual(args.todo_preamble, 'off')

    def test_unrelated_names_have_no_historical_alias(self):
        self.assertEqual(historical_environment_aliases('UNRELATED'), ())

    def test_retired_features_are_rejected_under_both_prefixes(self):
        for prefix in ('DORA_', 'ARQUILO_'):
            for suffix in ('CUA_APPROVE_ALL', 'IACT_ENABLED', 'QUEUE_STATE', 'PROMETHEUS_PORT'):
                with self.subTest(prefix=prefix, suffix=suffix):
                    with self.assertRaises(ValueError):
                        check_removed_environment({prefix + suffix: ''})
                    with self.assertRaises(ValueError):
                        check_removed_fields({prefix + suffix: False}, source='test')


class HistoricalSchemaTests(unittest.TestCase):
    def test_only_same_version_schema_alias_is_accepted(self):
        with self.assertWarns(FutureWarning):
            self.assertTrue(schema_matches('dora.runtime_profile.v1', 'arquilo.runtime_profile.v1'))
        for value in ('dora.runtime_profile.v2', 'other.runtime_profile.v1', [], None, True):
            self.assertFalse(schema_matches(value, 'arquilo.runtime_profile.v1'))
        with warnings.catch_warnings(record=True) as found:
            self.assertTrue(schema_matches('arquilo.runtime_profile.v1', 'arquilo.runtime_profile.v1'))
        self.assertEqual(found, [])

    def test_legacy_profile_loads_and_normalizes_without_rewriting(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'profile.json'
            p.write_text(json.dumps({'schema_version': 'dora.runtime_profile.v1',
                                    'profile_id': 'example', 'prompt_policy': {}}), encoding='utf-8')
            before = p.read_bytes()
            with self.assertWarns(FutureWarning):
                profile = load_runtime_profile(p, environ={})
            self.assertEqual(profile.schema_version, 'arquilo.runtime_profile.v1')
            self.assertEqual(p.read_bytes(), before)

    def test_legacy_profile_never_relaxes_policy(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'profile.json'
            p.write_text(json.dumps({'schema_version': 'dora.runtime_profile.v1',
                                    'profile_id': 'example', 'sandbox': 'danger-full-access'}), encoding='utf-8')
            with self.assertRaises(RuntimeProfileError):
                load_runtime_profile(p, environ={})

    def test_old_budget_keeps_claims_limits_and_file_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            manifest = p / 'budget.json'
            manifest.write_text(json.dumps({'schema_version': 'dora.call_budget.v1',
                                           'root_id': 'test', 'limit': 2}), encoding='utf-8')
            before = manifest.read_bytes()
            (p / 'call_000001.json').write_text('{}', encoding='utf-8')
            with self.assertWarns(FutureWarning):
                budget = CallBudget(p, 2, 'test')
            self.assertEqual(budget.snapshot()['used'], 1)
            self.assertEqual(budget.snapshot()['schema_version'], 'arquilo.call_budget.v1')
            self.assertEqual(budget.consume('test', 'review')['number'], 2)
            with self.assertRaises(BudgetExhausted):
                budget.consume('test', 'extra')
            self.assertEqual(manifest.read_bytes(), before)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', FutureWarning)
                with self.assertRaises(ValueError):
                    CallBudget(p, 3, 'test')
                with self.assertRaises(ValueError):
                    CallBudget(p, 2, 'different')

    def test_historical_budget_summary_is_validated(self):
        payload = {'completed': False, 'process_stop_triggered': False, 'review_required': True,
                   'exit_code': 9, 'status': core_status(9), 'last_answer': 'Unfinished',
                   'call_budget': {'schema_version': 'dora.call_budget.v1', 'root_id': 'test',
                                   'limit': 2, 'used': 1, 'remaining': 1}}
        with self.assertWarns(FutureWarning):
            self.assertEqual(validate_result(payload)['exit_code'], 9)
        payload['call_budget']['remaining'] = 2
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FutureWarning)
            with self.assertRaises(ValueError):
                validate_result(payload)

    def test_historical_package_manifest_is_readable(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / 'staged'
            stage_package(base, source=ROOT)
            p = base / 'documents/lean_package.json'
            manifest = json.loads(p.read_text(encoding='utf-8'))
            manifest['schema_version'] = 'dora.lean.package.v1'
            p.write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertWarns(FutureWarning):
                names = package_files(base)
            self.assertIn('arquilo_doctor.py', names)
            manifest['schema_version'] = 'dora.lean.package.v9'
            p.write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaises(ValueError):
                package_files(base)


class NamingGuardTests(unittest.TestCase):
    def test_no_active_predecessor_name(self):
        check_naming(ROOT)

    def test_active_name_regression_is_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / 'README.md').write_text('Run DORA Doctor', encoding='utf-8')
            with self.assertRaises(ValueError):
                check_naming(root)

    def test_historical_notice_and_fedora_are_not_false_positives(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / 'NOTICE').write_text('Historically named DORA Lean', encoding='utf-8')
            (root / 'README.md').write_text('ARQUILO on Fedora', encoding='utf-8')
            check_naming(root)


if __name__ == '__main__':
    unittest.main()
