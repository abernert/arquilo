#!/usr/bin/env python3
"""Offline regression for long outages, external state and review-only recovery."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, UTC
from pathlib import Path
import hashlib
import io
import json
import os
import re
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import arquilo
import codex_transport as transport
import controller_state
import project_logs
import review_resume as recovery
from runtime_contracts import ExecutionStatus
from test_review_resume import Fixture as ArchiveFixture, NEW, ANSWER, event_bytes
from test_reconnect_stop import Fixture as ProcessFixture, RECONNECT, COMPLETE, FAILED, WORK, PASS, FAIL, answer

TIMEOUT = {"type": "error", "message": "Reconnecting... 2/5 (request timed out)"}
WAITING = {"type": "error", "message": "Reconnecting... waiting for network (Connection failed: error sending request)"}


def snapshot(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


class OutageSequenceTests(ProcessFixture):
    def test_long_outage_then_completion_starts_one_review(self):
        notices = [RECONNECT] + [{**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', f'{i}/5')}
                                for i in range(2, 6)] + [WAITING] * 215
        summary, payload, calls = self.build([
            {'events': notices + [WORK, answer('Recovered production.'), COMPLETE]},
            {'events': [answer(json.dumps(PASS)), COMPLETE]},
        ])
        self.assertTrue(payload['completed'])
        self.assertEqual((summary.auftrag_runs, summary.review_runs, calls), (1, 1, 2))
        self.assertEqual(len(summary.run_history[0].stream_diagnostics), 220)
        self.assertEqual(summary.run_history[0].stream_errors, [])

    def test_new_notices_do_not_hide_real_terminal_failures(self):
        for events, code, expected in (
            ([TIMEOUT, WAITING, FAILED], 1, 'codex_turn_failed'),
            ([TIMEOUT, WAITING, answer('partial')], 0, 'codex_missing_completion'),
            ([WAITING, answer('completed'), COMPLETE], 7, 'codex_process_failed'),
            ([WAITING, COMPLETE], 0, 'codex_missing_answer'),
            ([WAITING, {'type': 'error', 'message': '401 Unauthorized'}, answer('x'), COMPLETE], 0, 'codex_stream_error'),
            ([answer('done'), COMPLETE, WAITING], 0, 'codex_stream_error'),
        ):
            with self.subTest(expected=expected, events=events):
                result = self.execute({'events': events, 'exit': code})
                self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
                self.assertEqual(result.trace.execution_error['code'], expected)

    def test_stop_during_network_wait_still_cancels(self):
        result = self.execute({'events': [TIMEOUT, WAITING], 'mode': 'wait', 'stop': True})
        self.assertEqual(result.execution.status, ExecutionStatus.CANCELLED)
        self.assertTrue(result.trace.process_stop_triggered)

    def test_classifier_rejects_near_matches_and_post_terminal_notices(self):
        for notice in (TIMEOUT, WAITING):
            self.assertTrue(transport.is_transient_reconnect(notice, terminal_seen=False))
            self.assertFalse(transport.is_transient_reconnect(notice, terminal_seen=True))
        for notice in (
            {**WAITING, 'code': 401},
            {**WAITING, 'message': WAITING['message'] + ' extra'},
            {**WAITING, 'message': WAITING['message'].replace('error sending request', '401 Unauthorized')},
            {**WAITING, 'message': WAITING['message'].replace('waiting for network', 'waiting for model')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', '6/5')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', '0/5')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', '02/5')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', '１/５')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('2/5', '1/1001')},
            {**TIMEOUT, 'message': TIMEOUT['message'].replace('request timed out', 'authentication failed')},
        ):
            self.assertFalse(transport.is_transient_reconnect(notice, terminal_seen=False), notice)


class MixedArchiveTests(ArchiveFixture):
    def mixed(self):
        self.events = [{'type': 'thread.started'}, {'type': 'turn.started'}, NEW,
                       TIMEOUT, WAITING, WAITING,
                       {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': ANSWER}}, COMPLETE]
        self.capture_info.update(stream_errors=[TIMEOUT, WAITING, WAITING],
                                 stream_diagnostics=[{'kind': 'codex_reconnect', 'event_index': 3, 'event': NEW}])
        self.write_archive()

    def test_mixed_error_diagnostic_partition_and_unchanged_archive(self):
        self.mixed()
        before = snapshot(self.home)
        evidence = self.recover()
        self.assertEqual(len(evidence.notices), 4)
        self.assertEqual(before, snapshot(self.home))

    def test_mixed_partition_rejects_missing_duplicate_unknown_or_mismatched_entries(self):
        mutations = [
            {'stream_diagnostics': [{'kind': 'unexpected', 'event_index': 3, 'event': NEW}]},
            {'stream_diagnostics': [{'kind': 'codex_reconnect', 'event_index': 4, 'event': NEW}]},
            {'stream_diagnostics': [{'kind': 'codex_reconnect', 'event_index': 3, 'event': WAITING}]},
            {'stream_diagnostics': [{'kind': 'codex_reconnect', 'event_index': 3, 'event': NEW}] * 2},
            {'stream_diagnostics': {}},
            {'stream_errors': [TIMEOUT, WAITING]},
            {'stream_errors': [TIMEOUT, WAITING, WAITING, WAITING]},
            {'stream_errors': []},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.mixed()
                self.capture_info.update(mutation)
                self.write_archive()
                with self.assertRaises(recovery.RecoveryRefused):
                    self.recover()

    def test_post_terminal_activity_is_not_recovered(self):
        for event in (WAITING, answer(ANSWER), {'type': 'thread.started'}, FAILED):
            self.mixed()
            self.events.append(event)
            self.write_archive()
            with self.subTest(event=event), self.assertRaises(recovery.RecoveryRefused):
                self.recover()

    def test_missing_or_truncated_stderr_is_rejected(self):
        self.mixed()
        (self.capture / 'stderr.bin').write_bytes(b'unrecorded')
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()
        (self.capture / 'stderr.bin').unlink()
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_summary_stop_is_not_recovered(self):
        self.mixed()
        path = self.dir / 'autobuild_summary.json'
        document = json.loads(path.read_text())
        document['process_stop_triggered'] = True
        path.write_text(json.dumps(document))
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()

    def test_parent_symlink_and_hardlinked_capture_rejected(self):
        if os.name == 'nt':
            self.skipTest('POSIX symlink creation fixture')
        linked = self.home / 'parent-link'
        linked.symlink_to(self.dir, target_is_directory=True)
        with self.assertRaises(recovery.RecoveryRefused):
            recovery.load_verified_recovery(linked / self.capture.name, self.work, '2')
        os.link(self.capture / 'capture.json', self.home / 'capture-copy.json')
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()


class ExternalArchiveTests(MixedArchiveTests):
    project_id = None

    def setUp(self):
        super().setUp()
        self.todo = self.work / 'tasks.md'
        self.todo.write_text('2. ***Task***: Synthetic task.\n', encoding='utf-8')
        self.root = self.home / 'private-state'
        self.state = controller_state.state_directory(self.work.resolve(), self.todo.resolve(), self.root)
        logs = project_logs.project_logs(self.state, self.work.resolve(), self.todo.resolve(), self.project_id)
        self.run = logs.new_run(datetime(2026, 11, 5, 17, 22, 57, 633000, tzinfo=UTC),
                                run_id='test', workspace=self.work.resolve(), todo=self.todo.resolve())
        target = self.run / 'task-2'
        shutil.move(str(self.dir), target)
        self.dir = target
        self.capture = target / '001-production'
        self.run_info = json.loads((self.run / 'run.json').read_text())
        self.run_info.update(status='failed', finished_at='2026-11-06T10:51:06Z',
                             process_stop_triggered=False, tasks=[str(target / 'task_log.json')])
        (target / 'task_log.json').write_text('{}', encoding='utf-8')
        self.write_run()
        self.mixed()

    def write_run(self):
        (self.run / 'run.json').write_text(json.dumps(self.run_info), encoding='utf-8')

    def recover(self):
        return recovery.load_verified_recovery(self.capture, self.work, '2',
                                                todo_file=self.todo, state_root=self.root)

    def argv(self):
        return ['resume-review', '--todo', '2', '--capture-dir', str(self.capture), '--',
                'tasklist', 'run', '--workdir', str(self.work), '--todo-file', str(self.todo),
                '--state-dir', str(self.root), '--start', '2', '--stop', '2',
                '--max-steps', '1', '--max-retries', '1', '--breakdown-policy', 'off']

    def test_external_check_only_has_no_writes_or_model_calls(self):
        before = snapshot(self.home)
        args = self.argv()
        args.insert(1, '--check-only')
        with patch.object(transport, 'execute', side_effect=AssertionError('model call')), \
                patch.object(arquilo, 'main', side_effect=AssertionError('runner started')), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(recovery.main(args), 0)
        self.assertEqual(before, snapshot(self.home))

    def test_external_metadata_mismatches_are_rejected(self):
        original = dict(self.run_info)
        for mutation in ({'status': 'running'}, {'finished_at': None},
                         {'workspace': str(self.home)}, {'todo_file': str(self.todo) + '.missing'},
                         {'controller_state': str(self.root)}, {'run_directory': str(self.root)},
                         {'process_stop_triggered': True}):
            self.run_info = {**original, **mutation}
            self.write_run()
            with self.subTest(mutation=mutation), self.assertRaises(recovery.RecoveryRefused):
                self.recover()

    def test_wrong_state_root_or_unbound_external_path_is_rejected(self):
        wrong = self.home / 'wrong-state'
        wrong.mkdir(mode=0o700)
        with self.assertRaises((recovery.RecoveryRefused, controller_state.PlanIntegrityError)):
            recovery.load_verified_recovery(self.capture, self.work, '2', todo_file=self.todo, state_root=wrong)
        with self.assertRaises(recovery.RecoveryRefused):
            recovery.load_verified_recovery(self.capture, self.work, '2')

    def test_another_task_file_cannot_reuse_archive(self):
        other = self.work / 'other.md'
        other.write_text(self.todo.read_text())
        controller_state.state_directory(self.work.resolve(), other.resolve(), self.root)
        with self.assertRaises(recovery.RecoveryRefused):
            recovery.load_verified_recovery(self.capture, self.work, '2', todo_file=other, state_root=self.root)


class NamedExternalArchiveTests(ExternalArchiveTests):
    project_id = 'recovery-test'

    def test_project_binding_mismatch_is_rejected(self):
        path = self.root / self.project_id / 'project.json'
        record = json.loads(path.read_text())
        record['plans'][self.state.name]['controller_state'] = str(self.root)
        path.write_text(json.dumps(record))
        with self.assertRaises(recovery.RecoveryRefused):
            self.recover()


class NativeRecoveryTests(ProcessFixture):
    def make_failed_archive(self):
        self.todo = self.work / 'tasks.md'
        self.todo.write_text('2. ***Task***: Create a synthetic output.\n3. ***Task***: Must not run.\n', encoding='utf-8')
        self.root = self.base / 'private-state'
        self.run_args = ['tasklist', 'run', '--todo-file', str(self.todo), '--workdir', str(self.work),
                         '--state-dir', str(self.root), '--start', '2', '--stop', '2',
                         '--max-steps', '1', '--max-retries', '1', '--max-calls', '12',
                         '--breakdown-policy', 'off', '--skip-backend-preflight']
        old_classifier = re.compile(r'Reconnecting\.\.\. ([1-9][0-9]{0,3})/([1-9][0-9]{0,3}) '
                                    r'\(stream disconnected before completion: ([^\r\n()]{1,240})\)')
        def old(event, *, terminal_seen):
            return not terminal_seen and isinstance(event, dict) and bool(old_classifier.fullmatch(event.get('message', '')))
        with self.launch([{'events': [RECONNECT, TIMEOUT, WAITING, answer('Completed original work.'), COMPLETE]}]), \
                patch.object(transport, 'is_transient_reconnect', old), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(arquilo.main(self.run_args), 0)
        self.capture = next(self.root.glob('*/runs/*/task-2/001-production/capture.json')).parent
        summary = json.loads((self.capture.parent / 'autobuild_summary.json').read_text())
        self.assertEqual((summary['auftrag_runs'], summary['review_runs']), (1, 0))
        self.assertEqual(summary['execution_error']['code'], 'codex_stream_error')
        self.args = ['tasklist', 'resume-review', '--todo', '2', '--capture-dir', str(self.capture), '--', *self.run_args]

    def test_real_cli_resumes_review_once_without_production_or_archive_changes(self):
        self.make_failed_archive()
        before = snapshot(self.capture.parent.parent)
        with self.launch([{'events': [answer(json.dumps(PASS)), COMPLETE]}]) as calls, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(arquilo.main(self.args), 0)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(before, snapshot(self.capture.parent.parent))
        self.assertIn('2. ***DONE***', self.todo.read_text())
        self.assertIn('3. ***Task***', self.todo.read_text())

    def test_real_cli_review_failure_does_not_repeat_production_or_mark_done(self):
        self.make_failed_archive()
        with self.launch([{'events': [answer(json.dumps(FAIL)), COMPLETE]}]) as calls, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(arquilo.main(self.args), 0)
        self.assertEqual(calls.call_count, 1)
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_real_cli_prompt_change_refuses_before_any_model_call(self):
        self.make_failed_archive()
        args = [*self.args, '--process-stop-policy', 'controller-only']
        with self.launch([]) as calls, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(arquilo.main(args), 0)
        self.assertEqual(calls.call_count, 0)
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_real_cli_active_stop_is_not_bypassed(self):
        self.make_failed_archive()
        self.stop.write_text('Operator stop remains authoritative.', encoding='utf-8')
        with self.launch([]) as calls, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(arquilo.main(self.args), 0)
        self.assertEqual(calls.call_count, 0)
        self.assertEqual(self.stop.read_text(), 'Operator stop remains authoritative.')


if __name__ == '__main__':
    unittest.main()
