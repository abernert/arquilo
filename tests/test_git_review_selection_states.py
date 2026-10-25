# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Reviewer-visible selected states against real Git trees, without models.

A run-wide publication allowlist is not a list of changes or an expansion of
the current task. In particular, two null snapshot entries can mean either an
actual deletion or a later task's still-absent output. Keep that distinction
bound to the controller's baseline and the exact reviewed snapshot.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import git_snapshot
from reviewed_git import ReviewedGit


def review_metadata(prompt):
    for line in prompt.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and 'snapshot_root' in value:
            return value
    raise AssertionError('Reviewer received no frozen publication binding')


@unittest.skipUnless(shutil.which('git'), 'Local Git required')
class GitReviewSelectionStates(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='arquilo-selection-states-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'; self.work.mkdir()
        self.state = self.base / 'state'; self.state.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Selection Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        (self.work / 'tracked.txt').write_bytes(b'original\n')
        self.git('add', '--', 'tracked.txt')
        self.git('commit', '-qm', 'clean selected baseline')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work,
                                       stderr=subprocess.PIPE, timeout=20)

    def capture(self, publisher, *, task='1'):
        request = publisher.begin_review(run='selected-states', task=task, attempt='one')
        token, cwd = git_snapshot.capture(request, self.work, 1)
        self.assertEqual(cwd, self.work)
        metadata = review_metadata(git_snapshot.review_instructions(request, token))
        return request, token, metadata

    def assert_state(self, metadata, name, state, *, tracked, present):
        self.assertEqual(metadata['selected_path_states'][name], {
            'baseline_tracked': tracked, 'snapshot_present': present, 'state': state})

    def test_identical_null_entries_distinguish_real_deletion_from_later_absent_output(self):
        publisher = ReviewedGit(self.work, ['tracked.txt', 'new.txt', 'later.txt'], self.state)
        (self.work / 'tracked.txt').unlink()
        (self.work / 'new.txt').write_bytes(b'new\n')
        request, token, metadata = self.capture(publisher)
        manifest = json.loads((Path(request['directory']) / token['candidate'] / 'manifest.json').read_text())
        self.assertIsNone(manifest['selection']['tracked.txt'])
        self.assertIsNone(manifest['selection']['later.txt'])
        self.assert_state(metadata, 'tracked.txt', 'deleted', tracked=True, present=False)
        self.assert_state(metadata, 'new.txt', 'added', tracked=False, present=True)
        self.assert_state(metadata, 'later.txt', 'absent_unchanged', tracked=False, present=False)
        self.assertEqual(Path(metadata['snapshot_root']).joinpath('new.txt').read_bytes(), b'new\n')
        # Independently check the actual Git diff, not just the derived labels.
        candidate = publisher.accept_review(request, token, review_index=1)
        result = publisher.commit('reviewed creation and deletion', candidate=candidate)
        self.assertEqual(set(result['paths']), {'tracked.txt', 'new.txt'})
        changed = set(self.git('diff-tree', '--no-commit-id', '--name-status', '-r', 'HEAD').splitlines())
        self.assertEqual(changed, {b'D\ttracked.txt', b'A\tnew.txt'})

    def test_empty_new_file_is_present_and_added(self):
        publisher = ReviewedGit(self.work, ['empty.txt'], self.state)
        (self.work / 'empty.txt').write_bytes(b'')
        request, token, metadata = self.capture(publisher)
        self.assert_state(metadata, 'empty.txt', 'added', tracked=False, present=True)
        self.assertEqual(git_snapshot.verify(request, token, 1)['empty.txt'][0], b'')

    def test_present_existing_does_not_claim_bytes_are_unchanged(self):
        publisher = ReviewedGit(self.work, ['tracked.txt'], self.state)
        for content in (b'original\n', b'modified\n'):
            with self.subTest(content=content):
                (self.work / 'tracked.txt').write_bytes(content)
                request, token, metadata = self.capture(publisher)
                self.assert_state(metadata, 'tracked.txt', 'present_existing', tracked=True, present=True)
                self.assertEqual(git_snapshot.verify(request, token, 1)['tracked.txt'][0], content)

    def test_same_publisher_after_deletion_has_absent_baseline_and_recreation_is_added(self):
        publisher = ReviewedGit(self.work, ['tracked.txt'], self.state)
        (self.work / 'tracked.txt').unlink()
        request, token, metadata = self.capture(publisher)
        self.assert_state(metadata, 'tracked.txt', 'deleted', tracked=True, present=False)
        candidate = publisher.accept_review(request, token, review_index=1)
        publisher.commit('accepted deletion', candidate=candidate)
        self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'HEAD'), b'')

        request, token, metadata = self.capture(publisher, task='2')
        self.assertNotIn('tracked.txt', request['modes'])
        self.assert_state(metadata, 'tracked.txt', 'absent_unchanged', tracked=False, present=False)
        candidate = publisher.accept_review(request, token, review_index=1)
        self.assertIsNone(publisher.commit('accepted unchanged absence', candidate=candidate))

        (self.work / 'tracked.txt').write_bytes(b'recreated\n')
        request, token, metadata = self.capture(publisher, task='3')
        self.assert_state(metadata, 'tracked.txt', 'added', tracked=False, present=True)
        candidate = publisher.accept_review(request, token, review_index=1)
        publisher.commit('accepted recreation', candidate=candidate)
        self.assertEqual(self.git('show', 'HEAD:tracked.txt'), b'recreated\n')

    def test_changed_baseline_cannot_relabel_deletion_as_unchanged_absence(self):
        publisher = ReviewedGit(self.work, ['tracked.txt'], self.state)
        (self.work / 'tracked.txt').unlink()
        request, token, _ = self.capture(publisher)
        forged = deepcopy(request)
        forged['modes'].pop('tracked.txt')
        with self.assertRaises(git_snapshot.GitSnapshotError):
            git_snapshot.review_instructions(forged, token)

    def test_frozen_absence_still_rejects_file_created_after_review_capture(self):
        publisher = ReviewedGit(self.work, ['later.txt'], self.state)
        request, token, metadata = self.capture(publisher)
        self.assert_state(metadata, 'later.txt', 'absent_unchanged', tracked=False, present=False)
        (self.work / 'later.txt').write_bytes(b'unreviewed later task\n')
        with self.assertRaisesRegex(git_snapshot.GitSnapshotError, 'changed after review'):
            git_snapshot.verify_live(request, token, 1)
        # The explanation itself continues to describe frozen, not live, bytes.
        frozen_metadata = review_metadata(git_snapshot.review_instructions(request, token))
        self.assert_state(frozen_metadata, 'later.txt', 'absent_unchanged', tracked=False, present=False)


if __name__ == '__main__':
    unittest.main()
