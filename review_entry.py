# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Native review-first continuation, without fabricating a production success.

arquilo tasklist resume-review --todo ID --capture-dir ORIGINAL_CAPTURE
Add --check-only for read-only validation, or --continue-on-fail to allow bounded
review-directed fixes. Optional runner settings follow '-- tasklist run ...'.
The archived task and policy, not a regenerated producer prompt, bind the review.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable

import safe_io
from decision_request import snapshot_todo
from review_resume import (RecoveryRefused, _checked_path, _regular_file,
                           _record_path, _verify_capture_location)
from autobuild_contract import strict_object
import review_candidate as candidate


def read_json(path: Path, *, optional: bool = False) -> dict:
    if optional and not os.path.lexists(path):
        return {}
    try:
        def nonfinite(value):
            raise ValueError('Non-finite JSON value')
        value = json.loads(_regular_file(path, 16 << 20), object_pairs_hook=strict_object,
                           parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RecoveryRefused('Malformed recovery record: ' + path.name) from exc
    if not isinstance(value, dict):
        raise RecoveryRefused('Recovery record must be an object: ' + path.name)
    return value


def _text(path: Path, limit: int = 16 << 20) -> str:
    try:
        return _regular_file(path, limit).decode('utf-8-sig')
    except UnicodeError as exc:
        raise RecoveryRefused('Recovery text is not UTF-8: ' + path.name) from exc


def _task_scope(plan: str, task_id: str, prompt: str, source: Path):
    snap = snapshot_todo(plan, task_id=task_id, reference_prompt=prompt,
                         attempt_prompt=prompt, source=str(source))
    # Preserve immediately preceding CFG/WAIT/default scope as well as the task.
    from todo_syntax import task_headers, visible_lines
    from run_todos import TodoRunner
    index = next(i for i, m in task_headers(plan) if m.group(1) == task_id)
    visible = dict(visible_lines(plan))
    directives = []
    cursor = index - 1
    while cursor >= 0:
        line = visible.get(cursor, '').strip()
        if not line or not TodoRunner.DIRECTIVE_PATTERN.match(line):
            break
        directives.insert(0, line)
        cursor -= 1
    from task_resources import resolve_task_resources
    return snap, (tuple(directives), resolve_task_resources(plan, task_id))


@dataclass
class ReviewEntry:
    capture_dir: Path
    task_id: str
    workdir: Path
    todo_file: Path
    state_root: Path
    prompt: str
    contract: dict
    original_plan: str
    policy: bytes
    prior: dict
    source_hashes: dict[str, str]
    continue_on_fail: bool = False
    claimed: bool = False
    candidate_manifest: dict | None = None
    candidate_directory: Path | None = None
    correction_preflight: Callable[[], None] | None = None
    preflight_done: bool = False

    @property
    def evidence_note(self) -> str:
        return ('Native review-first entry. No new production has run and no historical '
                'production is claimed successful. Assess the PRESENT candidate against '
                'the archived task contract, including required tests, sources and limitations. '
                'A missing/incomplete old answer is not itself evidence that the candidate fails '
                'or passes. Historical provider/transport results remain unchanged.\n'
                + json.dumps(self.prior, ensure_ascii=False, sort_keys=True))

    def validate_current(self, plan: str | None = None) -> None:
        if os.path.lexists(self.workdir / 'process_stop'):
            raise RecoveryRefused('process_stop remains active; review entry cannot remove or bypass it')
        current = _text(self.todo_file) if plan is None else plan
        old, old_directives = _task_scope(self.original_plan, self.task_id, self.prompt, self.todo_file)
        new, new_directives = _task_scope(current, self.task_id, self.prompt, self.todo_file)
        if any(re.search(r'\b(?:parallel|workspace)\s*=', d) for d in new_directives[0]):
            raise RecoveryRefused('Review entry requires a serial primary-workspace task')
        if (new.task_text, new.preamble, new_directives) != (old.task_text, old.preamble, old_directives):
            raise RecoveryRefused('Task requirements, preamble or task directives changed; review contract differs')
        if _regular_file(self.workdir / 'config/policy.md', 8 << 20) != self.policy:
            raise RecoveryRefused('Workspace policy changed; explicit inspection required')
        from todo_syntax import task_headers, canonical_status
        status = next(canonical_status(m.group(2)) for _, m in task_headers(current) if m.group(1) == self.task_id)
        if status != 'Auftrag':
            raise RecoveryRefused('Review entry requires an open task; DONE/OBSOLETE is not reopened')
        for name, digest in self.source_hashes.items():
            if candidate.sha(_regular_file(Path(name), 16 << 20)) != digest:
                raise RecoveryRefused('Source archive changed after validation: ' + Path(name).name)

    def validate_options(self, args) -> None:
        if (args.backend != 'codex' or args.start_id != self.task_id or args.stop_id != self.task_id
                or _checked_path(args.workdir) != self.workdir or _checked_path(args.todo_file) != self.todo_file
                or _checked_path(args.state_dir) != self.state_root
                or args.dry_run or args.git or args.git_push or args.git_required
                or args.todo_template or args.allow_todo_modifications or args.accept_plan_changes
                or args.logs_in_workdir or args.breakdown_policy != 'off'):
            raise RecoveryRefused('Review entry requires the original plan/state, serial bounded scope, no Git/plan adoption')
        if not self.continue_on_fail and (args.max_steps != 1 or args.max_retries != 1):
            raise RecoveryRefused('Use --continue-on-fail to authorize review-directed corrections')
        self.validate_current()

    def validate_task(self, todo) -> None:
        if todo.identifier != self.task_id or todo.config.get('parallel') or todo.config.get('workspace'):
            raise RecoveryRefused('Review entry supports this serial primary-workspace task only')

    def claim(self, identifier: str, workdir: Path, todo_file: Path, accepted_plan: str) -> None:
        if (self.claimed or identifier != self.task_id or _checked_path(workdir) != self.workdir
                or _checked_path(todo_file) != self.todo_file):
            raise RecoveryRefused('Unexpected task, worker or repeated review-entry dispatch')
        self.validate_current(accepted_plan)
        self.claimed = True

    def before_fix(self) -> None:
        if not self.continue_on_fail:
            raise RecoveryRefused('Correction requires explicit --continue-on-fail')
        self.validate_current()
        if not self.preflight_done and self.correction_preflight is not None:
            self.correction_preflight()
            self.preflight_done = True
        self.validate_current()

    def validate_call(self, task, workdir, context) -> None:
        if (not self.claimed or task != self.prompt or Path(workdir).resolve() != self.workdir
                or context.todo_identifier != self.task_id or context.git_review is not None):
            raise RecoveryRefused('Native review-entry handoff is not bound to the selected original contract')
        self.validate_current()

    def archive_entry(self, log_dir: Path) -> None:
        # The new log records source provenance; the old execution is never edited.
        safe_io.write_bytes(log_dir / 'review_entry.json', candidate.canonical({
            'schema_version': 'arquilo.review_entry.v1', 'source_capture': str(self.capture_dir),
            'task_id': self.task_id, 'source_hashes': self.source_hashes,
            'prior_execution': self.prior, 'production_replayed': False,
            'continue_on_fail': self.continue_on_fail}), exclusive=True)

    def bind_candidate(self, log_dir: Path, round_: int) -> str:
        self.validate_current()
        manifest, diffs = candidate.capture(self.workdir)
        directory = log_dir / f'review-candidate-{round_:03d}'
        safe_io.mkdir(directory)
        raw = candidate.canonical(manifest)
        safe_io.write_bytes(directory / 'manifest.json', raw, exclusive=True)
        for name, data in diffs.items():
            safe_io.write_bytes(directory / name, data, exclusive=True)
        self.candidate_manifest, self.candidate_directory = manifest, directory
        return ('\n\nReview candidate identity: ' + candidate.sha(raw) + '\nManifest: '
                + str(directory / 'manifest.json') + '\n' + manifest['scope']
                + '\nThe controller will recheck these files before accepting your review. '
                  'Report sources, changes, tests (PASS/FAIL/NOT_RUN/BLOCKED), candidate identity '
                  'and open limitations in the existing review schema (summary, observations '
                  'and references); do not add new top-level fields. Never infer DONE from '
                  'an old answer or partial review.\n')

    def verify_candidate(self) -> None:
        if self.candidate_manifest is None or self.candidate_directory is None:
            raise RecoveryRefused('No review candidate has been bound')
        self.validate_current()
        manifest, _ = candidate.capture(self.workdir)
        if manifest != self.candidate_manifest:
            raise RecoveryRefused('Review candidate changed during review or before acceptance; fresh review required')
        if _regular_file(self.candidate_directory / 'manifest.json', 64 << 20) != candidate.canonical(manifest):
            raise RecoveryRefused('Private review-candidate manifest changed')


def load_entry(capture_dir: Path, task_id: str, *, continue_on_fail: bool = False) -> ReviewEntry:
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', task_id):
        raise RecoveryRefused('Invalid task ID')
    capture = _checked_path(capture_dir)
    task_dir, run_dir = capture.parent, capture.parent.parent
    run = read_json(run_dir / 'run.json')
    work = _record_path(run, 'workspace')
    todo = _record_path(run, 'todo_file')
    state = _record_path(run, 'controller_state')
    _verify_capture_location(capture, work, task_id, todo_file=todo, state_root=state.parent, fresh_review=True)
    # Input archives exist before dispatch, even if a killed controller did not
    # finalize the task_log input index or AutoBuild summary.
    if not todo.is_relative_to(work):
        raise RecoveryRefused('Use the original working task file inside the workspace')
    contract_path = task_dir / 'original_contract.json'
    plan_path = task_dir / 'inputs' / todo.relative_to(work)
    policy_path = task_dir / 'inputs/config/policy.md'
    prompt_path = task_dir / 'prompt.md'
    contract = read_json(contract_path)
    prompt = _text(prompt_path)
    original_plan = _text(plan_path)
    if (contract.get('schema_version') != 'arquilo.review_contract.v1'
            or not prompt.strip() or contract.get('original_request') != prompt
            or _record_path(contract, 'source') != todo):
        raise RecoveryRefused('Original task contract, source and archived prompt do not agree')
    snap, _ = _task_scope(original_plan, task_id, prompt, todo)
    if snap.task_text != contract.get('task_text'):
        raise RecoveryRefused('Archived task snapshot does not match the original contract')
    info = read_json(capture / 'capture.json', optional=True)
    summary = read_json(task_dir / 'autobuild_summary.json', optional=True)
    task_log = read_json(task_dir / 'task_log.json')
    for record in (info, summary, task_log):
        if record.get('process_stop_triggered', False) is not False:
            raise RecoveryRefused('Source records an unresolved STOP; review entry does not override it')
    if info and (info.get('schema_version') != 'arquilo.codex.io_capture.v1'
                 or _record_path(info, 'cwd') != work or info.get('phase') not in {'auftrag', 'fix', 'review'}):
        raise RecoveryRefused('Selected capture belongs to another workspace/backend/phase')
    if task_log.get('schema_version') != 'arquilo.task_log.v1' or task_log.get('identifier') != task_id:
        raise RecoveryRefused('Task-log identity mismatch')
    paths = [run_dir/'run.json', contract_path, plan_path, policy_path, prompt_path, task_dir/'task_log.json']
    paths += [p for p in (capture/'capture.json', task_dir/'autobuild_summary.json') if p.is_file()]
    prior = {'capture': str(capture), 'run_status': run.get('status'),
             'capture_status': info.get('status', 'NOT_FINALIZED'), 'phase': info.get('phase'),
             'completion_seen': info.get('completion_seen'), 'exit_code': info.get('process_exit_code'),
             'execution_error': info.get('error'), 'old_review_runs': summary.get('review_runs'),
             'old_completed': summary.get('completed'),
             'interpretation': 'Historical diagnostics only. A fresh review of the current candidate is required.'}
    entry = ReviewEntry(capture, task_id, work, todo, state.parent, prompt, contract, original_plan,
                        _regular_file(policy_path, 8 << 20), prior,
                        {str(p): candidate.sha(_regular_file(p, 16 << 20)) for p in paths}, continue_on_fail)
    entry.validate_current()
    return entry


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] != ['resume-review']:
        print('Use: arquilo tasklist resume-review --help', file=sys.stderr); return 2
    if arguments[1:] in (['-h'], ['--help']):
        print(__doc__); return 0
    separator = arguments.index('--') if '--' in arguments else len(arguments)
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--todo', required=True)
    parser.add_argument('--capture-dir', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--continue-on-fail', action='store_true')
    opt = parser.parse_args(arguments[1:separator])
    runner_args = arguments[separator + 1:]
    try:
        entry = load_entry(opt.capture_dir, opt.todo, continue_on_fail=opt.continue_on_fail)
        if runner_args and runner_args[:2] != ['tasklist', 'run']:
            raise RecoveryRefused("Expected '-- tasklist run ...'")
        runner_args = runner_args[2:] if runner_args else []
        # Normalize dispatch bounds only; they are not a task requirement. Do not
        # rewrite any task file or source prompt to do this.
        def set_option(name, value, force=False):
            nonlocal runner_args
            indices = [i for i, token in enumerate(runner_args) if token == name or token.startswith(name+'=')]
            if len(indices) > 1:
                raise RecoveryRefused('Duplicate recovery runner option: ' + name)
            if indices and not force:
                return
            if indices:
                i = indices[0]
                length = 1 if '=' in runner_args[i] else 2
                if i + length > len(runner_args):
                    raise RecoveryRefused('Missing runner value: ' + name)
                del runner_args[i:i+length]
            runner_args += [name, str(value)]
        set_option('--workdir', entry.workdir)
        set_option('--todo-file', entry.todo_file)
        set_option('--state-dir', entry.state_root)
        set_option('--start', entry.task_id, True)
        set_option('--stop', entry.task_id, True)
        set_option('--breakdown-policy', 'off', True)
        set_option('--max-steps', 3 if opt.continue_on_fail else 1, not opt.continue_on_fail)
        set_option('--max-retries', 1, not opt.continue_on_fail)
        config = read_json(entry.capture_dir.parent.parent / 'run_config.json')
        limit = config.get('limits', {}).get('max_calls')
        if type(limit) is not int or limit < 0:
            raise RecoveryRefused('Original call-budget limit is unavailable')
        set_option('--max-calls', limit)
        # Default to no MCP tools for the short form. Explicit long-form resource
        # grants are checked by the ordinary runner and are not inferred from logs.
        if separator == len(arguments):
            set_option('--mcp', 'none'); set_option('--review-mcp', 'none'); set_option('--skills', 'none')
        import run_todos
        parsed = run_todos.parse_args(runner_args)
        entry.validate_options(parsed)
        if opt.check_only:
            print('[recovery] Archive, current task/policy and state binding verified. No model calls or state writes.')
            print('[recovery] Native review entry eligible; candidate capture, plan lock and budget checks occur at execution.')
            return 0
        print('[recovery] Starting fresh review of existing work; no production replay or prompt-reconstruction requirement.')
        result = run_todos.main(runner_args, review_entry=entry)
        if not entry.claimed:
            print('[recovery] Review did not start; no acceptance inferred.', file=sys.stderr)
            return result if result else 125
        return result
    except (RecoveryRefused, OSError, ValueError, RuntimeError) as exc:
        print('[recovery] Refused: ' + str(exc), file=sys.stderr)
        return 125
