# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Content/attempt-bound publication, real local Git, no external services.

Unit fixtures accept synthetic reviews explicitly. Controller tests run the real
production/review/acceptance sequence with synthetic model answers and inspect
physical files, commit objects and private journals independently of those answers.
"""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import autobuild
from autobuild_contract import AutoBuildContext, AutoBuildOptions, call_payload, decode_call
from codex_transport import RunResult
import git_snapshot
import reviewed_git
from git_review_fixture import reviewed_candidate
from reviewed_git import ReviewedGit, ReviewedGitError
import safe_io
from adversarial.harness import IsolatedControllerCase

PASS = {'verdict': 'PASS', 'short_summary': 'Inspected the frozen output bytes.',
        'blocking_issues': [], 'non_blocking_observations': [],
        'breakdown_recommended': False, 'breakdown_reason': None}
PLAN = '1. ***Task***: Create proof.txt containing exactly RIGHT.\n'


def answer(text):
    return RunResult(assistant_messages=[text], turn_completed=True, process_exit_code=0)


@unittest.skipUnless(shutil.which('git'), 'Git required')
class GitIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='arquilo-git-integrity-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.work = self.base / 'work'; self.work.mkdir()
        self.state = self.base / 'state'; self.state.mkdir(mode=0o700)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Owner')
        self.git('config', 'user.email', 'owner@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'commit.gpgsign', 'false')
        (self.work / 'selected.txt').write_bytes(b'old\n')
        (self.work / 'other.txt').write_bytes(b'other\n')
        self.git('add', '--', 'selected.txt', 'other.txt')
        self.git('commit', '-qm', 'base')
        self.old = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args, check=True):
        return subprocess.run(['git', *args], cwd=self.work, capture_output=True,
                              check=check, timeout=20).stdout

    def selection(self, *, push=False):
        return ReviewedGit(self.work, ['selected.txt', 'new.txt'], self.state, push=push)

    def change(self):
        (self.work / 'selected.txt').write_bytes(b'reviewed\n')

    def remote(self):
        remote = self.base / 'remote.git'
        self.git('init', '--bare', '-q', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.git('push', '-qu', 'origin', 'HEAD')
        return remote

    def remote_advance(self, remote, branch):
        tree = self.git('--git-dir', str(remote), 'rev-parse', self.old.decode() + '^{tree}').strip().decode()
        new = self.git('--git-dir', str(remote), '-c', 'user.name=Other',
                       '-c', 'user.email=other@example.invalid', 'commit-tree', tree,
                       '-p', self.old.decode(), '-m', 'remote writer').strip()
        self.git('--git-dir', str(remote), 'update-ref', branch, new.decode(), self.old.decode())
        return new

    def test_commit_without_accepted_snapshot_is_refused(self):
        g = self.selection(); self.change()
        with self.assertRaisesRegex(ReviewedGitError, 'pre-review snapshot'):
            g.commit('no review')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_post_review_file_change_is_refused(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        (self.work / 'selected.txt').write_bytes(b'unreviewed\n')
        with self.assertRaisesRegex(ReviewedGitError, 'changed after review'):
            g.commit('reject', candidate=candidate)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_late_change_cannot_replace_commit_bytes(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        original = g.git
        def race(*args, **kwargs):
            if args[0] == 'read-tree' and kwargs.get('private'):
                (self.work / 'selected.txt').write_bytes(b'too late\n')
            return original(*args, **kwargs)
        with patch.object(g, 'git', side_effect=race):
            result = g.commit('frozen', candidate=candidate)
        self.assertEqual(self.git('show', result['commit'] + ':selected.txt'), b'reviewed\n')
        self.assertEqual((self.work / 'selected.txt').read_bytes(), b'too late\n')

    def test_snapshot_tampering_is_refused(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        frozen = Path(candidate.request['directory']) / candidate.token['candidate'] / 'workspace' / 'selected.txt'
        frozen.chmod(0o600); frozen.write_bytes(b'changed privately\n')
        with self.assertRaises(git_snapshot.GitSnapshotError):
            g.commit('reject', candidate=candidate)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_added_control_file_in_snapshot_is_not_ignored(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        extra = Path(candidate.request['directory']) / candidate.token['candidate'] / 'workspace' / '.git'
        extra.mkdir(); (extra / 'config').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(git_snapshot.GitSnapshotError, 'inventory changed'):
            g.commit('reject', candidate=candidate)

    def test_missing_or_replaced_manifest_is_refused(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        manifest = Path(candidate.request['directory']) / candidate.token['candidate'] / 'manifest.json'
        manifest.write_bytes(b'{}')
        with self.assertRaisesRegex(git_snapshot.GitSnapshotError, 'manifest missing or changed'):
            g.commit('reject', candidate=candidate)

    def test_request_token_and_review_round_must_match(self):
        g = self.selection(); self.change()
        one = g.begin_review(run='r', task='1', attempt='one')
        token, _ = git_snapshot.capture(one, self.work, 1)
        two = g.begin_review(run='r', task='1', attempt='two')
        with self.assertRaises(git_snapshot.GitSnapshotError):
            g.accept_review(two, token, review_index=1)
        with self.assertRaises(git_snapshot.GitSnapshotError):
            g.accept_review(one, token, review_index=2)
        forged = deepcopy(one); forged['binding']['task'] = 'other'
        with self.assertRaises(ReviewedGitError):
            g.accept_review(forged, token, review_index=1)

    def test_accepted_candidate_cannot_be_retargeted_or_reused(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        forged = deepcopy(candidate); forged.request['paths'].append('other.txt')
        with self.assertRaises(ReviewedGitError):
            g.commit('retarget', candidate=forged)
        g.commit('accepted', candidate=candidate)
        with self.assertRaises(ReviewedGitError):
            g.commit('replay', candidate=candidate)

    def test_noop_still_consumes_an_accepted_candidate(self):
        g = self.selection(); candidate = reviewed_candidate(g)
        self.assertIsNone(g.commit('noop', candidate=candidate))
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)
        with self.assertRaises(ReviewedGitError):
            g.commit('replay', candidate=candidate)

    def test_creation_and_deletion_are_snapshot_entries(self):
        g = self.selection()
        (self.work / 'selected.txt').unlink()
        (self.work / 'new.txt').write_bytes(b'new reviewed\n')
        candidate = reviewed_candidate(g)
        self.assertIsNone(candidate.contents()['selected.txt'])
        g.commit('create/delete', candidate=candidate)
        self.assertEqual(self.git('show', 'HEAD:new.txt'), b'new reviewed\n')
        self.assertNotIn(b'selected.txt\0', self.git('ls-tree', '-rz', '--name-only', 'HEAD'))

    @unittest.skipIf(os.name == 'nt', 'Native POSIX executable modes')
    def test_executable_mode_change_requires_fresh_review(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        (self.work / 'selected.txt').chmod(0o755)
        with self.assertRaisesRegex(ReviewedGitError, 'changed after review'):
            g.commit('reject mode', candidate=candidate)

    def test_linked_context_is_rejected_without_reading_target(self):
        g = self.selection(); self.change()
        secret = self.base / 'secret'; secret.write_bytes(b'outside')
        try:
            (self.work / 'linked-context').symlink_to(secret)
        except OSError:
            self.skipTest('Native symlinks unavailable')
        with self.assertRaises(safe_io.UnsafePathError):
            reviewed_candidate(g)
        self.assertEqual(secret.read_bytes(), b'outside')

    def test_snapshot_limits_fail_before_acceptance(self):
        g = self.selection(); self.change()
        with patch.object(git_snapshot, 'MAX_FILE_BYTES', 3):
            with self.assertRaises(git_snapshot.GitSnapshotError):
                reviewed_candidate(g)
        with patch.object(git_snapshot, 'MAX_TOTAL_BYTES', 4):
            with self.assertRaises(git_snapshot.GitSnapshotError):
                reviewed_candidate(g)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_forged_tracking_ref_cannot_publish_unreviewed_parent(self):
        remote = self.remote()
        (self.work / 'secret-parent.txt').write_bytes(b'not selected')
        self.git('add', 'secret-parent.txt'); self.git('commit', '-qm', 'unpublished parent')
        branch = self.git('symbolic-ref', '--short', 'HEAD').strip().decode()
        self.git('update-ref', 'refs/remotes/origin/' + branch, 'HEAD')
        with self.assertRaisesRegex(ReviewedGitError, 'actual push destination'):
            self.selection(push=True)
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', 'refs/heads/' + branch).strip(), self.old)

    def test_final_push_lease_rejects_remote_race(self):
        remote = self.remote(); g = self.selection(push=True); self.change()
        candidate = reviewed_candidate(g); original = g.git; advanced = []
        def race(*args, **kwargs):
            if args[0] == 'push':
                advanced.append(self.remote_advance(remote, g.remote_branch))
                self.assertIn('--force-with-lease=' + g.remote_branch + ':' + self.old.decode(), args)
            return original(*args, **kwargs)
        with patch.object(g, 'git', side_effect=race), self.assertRaisesRegex(ReviewedGitError, 'Local reviewed commit'):
            g.commit('no overwrite', candidate=candidate)
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', g.remote_branch).strip(), advanced[0])
        self.assertEqual(self.git('show', 'HEAD:selected.txt'), b'reviewed\n')

    def test_final_url_swap_cannot_redirect_transport(self):
        remote = self.remote(); other = self.base / 'other.git'
        self.git('init', '--bare', '-q', str(other))
        g = self.selection(push=True); self.change(); candidate = reviewed_candidate(g); original = g.git
        def race(*args, **kwargs):
            if args[0] == 'push':
                self.git('config', 'remote.origin.pushurl', str(other))
                self.assertTrue(kwargs.get('private'))
                self.assertIn(str(remote), args)
                self.assertNotIn('origin', args)
            return original(*args, **kwargs)
        with patch.object(g, 'git', side_effect=race):
            result = g.commit('pinned endpoint', candidate=candidate)
        self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', g.remote_branch).strip().decode(), result['commit'])
        self.assertEqual(self.git('--git-dir', str(other), 'for-each-ref'), b'')

    def test_mirror_tags_and_additional_refspecs_do_not_expand_push(self):
        remote = self.remote()
        self.git('tag', 'unapproved')
        self.git('config', 'remote.origin.mirror', 'true')
        self.git('config', '--add', 'remote.origin.push', 'refs/tags/*:refs/tags/*')
        g = self.selection(push=True); self.change(); candidate = reviewed_candidate(g)
        g.commit('one ref', candidate=candidate)
        refs = self.git('--git-dir', str(remote), 'for-each-ref', '--format=%(refname)').splitlines()
        self.assertEqual(refs, [g.remote_branch.encode()])
        self.assertEqual(self.git('config', '--get', 'remote.origin.mirror').strip(), b'true')

    def test_filters_fsmonitor_and_source_hooks_do_not_run(self):
        remote = self.remote()
        marker = self.base / 'forbidden-helper'
        # Git for Windows also invokes shell-valued helpers using its sh.
        command = 'echo forbidden > "' + marker.as_posix() + '"; cat'
        self.git('config', 'filter.canary.clean', command)
        self.git('config', 'core.fsmonitor', command)
        self.git('config', 'remote.origin.receivepack', command)
        (self.work / '.gitattributes').write_text('selected.txt filter=canary\n')
        hooks = self.work / 'hooks'; hooks.mkdir()
        for name in ('pre-push', 'reference-transaction'):
            hook = hooks / name; hook.write_text('#!/bin/sh\n' + command + '\n', newline=''); hook.chmod(0o755)
        self.git('config', 'core.hooksPath', str(hooks))
        g = self.selection(push=True); self.change(); candidate = reviewed_candidate(g)
        g.commit('no host helpers', candidate=candidate)
        self.assertFalse(marker.exists())
        self.assertEqual(self.git('--git-dir', str(remote), 'show', g.remote_branch + ':selected.txt'), b'reviewed\n')

    def test_existing_index_lock_is_not_removed(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        lock = g.index_path.with_name('index.lock'); lock.write_bytes(b'other writer')
        with self.assertRaises(ReviewedGitError):
            g.commit('blocked', candidate=candidate)
        self.assertEqual(lock.read_bytes(), b'other writer')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_git_writers_are_blocked_during_index_publication(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        (self.work / 'other.txt').write_bytes(b'owner edit\n')
        original = safe_io.atomic_write; observed = []
        def check_locks(path, data):
            if Path(path) == g.index_path:
                for args in (['symbolic-ref', 'HEAD', 'refs/heads/unexpected'], ['add', '--', 'other.txt']):
                    result = subprocess.run(['git', *args], cwd=self.work, capture_output=True, timeout=15)
                    observed.append(result.returncode)
                    self.assertNotEqual(result.returncode, 0, args)
            return original(path, data)
        with patch.object(safe_io, 'atomic_write', side_effect=check_locks):
            g.commit('locked', candidate=candidate)
        self.assertEqual(len(observed), 2)
        self.assertEqual(self.git('symbolic-ref', 'HEAD').strip().decode(), g.branch)
        self.assertEqual(self.git('show', 'HEAD:other.txt'), b'other\n')
        self.assertEqual((self.work / 'other.txt').read_bytes(), b'owner edit\n')

    def test_same_oid_head_switch_before_prepare_aborts_transaction(self):
        g = self.selection(); self.change(); candidate = reviewed_candidate(g)
        self.git('branch', 'other-branch', self.old.decode())
        original = g.git; old_index = g.index_bytes
        def switch(*args, **kwargs):
            if args[0] == 'update-ref':
                self.git('symbolic-ref', 'HEAD', 'refs/heads/other-branch')
            return original(*args, **kwargs)
        with patch.object(g, 'git', side_effect=switch), self.assertRaises(ReviewedGitError):
            g.commit('must not follow HEAD', candidate=candidate)
        self.assertEqual(self.git('rev-parse', g.branch).strip(), self.old)
        self.assertEqual(self.git('rev-parse', 'other-branch').strip(), self.old)
        self.assertEqual(g.index_path.read_bytes(), old_index)

    def test_host_url_rewrite_race_cannot_redirect_pinned_transport(self):
        home = self.base / 'host-home'; home.mkdir()
        with patch.dict(os.environ, {'HOME': str(home), 'USERPROFILE': str(home),
                                    'XDG_CONFIG_HOME': str(home / '.config')}):
            remote = self.remote(); other = self.base / 'other.git'
            self.git('init', '--bare', '-q', str(other))
            g = self.selection(push=True); self.change(); candidate = reviewed_candidate(g)
            original = g.git
            def race(*args, **kwargs):
                if args[0] == 'push':
                    self.git('config', '--global', 'url.' + str(other) + '.insteadOf', str(remote))
                return original(*args, **kwargs)
            with patch.object(g, 'git', side_effect=race):
                result = g.commit('frozen host transport', candidate=candidate)
            self.assertEqual(self.git('--git-dir', str(remote), 'rev-parse', g.remote_branch).strip().decode(), result['commit'])
            self.assertEqual(self.git('--git-dir', str(other), 'for-each-ref'), b'')

    def test_pack_transfer_is_bounded_before_accumulation(self):
        with patch.object(reviewed_git, 'MAX_PACK_BYTES', 1024):
            with self.assertRaisesRegex(ReviewedGitError, 'output limit'):
                ReviewedGit._bounded_pack([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(b"X"*1000000)'],
                                          self.base, dict(os.environ), b'')

    def test_pack_transfer_has_an_absolute_deadline(self):
        with patch.object(reviewed_git, 'PACK_TIMEOUT_SECONDS', .3):
            with self.assertRaisesRegex(ReviewedGitError, 'deadline'):
                ReviewedGit._bounded_pack([sys.executable, '-c', 'import time; time.sleep(20)'],
                                          self.base, dict(os.environ), b'')

    def test_pack_transfer_preserves_exact_binary_bytes(self):
        data = bytes(range(256)) * 400
        result = ReviewedGit._bounded_pack([sys.executable, '-c',
            'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'], self.base, dict(os.environ), data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, data)

    def test_worker_context_roundtrip_binds_identical_request(self):
        g = self.selection(); request = g.begin_review(run='r', task='1', attempt='1')
        context = AutoBuildContext(git_review=request)
        payload = call_payload(task='synthetic', workdir=self.work,
                               options=AutoBuildOptions(), context=context)
        restored = decode_call(json.loads(json.dumps(payload)))['context']
        self.assertEqual(restored.git_review, request)
        self.assertIsNot(restored.git_review, request)
        with self.assertRaises(ValueError):
            AutoBuildContext(git_review={'paths': ['selected.txt']})


@unittest.skipUnless(shutil.which('git'), 'Git required')
class GitControllerTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp(); self.write_plan(PLAN)
        self.git('init', '-q'); self.git('config', 'user.name', 'Synthetic Controller')
        self.git('config', 'user.email', 'controller@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('add', '--', 'tasks.md'); self.git('commit', '-qm', 'owner plan')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.work, stderr=subprocess.PIPE)

    def test_controller_reviews_private_copy_and_publishes_same_bytes(self):
        runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
        seen = []
        def dispatch(**kwargs):
            cwd = Path(kwargs['cwd']); seen.append(cwd)
            if kwargs['phase'] == 'auftrag':
                self.assertEqual(cwd, self.work)
                (cwd / 'proof.txt').write_bytes(b'RIGHT')
                return answer('Created proof.')
            self.assertNotEqual(cwd, self.work)
            self.assertTrue(cwd.is_relative_to(runner.state_dir))
            self.assertEqual((cwd / 'proof.txt').read_bytes(), b'RIGHT')
            self.assertEqual(kwargs['sandbox'], 'read-only')
            self.assertIn('--skip-git-repo-check', kwargs['extra_args'])
            return answer(json.dumps(PASS))
        with self.fake_codex(dispatch):
            runner.run()
        self.assertEqual(runner.exit_code, 0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.git('show', 'HEAD:proof.txt'), b'RIGHT')
        self.assert_accepted_artifact(runner, plan=PLAN.replace('***Task***', '***DONE***'), artifact='proof.txt', data=b'RIGHT')
        record = json.loads((runner.run_dir / 'git_1.json').read_text())
        self.assertRegex(record['review_snapshot'], r'^[a-f0-9]{64}$')

    def test_worker_claim_without_snapshot_cannot_persist_done(self):
        runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
        def fake_start(*args, **kwargs):
            options = kwargs['options']; (self.work / 'proof.txt').write_bytes(b'RIGHT')
            return autobuild.AutoBuildSummary(last_answer='claimed', completed=True, auftrag_runs=1, review_runs=1,
                workspace=self.work, pretty_log=options.logfile, raw_log=options.rawlog,
                readonly_result_path=None, review_classification={**PASS, 'valid': True, 'source_format': 'json_v2'})
        with patch('run_todos.autobuild_start', side_effect=fake_start), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.todo.read_text(), PLAN)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], PLAN)

    def test_live_change_during_snapshot_review_prevents_done(self):
        runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
        def dispatch(**kwargs):
            if kwargs['phase'] == 'auftrag':
                (self.work / 'proof.txt').write_bytes(b'RIGHT'); return answer('Ready')
            self.assertEqual((Path(kwargs['cwd']) / 'proof.txt').read_bytes(), b'RIGHT')
            (self.work / 'proof.txt').write_bytes(b'WRONG')
            return answer(json.dumps(PASS))
        with self.fake_codex(dispatch):
            runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.todo.read_text(), PLAN)
        self.assertEqual(json.loads((runner.state_dir / 'plan.json').read_text())['text'], PLAN)

    def test_snapshot_mutation_during_review_prevents_done(self):
        runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
        def dispatch(**kwargs):
            cwd = Path(kwargs['cwd'])
            if kwargs['phase'] == 'auftrag':
                (cwd / 'proof.txt').write_bytes(b'RIGHT'); return answer('Ready')
            path = cwd / 'proof.txt'; path.chmod(0o600); path.write_bytes(b'WRONG')
            return answer(json.dumps(PASS))
        with self.fake_codex(dispatch):
            runner.run()
        self.assertNotEqual(runner.exit_code, 0)
        self.assertEqual(self.todo.read_text(), PLAN)

    def test_parallel_git_is_refused_before_any_model_dispatch(self):
        self.write_plan('***CFG parallel=p workspace=child***\n' + PLAN)
        self.git('add', '--', 'tasks.md'); self.git('commit', '-qm', 'parallel plan')
        runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
        with self.fake_codex(lambda **kw: self.fail('No model may start')), self.assertRaisesRegex(ReviewedGitError, 'serial tasks'):
            runner.run()

    def test_task_plan_cannot_be_selected_for_publication(self):
        with self.assertRaisesRegex(ReviewedGitError, 'task plan'):
            self.runner(git_enabled=True, git_paths=['tasks.md'])

    @unittest.skipIf(os.name == 'nt', 'POSIX synthetic executable; serialization covered on Windows')
    def test_real_private_python_worker_carries_snapshot_identity(self):
        host = self.base / 'host'; host.mkdir()
        program = host / 'codex'
        program.write_text(f'''#!{sys.executable}
import json, pathlib, sys
if '--version' in sys.argv:
    print('codex-cli 0.159.1'); raise SystemExit(0)
sys.stdin.buffer.read()
review = sys.argv[sys.argv.index('--sandbox')+1] == 'read-only'
if not review:
    pathlib.Path('proof.txt').write_bytes(b'RIGHT')
else:
    assert pathlib.Path('proof.txt').read_bytes() == b'RIGHT'
text = {json.dumps(PASS)!r} if review else 'Produced RIGHT'
for event in ({{'type':'turn.started'}}, {{'type':'item.completed','item':{{'type':'agent_message','text':text}}}}, {{'type':'turn.completed'}}):
    print(json.dumps(event), flush=True)
''', encoding='utf-8', newline='')
        program.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(host) + os.pathsep + os.environ.get('PATH', '')}), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            runner = self.runner(git_enabled=True, git_paths=['proof.txt'])
            outcome, _, _ = runner._execute_todo_autobuild(runner._parse_todo_file()[0], use_cli_subprocess=True)
            self.assertTrue(outcome.completed, outcome.message)
            self.assertIsNotNone(outcome.git_candidate)
            result = runner.git_selection.commit('private worker reviewed', candidate=outcome.git_candidate)
        self.assertEqual(self.git('show', result['commit'] + ':proof.txt'), b'RIGHT')
        requests = list((runner.state_dir / 'worker_calls').glob('*/request.json'))
        self.assertEqual(len(requests), 1)
        request = json.loads(requests[0].read_text())['context']['git_review']
        self.assertEqual(request['binding']['task'], '1')
        self.assertEqual(outcome.git_candidate.request, request)
