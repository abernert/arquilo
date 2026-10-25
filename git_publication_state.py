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
OBLIGATION_FIELDS = {'schema_version', 'id', 'workspace', 'run', 'task', 'attempt',
                     'paths', 'push', 'branch', 'destination_sha256', 'error',
                     'status', 'resolved_by'}
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


def obligation_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'obligation-[0-9a-f]{32}', value):
        raise PublicationStateError('Invalid blocked publication identity.')
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
    version = record.get('schema_version') if isinstance(record, dict) else None
    expected_fields = FIELDS | {'supersedes'} if version == 'arquilo.git_publication.v2' else FIELDS
    if (not isinstance(record, dict) or set(record) != expected_fields
            or version not in ('arquilo.git_publication.v1', 'arquilo.git_publication.v2')):
        raise PublicationStateError('Invalid Git publication receipt schema.')
    if version == 'arquilo.git_publication.v2':
        supersedes = record['supersedes']
        if (not isinstance(supersedes, list) or len(supersedes) > MAX_PUBLICATIONS
                or any(not isinstance(value, str) for value in supersedes)
                or len(set(supersedes)) != len(supersedes)):
            raise PublicationStateError('Invalid bound publication obligations.')
        for value in supersedes:
            obligation_identifier(value)
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


def _entries(directory: Path):
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
    return sorted(entries)


def list_records(state: Path, workspace: Path):
    records = []
    for name in _entries(root(state, workspace) / 'receipts'):
        if re.fullmatch(r'publication-[0-9a-f]{32}\.json', name):
            records.append(summary(load(state, workspace, name[:-5])))
    for name in _entries(root(state, workspace) / 'obligations'):
        if re.fullmatch(r'obligation-[0-9a-f]{32}\.json', name):
            records.append(obligation_summary(load_obligation(state, workspace, name[:-5])))
    return records


def normalize_task(value):
    return value.removesuffix('-review')


def _identity_text(value):
    return (isinstance(value, str) and bool(value) and len(value.encode('utf-8')) <= 2048
            and not any(ord(char) < 32 for char in value))


def validate_obligation(record, state: Path, workspace: Path):
    root(state, workspace)
    if (not isinstance(record, dict) or set(record) != OBLIGATION_FIELDS
            or record['schema_version'] != 'arquilo.git_publication_obligation.v1'):
        raise PublicationStateError('Invalid blocked publication schema.')
    obligation_identifier(record['id'])
    if record['workspace'] != str(workspace.resolve()):
        raise PublicationStateError('Blocked publication belongs to a different workspace.')
    if any(not _identity_text(record[field]) for field in ('run', 'task', 'attempt')):
        raise PublicationStateError('Invalid blocked publication attempt identity.')
    paths = record['paths']
    if (not isinstance(paths, list) or not paths or len(paths) > git_snapshot.MAX_FILES
            or any(not isinstance(value, str) for value in paths) or len(set(paths)) != len(paths)):
        raise PublicationStateError('Invalid blocked publication selection.')
    for value in paths:
        git_snapshot.relative_name(value)
    if type(record['push']) is not bool or not _hash(record['destination_sha256'], nullable=True):
        raise PublicationStateError('Invalid blocked publication destination.')
    if not record['push'] and record['destination_sha256'] is not None:
        raise PublicationStateError('Unexpected destination for a local publication block.')
    if record['branch'] is not None and (not _identity_text(record['branch'])
            or not record['branch'].startswith('refs/heads/')):
        raise PublicationStateError('Invalid blocked publication source branch.')
    error = record['error']
    if (not isinstance(error, dict) or set(error) != {'code', 'message'}
            or not isinstance(error['code'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,95}', error['code'])
            or not isinstance(error['message'], str) or '\0' in error['message']
            or len(error['message'].encode('utf-8')) > 16384):
        raise PublicationStateError('Invalid blocked publication diagnostic.')
    if record['status'] == 'blocked':
        if record['resolved_by'] is not None:
            raise PublicationStateError('An unresolved publication cannot name a resolver.')
    elif record['status'] == 'superseded':
        identifier(record['resolved_by'])
    else:
        raise PublicationStateError('Invalid blocked publication lifecycle state.')
    return record


def obligation_path(state: Path, workspace: Path, obligation_id: str):
    return root(state, workspace) / 'obligations' / (obligation_identifier(obligation_id) + '.json')


def load_obligation(state: Path, workspace: Path, obligation_id: str):
    data = git_snapshot.read_regular(obligation_path(state, workspace, obligation_id), limit=MAX_RECEIPT_BYTES)
    if data is None:
        raise PublicationStateError('Blocked publication identity not found.')
    try:
        record = json.loads(data[0], object_pairs_hook=git_snapshot._json_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise PublicationStateError('Invalid blocked publication JSON.') from exc
    validate_obligation(record, state, workspace)
    if record['id'] != obligation_id:
        raise PublicationStateError('Blocked publication identity mismatch.')
    if record['status'] == 'superseded':
        receipt = load(state, workspace, record['resolved_by'])
        if (receipt['status'] not in {'published', 'noop'}
                or obligation_id not in receipt.get('supersedes', [])
                or not _can_supersede(record, receipt)):
            raise PublicationStateError('Blocked publication has no matching successful resolution authority.')
    return record


def save_obligation(record, state: Path, workspace: Path, *, create=False):
    validate_obligation(record, state, workspace)
    data = git_snapshot.canonical_bytes(record)
    if len(data) > MAX_RECEIPT_BYTES:
        raise PublicationStateError('Blocked publication exceeds its size limit.')
    destination = obligation_path(state, workspace, record['id'])
    if create:
        safe_io.write_bytes(destination, data, exclusive=True)
    else:
        safe_io.atomic_write(destination, data)


def obligation_summary(record):
    return {'id': record['id'], 'status': record['status'], 'commit': None, 'pushed': False,
            'paths': list(record['paths']), 'review_snapshot': None, 'parent': None,
            'run': record['run'], 'task': record['task'], 'attempt': record['attempt'],
            'code': record['error']['code'], 'message': record['error']['message'],
            'error_type': None, 'retryable': False, 'resolved_by': record['resolved_by']}


def record_block(state: Path, workspace: Path, *, run, task, attempt, paths, push,
                 destination_sha256, branch, error):
    if not isinstance(paths, (list, tuple)) or len(paths) > git_snapshot.MAX_FILES:
        raise PublicationStateError('Blocked publication paths must be explicit selections.')
    if not isinstance(error, dict):
        raise PublicationStateError('Blocked publication needs a structured diagnostic.')
    normalized, seen = [], set()
    for name in paths:
        if not isinstance(name, str):
            raise PublicationStateError('Blocked publication paths must be strings.')
        literal = git_snapshot.relative_name(Path(name).as_posix())
        if literal not in seen:
            normalized.append(literal)
            seen.add(literal)
    record = {'schema_version': 'arquilo.git_publication_obligation.v1',
              'workspace': str(workspace.resolve()), 'run': run, 'task': task, 'attempt': attempt,
              'paths': normalized, 'push': push, 'branch': branch,
              'destination_sha256': destination_sha256, 'error': dict(error),
              'status': 'blocked', 'resolved_by': None}
    # Repeated reporting of the same failed accepted attempt is idempotent.
    identity = {key: value for key, value in record.items()
                if key not in {'schema_version', 'error', 'status', 'resolved_by'}}
    record['id'] = 'obligation-' + git_snapshot.digest(git_snapshot.canonical_bytes(identity))[:32]
    validate_obligation(record, state, workspace)
    try:
        save_obligation(record, state, workspace, create=True)
    except FileExistsError:
        previous = load_obligation(state, workspace, record['id'])
        if any(previous[key] != record[key] for key in identity):
            raise PublicationStateError('Conflicting blocked publication attempt identity.')
        return obligation_summary(previous)
    return obligation_summary(record)


def _can_supersede(block, receipt):
    binding = receipt['request']['binding']
    return (block['branch'] is not None and block['branch'] == receipt['branch']
            and normalize_task(block['task']) == normalize_task(binding['task'])
            and (block['run'], block['attempt']) != (binding['run'], binding['attempt'])
            and set(block['paths']) <= set(receipt['paths'])
            and (not block['push'] or receipt['push'] and block['destination_sha256'] is not None
                 and block['destination_sha256'] == receipt['destination_sha256']))


def eligible_blocks(state: Path, workspace: Path, receipt):
    """Freeze only already existing matching blocks into a newly accepted receipt."""
    result = []
    for name in _entries(root(state, workspace) / 'obligations'):
        if re.fullmatch(r'obligation-[0-9a-f]{32}\.json', name):
            block = load_obligation(state, workspace, name[:-5])
            if block['status'] == 'blocked' and _can_supersede(block, receipt):
                result.append(block['id'])
    return result


def resolve_blocks(state: Path, workspace: Path, publication_id):
    receipt = load(state, workspace, publication_id)
    if receipt['status'] not in {'published', 'noop'}:
        return []
    git_snapshot.verify(receipt['request'], receipt['token'], receipt['token']['review_index'])
    resolved = []
    # Legacy v1 receipts have no resolution capability. In particular, retrying
    # an old successful receipt can never erase a subsequently created block.
    for obligation_id in receipt.get('supersedes', []):
        block = load_obligation(state, workspace, obligation_id)
        if not _can_supersede(block, receipt):
            raise PublicationStateError('Bound publication obligation changed scope.')
        if block['status'] == 'superseded':
            if block['resolved_by'] == publication_id:
                resolved.append(obligation_id)
            continue
        block.update(status='superseded', resolved_by=publication_id)
        save_obligation(block, state, workspace)
        resolved.append(obligation_id)
    return resolved
