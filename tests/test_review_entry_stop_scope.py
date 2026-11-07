#!/usr/bin/env python3
"""STOP ownership versus candidate evidence; synthetic archives, no providers."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import review_candidate
import run_todos
import test_review_entry as native
import test_review_resume_network as network
from test_reconnect_stop import PASS, COMPLETE, answer


# A subordinate diagnostic workspace, not a control path of the outer runner.
HISTORICAL = Path('reports/earlier-task/veto-diagnostic/work/.arquilo-flow/'
                  'synthetic-run/1/reviewed/produce/synthetic-attempt/process_stop')


class CandidateStopScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name).resolve() / 'work'
        self.work.mkdir()

    def marker(self):
        p = self.work / HISTORICAL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'Historical negative-test STOP evidence.\n')
        return p

    def test_nested_stop_remains_hashed_unchanged_evidence(self):
        p = self.marker()
        before = network.snapshot(self.work)
        manifest, _ = review_candidate.capture(self.work)
        self.assertEqual(manifest['files'][HISTORICAL.as_posix()]['sha256'],
                         hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertNotIn(HISTORICAL.as_posix(), manifest['excluded'])
        self.assertEqual(network.snapshot(self.work), before)

    def test_nested_stop_change_deletion_and_addition_change_identity(self):
        p = self.marker()
        first, _ = review_candidate.capture(self.work)
        p.write_bytes(b'Changed evidence.\n')
        changed, _ = review_candidate.capture(self.work)
        self.assertNotEqual(first, changed)
        p.unlink()
        deleted, _ = review_candidate.capture(self.work)
        self.assertNotEqual(changed, deleted)
        p.write_bytes(b'New evidence.\n')
        added, _ = review_candidate.capture(self.work)
        self.assertNotEqual(deleted, added)

    def test_empty_root_stop_blocks_before_traversal_without_deletion(self):
        p = self.work / 'process_stop'
        p.write_bytes(b'')
        with patch.object(review_candidate.safe_io, 'directory',
                          side_effect=AssertionError('traversal must not start')):
            with self.assertRaisesRegex(ValueError, 'process_stop blocks'):
                review_candidate.capture(self.work)
        self.assertTrue(p.is_file())

    def test_root_stop_directory_blocks(self):
        p = self.work / 'process_stop'; p.mkdir()
        with self.assertRaisesRegex(ValueError, 'process_stop blocks'):
            review_candidate.capture(self.work)
        self.assertTrue(p.is_dir())

    def test_dangling_root_stop_blocks(self):
        p = self.work / 'process_stop'
        try:
            p.symlink_to(self.work / 'missing')
        except (OSError, NotImplementedError):
            self.skipTest('Host does not permit symbolic-link fixture')
        with self.assertRaisesRegex(ValueError, 'process_stop blocks'):
            review_candidate.capture(self.work)
        self.assertTrue(p.is_symlink())

    def test_nested_stop_symlink_is_not_excused_as_historical_evidence(self):
        p = self.marker(); p.unlink()
        try:
            p.symlink_to(self.work / 'missing')
        except (OSError, NotImplementedError):
            self.skipTest('Host does not permit symbolic-link fixture')
        with self.assertRaisesRegex(ValueError, 'Linked candidate path'):
            review_candidate.capture(self.work)
        self.assertTrue(p.is_symlink())

    def test_root_stop_created_while_hashing_blocks_completed_capture(self):
        product = self.work / 'product.txt'; product.write_text('original')
        original_open = review_candidate.safe_io.open_file
        @contextmanager
        def open_and_stop(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as f:
                yield f
            if Path(path) == product:
                (self.work / 'process_stop').write_text('Operator stop during hashing')
        with patch.object(review_candidate.safe_io, 'open_file', open_and_stop):
            with self.assertRaisesRegex(ValueError, 'process_stop blocks'):
                review_candidate.capture(self.work)
        self.assertTrue((self.work / 'process_stop').exists())

    def test_entry_limit_remains_finite_and_reports_count_limit_and_path(self):
        for name in ('a', 'b', 'c'):
            (self.work / name).write_text(name)
        with patch.object(review_candidate, 'MAX_ENTRIES', 2):
            with self.assertRaisesRegex(ValueError, "count=3, limit=2, path='c'"):
                review_candidate.capture(self.work)
        with patch.object(review_candidate, 'MAX_ENTRIES', 3):
            manifest, _ = review_candidate.capture(self.work)
        self.assertEqual(set(manifest['files']), {'a', 'b', 'c'})


class NativeReviewStopScopeTests(network.ProcessFixture):
    make_failed_archive = native.NativeReviewEntryTests.make_failed_archive
    summaries = native.NativeReviewEntryTests.summaries
    invoke = native.NativeReviewEntryTests.invoke

    def historical_marker(self):
        p = self.work / HISTORICAL
        p.parent.mkdir(parents=True)
        p.write_text('Historical test STOP; retain as evidence.\n', encoding='utf-8')
        return p

    def test_fresh_review_with_historical_stop_no_producer_or_archive_mutation(self):
        self.make_failed_archive()
        p = self.historical_marker()
        before = network.snapshot(self.capture.parent.parent)
        result, phases, count = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}])
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])
        self.assertEqual(count, 1)
        self.assertEqual(before, network.snapshot(self.capture.parent.parent))
        self.assertEqual(p.read_text(), 'Historical test STOP; retain as evidence.\n')
        self.assertEqual((self.summaries()[0]['auftrag_runs'], self.summaries()[0]['review_runs']), (0, 1))
        manifests = list(self.root.glob('*/runs/*/task-2/review-candidate-001/manifest.json'))
        self.assertEqual(len(manifests), 1)
        self.assertIn(HISTORICAL.as_posix(), json.loads(manifests[0].read_text())['files'])
        self.assertIn('2. ***DONE***', self.todo.read_text())

    def test_historical_evidence_mutation_during_review_blocks_done(self):
        self.make_failed_archive()
        p = self.historical_marker()
        def change(kwargs, result):
            p.write_text('Altered historical evidence')
        result, phases, count = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}], callback=change)
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, ['review'])
        self.assertEqual(count, 1)
        self.assertNotIn('***DONE***', self.todo.read_text())
        self.assertEqual(self.summaries()[0]['execution_error']['code'], 'review_candidate_changed')

    def test_root_stop_still_blocks_before_any_model_call(self):
        self.make_failed_archive()
        self.historical_marker()
        self.stop.write_text('Actual operator stop')
        result, phases, count = self.invoke([])
        self.assertNotEqual(result, 0)
        self.assertEqual((phases, count), ([], 0))
        self.assertEqual(self.stop.read_text(), 'Actual operator stop')
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_stop_created_during_review_blocks_acceptance(self):
        self.make_failed_archive()
        self.historical_marker()
        def stop(kwargs, result):
            self.stop.write_text('Actual operator stop during review')
        result, phases, count = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}], callback=stop)
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, ['review'])
        self.assertNotIn('***DONE***', self.todo.read_text())
        self.assertEqual(self.stop.read_text(), 'Actual operator stop during review')

    def test_source_attempt_stop_remains_a_blocker(self):
        self.make_failed_archive()
        self.historical_marker()
        p = self.capture / 'capture.json'
        info = json.loads(p.read_text()); info['process_stop_triggered'] = True
        p.write_text(json.dumps(info))
        result, phases, count = self.invoke([])
        self.assertNotEqual(result, 0)
        self.assertEqual((phases, count), ([], 0))
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_registered_peer_stop_remains_authoritative_not_just_a_filename(self):
        self.make_failed_archive()
        p = self.historical_marker()
        original = run_todos.TodoRunner._poll_process_stop
        def active_peer(runner):
            runner._active_parallel_stop_paths = (p,)
            return original(runner)
        with patch.object(run_todos.TodoRunner, '_poll_process_stop', active_peer):
            result, phases, count = self.invoke([])
        self.assertNotEqual(result, 0)
        self.assertEqual((phases, count), ([], 0))
        self.assertNotIn('***DONE***', self.todo.read_text())
        self.assertEqual(p.read_text(), 'Historical test STOP; retain as evidence.\n')


if __name__ == '__main__':
    unittest.main()
