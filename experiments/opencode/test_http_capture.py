# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Tests of bounded HTTP diagnostics; no external network or credentials."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.error
from feasibility import Client


class HttpCaptureTests(unittest.TestCase):
    def test_error_identity_body_and_status_survive_capture(self):
        for status in (400, 401, 500):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                client = Client('http://127.0.0.1:12345', 'LOCAL_PASSWORD_SENTINEL')
                client.logs = Path(tmp)
                error = urllib.error.HTTPError(client.url + '/example', status, 'Example', {},
                                                io.BytesIO(b'{"message":"synthetic detail"}'))
                client.opener = Mock()
                client.opener.open.side_effect = error
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    client.call('/example')
                self.assertIs(ctx.exception, error)
                self.assertEqual(error.code, status)
                self.assertIn('synthetic detail', str(error))
                files = list(client.logs.glob('http-error-*.json'))
                self.assertEqual(len(files), 1)
                raw = files[0].read_text(encoding='utf-8')
                report = json.loads(raw)
                self.assertEqual(report['status'], status)
                self.assertEqual(report['method'], 'GET')
                self.assertEqual(report['path'], '/example')
                self.assertNotIn('LOCAL_PASSWORD_SENTINEL', raw)
                self.assertNotIn(client.auth, raw)

    def test_empty_success_is_valid_for_prompt_async(self):
        client = Client('http://127.0.0.1:12345', 'unused')
        client.opener = Mock()
        client.opener.open.return_value = io.BytesIO(b'')
        self.assertIsNone(client.call('/session/s/prompt_async', 'POST', {'parts': []}))

    def test_missing_diagnostic_sink_does_not_mask_http_error(self):
        client = Client('http://127.0.0.1:12345', 'unused')
        client.opener = Mock()
        client.opener.open.side_effect = urllib.error.HTTPError(
            client.url, 401, 'Unauthorized', {}, io.BytesIO(b''))
        with self.assertRaises(urllib.error.HTTPError):
            client.open('/session', auth=False)


if __name__ == '__main__':
    unittest.main()
