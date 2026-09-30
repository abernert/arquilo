# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Owner-only persistent plan authority outside all model-writable workspaces."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading

import safe_io
from todo_syntax import task_headers, canonical_status


class PlanIntegrityError(RuntimeError):
    pass


def default_state_root() -> Path:
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'ARQUILO' / 'controller'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ARQUILO' / 'controller'
    return Path.home() / '.local' / 'state' / 'arquilo' / 'controller'


def state_directory(workspace: Path, todo: Path, root: Path | None = None) -> Path:
    root = safe_io.lexical_path(root or default_state_root())
    workspace = workspace.resolve()
    if root.is_relative_to(workspace) or workspace.is_relative_to(root):
        raise PlanIntegrityError('Controller state must be outside the model workspace; choose --state-dir elsewhere.')
    safe_io.mkdir(root)
    info = root.stat()
    if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise PlanIntegrityError(f'Controller state must be owned by this user with mode 0700: {root}')
    key = hashlib.sha256((str(workspace) + '\0' + str(todo)).encode()).hexdigest()
    result = root / key
    safe_io.mkdir(result)
    return result


def _blocks(text: str):
    lines = text.splitlines(keepends=True)
    headers = list(task_headers(text))
    result = {}
    for number, (line, match) in enumerate(headers):
        ident = match.group(1)
        if ident in result:
            raise PlanIntegrityError(f'Duplicate task ID: {ident}')
        end = headers[number + 1][0] if number + 1 < len(headers) else len(lines)
        result[ident] = (canonical_status(match.group(2)), ''.join(lines[line:end]).strip())
    preamble = ''.join(lines[:headers[0][0]]) if headers else text
    return preamble.strip(), result


class PlanAuthority:
    """One controller per task file. Never accept workspace DONE as new authority.

    The first invocation accepts the owner's initial plan. Subsequent invocations
    require the persisted snapshot; owner edits require explicit adoption. A
    pending *controller-approved* status write can recover after a crash.
    """
    def __init__(self, todo: Path, directory: Path | None, *, accept_changes: bool = False):
        self.todo = safe_io.lexical_path(todo)
        self.directory = directory
        self.mutex = threading.RLock()
        self._lock_context = None
        self._lock_stream = None
        self.path = directory / 'plan.json' if directory else None
        current = safe_io.read_text(self.todo)
        self.text = current
        if directory is None:
            _blocks(current)
            return
        try:
            self._lock_context = safe_io.open_file(directory / 'controller.lock', 'a+b', shared=True)
            self._lock_stream = self._lock_context.__enter__()
            if os.name == 'nt':
                import msvcrt
                self._lock_stream.seek(0)
                msvcrt.locking(self._lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                saved = json.loads(safe_io.read_text(self.path))
            except FileNotFoundError:
                _blocks(current)
                self._save(current)
                return
            if (not isinstance(saved, dict) or saved.get('schema_version') != 'arquilo.plan_authority.v1'
                    or saved.get('todo') != str(self.todo) or not isinstance(saved.get('text'), str)):
                raise PlanIntegrityError('Invalid controller plan journal; do not reset it automatically.')
            self.text = saved['text']
            pending = saved.get('pending')
            if pending is not None:
                if not isinstance(pending, str) or current not in (self.text, pending):
                    raise PlanIntegrityError('Plan differs from both sides of a pending approved transition.')
                safe_io.atomic_write(self.todo, pending.encode('utf-8'))
                self.text = pending
                current = pending
                self._save(pending)
            if current != self.text:
                if not accept_changes:
                    raise PlanIntegrityError('Task plan changed outside the controller. Inspect it, restore it or explicitly use --accept-plan-changes; no task is accepted.')
                _blocks(current)
                # Preserve old evidence rather than silently resetting authority/budgets.
                audit = safe_io.unique_directory(directory / 'owner-adoptions', 'change')
                safe_io.write_text(audit / 'previous-plan.md', self.text, exclusive=True)
                self.text = current
                self._save(current)
            self.check()
        except BaseException:
            self.close()
            raise

    def close(self):
        context, self._lock_context = self._lock_context, None
        self._lock_stream = None
        if context is not None:
            context.__exit__(None, None, None)

    def __del__(self):
        self.close()

    def _save(self, text, *, pending=None):
        if self.path:
            safe_io.atomic_write(self.path, (json.dumps({
                'schema_version': 'arquilo.plan_authority.v1', 'todo': str(self.todo),
                'text': text, 'pending': pending,
            }, ensure_ascii=False, indent=2) + '\n').encode())

    def check(self):
        with self.mutex:
            current = safe_io.read_text(self.todo)
            _blocks(current)
            if current != self.text:
                raise PlanIntegrityError('Unapproved task-plan mutation (status, task removal, requirements or directives); stopping before acceptance.')

    def replace_approved(self, text: str):
        with self.mutex:
            self.check()
            _blocks(text)
            self._save(self.text, pending=text)
            safe_io.atomic_write(self.todo, text.encode('utf-8'))
            self.text = text
            self._save(text)

    def verify_children(self, parent: str, *, maximum: int | None = None) -> list[str]:
        """Only insert open direct children, in the parent block, without changing old work."""
        current = safe_io.read_text(self.todo)
        before_pre, before = _blocks(self.text)
        after_pre, after = _blocks(current)
        if before_pre != after_pre or not set(before).issubset(after):
            raise PlanIntegrityError('Breakdown removed tasks or changed the plan preamble.')
        if [key for key in after if key in before] != list(before):
            raise PlanIntegrityError('Breakdown reordered existing tasks.')
        for key, value in before.items():
            if after[key] != value:
                raise PlanIntegrityError(f'Breakdown changed existing task or its directives: {key}')
        added = [key for key in after if key not in before]
        if not added or (maximum is not None and len(added) > maximum):
            raise PlanIntegrityError('Breakdown has no children or exceeds its authorized child limit.')
        keys = list(after)
        parent_pos = keys.index(parent)
        for ident in added:
            if (ident.rsplit('.', 1)[0] != parent or '.' not in ident
                    or after[ident][0] != 'Auftrag'):
                raise PlanIntegrityError('Breakdown may only add open direct children.')
            index = keys.index(ident)
            if index <= parent_pos or any(key in before and not key.startswith(parent + '.')
                                        for key in keys[parent_pos + 1:index]):
                raise PlanIntegrityError('Breakdown child is outside its parent block.')
        return added

    def accept_children(self, parent: str, maximum: int):
        with self.mutex:
            added = self.verify_children(parent, maximum=maximum)
            self.text = safe_io.read_text(self.todo)
            self._save(self.text)
            return added
