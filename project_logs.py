# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Readable log namespaces, not a replacement for persistent plan/budget authority.

Keep the workspace+plan keyed state where it already lives. A named project is
an indexed view of those same records, never a fresh authority or budget. All
allocations use no-follow I/O and atomic exclusive directory creation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import re
import threading

import safe_io
from runtime_files import validate_component, safe_component


_INDEX_THREAD_LOCK = threading.RLock()


class ProjectLogError(ValueError):
    pass


def validate_project_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', value):
        raise ProjectLogError('project-id must be 1-48 letters/digits/hyphens/underscores, not a path.')
    value = validate_component(value.lower())
    if value == 'dry-run':
        raise ProjectLogError('Reserved project-id: dry-run')
    return value


def timestamp_name(value: datetime | None = None) -> str:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError('Run timestamp must have a timezone')
    return value.astimezone(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z').replace(':', '-')


@contextmanager
def index_lock(root: Path, name: str = ".projects.lock"):
    # Short-lived registry/latest-pointer lock, never held during model calls.
    # Serialize same-process creation before taking the cross-process lock.
    # Some hosts can race concurrent first-open/create on the same lock file.
    with _INDEX_THREAD_LOCK, safe_io.open_file(root / name, 'a+b', shared=True) as stream:
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


def _json(path: Path, payload: dict):
    safe_io.atomic_write(path, (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def reserve_directory(parent: Path, name: str) -> Path:
    """One readable name, collision suffix only when necessary; never reuse."""
    validate_component(name)
    with safe_io.directory(parent, create=True) as (base, fd):
        for number in range(1, 10000):
            component = name if number == 1 else f'{name}-{number:04d}'
            try:
                os.mkdir(base / component if fd is None else component, 0o700, dir_fd=fd)
                return base / component
            except FileExistsError:
                continue
    raise ProjectLogError('Cannot reserve an unused log directory')


def numbered_directory(parent: Path, role: str) -> Path:
    """Global order among roles in one task/attempt; concurrent allocations safe."""
    role = safe_component(role, limit=24)
    with index_lock(parent, ".calls.lock"), safe_io.directory(parent, create=True) as (base, fd):
        for _ in range(10000):
            entries = os.listdir(base if fd is None else fd)
            numbers = [int(match.group(1)) for name in entries
                       if (match := re.match(r'^(\d{3,})-', name))]
            number = max(numbers, default=0) + 1
            if number > 999999:
                raise ProjectLogError('Too many calls in one log directory')
            name = f'{number:03d}-{role}'
            try:
                os.mkdir(base / name if fd is None else name, 0o700, dir_fd=fd)
                return base / name
            except FileExistsError:
                continue
    raise ProjectLogError('Cannot reserve a numbered log directory')


@dataclass(frozen=True)
class ProjectLogs:
    project_id: str | None
    directory: Path
    state_directory: Path
    workspace_layout: bool = False

    @property
    def runs_directory(self) -> Path:
        return self.directory if self.workspace_layout else self.directory / 'runs'

    def new_run(self, started: datetime, *, run_id: str, workspace: Path, todo: Path) -> Path:
        # Use the same lock as project registration, so separate plans in a
        # project cannot race while updating the latest-started pointer.
        with index_lock(self.state_directory.parent):
            path = reserve_directory(self.runs_directory, timestamp_name(started))
            _json(path / 'run.json', {
                'schema_version': 'arquilo.run_log.v2', 'run_id': run_id,
                'project_id': self.project_id, 'run_directory': str(path),
                'workspace': str(workspace), 'todo_file': str(todo),
                'controller_state': str(self.state_directory),
                'started_at': started.astimezone(UTC).isoformat(), 'finished_at': None,
                'status': 'preparing', 'exit_code': None,
            })
            safe_io.write_text(path / 'overview.log', f'Preparing run: {path.name}\n', exclusive=True)
            latest = self.directory / 'latest-run.txt'
            current = ''
            try:
                current = safe_io.read_text(latest).strip()
            except FileNotFoundError:
                pass
            prefix = '' if self.workspace_layout else 'runs/'
            if current and not re.fullmatch(prefix + r'\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z(?:-\d{4})?', current):
                raise ProjectLogError('Invalid latest-run.txt; inspect it rather than following arbitrary paths')
            relative = prefix + path.name
            if relative > current:
                safe_io.atomic_write(latest, (relative + '\n').encode())
            return path


def project_logs(state_dir: Path, workspace: Path, todo: Path,
                 project_id: str | None = None) -> ProjectLogs:
    """Bind a readable ID to a workspace, without relocating its persistent state.

    The per-plan reverse binding also applies when the flag is later omitted.
    Multiple plans may share one project; different workspaces may not. A new ID
    never changes the workspace+todo-keyed plan/budget directory.
    """
    requested = validate_project_id(project_id)
    root = state_dir.parent
    with index_lock(root):
        index_path = root / 'projects.json'
        try:
            registry = json.loads(safe_io.read_text(index_path))
        except FileNotFoundError:
            registry = {'schema_version': 'arquilo.projects.v1', 'projects': {}, 'plans': {}}
        if (not isinstance(registry, dict) or registry.get('schema_version') != 'arquilo.projects.v1'
                or not isinstance(registry.get('projects'), dict) or not isinstance(registry.get('plans'), dict)):
            raise ProjectLogError('Invalid projects.json; refusing to reset the project index')
        key = state_dir.name
        bound = registry['plans'].get(key)
        if bound is not None and (not isinstance(bound, str) or bound not in registry['projects']):
            raise ProjectLogError('Invalid project binding')
        if requested is not None and bound is not None and requested != bound:
            raise ProjectLogError(f'This plan already belongs to project {bound!r}; omit --project-id or use that ID.')
        chosen = validate_project_id(requested or bound)
        if chosen is None:
            return ProjectLogs(None, state_dir, state_dir)
        workspace_key = os.path.normcase(str(workspace.resolve()))
        existing = registry['projects'].get(chosen)
        if existing is not None and existing != workspace_key:
            raise ProjectLogError(f'Project {chosen!r} is bound to a different workspace; choose another ID.')
        directory = safe_io.check_path(root / chosen)
        marker = directory / 'project.json'
        try:
            record = json.loads(safe_io.read_text(marker))
        except FileNotFoundError:
            if directory.exists() and any(directory.iterdir()):
                raise ProjectLogError('Project directory is not empty and has no project.json; refusing to reuse it.')
            record = {'schema_version': 'arquilo.project.v1', 'project_id': chosen,
                      'workspace': workspace_key, 'plans': {}}
        if (not isinstance(record, dict) or record.get('schema_version') != 'arquilo.project.v1'
                or record.get('project_id') != chosen or record.get('workspace') != workspace_key
                or not isinstance(record.get('plans'), dict)):
            raise ProjectLogError('Project metadata does not match; refusing to overwrite it')
        record['plans'][key] = {'todo_file': str(todo), 'controller_state': str(state_dir)}
        _json(marker, record)
        registry['projects'][chosen] = workspace_key
        registry['plans'][key] = chosen
        _json(index_path, registry)
        return ProjectLogs(chosen, directory, state_dir)
