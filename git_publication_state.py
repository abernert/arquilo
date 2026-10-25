# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded private publication receipts; no model, shell or transport operations."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
from contextlib import contextmanager

import git_snapshot
import safe_io
from controller_state import _overlaps_workspace

MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_PUBLICATIONS = 10000
STATUSES = {'accepted', 'preparing', 'prepared', 'push_pending', 'published', 'noop'}
FIELDS = {'schema_version', 'id', 'workspace', 'session', 'request', 'token',
          'branch', 'parent', 'object_format', 'paths', 'modes', 'baseline',
          'before_index_sha256', 'before_listing_sha256', 'after_index_sha256',
          'push', 'remote', 'remote_branch', 'destination_sha256', 'status',
          'commit', 'tree', 'selected_paths', 'message', 'error_type'}
_MUTEX = threading.RLock()


class PublicationStateError(ValueError):
    pass


def fingerprint(value):
    if value is None:
        return None
    data, mode = value
    return {'sha256': git_snapshot.digest(data), 'bytes': len(data), 'mode': mode}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'publication-[0-9a-f]{32}', value):
        raise PublicationStateError('Invalid publication identity; use an ID from git status.')
    return value


def _hash(value, *, nullable=False):
    return nullable and value is None or isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{64}', value))


def root(state: Path, workspace: Path) -> Path:
    state = safe_io.lexical_path(state)
    workspace = workspace.resolve()
    if _overlaps_workspace(state, workspace):
        raise PublicationStateError('Git publication state must be outside the workspace.')
    return state / 'git-publication'


def validate(record, state: Path, workspace: Path):
    base = root(state, workspace)
    if (not isinstance(record, dict) or set(record) != FIELDS
            or record['schema_version'] != 'arquilo.git_publication.v1'):
        raise PublicationStateError('Invalid Git publication receipt schema.')
    identifier(record['id'])
    if record['workspace'] != str(workspace.resolve()):
        raise PublicationStateError('Git publication belongs to a different workspace.')
    if (not isinstance(record['session'], str)
            or not re.fullmatch(r'session-[0-9a-f]{32}', record['session'])):
        raise PublicationStateError('Invalid Git publication session.')
    safe_io.check_path(base / record['session'], missing_ok=False)
    request = git_snapshot.validate_request(record['request'])
    expected = safe_io.lexical_path(state) / 'git-reviews'
    directory = Path(request['directory'])
    if (directory.parent != expected or not re.fullmatch(r'attempt-[0-9a-f]{32}', directory.name)
            or request['source'] != record['workspace'] or request['paths'] != record['paths']
            or request['modes'] != record['modes'] or request['binding']['parent'] != record['parent']):
        raise PublicationStateError('Publication receipt contradicts its owned review request.')
    if (not isinstance(record['status'], str) or record['status'] not in STATUSES
            or type(record['push']) is not bool or not isinstance(record['object_format'], str)
            or record['object_format'] not in {'sha1', 'sha256'}):
        raise PublicationStateError('Invalid Git publication state.')
    size = 40 if record['object_format'] == 'sha1' else 64
    for field in ('parent', 'commit', 'tree'):
        value = record[field]
        if value is None and field != 'parent':
            continue
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
            raise PublicationStateError('Invalid publication object identity.')
    if (not isinstance(record['branch'], str) or not record['branch'].startswith('refs/heads/')
            or any(ord(c) < 32 for c in record['branch'])):
        raise PublicationStateError('Invalid publication source branch.')
    for field in ('before_index_sha256', 'after_index_sha256', 'destination_sha256'):
        if not _hash(record[field], nullable=True):
            raise PublicationStateError('Invalid publication content fingerprint.')
    if not _hash(record['before_listing_sha256']):
        raise PublicationStateError('Invalid publication index fingerprint.')
    if record['push']:
        if (any(not isinstance(record[field], str) or not record[field]
                or any(ord(c) < 32 for c in record[field]) for field in ('remote', 'remote_branch'))
                or not record['remote_branch'].startswith('refs/heads/')
                or not _hash(record['destination_sha256'])):
            raise PublicationStateError('Invalid pinned publication destination.')
    elif any(record[field] is not None for field in ('remote', 'remote_branch', 'destination_sha256')):
        raise PublicationStateError('Unexpected transport in a local publication.')
    if not isinstance(record['baseline'], dict) or set(record['baseline']) != set(record['paths']):
        raise PublicationStateError('Invalid publication baseline.')
    for item in record['baseline'].values():
        if item is not None and (not isinstance(item, dict) or set(item) != {'sha256', 'bytes', 'mode'}
                or not _hash(item['sha256']) or type(item['bytes']) is not int
                or not 0 <= item['bytes'] <= git_snapshot.MAX_FILE_BYTES
                or type(item['mode']) is not int or item['mode'] not in (0o100644, 0o100755)):
            raise PublicationStateError('Invalid selected-output fingerprint.')
    selected = record['selected_paths']
    if (not isinstance(selected, list) or any(not isinstance(name, str) for name in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= set(record['paths'])):
        raise PublicationStateError('Invalid publication change selection.')
    if record['message'] is not None and (not isinstance(record['message'], str)
            or '\0' in record['message'] or len(record['message'].encode('utf-8')) > 65536):
        raise PublicationStateError('Invalid publication commit message.')
    if record['error_type'] is not None and (not isinstance(record['error_type'], str)
            or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,100}', record['error_type'])):
        raise PublicationStateError('Invalid publication error classification.')
    token = record['token']
    if (not isinstance(token, dict) or set(token) != {'candidate', 'sha256', 'review_index', 'binding'}
            or not isinstance(token['candidate'], str)
            or not re.fullmatch(r'review-[0-9a-f]{32}', token['candidate'])
            or not _hash(token['sha256']) or type(token['review_index']) is not int
            or token['review_index'] < 1 or token['binding'] != request['binding']):
        raise PublicationStateError('Invalid accepted-review publication token.')
    if record['status'] in {'prepared', 'push_pending', 'published'} and (
            record['commit'] is None or record['tree'] is None or record['after_index_sha256'] is None):
        raise PublicationStateError('Incomplete prepared publication receipt.')
    return record


def path(state: Path, workspace: Path, publication_id: str) -> Path:
    return root(state, workspace) / 'receipts' / (identifier(publication_id) + '.json')


def load(state: Path, workspace: Path, publication_id: str):
    data = git_snapshot.read_regular(path(state, workspace, publication_id), limit=MAX_RECEIPT_BYTES)
    if data is None:
        raise PublicationStateError('Publication identity not found in this controller state.')
    try:
        record = json.loads(data[0], object_pairs_hook=git_snapshot._json_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise PublicationStateError('Invalid publication receipt JSON.') from exc
    validate(record, state, workspace)
    if record['id'] != publication_id:
        raise PublicationStateError('Publication receipt identity mismatch.')
    return record


def save(record, state: Path, workspace: Path, *, create=False):
    validate(record, state, workspace)
    data = git_snapshot.canonical_bytes(record)
    if len(data) > MAX_RECEIPT_BYTES:
        raise PublicationStateError('Publication receipt exceeds its size limit.')
    destination = path(state, workspace, record['id'])
    if create:
        safe_io.write_bytes(destination, data, exclusive=True)
    else:
        safe_io.atomic_write(destination, data)


def summary(record):
    return {'id': record['id'], 'status': record['status'], 'commit': record['commit'],
            'paths': list(record['selected_paths']),
            'pushed': bool(record['push'] and record['status'] == 'published'),
            'review_snapshot': record['token']['sha256'], 'parent': record['parent'],
            'run': record['request']['binding']['run'], 'task': record['request']['binding']['task'],
            'attempt': record['request']['binding']['attempt'],
            'error_type': record['error_type']}


@contextmanager
def lock(state: Path, workspace: Path):
    """Process-owned lock: a crash releases it without deleting stale markers."""
    import os
    with _MUTEX, safe_io.open_file(root(state, workspace) / 'publication.lock', 'a+b', shared=True) as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PublicationStateError('Another Git publication is active.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def list_records(state: Path, workspace: Path):
    directory = root(state, workspace) / 'receipts'
    try:
        with safe_io.directory(directory) as (base, fd):
            import os
            entries = []
            with os.scandir(base if fd is None else fd) as iterator:
                for entry in iterator:
                    if len(entries) >= MAX_PUBLICATIONS:
                        raise PublicationStateError('Too many publication receipts for one bounded listing.')
                    entries.append(entry.name)
    except FileNotFoundError:
        return []
    records = []
    for name in sorted(entries):
        if re.fullmatch(r'publication-[0-9a-f]{32}\.json', name):
            records.append(summary(load(state, workspace, name[:-5])))
    return records
