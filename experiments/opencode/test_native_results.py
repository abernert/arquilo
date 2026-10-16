# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""A narrow observed workaround must never conceal unrelated API failures."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.error
from native_results import read_structured_result


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name)
        self.result = {'info': {'id': 'msg_result', 'sessionID': 'ses_test', 'parentID': 'msg_question',
                               'structured': {'answer': 42}}, 'parts': []}
        self.client = Mock()

    def error(self, code=400, message='OutputFormatJsonSchema'):
        return urllib.error.HTTPError('http://127.0.0.1/session', code, message, {}, io.BytesIO())

    def test_all_native_endpoints_work(self):
        self.client.call.side_effect = [self.result, [self.result], [self.result]]
        result, limitation = read_structured_result(self.client, 'ses_test', self.result, self.logs)
        self.assertIsNone(limitation)
        self.assertEqual(result, [self.result])
        self.assertEqual([c.args[0] for c in self.client.call.call_args_list], [
            '/session/ses_test/message/msg_result', '/session/ses_test/message?limit=1', '/session/ses_test/message'])
        self.assertTrue(all(len(c.args) == 1 and not c.kwargs for c in self.client.call.call_args_list))

    def test_known_history_failure_is_recorded_not_reported_as_full_success(self):
        self.client.call.side_effect = [self.result, [self.result], self.error()]
        _, limitation = read_structured_result(self.client, 'ses_test', self.result, self.logs)
        self.assertEqual(limitation['code'], 'structured_history_http_400')
        observation = json.loads((self.logs/'structured-history-observation.json').read_text())
        self.assertEqual(observation['status'], 'KNOWN_UPSTREAM_FAILURE')

    def test_unrelated_errors_are_not_downgraded(self):
        for code, text in [(401, 'OutputFormatJsonSchema'), (400, 'Other error'), (500, 'OutputFormatJsonSchema')]:
            self.client.call.side_effect = [self.result, [self.result], self.error(code, text)]
            with self.subTest(code=code, text=text), self.assertRaises(urllib.error.HTTPError):
                read_structured_result(self.client, 'ses_test', self.result, self.logs)

    def test_targeted_endpoint_failure_is_not_ignored(self):
        self.client.call.side_effect = self.error()
        with self.assertRaises(urllib.error.HTTPError):
            read_structured_result(self.client, 'ses_test', self.result, self.logs)

    def test_foreign_stale_different_or_failed_result_is_rejected(self):
        for key, value in [('id','msg_other'), ('sessionID','ses_other'), ('parentID','msg_other'),
                           ('structured',{'answer':43}), ('error',{'name':'APIError'})]:
            wrong = deepcopy(self.result); wrong['info'][key] = value
            self.client.call.side_effect = [wrong]
            with self.subTest(key=key), self.assertRaises(AssertionError):
                read_structured_result(self.client, 'ses_test', self.result, self.logs)

    def test_latest_endpoint_must_confirm_same_assistant(self):
        self.client.call.side_effect = [self.result, []]
        with self.assertRaises(AssertionError):
            read_structured_result(self.client, 'ses_test', self.result, self.logs)


if __name__ == '__main__':
    unittest.main()
