# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Synthetic process-group races; genuine cleanup failures must remain fatal."""
import errno
import os
import signal
import unittest
from unittest.mock import Mock, patch

import process_tree
from test_reconnect_stop import Fixture, WORK, ANSWER, COMPLETE, RECONNECT
from runtime_contracts import ExecutionStatus


@unittest.skipUnless(os.name == "posix", "POSIX process-group semantics")
class ProcessGroupRaceTests(unittest.TestCase):
    def run_cleanup(self, effect, *, platform="darwin", grace=0):
        tree = process_tree.ProcessTree()
        proc = Mock(pid=424242)
        proc.poll.side_effect = [None, -signal.SIGTERM]
        proc.wait.return_value = -signal.SIGTERM
        tree.bind(proc)
        with patch.object(process_tree.sys, "platform", platform), \
             patch.object(process_tree.os, "killpg", side_effect=effect) as kill:
            result = tree.terminate(reason="synthetic stop", grace_seconds=grace)
        tree.close()
        return result, kill.call_args_list

    def test_absent_group_does_not_receive_redundant_kill(self):
        def send(pid, sig):
            if sig == 0:
                raise ProcessLookupError(errno.ESRCH, "synthetic absent group")
            self.assertEqual(sig, signal.SIGTERM)
        result, calls = self.run_cleanup(send, grace=1)
        self.assertFalse(result.errors)
        self.assertEqual([call.args[1] for call in calls], [signal.SIGTERM, 0])

    def test_darwin_reaps_killed_leader_then_requires_absent_group(self):
        def send(pid, sig):
            if sig == signal.SIGKILL:
                raise PermissionError(errno.EPERM, "synthetic zombie-only group")
            if sig == 0:
                raise ProcessLookupError(errno.ESRCH, "absent after reaping")
        result, calls = self.run_cleanup(send)
        self.assertFalse(result.errors)
        self.assertTrue(result.forced_parent_exit)
        self.assertEqual(result.parent_exit_after, -signal.SIGTERM)
        self.assertEqual(result.actions, ["SIGTERM", "group_absent_after_reap"])
        self.assertEqual([call.args[1] for call in calls], [signal.SIGTERM, signal.SIGKILL, 0])

    def test_live_or_inaccessible_descendant_keeps_permission_failure(self):
        for inaccessible in (False, True):
            def send(pid, sig):
                if sig == signal.SIGKILL or (sig == 0 and inaccessible):
                    raise PermissionError(errno.EPERM, "synthetic real permission failure")
            result, calls = self.run_cleanup(send)
            self.assertTrue(result.errors)
            self.assertNotIn("group_absent_after_reap", result.actions)
            self.assertEqual([call.args[1] for call in calls].count(signal.SIGKILL), 2)

    def test_first_signal_permission_failure_is_not_excused(self):
        def send(pid, sig):
            raise PermissionError(errno.EPERM, "synthetic initial denial")
        result, _ = self.run_cleanup(send)
        self.assertTrue(result.errors)
        self.assertFalse(result.forced_parent_exit)
        self.assertFalse(result.actions)

    def test_other_platforms_do_not_gain_permission_exception(self):
        def send(pid, sig):
            if sig != signal.SIGTERM:
                raise PermissionError(errno.EPERM, "synthetic denied kill")
        result, calls = self.run_cleanup(send, platform="linux")
        self.assertTrue(result.errors)
        self.assertNotIn(0, [call.args[1] for call in calls])

    def test_live_group_still_receives_sigkill(self):
        result, calls = self.run_cleanup(lambda pid, sig: None)
        self.assertFalse(result.errors)
        self.assertIn(signal.SIGKILL, [call.args[1] for call in calls])
        self.assertEqual(result.actions, ["SIGTERM", "SIGKILL"])

    def test_natural_nonzero_exit_cannot_use_reap_exception(self):
        tree = process_tree.ProcessTree()
        proc = Mock(pid=424242)
        proc.poll.side_effect = [None, 1]
        proc.wait.return_value = 1
        tree.bind(proc)
        def send(pid, sig):
            if sig == signal.SIGKILL:
                raise PermissionError(errno.EPERM, "synthetic denied kill")
            if sig == 0:
                raise AssertionError("Natural failure cannot enter absence exception")
        with patch.object(process_tree.sys, "platform", "darwin"), \
             patch.object(process_tree.os, "killpg", side_effect=send):
            result = tree.terminate(reason="synthetic stop", grace_seconds=0)
        tree.close()
        self.assertTrue(result.errors)
        self.assertFalse(result.forced_parent_exit)


class RepeatedCleanupTests(Fixture):
    def test_repeated_real_stops_and_completed_turn_cleanup(self):
        for index in range(5):
            for completed in (False, True):
                with self.subTest(index=index, completed=completed):
                    self.stop.unlink(missing_ok=True)
                    spec = {"events": [RECONNECT, ANSWER, COMPLETE] if completed else [RECONNECT, WORK],
                            "mode": "wait", "stop": not completed}
                    result = self.execute(spec)
                    expected = ExecutionStatus.SUCCEEDED if completed else ExecutionStatus.CANCELLED
                    self.assertEqual(result.execution.status, expected, result.trace.execution_error)
                    self.assertFalse(result.trace.capture["process_tree"]["errors"])


if __name__ == "__main__":
    unittest.main()
