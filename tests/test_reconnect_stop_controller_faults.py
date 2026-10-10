# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""End-to-end synthetic I/O failures with stops, including real parallel workers."""
import json
from pathlib import Path

from test_reconnect_stop_controller import ControllerFixture
from test_reconnect_stop import RECONNECT, WORK, STOP
import test_reconnect_stop_faults as faults


class ControllerIOTests(ControllerFixture):
    def test_collector_io_failures_reach_controller_with_stop(self):
        for kind, exception, errno in (('read_error', 'OSError', 5),
                                        ('stdin_write_error', 'BrokenPipeError', 32)):
            with self.subTest(kind=kind):
                self.stop.unlink(missing_ok=True)
                diagnostic = {'type': kind, 'source': 'stdin' if kind == 'stdin_write_error' else 'stdout',
                              'message': 'Synthetic early I/O fault', 'exception_type': exception,
                              'errno': errno, 'during_shutdown': False}
                with faults.FaultTests.io_fault(self, diagnostic):
                    runner, _, calls = self.run_scenarios([
                        {'events': [RECONNECT, WORK], 'mode': 'wait', 'stop': True}])
                self.assertEqual(calls, 1)
                self.verify_logs(runner, code=7, terminal_phase='task', index=1)
                for record in runner.task_log_records.values():
                    summary = json.loads((record.log_dir / 'autobuild_summary.json').read_text(encoding='utf-8'))
                    capture = json.loads((Path(summary['terminal_attempt']['capture_directory']) / 'capture.json').read_text(encoding='utf-8'))
                    self.assertIn(diagnostic, capture['stream_errors'])
                runner.close()

    def test_decode_failure_and_stop_cross_real_parallel_worker_boundary(self):
        self.todo.write_text('***CFG workspace=one parallel=pair***\n1. ***TASK***: Synthetic parallel one.\n'
                             '***CFG workspace=two parallel=pair***\n2. ***TASK***: Synthetic parallel two.\n'
                             '3. ***TASK***: Must not run.\n', encoding='utf-8')
        runner, _, calls = self.run_scenarios([
            {'events': [RECONNECT, WORK], 'bad_utf8': True, 'mode': 'wait', 'stop': True}], worker=True)
        self.assertEqual(calls, 2)
        self.verify_logs(runner, code=7, terminal_phase='task', index=1, next_id='3')
        for record in runner.task_log_records.values():
            summary = json.loads((record.log_dir / 'autobuild_summary.json').read_text(encoding='utf-8'))
            capture = json.loads((Path(summary['terminal_attempt']['capture_directory']) / 'capture.json').read_text(encoding='utf-8'))
            self.assertTrue(any(error['type'] == 'decode_error' for error in capture['stream_errors']))
            self.assertEqual(capture['cancellation_reason'], STOP)
