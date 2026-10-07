"""Offline Git boundary tests using disposable local repositories only."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reviewed_git import ReviewedGit, ReviewedGitError
from safe_io import UnsafePathError


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class GitSelectionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        for name in ('selected.txt', 'staged.txt', 'private.txt'):
            (self.work / name).write_text('original\n')
        self.git('add', '--', 'selected.txt', 'staged.txt', 'private.txt')
        self.git('commit', '-qm', 'base')

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(['git', *args], cwd=cwd or self.work,
                                capture_output=True, check=check, timeout=15)
        return result.stdout

    def bare(self, name):
        path = self.root / name
        self.git('init', '--bare', '-q', str(path))
        return path

    def tree_paths(self):
        return set(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', 'HEAD').split(b'\0')) - {b''}

    def test_literal_selection_preserves_unselected_index_and_bytes(self):
        (self.work / 'staged.txt').write_text('private staged\n')
        self.git('add', '--', 'staged.txt')
        (self.work / 'private.txt').write_text('private unstaged\n')
        (self.work / 'untracked-secret').write_text('private untracked\n')
        selected = ReviewedGit(self.work, ['selected.txt', '[literal].txt'], self.state)
        (self.work / 'selected.txt').write_text('approved\n')
        (self.work / '[literal].txt').write_text('literal\n')
        (self.work / 'literal.txt').write_text('not selected\n')
        result = selected.commit('local selection')
        self.assertFalse(result['pushed'])
        self.assertEqual(self.tree_paths(), {b'selected.txt', b'[literal].txt'})
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'approved\n')
        self.assertEqual(self.git('show', 'HEAD:[literal].txt'), b'literal\n')
        self.assertEqual(self.git('diff', '--cached', '--name-only').strip(), b'staged.txt')
        self.assertEqual(self.git('show', 'HEAD:private.txt'), b'original\n')
        self.assertEqual((self.work / 'untracked-secret').read_text(), 'private untracked\n')

    def test_invalid_and_option_like_selection(self):
        for value in ('../escape', '.git/config', '.codex_runs/raw', 'process_stop', str(self.root / 'escape'), ''):
            with self.subTest(value=value), self.assertRaises(ReviewedGitError):
                ReviewedGit(self.work, [value], self.state)
        # A colon is a valid literal on POSIX, but an invalid/stream component
        # under the native Windows controller path policy.
        names = ['-x.txt']
        if os.name == 'nt':
            with self.assertRaises(UnsafePathError):
                ReviewedGit(self.work, [':magic.txt'], self.state)
        else:
            names.append(':magic.txt')
        selected = ReviewedGit(self.work, names, self.state)
        for name in names:
            (self.work / name).write_text('literal\n', encoding='utf-8')
        selected.commit('literal option-like paths')
        self.assertEqual(self.tree_paths(), {os.fsencode(name) for name in names})

    def test_initial_dirty_staged_and_untracked_selection_rejected(self):
        for name, change in (
            ('selected.txt', lambda: (self.work / 'selected.txt').write_text('dirty')),
            ('staged.txt', lambda: (self.work / 'staged.txt').write_text('staged')),
            ('new.txt', lambda: (self.work / 'new.txt').write_text('untracked')),
        ):
            with self.subTest(name=name):
                change()
                if name == 'staged.txt':
                    self.git('add', '--', name)
                with self.assertRaises(ReviewedGitError):
                    ReviewedGit(self.work, [name], self.state)
                self.git('reset', '--hard', 'HEAD')
                (self.work / 'new.txt').unlink(missing_ok=True)

    def test_link_replacement_does_not_commit_outside_bytes(self):
        selected = ReviewedGit(self.work, ['selected.txt'], self.state)
        victim = self.root / 'victim'
        victim.write_text('sentinel\n')
        (self.work / 'selected.txt').unlink()
        try:
            (self.work / 'selected.txt').symlink_to(victim)
        except OSError:
            self.skipTest('symlink creation unavailable')
        old = self.git('rev-parse', 'HEAD')
        with self.assertRaises(UnsafePathError):
            selected.commit('linked')
        self.assertEqual(self.git('rev-parse', 'HEAD'), old)
        self.assertEqual(victim.read_text(), 'sentinel\n')

    def test_hardlink_replacement_and_selected_deletion(self):
        selected = ReviewedGit(self.work, ['selected.txt'], self.state)
        victim = self.root / 'victim'
        victim.write_text('sentinel\n')
        (self.work / 'selected.txt').unlink()
        try:
            os.link(victim, self.work / 'selected.txt')
        except OSError:
            self.skipTest('hardlink creation unavailable')
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaises(UnsafePathError):
            selected.commit('hardlinked')
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(victim.read_text(), 'sentinel\n')
        (self.work / 'selected.txt').unlink()
        result = selected.commit('selected deletion')
        self.assertEqual(result['paths'], ['selected.txt'])
        self.assertEqual(self.tree_paths(), {b'selected.txt'})
        self.assertNotIn(b'selected.txt\0', self.git('ls-tree', '-rz', '--name-only', 'HEAD'))

    def test_head_index_and_branch_change_refused(self):
        for mutation in ('head', 'index', 'branch'):
            with self.subTest(mutation=mutation):
                selected = ReviewedGit(self.work, ['selected.txt'], self.state)
                if mutation == 'head':
                    self.git('commit', '--allow-empty', '-qm', 'owner commit')
                elif mutation == 'index':
                    (self.work / 'staged.txt').write_text('owner staged')
                    self.git('add', '--', 'staged.txt')
                else:
                    self.git('switch', '-q', '-c', 'another')
                (self.work / 'selected.txt').write_text('worker output')
                current = self.git('rev-parse', 'HEAD')
                with self.assertRaises(ReviewedGitError):
                    selected.commit('must refuse')
                self.assertEqual(self.git('rev-parse', 'HEAD'), current)
                if mutation == 'branch':
                    self.git('switch', '-q', '-')
                    self.git('branch', '-D', 'another')
                elif mutation == 'index':
                    self.git('reset', '--hard', 'HEAD')
                else:
                    self.git('reset', '--hard', 'HEAD~1')
                (self.work / 'selected.txt').write_text('original\n')

    def test_explicit_push_and_unpushed_commit_gate(self):
        remote = self.bare('remote.git')
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        selected = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
        (self.work / 'selected.txt').write_text('approved\n')
        result = selected.commit('reviewed local push')
        self.assertTrue(result['pushed'])
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', selected.remote_branch).strip(),
                         result['commit'].encode())
        self.git('commit', '--allow-empty', '-qm', 'owner unpushed')
        with self.assertRaises(ReviewedGitError):
            ReviewedGit(self.work, ['selected.txt'], self.state, push=True)

    def test_configured_remote_is_unchanged_without_push_opt_in(self):
        remote = self.bare('remote.git')
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        branch = self.git('symbolic-ref', 'HEAD').strip().decode()
        original = self.git('--git-dir', str(remote), 'rev-parse', branch).strip()
        selected = ReviewedGit(self.work, ['selected.txt'], self.state)
        (self.work / 'selected.txt').write_text('local only\n')
        result = selected.commit('local only')
        self.assertFalse(result['pushed'])
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', branch).strip(), original)
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'local only\n')

    def test_commit_tree_failure_keeps_branch_and_remote_unchanged(self):
        remote = self.bare('remote.git')
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        selected = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
        original = self.git('rev-parse', 'HEAD').strip()
        (self.work / 'selected.txt').write_text('reviewed bytes\n')
        real_git = selected.git
        def fail_commit_tree(*args, **kwargs):
            if args[0] == 'commit-tree':
                raise ReviewedGitError('synthetic local commit-tree failure')
            return real_git(*args, **kwargs)
        with patch.object(selected, 'git', side_effect=fail_commit_tree):
            with self.assertRaisesRegex(ReviewedGitError, 'commit-tree failure'):
                selected.commit('must fail')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), original)
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', selected.remote_branch).strip(), original)

    def test_remote_divergence_refuses_push_and_reports_local_commit(self):
        remote = self.bare('remote.git')
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        selected = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
        initial_head = self.git('rev-parse', 'HEAD').strip()
        self.git('commit', '--allow-empty', '-qm', 'other local writer')
        other = self.git('rev-parse', 'HEAD').strip()
        self.git('push', '-q', 'origin', 'HEAD')
        self.git('reset', '--hard', initial_head.decode())
        (self.work / 'selected.txt').write_text('reviewed local bytes\n')
        with self.assertRaises(ReviewedGitError):
            selected.commit('push must fail')
        self.assertNotEqual(self.git('rev-parse', 'HEAD').strip(), initial_head)
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'reviewed local bytes\n')
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', selected.remote_branch).strip(), other)

    def test_changed_push_destination_is_rejected_before_commit(self):
        original = self.bare('original.git')
        redirect = self.bare('redirect.git')
        self.git('remote', 'add', 'origin', str(original))
        self.git('push', '-qu', 'origin', 'HEAD')
        selected = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
        initial_head = self.git('rev-parse', 'HEAD')
        (self.work / 'selected.txt').write_text('reviewed bytes\n')
        self.git('config', 'remote.origin.pushurl', str(redirect))
        try:
            result = selected.commit('must not redirect')
        except ReviewedGitError:
            pass
        else:
            redirected = self.git('--git-dir', str(redirect), 'rev-parse', selected.remote_branch).strip()
            self.assertEqual(redirected, result['commit'].encode())
            self.fail('push reached the changed local destination')
        self.assertEqual(self.git('rev-parse', 'HEAD'), initial_head)
        self.assertEqual(self.git('--git-dir', str(original), 'rev-parse', selected.remote_branch).strip(), initial_head.strip())
        self.assertNotEqual(self.git('--git-dir', str(redirect), 'rev-parse', selected.remote_branch, check=False).strip(), initial_head.strip())

    def test_multiple_push_destinations_are_rejected_at_start(self):
        first = self.bare('first.git')
        second = self.bare('second.git')
        self.git('remote', 'add', 'origin', str(first))
        self.git('push', '-qu', 'origin', 'HEAD')
        self.git('config', '--add', 'remote.origin.pushurl', str(first))
        self.git('config', '--add', 'remote.origin.pushurl', str(second))
        with self.assertRaisesRegex(ReviewedGitError, 'exactly one'):
            ReviewedGit(self.work, ['selected.txt'], self.state, push=True)

    def test_push_destination_change_after_local_commit_blocks_push(self):
        original = self.bare('original.git')
        redirect = self.bare('redirect.git')
        self.git('remote', 'add', 'origin', str(original))
        self.git('push', '-qu', 'origin', 'HEAD')
        selected = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
        initial_head = self.git('rev-parse', 'HEAD').strip()
        (self.work / 'selected.txt').write_text('reviewed bytes\n')
        real_git = selected.git
        changed = False

        def git_and_change_destination(*args, **kwargs):
            nonlocal changed
            result = real_git(*args, **kwargs)
            if args[0] == 'update-index' and kwargs.get('index') is None and not changed:
                self.git('config', 'remote.origin.pushurl', str(redirect))
                changed = True
            return result

        with patch.object(selected, 'git', side_effect=git_and_change_destination):
            with self.assertRaisesRegex(ReviewedGitError, 'destination changed'):
                selected.commit('reviewed output')
        self.assertTrue(changed)
        self.assertNotEqual(self.git('rev-parse', 'HEAD').strip(), initial_head)
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'reviewed bytes\n')
        self.assertEqual(self.git('--git-dir', str(original), 'rev-parse', selected.remote_branch).strip(), initial_head)
        self.assertEqual(self.git('--git-dir', str(redirect), 'show-ref', '--verify', selected.remote_branch, check=False).strip(), b'')


if __name__ == '__main__':
    unittest.main()
