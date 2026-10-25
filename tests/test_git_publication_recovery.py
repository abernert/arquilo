# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Real local Git and synthetic accepted reviews; no models or external network."""
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
import git_publication_state
from reviewed_git import ReviewedGit, ReviewedGitError, list_publications, recover_publication


@unittest.skipUnless(shutil.which('git'), 'Git required')
class PublicationRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='arquilo-publish-retry-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'; self.work.mkdir()
        self.state = self.base / 'state'; self.state.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'commit.gpgsign', 'false')
        (self.work / 'selected.txt').write_bytes(b'original\n')
        (self.work / 'other.txt').write_bytes(b'context\n')
        self.git('add', '--', 'selected.txt', 'other.txt')
        self.git('commit', '-qm', 'base')
        self.parent = self.git('rev-parse', 'HEAD').strip().decode()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.work, capture_output=True,
                              check=True, timeout=20).stdout

    def remote(self):
        destination = self.base / 'remote.git'
        self.git('init', '--bare', '-q', str(destination))
        self.git('remote', 'add', 'origin', str(destination))
        self.git('push', '-qu', 'origin', 'HEAD')
        return destination

    def accepted(self, *, push=False):
        publisher = ReviewedGit(self.work, ['selected.txt'], self.state, push=push)
        (self.work / 'selected.txt').write_bytes(b'reviewed bytes\n')
        request = publisher.begin_review(run='offline-run', task='2701', attempt='one')
        token, cwd = git_snapshot.capture(request, self.work, 1)
        self.assertEqual(cwd, self.work)
        candidate = publisher.accept_review(request, token, review_index=1)
        return publisher, candidate

    def failed_prepare(self):
        publisher, candidate = self.accepted()
        original = publisher.git
        def fail(*args, **kwargs):
            if args[0] == 'read-tree' and kwargs.get('private'):
                raise ReviewedGitError('Synthetic preparation outage')
            return original(*args, **kwargs)
        with patch.object(publisher, 'git', side_effect=fail), self.assertRaises(ReviewedGitError):
            publisher.commit('Reviewed output', candidate=candidate)
        return publisher, candidate

    def failed_push(self, *, applied=False):
        destination = self.remote()
        publisher, candidate = self.accepted(push=True)
        original = publisher.git
        def fail(*args, **kwargs):
            if args[0] == 'push':
                if applied:
                    original(*args, **kwargs)
                raise ReviewedGitError('Synthetic lost transport response')
            return original(*args, **kwargs)
        with patch.object(publisher, 'git', side_effect=fail), self.assertRaisesRegex(ReviewedGitError, 'Local reviewed commit'):
            publisher.commit('Reviewed output', candidate=candidate)
        return publisher, candidate, destination

    def test_setup_and_begin_review_do_not_pack_history_or_contact_remote(self):
        self.remote()
        original = ReviewedGit.git
        observed = []
        def tracked(instance, *args, **kwargs):
            observed.append(args)
            self.assertNotEqual(args[0], 'pack-objects')
            self.assertFalse(args[0] == 'ls-remote' and '--get-url' not in args)
            return original(instance, *args, **kwargs)
        with patch.object(ReviewedGit, 'git', tracked):
            publisher = ReviewedGit(self.work, ['selected.txt'], self.state, push=True)
            (self.work / 'other.txt').write_bytes(b'owner staging\n')
            self.git('add', '--', 'other.txt')
            publisher.begin_review(run='r', task='1', attempt='a')
        self.assertTrue(observed)

    def test_selected_zero_byte_files_still_count_parent_directories(self):
        publisher = ReviewedGit(self.work, ['a/file', 'b/file'], self.state)
        for directory in ('a', 'b'):
            (self.work / directory).mkdir()
            (self.work / directory / 'file').write_bytes(b'')
        request = publisher.begin_review(run='r', task='1', attempt='a')
        with patch.object(git_snapshot, 'MAX_FILES', 3), self.assertRaises(git_snapshot.GitSnapshotUnavailable):
            git_snapshot.capture(request, self.work, 1)

    def test_backend_control_paths_and_original_depth_bound_remain_excluded(self):
        for name in ('.claude_runs/private.json', 'nested/.claude_runs/private.json',
                     '/'.join(['directory'] * 65 + ['file'])):
            with self.subTest(name=name), self.assertRaises(git_snapshot.GitSnapshotError):
                git_snapshot.relative_name(name)
        self.assertEqual(len(git_snapshot.relative_name('/'.join(['directory'] * 64 + ['file'])).split('/')), 65)

    def test_preparation_failure_retries_exact_output_once(self):
        publisher, _ = self.failed_prepare()
        pending = list_publications(self.state, self.work)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['status'], 'preparing')
        self.assertEqual(pending[0]['task'], '2701')
        self.assertEqual(pending[0]['attempt'], 'one')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.parent)
        result = recover_publication(self.work, self.state, pending[0]['id'])
        self.assertEqual(result['status'], 'published')
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'reviewed bytes\n')
        self.assertEqual(self.git('rev-list', '--count', self.parent + '..HEAD').strip(), b'1')
        self.assertEqual(recover_publication(self.work, self.state, pending[0]['id']), result)

    def test_push_failure_reuses_local_commit_without_new_model_or_commit(self):
        publisher, _, destination = self.failed_push()
        pending = list_publications(self.state, self.work)[0]
        self.assertEqual(pending['status'], 'push_pending')
        new = self.git('rev-parse', 'HEAD').strip().decode()
        result = recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(result['commit'], new)
        self.assertTrue(result['pushed'])
        self.assertEqual(self.git('--git-dir', str(destination), 'rev-parse', publisher.remote_branch).strip().decode(), new)
        self.assertEqual(self.git('rev-list', '--count', self.parent + '..HEAD').strip(), b'1')

    def test_prepared_commit_survives_object_transfer_failure(self):
        publisher, candidate = self.accepted()
        original = publisher.git
        def fail(*args, **kwargs):
            if args[0] == 'index-pack' and not kwargs.get('private'):
                raise ReviewedGitError('Synthetic local object-transfer failure')
            return original(*args, **kwargs)
        with patch.object(publisher, 'git', side_effect=fail), self.assertRaises(ReviewedGitError):
            publisher.commit('reviewed', candidate=candidate)
        pending = list_publications(self.state, self.work)[0]
        self.assertIsNotNone(pending['commit'])
        original_class = ReviewedGit.git
        def no_new_commit(instance, *args, **kwargs):
            self.assertNotEqual(args[0], 'commit-tree')
            return original_class(instance, *args, **kwargs)
        with patch.object(ReviewedGit, 'git', no_new_commit):
            result = recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(result['commit'], pending['commit'])

    def test_completed_local_transaction_with_lost_result_is_reconciled(self):
        publisher, candidate = self.accepted()
        original = publisher.git
        def fail_after_ref(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[0] == 'update-ref':
                raise ReviewedGitError('Synthetic lost transaction acknowledgment')
            return result
        with patch.object(publisher, 'git', side_effect=fail_after_ref), self.assertRaises(ReviewedGitError):
            publisher.commit('reviewed', candidate=candidate)
        pending = list_publications(self.state, self.work)[0]
        self.assertEqual(pending['status'], 'prepared')
        new = self.git('rev-parse', 'HEAD').strip().decode()
        self.assertEqual(new, pending['commit'])
        original_class = ReviewedGit.git
        def no_second_ref(instance, *args, **kwargs):
            self.assertNotIn(args[0], {'commit-tree', 'update-ref'})
            return original_class(instance, *args, **kwargs)
        with patch.object(ReviewedGit, 'git', no_second_ref):
            result = recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['commit'], new)

    def test_ambiguous_completed_push_reconciles_without_push_even_with_stop(self):
        publisher, _, _ = self.failed_push(applied=True)
        pending = list_publications(self.state, self.work)[0]
        (self.work / 'process_stop').write_bytes(b'')
        original = ReviewedGit.git
        def no_mutation(instance, *args, **kwargs):
            self.assertNotIn(args[0], {'push', 'commit-tree', 'update-ref', 'index-pack', 'update-index'})
            return original(instance, *args, **kwargs)
        with patch.object(ReviewedGit, 'git', no_mutation):
            result = recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(result['status'], 'published')
        self.assertTrue(result['pushed'])

    def test_remote_advance_is_not_overwritten(self):
        publisher, _, destination = self.failed_push()
        pending = list_publications(self.state, self.work)[0]
        tree = self.git('--git-dir', str(destination), 'rev-parse', self.parent + '^{tree}').strip().decode()
        other = self.git('--git-dir', str(destination), '-c', 'user.name=Other',
            '-c', 'user.email=other@example.invalid', 'commit-tree', tree, '-p', self.parent, '-m', 'other').strip().decode()
        self.git('--git-dir', str(destination), 'update-ref', publisher.remote_branch, other, self.parent)
        with self.assertRaises(ReviewedGitError):
            recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(self.git('--git-dir', str(destination), 'rev-parse', publisher.remote_branch).strip().decode(), other)
        self.assertEqual(list_publications(self.state, self.work)[0]['status'], 'push_pending')

    def test_changed_push_destination_cannot_receive_recovery(self):
        _, _, _ = self.failed_push()
        pending = list_publications(self.state, self.work)[0]
        different = self.base / 'different.git'
        self.git('init', '--bare', '-q', str(different))
        self.git('config', 'remote.origin.pushurl', str(different))
        with self.assertRaisesRegex(ReviewedGitError, 'destination changed'):
            recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(self.git('--git-dir', str(different), 'for-each-ref'), b'')

    def test_index_change_blocks_local_recovery_without_losing_staging(self):
        self.failed_prepare()
        pending = list_publications(self.state, self.work)[0]
        (self.work / 'other.txt').write_bytes(b'owner staged later\n')
        self.git('add', '--', 'other.txt')
        staged = self.git('show', ':other.txt')
        with self.assertRaisesRegex(ReviewedGitError, 'HEAD/index changed'):
            recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(self.git('show', ':other.txt'), staged)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.parent)

    def test_selected_change_requires_fresh_review(self):
        self.failed_prepare()
        pending = list_publications(self.state, self.work)[0]
        (self.work / 'selected.txt').write_bytes(b'not reviewed\n')
        with self.assertRaisesRegex(ReviewedGitError, 'changed after review'):
            recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.parent)

    def test_private_snapshot_manipulation_blocks_recovery(self):
        _, candidate = self.failed_prepare()
        pending = list_publications(self.state, self.work)[0]
        manifest = Path(candidate.request['directory']) / candidate.token['candidate'] / 'manifest.json'
        manifest.write_bytes(b'{}')
        with self.assertRaises(git_snapshot.GitSnapshotError):
            recover_publication(self.work, self.state, pending['id'])
        self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.parent)

    def test_receipt_id_schema_and_workspace_cannot_be_retargeted(self):
        self.failed_prepare()
        pending = list_publications(self.state, self.work)[0]
        with self.assertRaises(ValueError):
            recover_publication(self.work, self.state, '../receipts/' + pending['id'])
        other = self.base / 'other-workspace'; other.mkdir()
        with self.assertRaisesRegex(ValueError, 'different workspace'):
            recover_publication(other, self.state, pending['id'])
        receipt = git_publication_state.path(self.state, self.work, pending['id'])
        value = json.loads(receipt.read_bytes()); value['unexpected'] = True
        receipt.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'schema'):
            recover_publication(self.work, self.state, pending['id'])

    def test_stop_blocks_new_commit_but_preserves_receipt_for_explicit_retry(self):
        publisher, candidate = self.accepted()
        (self.work / 'process_stop').write_bytes(b'')
        with self.assertRaisesRegex(ReviewedGitError, 'process_stop'):
            publisher.commit('reviewed', candidate=candidate)
        pending = list_publications(self.state, self.work)[0]
        self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.parent)
        with self.assertRaisesRegex(ReviewedGitError, 'process_stop'):
            recover_publication(self.work, self.state, pending['id'])
        (self.work / 'process_stop').unlink()
        self.assertEqual(recover_publication(self.work, self.state, pending['id'])['status'], 'published')

    def test_stop_between_local_commit_and_push_prevents_transport(self):
        self.remote(); publisher, candidate = self.accepted(push=True)
        original = publisher.git
        def stop_after_local(*args, **kwargs):
            self.assertNotEqual(args[0], 'push')
            result = original(*args, **kwargs)
            if args[0] == 'update-ref':
                (self.work / 'process_stop').write_bytes(b'')
            return result
        with patch.object(publisher, 'git', side_effect=stop_after_local), self.assertRaisesRegex(ReviewedGitError, 'Local reviewed commit'):
            publisher.commit('reviewed', candidate=candidate)
        pending = list_publications(self.state, self.work)[0]
        self.assertEqual(pending['status'], 'push_pending')
        with self.assertRaises(ReviewedGitError):
            recover_publication(self.work, self.state, pending['id'])
        (self.work / 'process_stop').unlink()
        self.assertEqual(recover_publication(self.work, self.state, pending['id'])['status'], 'published')


if __name__ == '__main__':
    unittest.main()
