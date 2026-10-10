# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Ordered synthetic I/O faults; independent stop metadata must survive errors."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import autobuild
import codex_transport as transport
from runtime_contracts import ExecutionResult, ExecutionStatus, Failure, FailureKind
from runtime_failure import execution_error
from test_reconnect_stop import Fixture, RECONNECT, ANSWER, COMPLETE, STOP, PASS, answer

class FaultTests(Fixture):
    @contextmanager
    def io_fault(self, diagnostic, *, drain=False, after_shutdown=False):
        parent = queue.Queue
        instances = []
        class InjectedQueue(parent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.injected = self.interrupted = False
                instances.append(self)
            def put(self, item, *args, **kwargs):
                super().put(item, *args, **kwargs)
                if not after_shutdown and not self.injected and item[0] == 'stdout':
                    self.injected = True
                    super().put(('io_error', dict(diagnostic)))
            def get(self, *args, **kwargs):
                item = super().get(*args, **kwargs)
                if drain and item[0] == 'io_error' and not self.interrupted:
                    self.interrupted = True
                    super().put(item)
                    raise KeyboardInterrupt  # force final drain, not the main handler
                return item
        original = transport._terminate_process_group
        def terminate(*args, **kwargs):
            value = original(*args, **kwargs)
            for channel in instances:
                if after_shutdown and not channel.injected:
                    channel.injected = True
                    parent.put(channel, ('io_error', dict(diagnostic)))
            return value
        with patch.object(transport.queue, 'Queue', InjectedQueue), \
             patch.object(transport, '_terminate_process_group', side_effect=terminate):
            yield

    def test_read_and_log_faults_remain_fatal_with_stop(self):  # T101-12
        for kind in ('read_error', 'log_error'):
            self.stop.unlink(missing_ok=True)
            diagnostic = dict(type=kind, source='stdout', message='Synthetic I/O failure', during_shutdown=False,
                              exception_type='PermissionError', errno=13)
            with self.io_fault(diagnostic):
                result = self.execute({'events':[RECONNECT, ANSWER], 'stop':True, 'mode':'wait'})
            self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
            self.assertTrue(result.trace.process_stop_triggered)
            self.assertEqual(result.trace.process_stop_details, STOP)
            self.assertIn(diagnostic, result.trace.stream_errors)
            capture = self.assert_archive(result, {'events':[RECONNECT, ANSWER]}, healthy=False)
            self.assertFalse(capture['stdout']['complete'])

    def test_decode_fault_with_stop_preserves_raw_bytes(self):  # T101-12
        result = self.execute({'events':[RECONNECT, ANSWER], 'bad_utf8':True, 'stop':True, 'mode':'wait'})
        self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
        self.assertTrue(result.trace.process_stop_triggered)
        self.assertTrue(any(e['type']=='decode_error' for e in result.trace.stream_errors))
        self.assertIn(b'\xff', (result.trace.capture_dir/'stdout.bin').read_bytes())
        self.assertEqual(result.trace.capture['stdout']['invalid_utf8_bytes'], 1)

    def test_cleanup_fault_does_not_erase_stop(self):  # T101-12
        original = transport._terminate_process_group
        def cleanup(*args, **kwargs):
            result = original(*args, **kwargs)
            if not result.errors:
                result.errors.append('Synthetic cleanup fault')
            return result
        with patch.object(transport, '_terminate_process_group', side_effect=cleanup):
            result = self.execute({'events':[RECONNECT], 'stop':True, 'mode':'wait'})
        self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
        self.assertTrue(result.trace.process_stop_triggered)
        self.assertEqual(result.trace.process_stop_details, STOP)
        self.assertEqual(len(result.trace.stream_diagnostics), 1)

    def test_final_archive_failures_keep_trace_and_summary_stop(self):  # T101-13
        original = transport.atomic_write_text
        for filename in ('response.txt', 'capture.json'):
            self.stop.unlink(missing_ok=True)
            def fault(path, *args, **kwargs):
                if Path(path).name == filename:
                    raise PermissionError('Synthetic final archive fault')
                return original(path, *args, **kwargs)
            with patch.object(transport, 'atomic_write_text', side_effect=fault):
                summary, payload, calls = self.build([{'events':[RECONNECT], 'stop':True, 'mode':'wait'}])
            self.assertEqual((payload['exit_code'], calls), (7, 1))
            self.assertEqual(payload['process_stop_details'], STOP)
            self.assertEqual(payload['execution_error']['code'], 'codex_io_failed')
            trace = summary.run_history[0]
            self.assertEqual(trace.capture['status'], 'failed')
            self.assertTrue(trace.process_stop_triggered)
            self.assertEqual(len(trace.stream_diagnostics), 1)

    def test_unwritable_pretty_log_does_not_lose_stop_in_autobuild(self):
        # The real collector handles a broken pretty log; AutoBuild must not
        # then throw away its returned trace while printing a duplicate error.
        original = transport.append
        def fault(path, line):
            if Path(path).name == 'pretty.log' and ('[reconnect]' in line or self.stop.exists()):
                raise PermissionError('Synthetic pretty-log fault')
            return original(path, line)
        with patch.object(transport, 'append', side_effect=fault), patch.object(autobuild, 'append', side_effect=fault):
            summary, payload, calls = self.build([{'events':[RECONNECT], 'mode':'wait', 'stop':True}])
        self.assertEqual((payload['exit_code'],calls), (7,1))
        self.assertEqual(payload['process_stop_details'],STOP)
        self.assertTrue(payload['execution_error']['archive_errors'])
        self.assertEqual(summary.run_history[0].process_stop_details,STOP)

    def test_broken_pipe_after_shutdown_is_diagnostic_in_both_queue_paths(self):  # T101-14
        for drain in (False, True):
            self.stop.unlink(missing_ok=True)
            diagnostic = dict(type='stdin_write_error', source='stdin', message='Synthetic broken pipe',
                              during_shutdown=True, exception_type='BrokenPipeError', errno=32)
            with self.io_fault(diagnostic, drain=drain, after_shutdown=True):
                result = self.execute({'events':[RECONNECT], 'stop':True, 'mode':'wait'})
            self.assertEqual(result.execution.status, ExecutionStatus.CANCELLED)
            self.assertEqual(result.trace.process_stop_details, STOP)
            self.assertIn(diagnostic, result.trace.capture['diagnostics'])
            self.assertNotIn(diagnostic, result.trace.stream_errors)

    def test_stdin_fault_before_shutdown_is_fatal_in_both_queue_paths(self):  # T101-15
        for drain in (False, True):
            self.stop.unlink(missing_ok=True)
            diagnostic = dict(type='stdin_write_error', source='stdin', message='Synthetic early pipe fault',
                              during_shutdown=False, exception_type='BrokenPipeError', errno=32)
            with self.io_fault(diagnostic, drain=drain):
                result = self.execute({'events':[RECONNECT], 'stop':True, 'mode':'wait'})
            self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
            self.assertTrue(result.trace.process_stop_triggered)
            self.assertIn(diagnostic, result.trace.stream_errors)
            self.assertTrue(result.trace.process_stop_details)

    def test_during_shutdown_does_not_excuse_nonpipe_errors(self):  # T101-14/15
        for exception, errno in (('PermissionError',13), ('ValueError',None), ('OSError',5), (None,None)):
            self.stop.unlink(missing_ok=True)
            diagnostic = dict(type='stdin_write_error', source='stdin', message='Synthetic write fault',
                              during_shutdown=True, exception_type=exception, errno=errno)
            with self.io_fault(diagnostic, after_shutdown=True):
                result = self.execute({'events':[RECONNECT], 'stop':True, 'mode':'wait'})
            self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
            self.assertIn(diagnostic, result.trace.stream_errors)
        self.assertFalse(transport.expected_stdin_abort(
            dict(type='stdin_write_error', source='stdin', during_shutdown=True, exception_type='BrokenPipeError'),
            shutdown_started=False))

    def test_stop_observed_after_io_cleanup_started_is_retained(self):  # T101-16
        original = transport._terminate_process_group
        def cleanup(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get('reason') == 'stream_error':
                self.stop.write_text(STOP, encoding='utf-8')
            return result
        diagnostic = dict(type='read_error', source='stdout', message='Synthetic first failure',
                          during_shutdown=False, exception_type='OSError', errno=5)
        with patch.object(transport, '_terminate_process_group', side_effect=cleanup), self.io_fault(diagnostic):
            result = self.execute({'events':[RECONNECT], 'mode':'wait'})
        self.assertEqual(result.execution.status, ExecutionStatus.FAILED)
        self.assertEqual(result.trace.process_stop_details, STOP)
        self.assertEqual(result.trace.capture['process_tree']['reason'], 'stream_error')

    def test_timeout_remains_primary_when_stop_is_observed_later(self):  # T101-16
        original = transport._terminate_process_group
        def cleanup(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get('reason') == 'total_timeout':
                self.stop.write_text(STOP, encoding='utf-8')
            return result
        with patch.object(transport, '_terminate_process_group', side_effect=cleanup):
            result = self.execute({'events':[RECONNECT], 'mode':'activity'}, replace(self.request(),
                timeouts=transport.TransportTimeouts(total=.6, stall=2, kill_grace=.05)))
        self.assertEqual(result.trace.execution_error['code'], 'codex_timeout')
        self.assertTrue(result.trace.process_stop_triggered)
        self.assertEqual(result.trace.process_stop_details, STOP)
        self.assertEqual(result.trace.capture['process_tree']['reason'], 'total_timeout')

class DecideReturnTests(Fixture):
    def test_legacy_decide_failed_and_cancelled_preserve_stop(self):  # T101-26/34
        for failed in (False, True):
            self.stop.unlink(missing_ok=True)
            trace = transport.RunResult(process_stop_triggered=True, process_stop_details=STOP,
                                        capture_dir=self.base/'synthetic-decide')
            if failed:
                trace.execution_error = execution_error('Synthetic decide I/O failure', code='codex_io_failed', phase='decide')
                execution = ExecutionResult(status=ExecutionStatus.FAILED,
                    failure=Failure(kind=FailureKind.EXECUTION, code='codex_io_failed', message='Synthetic decide failure', phase='decide'))
            else:
                execution = ExecutionResult(status=ExecutionStatus.CANCELLED, cancellation_reason=STOP)
            call = SimpleNamespace(result=SimpleNamespace(execution=execution),
                                   attempt=SimpleNamespace(result=SimpleNamespace(trace=trace)))
            # Even a misleading legacy error label must not swallow a real trace error.
            failure = autobuild.RequiredDecisionError('decision_cancelled', 'Legacy decide label', call)
            with patch.object(autobuild, 'evaluate_completion_decision', side_effect=failure), \
                 patch.object(autobuild, '_decision_archive_payload', return_value={'directory':'synthetic-archive'}):
                summary, payload, calls = self.build([{'events':[ANSWER, COMPLETE]},
                    {'events':[answer('No issues found.'), COMPLETE]}])
            self.assertEqual(calls, 2)
            self.assertEqual(payload['exit_code'], 7 if failed else 6)
            self.assertFalse(payload['completed'])
            self.assertTrue(payload['process_stop_triggered'])
            self.assertEqual(payload['process_stop_details'], STOP)
            self.assertEqual(payload['terminal_attempt']['phase'], 'decide')
            self.assertIsNone(payload['decision']['selected_option'])
            if failed:
                self.assertEqual(payload['execution_error']['code'], 'codex_io_failed')
            else:
                self.assertIsNone(payload['execution_error'])

if __name__ == '__main__':
    unittest.main()
