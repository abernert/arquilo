# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Regressions from native 2.1.303 recordings; no CLI, model or network."""
import json
from pathlib import Path
import tempfile
import unittest

from agent_types import RunResult
from claude_transport import ClaudeProtocol, ClaudeRequest


class NativeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.request = ClaudeRequest(prompt='Synthetic test', cwd=root, env={},
                                     raw_log=root/'raw', pretty_log=root/'pretty',
                                     sandbox='read-only')
        self.trace = RunResult()
        self.protocol = ClaudeProtocol(self.request)

    def send(self, event):
        return self.protocol.accept(json.dumps({'session_id': self.request.session_id, **event}), self.trace)

    def init(self, **extra):
        return {'type': 'system', 'subtype': 'init', 'permissionMode': 'dontAsk',
                'tools': ['Read', 'Glob', 'Grep'], **extra}

    def ui(self, **extra):
        return {'type': 'system', 'subtype': 'ui_invalidate', 'event': 'ui.render',
                'uuid': '1aec5a14-4258-4639-bfb9-53e8760df68c', **extra}

    def test_ui_before_and_after_init_never_completes(self):
        self.assertFalse(self.send(self.ui()))
        self.assertFalse(self.protocol.initialized)
        self.assertFalse(self.send(self.init()))
        self.assertFalse(self.send(self.ui()))
        self.assertFalse(self.trace.turn_completed)
        self.assertTrue(self.send({'type':'result', 'subtype':'success', 'is_error':False,
                                   'result':'Actual completed result'}))
        with self.assertRaises(ValueError):
            self.send(self.ui())

    def test_ui_exception_is_narrow_and_session_bound(self):
        for extra in ({'event':'tool.run'}, {'tool':'Bash'}, {'uuid':None},
                      {'session_id':'foreign'}, {'subtype':'unknown'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.send(self.ui(**extra))
        self.assertFalse(self.protocol.initialized)
        self.assertFalse(self.trace.turn_completed)

    def test_measured_bundled_components_are_recorded(self):
        plugins = [{'name': name, 'path':'builtin', 'source':name+'@builtin'}
                   for name in ('cc-plugin-agents-md', 'cc-plugin-plugin-authoring')]
        self.send(self.init(plugins=plugins))
        self.assertEqual(self.trace.capture['runtime_components'], plugins)
        self.assertTrue(self.trace.capture['verified_init'])
        self.assertFalse(self.trace.turn_completed)

    def test_installed_unknown_and_lookalike_components_rejected(self):
        good = {'name':'cc-plugin-agents-md', 'path':'builtin', 'source':'cc-plugin-agents-md@builtin'}
        for plugins in ('builtin', [good, good], [{**good,'path':'/tmp/plugin'}],
                        [{**good,'source':'cc-plugin-agents-md@other'}],
                        [{**good,'name':'unknown'}], [{**good,'hook':'run'}], [None]):
            self.protocol = ClaudeProtocol(self.request)
            with self.subTest(plugins=plugins), self.assertRaises(ValueError):
                self.send(self.init(plugins=plugins))
            self.assertFalse(self.protocol.initialized)

    def test_native_startup_error_retains_cause_without_init(self):
        with self.assertRaisesRegex(ValueError, 'Sandbox required but unavailable'):
            self.send({'type':'result', 'subtype':'error_during_execution', 'is_error':True,
                       'errors':['Sandbox required but unavailable']})
        self.assertFalse(self.protocol.initialized)
        self.assertFalse(self.trace.turn_completed)
        self.assertEqual(self.trace.capture['native_error']['errors'], ['Sandbox required but unavailable'])

    def test_failure_or_success_cannot_use_diagnostic_instead_of_init(self):
        self.send(self.ui())
        with self.assertRaisesRegex(ValueError, 'before verified init'):
            self.send({'type':'result','subtype':'success','is_error':False,'result':'not authorized'})
        with self.assertRaisesRegex(ValueError, 'foreign session'):
            self.send({'type':'result','is_error':True,'session_id':'other'})
        self.assertFalse(self.trace.turn_completed)

    def test_mcp_skills_and_plugin_errors_still_rejected(self):
        for field in ('mcp_servers','mcp_server_errors','skills','slash_commands','plugin_errors'):
            self.protocol = ClaudeProtocol(self.request)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.send(self.init(**{field:['unapproved']}))
            self.assertFalse(self.protocol.initialized)


if __name__ == '__main__':
    unittest.main()
