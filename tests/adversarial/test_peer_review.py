# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Independent integration regressions; synthetic files and local Git only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from reviewed_git import ReviewedGit, ReviewedGitError
import safe_io
from todo_lint import lint_todo_file
from todo_syntax import task_headers


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class PeerGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='arquilo-peer-git-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'
        self.work.mkdir()
        self.state = self.base / 'state'
        self.state.mkdir(mode=0o700)
        home = self.base / 'home'
        home.mkdir()
        env = patch.dict(os.environ, {'HOME': str(home), 'USERPROFILE': str(home),
                                     'XDG_CONFIG_HOME': str(home / '.config')})
        env.start()
        self.addCleanup(env.stop)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Reviewer')
        self.git('config', 'user.email', 'reviewer@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        (self.work / 'output.txt').write_bytes(b'original\n')
        self.git('add', '--', 'output.txt')
        self.git('commit', '-qm', 'base')
        self.remote = self.base / 'remote.git'
        self.git('init', '--bare', '-q', str(self.remote))
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-qu', 'origin', 'HEAD')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.work, check=True,
                              capture_output=True, timeout=15).stdout

    def assert_only_reviewed_ref_pushed(self, selection):
        (self.work / 'output.txt').write_bytes(b'reviewed\n')
        result = selection.commit('reviewed output')
        self.assertTrue(result['pushed'])
        self.assertEqual(self.git('--git-dir', str(self.remote), 'for-each-ref',
                                  '--format=%(refname)').splitlines(),
                         [selection.remote_branch.encode()])
        self.assertEqual(self.git('--git-dir', str(self.remote), 'show',
                                  selection.remote_branch + ':output.txt'), b'reviewed\n')
        self.assertEqual(self.git('tag', '--list').splitlines(), [b'local-only-tag'])
        self.assertEqual(self.git('config', '--get', 'push.followTags').strip(), b'true')

    def test_follow_tags_config_does_not_expand_approved_push(self):
        self.git('tag', '-a', 'local-only-tag', '-m', 'Not approved for publication')
        self.git('config', 'push.followTags', 'true')
        selection = ReviewedGit(self.work, ['output.txt'], self.state, push=True)
        self.assert_only_reviewed_ref_pushed(selection)

    def test_follow_tags_enabled_after_start_does_not_expand_push(self):
        selection = ReviewedGit(self.work, ['output.txt'], self.state, push=True)
        self.git('tag', '-a', 'local-only-tag', '-m', 'Not approved for publication')
        self.git('config', 'push.followTags', 'true')
        self.assert_only_reviewed_ref_pushed(selection)

    def test_url_rewrite_change_is_rejected_before_commit(self):
        selection = ReviewedGit(self.work, ['output.txt'], self.state, push=True)
        old = self.git('rev-parse', 'HEAD')
        other = self.base / 'other.git'
        self.git('init', '--bare', '-q', str(other))
        self.git('config', 'url.' + str(other) + '.insteadOf', str(self.remote))
        (self.work / 'output.txt').write_bytes(b'reviewed\n')
        with self.assertRaisesRegex(ReviewedGitError, 'destination changed'):
            selection.commit('must stop')
        self.assertEqual(self.git('rev-parse', 'HEAD'), old)
        self.assertEqual(self.git('--git-dir', str(other), 'for-each-ref'), b'')

    def test_removing_pinned_pushurl_is_rejected_before_commit(self):
        other = self.base / 'other.git'
        self.git('init', '--bare', '-q', str(other))
        self.git('config', 'remote.origin.pushurl', str(other))
        selection = ReviewedGit(self.work, ['output.txt'], self.state, push=True)
        old = self.git('rev-parse', 'HEAD')
        self.git('config', '--unset', 'remote.origin.pushurl')
        (self.work / 'output.txt').write_bytes(b'reviewed\n')
        with self.assertRaisesRegex(ReviewedGitError, 'destination changed'):
            selection.commit('must stop')
        self.assertEqual(self.git('rev-parse', 'HEAD'), old)
        self.assertEqual(self.git('--git-dir', str(other), 'for-each-ref'), b'')


class PeerParserTests(IsolatedControllerCase):
    def test_up_to_three_spaces_remain_real_tasks(self):
        for indent in ('', ' ', '  ', '   '):
            with self.subTest(indent=repr(indent)):
                self.assertEqual([m.group(1) for _, m in task_headers(
                    indent + '1. ***Task***: Visible.\n')], ['1'])

    def test_indented_stop_before_task_is_not_scheduler_control(self):
        for indent in ('    ', '\t', '   \t'):
            with self.subTest(indent=repr(indent)):
                plan = 'Example:\n\n' + indent + '***STOP***\n1. ***Task***: Visible.\n'
                self.write_plan(plan)
                self.assertEqual(lint_todo_file(self.todo, workdir=self.work), [])
                runner = self.runner()
                try:
                    item, = runner._parse_todo_file()
                    self.assertFalse(runner._stop_marker_before(item))
                    self.assertEqual(runner._next_todo().identifier, '1')
                finally:
                    runner.close()
                # The next subcase is a new owner plan, not an in-place adoption.
                for path in self.state_root.iterdir():
                    if path.is_dir():
                        shutil.rmtree(path)

    def test_indented_fence_cannot_end_real_fenced_example(self):
        text = ('```text\n    ```\n77. ***Task***: Still an example.\n'
                '```\n1. ***Task***: Visible.\n')
        self.assertEqual([m.group(1) for _, m in task_headers(text)], ['1'])

    def test_indented_comment_end_does_not_hide_following_task(self):
        text = '<!--\n 77. ***Task***: Hidden.\n    -->\n1. ***Task***: Visible.\n'
        self.assertEqual([m.group(1) for _, m in task_headers(text)], ['1'])


class PeerReadTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan('1. ***Task***: Inspect proof.\n')

    def hardlink(self, source, destination):
        try:
            os.link(source, destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Native hardlink creation unavailable: {exc}')

    def test_feedback_hardlink_refuses_without_reading_or_writing_victim(self):
        runner = self.runner()
        victim = self.victims / 'report'
        original = b'\xff\xfeSYNTHETIC_PRIVATE_BYTES'
        victim.write_bytes(original)
        destination = self.work / 'todo_result_1.md'
        self.hardlink(victim, destination)
        with self.assertRaises(safe_io.UnsafePathError):
            runner._record_review(destination, 'review', '1')
        self.assertEqual(victim.read_bytes(), original)
        self.assertEqual(json.loads(safe_io.read_text(runner.state_dir / 'plan.json'))['text'],
                         self.todo.read_text(encoding='utf-8'))

    def test_breakdown_hardlink_refuses_without_trusting_round(self):
        runner = self.runner()
        directory = runner.state_dir / 'breakdowns' / '1'
        safe_io.mkdir(directory)
        victim = self.victims / 'round.json'
        victim.write_bytes(b'{"round": 999}')
        destination = directory / 'breakdown_plan.json'
        self.hardlink(victim, destination)
        with self.assertRaises(safe_io.UnsafePathError):
            runner._infer_breakdown_round('1')
        self.assertEqual(victim.read_bytes(), b'{"round": 999}')
        destination.unlink()
        destination.write_bytes(b'{"round": 2}')
        self.assertEqual(runner._infer_breakdown_round('1'), 2)


if __name__ == '__main__':
    unittest.main()
