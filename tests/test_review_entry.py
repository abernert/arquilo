#!/usr/bin/env python3
"""Native review-first recovery qualification; no real providers or credentials."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import arquilo
import autobuild
import run_todos
import review_entry
import review_candidate
import test_review_resume_network as network_tests
from test_review_resume_network import snapshot
from test_reconnect_stop import PASS, FAIL, COMPLETE, FAILED, answer


class NativeReviewEntryTests(network_tests.ProcessFixture):
    make_failed_archive = network_tests.NativeRecoveryTests.make_failed_archive
    def summaries(self):
        return [json.loads(p.read_text()) for p in self.root.glob('*/runs/*/task-2/autobuild_summary.json')
                if p.parent != self.capture.parent]

    def invoke(self, scenarios, args=None, callback=None):
        output = io.StringIO()
        original = autobuild.run_codex_exec_json
        phases = []
        def call(**kwargs):
            phases.append(kwargs['phase'])
            result = original(**kwargs)
            if callback:
                callback(kwargs, result)
            return result
        with self.launch(scenarios) as calls, patch.object(autobuild, 'run_codex_exec_json', side_effect=call), \
                redirect_stdout(output), redirect_stderr(output):
            result = arquilo.main(args or self.args)
        self.last_output = output.getvalue()
        return result, phases, calls.call_count

    def test_native_review_counts_only_actual_calls(self):
        self.make_failed_archive()
        before = snapshot(self.capture.parent.parent)
        result, phases, count = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}])
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])
        summary = self.summaries()[0]
        self.assertEqual((summary['auftrag_runs'], summary['review_runs']), (0, 1))
        self.assertEqual(summary['call_budget']['used'], 2)  # original producer + new review
        self.assertEqual(before, snapshot(self.capture.parent.parent))
        self.assertEqual(summary['execution_attempts'][0]['phase'], 'review')

    def test_short_form_derives_paths_and_budget_without_old_flags(self):
        self.make_failed_archive()
        short = self.args[:self.args.index('--')]
        # Stub inventory metadata too; short form deliberately disables inherited MCP.
        with patch.object(autobuild, 'run_codex_exec_json') as call:
            call.return_value = autobuild.RunResult(assistant_messages=[json.dumps(PASS)],
                turn_completed=True, process_exit_code=0)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(arquilo.main(short), 0)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.kwargs['phase'], 'review')
            self.assertEqual(call.call_args.kwargs['mcp_servers'], ())

    def test_original_range_and_prompt_catalog_change_are_not_task_changes(self):
        self.make_failed_archive()
        args = self.args.copy()
        args[args.index('--start') + 1] = '1'
        args += ['--prompt-config', 'en']
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}], args)
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])
        self.assertIn('3. ***Task***', self.todo.read_text())

    def test_unfinished_production_can_be_freshly_reviewed_without_claiming_success(self):
        self.make_failed_archive()
        p = self.capture / 'capture.json'
        info = json.loads(p.read_text()); info.update(completion_seen=False, process_exit_code=1,
            error={'code': 'codex_missing_completion'}, status='failed')
        p.write_text(json.dumps(info))
        # No old final answer is needed to review the current candidate.
        (self.capture / 'response.txt').unlink()
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}])
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])
        self.assertFalse(json.loads(p.read_text())['completion_seen'])
        self.assertEqual(self.summaries()[0]['auftrag_runs'], 0)

    def test_crash_without_finalized_capture_or_summary_is_reviewable(self):
        self.make_failed_archive()
        (self.capture / 'capture.json').unlink()
        (self.capture.parent / 'autobuild_summary.json').unlink()
        p = self.capture.parent.parent / 'run.json'
        run = json.loads(p.read_text()); run.update(status='running', finished_at=None, tasks=[])
        p.write_text(json.dumps(run))
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}])
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])

    def test_check_only_does_not_write_or_call_any_model(self):
        self.make_failed_archive()
        args = self.args.copy(); args.insert(2, '--check-only')
        before = snapshot(self.base)
        with patch.object(run_todos, 'main', side_effect=AssertionError('runner started')):
            result, phases, count = self.invoke([], args)
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, [])
        self.assertEqual(count, 0)
        self.assertEqual(before, snapshot(self.base))

    def test_changed_actual_task_is_refused_before_review(self):
        self.make_failed_archive()
        self.todo.write_text(self.todo.read_text().replace('synthetic output', 'different product'))
        result, phases, _ = self.invoke([])
        self.assertEqual(result, 125)
        self.assertEqual(phases, [])
        self.assertIn('requirements', self.last_output)

    def test_changed_policy_is_refused_before_review(self):
        self.make_failed_archive()
        (self.work / 'config/policy.md').write_text('New policy')
        result, phases, _ = self.invoke([])
        self.assertEqual(result, 125)
        self.assertEqual(phases, [])
        self.assertIn('policy changed', self.last_output)

    def test_source_contract_tamper_is_refused(self):
        self.make_failed_archive()
        p = self.capture.parent / 'original_contract.json'
        data = json.loads(p.read_text()); data['task_text'] = 'fabricated contract'; p.write_text(json.dumps(data))
        result, phases, _ = self.invoke([])
        self.assertEqual(result, 125)
        self.assertEqual(phases, [])

    def test_live_candidate_drift_blocks_pass_and_done(self):
        self.make_failed_archive()
        product = self.work / 'product.txt'; product.write_text('before')
        def change(kwargs, result):
            if kwargs['phase'] == 'review':
                product.write_text('after')
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}], callback=change)
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, ['review'])
        self.assertNotIn('***DONE***', self.todo.read_text())
        self.assertEqual(self.summaries()[0]['execution_error']['code'], 'review_candidate_changed')

    def test_recheck_after_logging_before_done_blocks_late_drift(self):
        self.make_failed_archive()
        original = run_todos.TodoRunner._finalize_post_todo_log
        def late(runner, outcome):
            original(runner, outcome)
            (self.work / 'late.txt').write_text('late mutation')
        with patch.object(run_todos.TodoRunner, '_finalize_post_todo_log', late):
            result, _, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}])
        self.assertNotEqual(result, 0)
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_review_failure_does_not_start_fix_without_opt_in_or_write_stop(self):
        self.make_failed_archive()
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(FAIL)), COMPLETE]}])
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, ['review'])
        self.assertFalse(self.stop.exists())
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_explicit_continue_runs_review_fix_review_not_production(self):
        self.make_failed_archive()
        args = self.args.copy(); args.insert(2, '--continue-on-fail')
        result, phases, _ = self.invoke([
            {'events': [answer(json.dumps(FAIL)), COMPLETE]},
            {'events': [answer('Fixed missing output.'), COMPLETE]},
            {'events': [answer(json.dumps(PASS)), COMPLETE]},
        ], args)
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review', 'fix', 'review'])
        self.assertEqual(self.summaries()[0]['auftrag_runs'], 1)
        self.assertEqual(self.summaries()[0]['call_budget']['used'], 4)

    def test_review_transport_failure_does_not_start_fix(self):
        self.make_failed_archive()
        args = self.args.copy(); args.insert(2, '--continue-on-fail')
        result, phases, _ = self.invoke([{'events': [FAILED], 'exit': 1}], args)
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, ['review'])

    def test_budget_cannot_be_refunded_by_recovery(self):
        self.make_failed_archive()
        args = self.args.copy(); args[args.index('--max-calls') + 1] = '1'
        result, phases, _ = self.invoke([], args)
        self.assertNotEqual(result, 0)
        self.assertEqual(phases, [])
        self.assertNotIn('***DONE***', self.todo.read_text())

    def test_past_stop_cannot_be_excused_as_connectivity(self):
        self.make_failed_archive()
        p = self.capture / 'capture.json'
        info = json.loads(p.read_text()); info['process_stop_triggered'] = True; p.write_text(json.dumps(info))
        result, phases, _ = self.invoke([])
        self.assertEqual(result, 125)
        self.assertEqual(phases, [])

    def test_candidate_records_uncommitted_nested_repo_diff_and_hashes_without_filters(self):
        self.make_failed_archive()
        repo = self.work / 'target'; repo.mkdir()
        def git(*args):
            subprocess.run(['git', '-C', str(repo), *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git('init'); git('config', 'user.email', 'test@example.invalid'); git('config', 'user.name', 'Test')
        source = repo / 'source.txt'; source.write_text('old\n')
        git('add', 'source.txt'); git('commit', '-m', 'initial')
        source.write_text('new\n')
        marker = self.base / 'filter-executed'
        # A configured clean filter must never be invoked by candidate capture.
        git('config', 'filter.evil.clean', f'echo bad > "{marker}"')
        (repo / '.gitattributes').write_text('*.txt filter=evil\n')
        manifest, diffs = review_candidate.capture(self.work)
        self.assertFalse(marker.exists())
        self.assertIn('target/source.txt', manifest['files'])
        self.assertIn(b'-old', diffs['git-001.diff'])
        self.assertIn(b'+new', diffs['git-001.diff'])
        self.assertEqual(manifest['repositories'][0]['root'], 'target')

    def test_interrupted_review_starts_a_new_review_not_a_producer(self):
        self.make_failed_archive()
        result, phases, _ = self.invoke([{'events': [FAILED], 'exit': 1}])
        self.assertNotEqual(result, 0)
        captures = list(self.root.glob('*/runs/*/task-2/001-review/capture.json'))
        self.assertEqual(len(captures), 1)
        args = self.args.copy(); args[args.index('--capture-dir') + 1] = str(captures[0].parent)
        result, phases, _ = self.invoke([{'events': [answer(json.dumps(PASS)), COMPLETE]}], args)
        self.assertEqual(result, 0, self.last_output)
        self.assertEqual(phases, ['review'])

    def test_live_controller_lock_prevents_review_dispatch(self):
        self.make_failed_archive()
        from controller_state import PlanAuthority
        state = self.capture.parents[3]
        lock = PlanAuthority(self.todo, state, workspace=self.work)
        try:
            result, phases, _ = self.invoke([])
            self.assertNotEqual(result, 0)
            self.assertEqual(phases, [])
        finally:
            lock.close()

    def test_runtime_profile_preflight_only_before_authorized_fix(self):
        self.make_failed_archive()
        with patch.object(run_todos, 'run_runtime_profile_preflight') as preflight:
            result, phases, _ = self.invoke([{'events': [answer(json.dumps(FAIL)), COMPLETE]}])
            self.assertNotEqual(result, 0)
            preflight.assert_not_called()
        args = self.args.copy(); args.insert(2, '--continue-on-fail')
        with patch.object(run_todos, 'run_runtime_profile_preflight') as preflight:
            result, phases, _ = self.invoke([
                {'events': [answer(json.dumps(FAIL)), COMPLETE]},
                {'events': [answer('fixed'), COMPLETE]},
                {'events': [answer(json.dumps(PASS)), COMPLETE]},
            ], args)
            self.assertEqual(result, 0, self.last_output)
            self.assertEqual(phases, ['review', 'fix', 'review'])
            preflight.assert_called_once()


if __name__ == '__main__':
    unittest.main()
