# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Git publication keeps native Windows long-path support command-scoped."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import git_snapshot
from reviewed_git import ReviewedGit


class GitLongPathPolicyTests(unittest.TestCase):
    def test_long_paths_are_pinned_without_changing_host_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            publisher = ReviewedGit.__new__(ReviewedGit)
            publisher.environment = {'PATH': os.environ.get('PATH', '')}
            publisher.executable = 'git'
            publisher.empty = root / 'empty'
            publisher.workspace = root / 'workspace'
            publisher.directory = root / 'private'
            publisher.git_directory = publisher.workspace / '.git'
            publisher.publication = publisher.directory / 'publication.git'
            publisher.identity = {}
            publisher.transport_config = [('core.longpaths', 'false')]
            original = dict(publisher.environment)
            for private in (False, True):
                with self.subTest(private=private), patch('reviewed_git.subprocess.run') as run:
                    run.return_value = subprocess.CompletedProcess([], 0, b'OK', b'')
                    self.assertEqual(publisher.git('rev-parse', 'HEAD', private=private), b'OK')
                    command = run.call_args.args[0]
                    self.assertIn('core.longpaths=true', command)
                    self.assertEqual(command[command.index('core.longpaths=true') - 1], '-c')
                    if private:
                        self.assertIn('--git-dir=publication.git', command)
                        self.assertEqual(run.call_args.kwargs['cwd'], publisher.directory)
                    self.assertFalse(run.call_args.kwargs['shell'])
                    self.assertEqual(publisher.environment, original)


@unittest.skipUnless(shutil.which('git'), 'Git required')
class GitLongPathIntegrationTests(unittest.TestCase):
    def test_deep_private_state_preserves_reviewed_binary_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / 'workspace'
            workspace.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-c', 'core.longpaths=true', *args],
                    cwd=workspace, stderr=subprocess.PIPE)
            git('init', '-q')
            git('config', 'user.name', 'Synthetic Long Path')
            git('config', 'user.email', 'long-path@example.invalid')
            git('config', 'commit.gpgsign', 'false')
            git('config', 'core.longpaths', 'false')
            selected = workspace / 'output.bin'
            selected.write_bytes(b'initial\x00bytes')
            git('add', '--', 'output.bin')
            git('commit', '-qm', 'initial')
            config_before = (workspace / '.git' / 'config').read_bytes()
            state = root / 'private' / ('a' * 55) / ('b' * 55)
            state.mkdir(parents=True)
            publisher = ReviewedGit(workspace, ['output.bin'], state)
            longest_pack = publisher.publication / 'objects' / 'pack' / ('pack-' + '0' * 40 + '.pack')
            self.assertGreater(len(str(longest_pack)), 260)
            expected = bytes(range(256)) * 3 + b'\r\nreviewed\x00'
            selected.write_bytes(expected)
            request = publisher.begin_review(run='long-path', task='1', attempt='1')
            token, review_cwd = git_snapshot.capture(request, workspace, 1)
            self.assertEqual(review_cwd, workspace)
            mirror = Path(request['directory']) / token['candidate'] / 'workspace'
            self.assertEqual((mirror / 'output.bin').read_bytes(), expected)
            # Synthetic successful review: no model or provider is invoked.
            candidate = publisher.accept_review(request, token, review_index=1)
            result = publisher.commit('reviewed long path', candidate=candidate)
            self.assertEqual(git('show', result['commit'] + ':output.bin'), expected)
            self.assertEqual((workspace / '.git' / 'config').read_bytes(), config_before)
            self.assertFalse((workspace / '.git' / 'index.lock').exists())


if __name__ == '__main__':
    unittest.main()
