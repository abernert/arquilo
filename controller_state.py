# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Owner-only persistent plan authority outside all model-writable workspaces."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import unicodedata

import safe_io
from todo_syntax import task_headers, canonical_status


class PlanIntegrityError(RuntimeError):
    pass


_STATE_ALLOCATION_LOCK = threading.RLock()


def _overlaps_workspace(root: Path, workspace: Path) -> bool:
    """Include native case/Unicode aliases, even when the new root is missing."""
    if root.is_relative_to(workspace) or workspace.is_relative_to(root):
        return True
    for child, parent in ((root, workspace), (workspace, root)):
        for candidate in (child, *child.parents):
            try:
                if candidate.samefile(parent):
                    return True
            except FileNotFoundError:
                continue
    return False


def _same_location(left: Path, right: Path) -> bool:
    """Stable path identity; never use a replaceable task file's inode as a key."""
    left, right = safe_io.check_path(left), safe_io.check_path(right)
    if str(left) == str(right):
        return True
    try:
        return left.samefile(right)
    except FileNotFoundError:
        # A new task file may not exist yet (template initialization and
        # standalone AutoBuild). Refuse ambiguous spellings until distinct
        # files exist; do not allocate two fresh counters for a possible alias.
        def exists(path):
            try:
                path.stat()
                return True
            except FileNotFoundError:
                return False
        if exists(left) != exists(right) or left.parent == left or right.parent == right:
            return False
        names = [unicodedata.normalize('NFC', path.name).casefold() for path in (left, right)]
        return names[0] == names[1] and _same_location(left.parent, right.parent)


def _state_identity(path: Path) -> dict | None:
    try:
        with safe_io.open_file(path / 'identity.json', 'rb') as stream:
            data = stream.read(65537)
        value = json.loads(data)
        if (len(data) > 65536 or not isinstance(value, dict)
                or value.get('schema_version') != 'arquilo.state_identity.v1'
                or value.get('state_key') != path.name
                or not isinstance(value.get('workspace'), str)
                or not isinstance(value.get('todo'), str)):
            raise ValueError('Invalid state identity')
        return value
    except FileNotFoundError:
        # Existing v1 journals predate the identity marker. Preserve their
        # directory and counters; they still identify the original task path.
        try:
            value = json.loads(safe_io.read_text(path / 'plan.json'))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
            return _legacy_identity_hint(path)
        if isinstance(value, dict) and isinstance(value.get('todo'), str):
            return {'todo': value['todo']}
        return _legacy_identity_hint(path)
    except (ValueError, UnicodeError) as exc:
        raise PlanIntegrityError(f'Invalid controller state identity; inspect it without resetting counters: {path}') from exc


def _private_metadata(path: Path) -> dict:
    try:
        with safe_io.open_file(path, 'rb') as stream:
            data = stream.read(65537)
        value = json.loads(data) if len(data) <= 65536 else None
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _legacy_identity_hint(path: Path) -> dict | None:
    """Private metadata may reject aliases, never authorize a plan or refund calls."""
    def bound(record, workspace):
        if (not isinstance(record, dict) or not isinstance(record.get('todo_file'), str)
                or not isinstance(record.get('controller_state'), str)):
            return None
        state = Path(record['controller_state'])
        if not state.is_absolute():
            return None
        try:
            if not safe_io.check_path(state).samefile(path):
                return None
        except FileNotFoundError:
            return None
        result = {'todo': record['todo_file']}
        if isinstance(workspace, str):
            result['workspace'] = workspace
        return result

    registry = _private_metadata(path.parent / 'projects.json')
    plans = registry.get('plans', {})
    project = plans.get(path.name) if isinstance(plans, dict) else None
    if (registry.get('schema_version') == 'arquilo.projects.v1'
            and isinstance(project, str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,47}', project)):
        record = _private_metadata(path.parent / project / 'project.json')
        plans = record.get('plans', {})
        if record.get('schema_version') == 'arquilo.project.v1' and isinstance(plans, dict):
            hint = bound(plans.get(path.name), record.get('workspace'))
            if hint is not None:
                return hint
    try:
        with safe_io.open_file(path / 'latest-run.txt', 'r', encoding='utf-8') as stream:
            latest = stream.read(256).strip()
    except FileNotFoundError:
        return None
    if not re.fullmatch(r'runs/\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z(?:-\d{4})?', latest):
        return None
    record = _private_metadata(path / latest / 'run.json')
    if record.get('schema_version') == 'arquilo.run_log.v2':
        return bound(record, record.get('workspace'))
    return None


def _reject_state_alias(result: Path, todo: Path) -> None:
    try:
        with safe_io.directory(result.parent) as (root, fd):
            names = os.listdir(root if fd is None else fd)
    except FileNotFoundError:
        return
    for name in names:
        if len(name) != 64 or any(c not in '0123456789abcdef' for c in name):
            continue
        path = result.parent / name
        identity = _state_identity(path)
        if identity is None:
            continue
        same_plan = _same_location(Path(identity['todo']), todo)
        if name == result.name and not same_plan:
            raise PlanIntegrityError(f'Controller state key is already bound to a different task path: {path}')
        if same_plan and name != result.name:
            raise PlanIntegrityError(
                f'Controller state already exists for this plan under another path spelling: '
                f'{identity.get("workspace", "workspace recorded by the original invocation")} / '
                f'{identity.get("key_todo", identity["todo"])} (state {path}). Continue with the original paths; '
                'do not reset plan authority or call budgets.')


@contextmanager
def _state_allocation_lock(root: Path):
    # Covers identity registration, including the gap before a plan journal is
    # created. A second controller must not allocate an alias budget meanwhile.
    with _STATE_ALLOCATION_LOCK, safe_io.open_file(root / 'identity.lock', 'a+b', shared=True) as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def default_state_root() -> Path:
    if os.name == 'nt':
        appdata = os.environ.get('LOCALAPPDATA')
        if not appdata:
            # Read the current user's registered local folder even when the
            # caller deliberately sanitized HOME/USERPROFILE/environment.
            import ctypes
            from ctypes import wintypes
            query = ctypes.WinDLL('shell32').SHGetFolderPathW
            query.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                              wintypes.DWORD, wintypes.LPWSTR]
            query.restype = ctypes.c_long
            buffer = ctypes.create_unicode_buffer(260)
            if query(None, 0x001c, None, 0, buffer) != 0 or not buffer.value:
                raise PlanIntegrityError('Cannot determine private Windows state root; use --state-dir.')
            appdata = buffer.value
        return Path(appdata) / 'ARQUILO' / 'controller'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'ARQUILO' / 'controller'
    return Path.home() / '.local' / 'state' / 'arquilo' / 'controller'


def state_directory_path(workspace: Path, todo: Path, root: Path | None = None) -> Path:
    """Compute the plan-specific path without creating/resetting any state."""
    root = safe_io.lexical_path(root or default_state_root())
    workspace = workspace.resolve()
    if _overlaps_workspace(root, workspace):
        raise PlanIntegrityError('Controller state must be outside the model workspace; choose --state-dir elsewhere.')
    # Keep the existing key: changing it would silently reset persistent budgets.
    key = hashlib.sha256((str(workspace) + '\0' + str(todo)).encode()).hexdigest()
    result = root / key
    _reject_state_alias(result, safe_io.lexical_path(todo))
    return result


def state_directory(workspace: Path, todo: Path, root: Path | None = None) -> Path:
    result = state_directory_path(workspace, todo, root)
    root = result.parent
    safe_io.mkdir(root)
    info = root.stat()
    if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise PlanIntegrityError(f'Controller state must be owned by this user with mode 0700: {root}')
    with _state_allocation_lock(root):
        if _overlaps_workspace(root, workspace.resolve()):
            raise PlanIntegrityError('Controller state must be outside the model workspace; choose --state-dir elsewhere.')
        _reject_state_alias(result, safe_io.lexical_path(todo))
        safe_io.mkdir(result)
        if _state_identity(result) is None or not (result / 'identity.json').exists():
            safe_io.atomic_write(result / 'identity.json', (json.dumps({
                'schema_version': 'arquilo.state_identity.v1', 'state_key': result.name,
                'workspace': str(workspace.resolve()), 'todo': str(safe_io.lexical_path(todo)),
                'key_todo': str(todo),
            }, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
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
    def __init__(self, todo: Path, directory: Path | None, *, accept_changes: bool = False,
                 allow_modifications: bool = False, workspace: Path | None = None):
        if type(allow_modifications) is not bool:
            raise ValueError('allow_modifications must be bool')
        self.allow_modifications = allow_modifications
        self.mutations = []
        self.todo = safe_io.lexical_path(todo)
        self.workspace = workspace or self.todo.parent
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
                if allow_modifications:
                    self._adopt_mutation(current, source='startup')
                else:
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

    def _adopt_mutation(self, current: str, *, source: str):
        # Observation/adoption is NOT independent verification of DONE or outputs.
        before_pre, before = _blocks(self.text)
        after_pre, after = _blocks(current)
        from todo_lint import lint_todo_file
        issues = lint_todo_file(self.todo, workdir=self.workspace)
        if issues:
            raise PlanIntegrityError("Mutable task plan is invalid: " + "; ".join(
                f"line {issue.line}: {issue.message}" for issue in issues[:8]))
        if safe_io.read_text(self.todo) != current:
            raise PlanIntegrityError('Task file changed during validation; retry after the writer has stopped')
        from datetime import datetime, UTC
        record = {
            'schema_version': 'arquilo.plan_mutation.v1',
            'observed_at': datetime.now(UTC).isoformat(), 'source': source,
            'added': [key for key in after if key not in before],
            'removed': [key for key in before if key not in after],
            'changed': [key for key in after if key in before and after[key] != before[key]],
            'preamble_changed': before_pre != after_pre,
            'independently_verified': False,
        }
        if self.directory is not None:
            audit = safe_io.unique_directory(self.directory / 'plan-mutations', 'change')
            safe_io.write_text(audit / 'before.md', self.text, exclusive=True)
            safe_io.write_text(audit / 'after.md', current, exclusive=True)
            safe_io.write_text(audit / 'change.json', json.dumps(record, indent=2) + '\n', exclusive=True)
            record['archive'] = str(audit)
            self._save(current)
        self.text = current
        self.mutations.append(record)

    def check(self):
        with self.mutex:
            current = safe_io.read_text(self.todo)
            _blocks(current)
            if current != self.text:
                if self.allow_modifications:
                    self._adopt_mutation(current, source='runtime')
                else:
                    raise PlanIntegrityError('Unapproved task-plan mutation (status, task removal, requirements or directives); stopping before acceptance.')

    def snapshot(self) -> str:
        """Return the exact accepted revision, never a second workspace read."""
        with self.mutex:
            self.check()
            return self.text

    def replace_approved(self, text: str, *, expected_text: str | None = None,
                         task_id: str | None = None):
        """Commit only one open-to-DONE token on the captured accepted revision."""
        with self.mutex:
            self.check()
            if expected_text is not None and expected_text != self.text:
                raise PlanIntegrityError('Task plan changed since completion was prepared; no DONE is accepted.')
            _blocks(text)
            after = {match.group(1): (line, match) for line, match in task_headers(text)}
            lines = self.text.splitlines(keepends=True)
            valid = False
            for index, match in task_headers(self.text):
                ident = match.group(1)
                if task_id is not None and ident != task_id:
                    continue
                target = after.get(ident)
                if (canonical_status(match.group(2)) != 'Auftrag' or target is None
                        or target[0] != index or canonical_status(target[1].group(2)) != 'DONE'):
                    continue
                raw = lines[index]
                bom = 1 if index == 0 and raw.startswith('\ufeff') else 0
                content = raw[bom:]
                offset = bom + len(content) - len(content.lstrip())
                start, end = offset + match.start(2), offset + match.end(2)
                candidate = lines.copy()
                candidate[index] = raw[:start] + target[1].group(2) + raw[end:]
                if ''.join(candidate) == text:
                    valid = True
                    break
            if not valid:
                raise PlanIntegrityError('Approved completion may change only the selected open task command to DONE.')
            self._save(self.text, pending=text)
            safe_io.atomic_write(self.todo, text.encode('utf-8'))
            self.text = text
            self._save(text)

    def _validated_children(self, parent: str, *, maximum: int | None = None) -> tuple[str, list[str]]:
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
        return current, added

    def verify_children(self, parent: str, *, maximum: int | None = None) -> list[str]:
        with self.mutex:
            return self._validated_children(parent, maximum=maximum)[1]

    def accept_children(self, parent: str, maximum: int):
        with self.mutex:
            current, added = self._validated_children(parent, maximum=maximum)
            if safe_io.read_text(self.todo) != current:
                raise PlanIntegrityError('Task plan changed while accepting children; no children are accepted.')
            # A later workspace write cannot taint this journal: persist only
            # the same bytes validated above, not the comparison read.
            self._save(current)
            self.text = current
            return added
