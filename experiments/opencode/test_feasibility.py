# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline checks of the spike's verdict logic, not of OpenCode itself."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from feasibility import terminal, test_environment, configuration


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.message = {'info': {'role': 'assistant', 'sessionID': 's',
                        'time': {'completed': 1}, 'finish': 'stop'}, 'parts': []}

    def test_complete_assistant(self):
        self.assertTrue(terminal(self.message, 's'))

    def test_foreign_session_rejected(self):
        self.assertFalse(terminal(self.message, 'other'))

    def test_error_never_success(self):
        self.message['info']['error'] = {'name': 'APIError'}
        self.assertFalse(terminal(self.message, 's'))

    def test_user_never_success(self):
        self.message['info']['role'] = 'user'
        self.assertFalse(terminal(self.message, 's'))

    def test_no_terminal_timestamp_rejected(self):
        self.message['info']['time'] = {}
        self.assertFalse(terminal(self.message, 's'))

    def test_truncated_or_unknown_finishes_rejected(self):
        for finish in ('length', 'content-filter', 'unknown', 'arbitrary', None):
            self.message['info']['finish'] = finish
            self.assertFalse(terminal(self.message, 's'))

    def test_verified_internal_structured_completion(self):
        self.message['info'].update(finish='tool-calls', structured={'answer': 42})
        self.message['parts'] = [{'type': 'tool', 'tool': 'StructuredOutput', 'state': {'status': 'completed'}}]
        self.assertTrue(terminal(self.message, 's'))
        self.message['parts'][0]['tool'] = 'write'
        self.assertFalse(terminal(self.message, 's'))

    def test_tool_round_not_final(self):
        self.message['info']['finish'] = 'tool-calls'
        self.assertFalse(terminal(self.message, 's'))

    def test_live_tool_not_final(self):
        for state in ('pending', 'running'):
            self.message['parts'] = [{'type': 'tool', 'state': {'status': state}}]
            self.assertFalse(terminal(self.message, 's'))

    def test_no_implicit_host_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'PRIVATE',
                   'DATABRICKS_TOKEN': 'PRIVATE', 'GH_TOKEN': 'PRIVATE', 'OPENCODE_CONFIG_CONTENT': 'PRIVATE'}):
            env = test_environment(Path(tmp))
            self.assertNotIn('PRIVATE', repr(env))
            self.assertNotIn('OPENCODE_CONFIG_CONTENT', env)
            self.assertEqual(env['NO_PROXY'], '127.0.0.1,localhost')

    def test_fixture_role_separation(self):
        config = configuration(12345)
        self.assertEqual(config['model'], config['small_model'])
        self.assertEqual(config['enabled_providers'], ['spike'])
        self.assertEqual(config['share'], 'disabled')
        self.assertEqual(config['agent']['spike_read']['permission']['*'], 'deny')
        self.assertNotIn('edit', config['agent']['spike_read']['permission'])
        self.assertEqual(config['agent']['spike_write']['permission']['edit'], 'allow')
        self.assertEqual(config['agent']['spike_ask']['permission']['edit'], 'ask')
        self.assertEqual(config['agent']['spike_decide']['permission'], {'*': 'deny', 'StructuredOutput': 'allow'})


if __name__ == '__main__':
    unittest.main()
