# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline tests: no network, credentials, Codex execution or model calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import run_todos
import safe_io
from controller_state import PlanIntegrityError, state_directory, state_directory_path
from todo_context import MAX_PREAMBLE_BYTES
from todo_lint import lint_todo_file, lint_todo_text
from todo_template import initialize_todo_template


class TodoTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root / 'work space'
        self.workspace.mkdir()
        self.target = self.workspace / 'tasks.md'
        self.source = self.root / 'Vorlage ä.md'
        self.source.write_text('# Project\n\n1. ***Task***: Create hello.txt\n', encoding='utf-8')
        self.state = self.root / 'private-state'

    def initialize(self, **overrides):
        arguments = dict(workdir=self.workspace, state_root=self.state,
                         validate_directives=run_todos.validate_removed_directives)
        arguments.update(overrides)
        return initialize_todo_template(self.target, self.source, **arguments)

    def cli(self, *extra, template=True):
        arguments = ['--todo-file', str(self.target), '--workdir', str(self.workspace),
                     '--state-dir', str(self.state)]
        if template:
            arguments += ['--todo-template', str(self.source)]
        arguments += list(extra)
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), patch.object(run_todos, '_beep'):
            code = run_todos.main(arguments)
        return code, output.getvalue(), errors.getvalue()

    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Symlinks unavailable on this host: {exc}')

    def test_copy_preserves_exact_bytes_and_does_not_create_state(self):
        data = b'\xef\xbb\xbf# Project\r\n\r\n1. ***Task***: Gr\xc3\xbc\xc3\x9fe\r\n'
        self.source.write_bytes(data)
        path, workspace, created = self.initialize()
        self.assertEqual((path, workspace, created), (self.target, self.workspace, True))
        self.assertEqual(self.target.read_bytes(), data)
        self.assertEqual(self.source.read_bytes(), data)
        self.assertEqual(self.target.stat().st_nlink, 1)
        self.assertFalse(self.state.exists())
        self.assertEqual(list(self.workspace.glob('.arquilo-init-*')), [])

    def test_existing_target_ignores_changed_template(self):
        self.target.write_text('1. ***DONE***: Keep this progress\n')
        self.source.write_text('not a valid task list')
        self.assertFalse(self.initialize()[2])
        self.assertEqual(self.target.read_text(), '1. ***DONE***: Keep this progress\n')

    def test_existing_target_does_not_read_or_resolve_unused_template(self):
        self.target.write_text('1. ***DONE***: Kept\n')
        self.source.unlink()
        self.source = Path('unused\0invalid')
        with patch.object(safe_io, 'read_bytes', side_effect=AssertionError('unused source read')):
            self.assertFalse(self.initialize()[2])

    def test_nested_destination_is_created(self):
        self.target = self.workspace / 'plans' / 'iteration' / 'tasks.md'
        self.assertTrue(self.initialize()[2])
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_default_workspace_is_destination_parent(self):
        self.assertEqual(self.initialize(workdir=None)[1], self.workspace)

    def test_relative_paths_keep_invocation_directory_semantics(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.target = Path('work space/tasks.md')
            self.source = Path('Vorlage ä.md')
            target, workspace, created = self.initialize(workdir=Path('work space'))
        finally:
            os.chdir(previous)
        self.assertEqual(target, self.workspace / 'tasks.md')
        self.assertEqual(workspace, self.workspace)
        self.assertTrue(created)

    def test_relative_target_is_not_rebased_to_workdir(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.target = Path('tasks.md')
            with self.assertRaisesRegex(ValueError, 'inside --workdir'):
                self.initialize()
        finally:
            os.chdir(previous)
        self.assertFalse((self.root / 'tasks.md').exists())

    def test_outside_target_is_rejected(self):
        self.target = self.root / 'outside.md'
        with self.assertRaisesRegex(ValueError, 'inside --workdir'):
            self.initialize()
        self.assertFalse(self.target.exists())

    def test_missing_workdir_is_not_created(self):
        self.workspace = self.root / 'missing'
        self.target = self.workspace / 'tasks.md'
        with self.assertRaisesRegex(ValueError, 'Workdir must already exist'):
            self.initialize()
        self.assertFalse(self.workspace.exists())

    def test_existing_destination_directory_is_not_overwritten(self):
        self.target.mkdir()
        with self.assertRaisesRegex(ValueError, 'not a regular file'):
            self.initialize()
        self.assertTrue(self.target.is_dir())

    def test_missing_template_fails_without_creating_destination_or_state(self):
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            self.initialize()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.state.exists())

    def test_template_directory_is_rejected(self):
        self.source.unlink()
        self.source.mkdir()
        with self.assertRaises((ValueError, OSError)):
            self.initialize()
        self.assertFalse(self.target.exists())

    def test_unreadable_template_is_reported_without_writes(self):
        with patch.object(safe_io, 'read_bytes', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.initialize()
        self.assertFalse(self.target.exists())

    def test_invalid_utf8_and_misplaced_bom_fail_before_copy(self):
        for data in (b'\xff', b'\xef\xbb\xbf\xef\xbb\xbf1. ***Task***: Duplicate BOM\n'):
            with self.subTest(data=data):
                self.source.write_bytes(data)
                with self.assertRaises(UnicodeError):
                    self.initialize()
                self.assertFalse(self.target.exists())

    def test_invalid_task_lists_fail_before_copy(self):
        for text in ('', '# No tasks\n', '1. ***Task***: A\n1. ***Task***: B\n',
                     '1. ***DOING***: Unsupported\n', '***WAIT on=todo:9***\n1. ***Task***: A\n',
                     '***CFG iact=true***\n1. ***Task***: Removed directive\n'):
            with self.subTest(text=text):
                self.source.write_text(text)
                with self.assertRaises(ValueError):
                    self.initialize()
                self.assertFalse(self.target.exists())
                self.assertFalse(self.state.exists())

    def test_required_preamble_is_validated_before_copy(self):
        self.source.write_text('1. ***Task***: Missing context\n')
        with self.assertRaisesRegex(ValueError, 'preamble required'):
            self.initialize(preamble_mode='required')
        self.assertFalse(self.target.exists())

    def test_oversized_preamble_is_not_silently_copied(self):
        self.source.write_text('X' * (MAX_PREAMBLE_BYTES + 1) + '\n1. ***Task***: A\n')
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.initialize()
        self.assertFalse(self.target.exists())
        self.assertTrue(self.initialize(preamble_mode='off')[2])

    def test_referenced_files_are_not_copied(self):
        (self.root / 'input.txt').write_text('private input')
        self.source.write_text('1. ***Task***: Read input.txt and write output.txt\n')
        self.initialize()
        self.assertFalse((self.workspace / 'input.txt').exists())

    def test_copy_uses_validated_snapshot_even_if_template_changes(self):
        original = self.source.read_bytes()
        def change_source(_):
            self.source.write_text('not a task list anymore')
        self.initialize(validate_directives=change_source)
        self.assertEqual(self.target.read_bytes(), original)

    def test_state_path_lookup_has_no_side_effects_and_matches_runner(self):
        path = state_directory_path(self.workspace, self.target, self.state)
        self.assertFalse(self.state.exists())
        self.assertEqual(state_directory(self.workspace, self.target, self.state), path)

    def test_missing_task_with_saved_or_empty_controller_state_refuses(self):
        path = state_directory(self.workspace, self.target, self.state)
        with self.assertRaisesRegex(PlanIntegrityError, 'controller state already exists'):
            self.initialize()
        (path / 'plan.json').write_text('keep this evidence')
        with self.assertRaises(PlanIntegrityError):
            self.initialize()
        self.assertEqual((path / 'plan.json').read_text(), 'keep this evidence')
        self.assertFalse(self.target.exists())

    def test_default_state_root_is_checked_too(self):
        with patch('controller_state.default_state_root', return_value=self.state):
            state_directory(self.workspace, self.target)
            with self.assertRaises(PlanIntegrityError):
                self.initialize(state_root=None)

    def test_other_plan_state_does_not_block_a_new_task_list(self):
        state_directory(self.workspace, self.workspace / 'other.md', self.state)
        self.assertTrue(self.initialize()[2])

    def test_state_root_inside_workspace_is_rejected_before_copy(self):
        with self.assertRaises(PlanIntegrityError):
            self.initialize(state_root=self.workspace / 'state')
        self.assertFalse(self.target.exists())

    def test_state_appearing_during_validation_blocks_copy(self):
        def add_state(_):
            state_directory(self.workspace, self.target, self.state)
        with self.assertRaisesRegex(PlanIntegrityError, 'appeared'):
            self.initialize(validate_directives=add_state)
        self.assertFalse(self.target.exists())

    def test_target_symlink_is_not_followed(self):
        outside = self.root / 'outside.md'
        outside.write_text('keep')
        self.symlink(self.target, outside)
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()
        self.assertEqual(outside.read_text(), 'keep')

    def test_dangling_target_symlink_is_not_overwritten(self):
        outside = self.root / 'not-created.md'
        self.symlink(self.target, outside)
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()
        self.assertFalse(outside.exists())
        self.assertTrue(self.target.is_symlink())

    def test_symlinked_destination_parent_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.symlink(self.workspace / 'linked', outside, directory=True)
        self.target = self.workspace / 'linked' / 'tasks.md'
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()
        self.assertFalse((outside / 'tasks.md').exists())

    def test_explicit_workspace_root_alias_can_be_canonicalized(self):
        alias = self.root / 'alias'
        self.symlink(alias, self.workspace, directory=True)
        self.target = alias / 'tasks.md'
        target, workspace, created = self.initialize(workdir=alias)
        self.assertEqual(target, self.workspace / 'tasks.md')
        self.assertEqual(workspace, self.workspace)
        self.assertTrue(created)

    def test_source_symlink_and_hardlink_are_rejected(self):
        original = self.source
        self.source = self.root / 'linked-source.md'
        self.symlink(self.source, original)
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()
        self.source.unlink()
        os.link(original, self.source)
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()
        self.assertFalse(self.target.exists())

    def test_hardlinked_target_is_rejected(self):
        os.link(self.source, self.target)
        with self.assertRaises(safe_io.UnsafePathError):
            self.initialize()

    def test_racing_target_is_never_overwritten(self):
        publish = safe_io.atomic_create
        def race(target, data):
            target.write_text('another caller wins')
            publish(target, data)
        with patch.object(safe_io, 'atomic_create', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.initialize()
        self.assertEqual(self.target.read_text(), 'another caller wins')
        self.assertEqual(list(self.workspace.glob('.arquilo-init-*')), [])

    def test_atomic_create_refuses_existing_file_and_directory(self):
        self.target.write_text('original')
        with self.assertRaises(OSError):
            safe_io.atomic_create(self.target, b'new')
        self.assertEqual(self.target.read_text(), 'original')
        self.target.unlink()
        self.target.mkdir()
        with self.assertRaises(OSError):
            safe_io.atomic_create(self.target, b'new')
        self.assertTrue(self.target.is_dir())

    def test_staging_failure_leaves_no_partial_target(self):
        with patch.object(safe_io.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.initialize()
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.workspace.glob('.arquilo-init-*')), [])

    def test_two_initializers_publish_only_one_complete_file(self):
        publish = safe_io.atomic_create
        barrier = threading.Barrier(2)
        def synchronized(target, data):
            barrier.wait(timeout=10)
            publish(target, data)
        def attempt():
            try:
                return self.initialize()[2]
            except FileExistsError:
                return False
        with patch.object(safe_io, 'atomic_create', side_effect=synchronized):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_nlink, 1)

    def test_text_and_file_lint_use_same_contract(self):
        self.assertEqual(lint_todo_file(self.source, workdir=self.workspace),
                         lint_todo_text(self.source.read_text(), workdir=self.workspace))

    def test_cli_requires_todo_file_and_keeps_old_missing_file_error(self):
        with redirect_stderr(io.StringIO()), patch.object(run_todos, '_beep'):
            self.assertEqual(run_todos.main(['--todo-template', str(self.source)]), 2)
        self.assertEqual(self.cli(template=False)[0], 1)
        self.assertFalse(self.target.exists())

    def test_cli_initialization_failure_precedes_codex_and_runner(self):
        self.source.write_text('invalid')
        with patch.object(run_todos, 'TodoRunner') as runner, \
             patch.object(run_todos, 'run_codex_workspace_write_preflight') as preflight:
            code, _, error = self.cli()
        self.assertEqual(code, 2)
        self.assertIn('Invalid task-list template', error)
        runner.assert_not_called()
        preflight.assert_not_called()

    def test_cli_initializes_before_preflight_and_passes_working_copy(self):
        def check_preflight(**_):
            self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        with patch.object(run_todos, 'TodoRunner') as runner, \
             patch.object(run_todos, 'run_codex_workspace_write_preflight', side_effect=check_preflight):
            runner.return_value.exit_code = 0
            self.assertEqual(self.cli()[0], 0)
        self.assertEqual(runner.call_args.kwargs['todo_file'], self.target)
        self.assertEqual(runner.call_args.kwargs['workdir'], self.workspace)
        runner.return_value.run.assert_called_once()

    def test_cli_without_template_keeps_external_todo_file_compatibility(self):
        external = self.source
        self.target = external
        with patch.object(run_todos, 'TodoRunner') as runner, \
             patch.object(run_todos, 'run_codex_workspace_write_preflight'), \
             patch.object(run_todos, 'initialize_todo_template') as initialize:
            runner.return_value.exit_code = 0
            self.assertEqual(self.cli(template=False)[0], 0)
        initialize.assert_not_called()
        self.assertEqual(runner.call_args.kwargs['todo_file'], external)

    def test_explicit_initialization_also_runs_in_dry_run_but_no_models_or_state(self):
        preview = self.workspace / 'preview.md'
        with patch.object(run_todos, 'autobuild_start', side_effect=AssertionError('model call')):
            code, _, error = self.cli('--dry-run', '--dry-run-file', str(preview))
        self.assertEqual(code, 0, error)
        self.assertIn('Initialized task list', error)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertTrue(preview.is_file())
        self.assertFalse(self.state.exists())

    def test_actual_no_work_run_resume_and_missing_file_recovery(self):
        self.source.write_text('1. ***DONE***: Already reviewed\n')
        original = self.source.read_bytes()
        with patch.object(run_todos, 'autobuild_start', side_effect=AssertionError('model call')):
            code, _, error = self.cli('--skip-codex-preflight')
            self.assertEqual(code, 0, error)
            path = state_directory_path(self.workspace, self.target, self.state)
            evidence = path / 'plan.json'
            before = evidence.read_bytes()
            self.source.unlink()
            code, _, error = self.cli('--skip-codex-preflight')
            self.assertEqual(code, 0, error)
            self.assertIn('ignored', error)
            self.assertEqual(self.target.read_bytes(), original)
            self.assertEqual(evidence.read_bytes(), before)
            self.target.unlink()
            self.source.write_bytes(original)
            code, _, error = self.cli('--skip-codex-preflight', '--accept-plan-changes')
            self.assertEqual(code, 2, error)
            self.assertIn('controller state already exists', error)
            self.assertEqual(evidence.read_bytes(), before)
            self.assertFalse(self.target.exists())

    def test_capabilities_and_parser_advertise_template(self):
        self.assertEqual(run_todos.arquilo_capabilities_payload()['features']['run_todos.todo_template'], 1)
        self.assertEqual(run_todos.parse_args(['--todo-template', str(self.source)]).todo_template, self.source)
        self.assertIsNone(run_todos.parse_args([]).todo_template)


if __name__ == '__main__':
    unittest.main()
