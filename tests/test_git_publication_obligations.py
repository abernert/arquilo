# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Unbound publication failures survive restart without becoming authorization."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import git_snapshot
import git_publication_state as state_io
import safe_io
from reviewed_git import (ReviewedGit, ReviewedGitError, list_publications,
                          record_publication_block, recover_publication, resolve_publication_blocks)


@unittest.skipUnless(shutil.which('git'), 'Git required')
class PublicationObligationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='arquilo-obligations-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'; self.work.mkdir()
        self.state = self.base / 'state'; self.state.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.autocrlf', 'false')
        (self.work / 'selected.txt').write_bytes(b'original\n')
        self.git('add', '--', 'selected.txt')
        self.git('commit', '-qm', 'base')
        self.branch = self.git('symbolic-ref', 'HEAD').strip().decode()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.work, capture_output=True,
                              check=True, timeout=20).stdout

    def block(self, **overrides):
        values = dict(run='old-run', task='1', attempt='old-attempt', paths=['selected.txt'],
                      push=False, destination_sha256=None, branch=self.branch,
                      error={'code': 'git_snapshot_unavailable', 'message': 'Selected output was not captured.'})
        values.update(overrides)
        return record_publication_block(self.state, self.work, **values)

    def accept(self, *, run='new-run', attempt='new-attempt', change=True, push=False):
        publisher = ReviewedGit(self.work, ['selected.txt'], self.state, push=push)
        if change:
            (self.work / 'selected.txt').write_bytes(b'fresh reviewed output\n')
        request = publisher.begin_review(run=run, task='1', attempt=attempt)
        token, _ = git_snapshot.capture(request, self.work, 1)
        return publisher, publisher.accept_review(request, token, review_index=1)

    def row(self, identity):
        return next(row for row in list_publications(self.state, self.work) if row['id'] == identity)

    def test_durable_block_is_idempotent_and_never_retry_authority(self):
        block = self.block()
        self.assertEqual(self.block(), block)
        self.assertEqual(self.row(block['id'])['status'], 'blocked')
        self.assertFalse(block['retryable'])
        self.assertIsNone(block['commit'])
        with patch.object(ReviewedGit, 'git', side_effect=AssertionError('No Git operation')):
            with self.assertRaisesRegex(ReviewedGitError, 'no accepted immutable candidate'):
                recover_publication(self.work, self.state, block['id'])
        self.assertEqual(len(list_publications(self.state, self.work)), 1)

    def test_fresh_review_binds_old_block_and_success_preserves_resolution_audit(self):
        block = self.block(task='1-review')
        publisher, candidate = self.accept()
        identity = publisher.last_publication['id']
        receipt = state_io.load(self.state, self.work, identity)
        self.assertEqual(receipt['schema_version'], 'arquilo.git_publication.v2')
        self.assertEqual(receipt['supersedes'], [block['id']])
        self.assertEqual(self.row(block['id'])['status'], 'blocked')
        publisher.commit('Fresh reviewed attempt', candidate=candidate)
        resolved = self.row(block['id'])
        self.assertEqual(resolved['status'], 'superseded')
        self.assertEqual(resolved['resolved_by'], identity)
        self.assertEqual(resolved['run'], 'old-run')
        self.assertEqual(resolve_publication_blocks(self.state, self.work, identity), [block['id']])

    def test_old_pending_or_published_receipt_cannot_clear_a_newer_block(self):
        publisher, candidate = self.accept(run='older-run', attempt='older-attempt')
        identity = publisher.last_publication['id']
        during = self.block(run='later-run', attempt='later-attempt')
        publisher.commit('Old already reviewed candidate', candidate=candidate)
        after = self.block(run='latest-run', attempt='latest-attempt')
        self.assertEqual(resolve_publication_blocks(self.state, self.work, identity), [])
        recover_publication(self.work, self.state, identity)
        self.assertEqual(self.row(during['id'])['status'], 'blocked')
        self.assertEqual(self.row(after['id'])['status'], 'blocked')

    def test_scope_and_attempt_mismatches_cannot_be_resolved(self):
        good = self.block()
        mismatches = [self.block(attempt='other-path', paths=['other.txt']),
                      self.block(attempt='other-branch', branch='refs/heads/other'),
                      self.block(attempt='push-required', push=True, destination_sha256='a' * 64),
                      self.block(attempt='other-task', task='2'),
                      self.block(attempt='unknown-branch', branch=None),
                      self.block(run='new-run', attempt='new-attempt')]
        publisher, candidate = self.accept()
        receipt = state_io.load(self.state, self.work, publisher.last_publication['id'])
        self.assertEqual(receipt['supersedes'], [good['id']])
        publisher.commit('Reviewed', candidate=candidate)
        for block in mismatches:
            self.assertEqual(self.row(block['id'])['status'], 'blocked')

    def test_successful_model_free_retry_resolves_only_its_bound_block(self):
        old = self.block()
        publisher, candidate = self.accept()
        original = publisher.git
        def failed(*args, **kwargs):
            if args[0] == 'read-tree' and kwargs.get('private'):
                raise ReviewedGitError('Synthetic preparation failure')
            return original(*args, **kwargs)
        with patch.object(publisher, 'git', side_effect=failed), self.assertRaises(ReviewedGitError):
            publisher.commit('Reviewed', candidate=candidate)
        identity = publisher.last_publication['id']
        later = self.block(run='after-acceptance', attempt='after-acceptance')
        recover_publication(self.work, self.state, identity)
        self.assertEqual(self.row(old['id'])['status'], 'superseded')
        self.assertEqual(self.row(later['id'])['status'], 'blocked')

    def test_legacy_v1_receipt_remains_usable_without_resolution_capability(self):
        block = self.block()
        publisher, candidate = self.accept()
        identity = publisher.last_publication['id']
        receipt = state_io.load(self.state, self.work, identity)
        receipt['schema_version'] = 'arquilo.git_publication.v1'
        del receipt['supersedes']
        state_io.save(receipt, self.state, self.work)
        publisher.commit('Reviewed legacy receipt', candidate=candidate)
        recover_publication(self.work, self.state, identity)
        self.assertEqual(self.row(block['id'])['status'], 'blocked')

    def test_fresh_reviewed_noop_can_supersede_block(self):
        block = self.block()
        publisher, candidate = self.accept(change=False)
        self.assertIsNone(publisher.commit('Fresh review of existing bytes', candidate=candidate))
        self.assertEqual(publisher.last_publication['status'], 'noop')
        self.assertEqual(self.row(block['id'])['status'], 'superseded')

    def test_only_the_original_push_destination_can_satisfy_push_obligation(self):
        remote = self.base / 'remote.git'
        self.git('init', '--bare', '-q', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        exact = git_snapshot.digest(str(remote).encode())
        good = self.block(push=True, destination_sha256=exact)
        other = self.block(attempt='other-destination', push=True, destination_sha256='b' * 64)
        publisher, candidate = self.accept(push=True)
        publisher.commit('Fresh reviewed push', candidate=candidate)
        self.assertEqual(self.row(good['id'])['status'], 'superseded')
        self.assertEqual(self.row(other['id'])['status'], 'blocked')

    def test_unknown_schema_and_linked_obligation_are_not_silently_ignored(self):
        block = self.block()
        record = state_io.obligation_path(self.state, self.work, block['id'])
        original = record.read_bytes()
        value = json.loads(original); value['candidate'] = {'pretend': 'accepted'}
        record.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'schema'):
            list_publications(self.state, self.work)
        value = json.loads(original)
        value.update(status='superseded', resolved_by='publication-' + '0' * 32)
        record.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'not found'):
            list_publications(self.state, self.work)
        record.write_bytes(original)
        outside = self.base / 'outside.json'; outside.write_bytes(original)
        record.unlink()
        try:
            record.symlink_to(outside)
        except OSError:
            self.skipTest('Native symlinks unavailable')
        with self.assertRaises(safe_io.UnsafePathError):
            list_publications(self.state, self.work)
        self.assertEqual(outside.read_bytes(), original)

    def test_journal_write_failure_is_propagated_to_the_before_done_gate(self):
        with patch.object(state_io, 'save_obligation', side_effect=OSError('Synthetic state storage failure')):
            with self.assertRaises(OSError):
                self.block()
        self.assertEqual(list_publications(self.state, self.work), [])

    def test_changed_bound_scope_cannot_be_silently_superseded(self):
        block = self.block()
        publisher, candidate = self.accept()
        record = state_io.load_obligation(self.state, self.work, block['id'])
        record['paths'] = ['unrelated.txt']
        state_io.save_obligation(record, self.state, self.work)
        with self.assertRaisesRegex(ValueError, 'changed scope'):
            publisher.commit('Reviewed', candidate=candidate)
        self.assertEqual(self.row(block['id'])['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
