# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded concurrent writers; real files and journals, no model/provider calls."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import queue
import threading
from unittest.mock import patch

from adversarial.harness import IsolatedControllerCase
from controller_state import PlanAuthority, PlanIntegrityError
from decision_request import DecisionInputError, read_input_text
import run_todos
import safe_io


PLAN = '1. ***Task***: Create first.txt.\n2. ***Task***: Create second.txt.\n'
CHILDREN = PLAN.replace('2. ***Task***', '1.1. ***Task***: Create child.txt.\n2. ***Task***')


class ControlledWriter:
    """A real competing writer, with explicit barriers instead of timed sleeps."""

    def __init__(self, path):
        self.path = path
        self.commands = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while (request := self.commands.get()) is not None:
            text, done, errors = request
            try:
                self.path.write_bytes(text.encode('utf-8'))
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

    def write(self, text):
        done, errors = threading.Event(), []
        self.commands.put((text, done, errors))
        if not done.wait(5):
            raise AssertionError('Competing writer did not reach its barrier')
        if errors:
            raise errors[0]

    def close(self):
        self.commands.put(None)
        self.thread.join(5)
        if self.thread.is_alive():
            raise AssertionError('Competing writer did not stop')


class SnapshotAuthorityTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)

    def writer(self):
        writer = ControlledWriter(self.todo)
        self.addCleanup(writer.close)
        return writer

    def journal(self, runner):
        return json.loads(safe_io.read_text(runner.state_dir / 'plan.json'))['text']

    def test_mark_done_cannot_import_a_transient_unapproved_read(self):
        runner = self.runner()
        first = runner._parse_todo_file()[0]
        writer = self.writer()
        read = run_todos.read_utf8
        forged = PLAN.replace('2. ***Task***', '2. ***DONE***')

        def transient(path, **options):
            if Path(path) == self.todo and options.get('preserve_bom'):
                writer.write(forged)
                value = read(path, **options)
                writer.write(PLAN)
                return value
            return read(path, **options)

        # This is the old unbound read boundary, not a fabricated return value.
        # Removing that read is also a valid way to eliminate the interleaving.
        with patch.object(run_todos, 'read_utf8', side_effect=transient), redirect_stdout(io.StringIO()):
            runner._mark_todo_as_done(first)
        expected = PLAN.replace('1. ***Task***', '1. ***DONE***')
        self.assertEqual(self.todo.read_bytes(), expected.encode('utf-8'))
        self.assertEqual(self.journal(runner), expected)
        runner.close()
        restarted = self.runner()
        self.assertEqual(restarted._next_todo().identifier, '2')

    def test_approved_replace_rejects_extra_status_requirements_and_directives(self):
        runner = self.runner()
        authority = runner.plan_authority
        done = PLAN.replace('1. ***Task***', '1. ***DONE***')
        for candidate in (done.replace('2. ***Task***', '2. ***DONE***'),
                          done.replace('second.txt', 'easier.txt'),
                          '***CFG max_calls=1***\n' + done):
            with self.subTest(candidate=candidate):
                with self.assertRaises(PlanIntegrityError):
                    authority.replace_approved(candidate)
                self.assertEqual(self.journal(runner), PLAN)
                self.assertEqual(self.todo.read_bytes(), PLAN.encode('utf-8'))

    def test_mutable_revision_cannot_be_overwritten_by_stale_completion(self):
        runner = self.runner(allow_todo_modifications=True, max_calls=2)
        first = runner._parse_todo_file()[0]
        budget = runner._call_budget_for('1')
        budget.consume('1', 'production')
        writer = self.writer()
        changed = PLAN.replace('Create first.txt.', 'Create revised.txt.')
        replace = runner.plan_authority.replace_approved

        def intervene(candidate, **kwargs):
            writer.write(changed)
            return replace(candidate, **kwargs)

        with patch.object(runner.plan_authority, 'replace_approved', side_effect=intervene):
            with self.assertRaises(PlanIntegrityError):
                runner._mark_todo_as_done(first)
        self.assertEqual(self.todo.read_bytes(), changed.encode('utf-8'))
        self.assertEqual(self.journal(runner), changed)
        self.assertFalse(runner.plan_authority.mutations[-1]['independently_verified'])
        self.assertEqual(budget.snapshot()['used'], 1)

    def test_children_adoption_rejects_a_changed_comparison_read(self):
        runner = self.runner()
        self.write_plan(CHILDREN)
        writer = self.writer()
        forged = CHILDREN.replace('2. ***Task***', '2. ***DONE***')
        read, reads = safe_io.read_text, 0

        def intervene(path, *args, **kwargs):
            nonlocal reads
            if Path(path) == self.todo:
                reads += 1
                if reads == 2:
                    writer.write(forged)
            return read(path, *args, **kwargs)

        with patch.object(safe_io, 'read_text', side_effect=intervene):
            with self.assertRaises(PlanIntegrityError):
                runner.plan_authority.accept_children('1', 2)
        self.assertEqual(self.journal(runner), PLAN)
        self.assertEqual(runner.plan_authority.text, PLAN)
        runner.close()
        with self.assertRaises(PlanIntegrityError):
            PlanAuthority(self.todo, runner.state_dir)

    def test_children_late_write_never_becomes_private_authority(self):
        runner = self.runner()
        self.write_plan(CHILDREN)
        writer = self.writer()
        forged = CHILDREN.replace('2. ***Task***', '2. ***DONE***')
        save = runner.plan_authority._save

        def intervene(text, **kwargs):
            writer.write(forged)
            return save(text, **kwargs)

        with patch.object(runner.plan_authority, '_save', side_effect=intervene):
            self.assertEqual(runner.plan_authority.accept_children('1', 2), ['1.1'])
        self.assertEqual(self.journal(runner), CHILDREN)
        self.assertEqual(runner.plan_authority.text, CHILDREN)
        with self.assertRaises(PlanIntegrityError):
            runner.plan_authority.check()

    def test_bom_crlf_and_mixed_command_styles_survive_done_and_children(self):
        plan = '\ufeff 1. ***Task***: Create café.txt.\r\n2. Auftrag: Create second.txt.\r\n'
        self.write_plan(plan)
        runner = self.runner()
        with redirect_stdout(io.StringIO()):
            runner._mark_todo_as_done(runner._parse_todo_file()[0])
        done = plan.replace('***Task***', '***DONE***', 1)
        children = done + '2.1. Auftrag: Create child.txt.\r\n'
        self.write_plan(children)
        runner.plan_authority.accept_children('2', 1)
        self.assertEqual(self.todo.read_bytes(), children.encode('utf-8'))
        self.assertEqual(self.journal(runner), children)
        runner.close()
        self.runner().plan_authority.check()


class OriginalContractReadTests(IsolatedControllerCase):
    def setUp(self):
        super().setUp()
        self.write_plan(PLAN)

    def link(self, path, target, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Native symlink creation unavailable: {exc}')

    def capture(self, runner, path=None):
        runner._capture_original_contract('1', 'Create first.txt.', path or self.todo,
                                          runner.run_dir / 'contract-regression')

    def test_contract_refuses_replaced_task_symlink_before_archiving(self):
        runner = self.runner()
        secret = self.victims / 'outside.md'
        secret.write_text(PLAN.replace('first.txt', 'PRIVATE_CANARY'))
        self.todo.unlink()
        self.link(self.todo, secret)
        with self.assertRaises((DecisionInputError, safe_io.UnsafePathError, OSError)):
            self.capture(runner)
        self.assertNotIn('1', runner.review_contracts)
        self.assertFalse((runner.run_dir / 'contract-regression' / 'original_contract.json').exists())

    def test_contract_uses_accepted_bytes_during_old_reader_aba(self):
        runner = self.runner()
        writer = ControlledWriter(self.todo)
        self.addCleanup(writer.close)
        read = read_input_text

        def transient(path, **kwargs):
            writer.write(PLAN.replace('first.txt', 'PRIVATE_CANARY'))
            value = read(path, **kwargs)
            writer.write(PLAN)
            return value

        with patch.object(run_todos, 'read_input_text', side_effect=transient):
            self.capture(runner)
        contract = json.loads(runner.review_contracts['1'][1])
        self.assertEqual(contract['task_text'], PLAN.splitlines(keepends=True)[0])
        self.assertNotIn('PRIVATE_CANARY', runner.review_contracts['1'][1])

    def test_untrusted_copy_cannot_replace_the_original_contract(self):
        runner = self.runner()
        copy = self.work / 'copy.md'
        copy.write_text(PLAN.replace('first.txt', 'easier.txt'))
        with self.assertRaises(PlanIntegrityError):
            self.capture(runner, copy)
        self.assertNotIn('1', runner.review_contracts)

    def test_safe_copy_can_have_unrelated_task_status_changes(self):
        runner = self.runner()
        copy = self.work / 'copy.md'
        copy.write_text(PLAN.replace('2. ***Task***', '2. ***DONE***'), newline='')
        self.capture(runner, copy)
        self.assertEqual(json.loads(runner.review_contracts['1'][1])['task_text'],
                         PLAN.splitlines(keepends=True)[0])

    def test_bounded_reader_rejects_leaf_parent_and_hardlink_aliases(self):
        victim = self.victims / 'context.txt'
        victim.write_text('PRIVATE_CANARY')
        leaf = self.work / 'linked.txt'
        self.link(leaf, victim)
        parent = self.work / 'linked-parent'
        self.link(parent, self.victims, directory=True)
        hardlink = self.work / 'hardlink.txt'
        try:
            os.link(victim, hardlink)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Native hardlink creation unavailable: {exc}')
        for path in (leaf, parent / victim.name, hardlink):
            with self.subTest(path=path):
                with self.assertRaises(DecisionInputError) as caught:
                    read_input_text(path)
                self.assertEqual(caught.exception.code, 'decision_input_unreadable')

    def test_bounded_reader_preserves_encoding_and_limit_contract(self):
        self.todo.write_bytes(b'\xef\xbb\xbfhello\r\n')
        self.assertEqual(read_input_text(self.todo, limit=10), 'hello\r\n')
        with self.assertRaises(DecisionInputError) as caught:
            read_input_text(self.todo, limit=9)
        self.assertEqual(caught.exception.code, 'decision_input_too_large')
        self.todo.write_bytes(b'\xef\xbb\xbf\xef\xbb\xbfhello')
        with self.assertRaises(DecisionInputError) as caught:
            read_input_text(self.todo)
        self.assertEqual(caught.exception.code, 'decision_invalid_encoding')
