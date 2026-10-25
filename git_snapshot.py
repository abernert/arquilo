# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Private, content-bound selected outputs for explicit Git publication.

A snapshot is a review candidate, not evidence that a model is truthful. Only
an accepted private worker result may authorize its publication. The parent
retains the request identity; a workspace summary is never an authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
import uuid

import safe_io
from controller_state import _overlaps_workspace

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 20000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
EXCLUDED = {'.git', '.codex_runs', '.claude_runs', '.arquilo', 'process_stop'}


class GitSnapshotError(ValueError):
    pass


class GitSnapshotUnavailable(GitSnapshotError):
    """Selected source cannot be captured; no publication review has begun.

    Only source-read/capacity failures use this type. Private request, manifest,
    token and snapshot integrity failures always remain GitSnapshotError.
    """


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_name(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise GitSnapshotError('Invalid Git snapshot relative path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        raise GitSnapshotError('Git snapshot paths must be normalized relative names')
    # The old recursive capture allowed directories at depths 0..64. Preserve
    # that bound for selected-only copies (at most 64 parents plus the file).
    if len(path.parts) > 65:
        raise GitSnapshotError('Git review snapshot nesting limit exceeded')
    if any(p.lower() in EXCLUDED or p.startswith('.arquilo-write-') for p in path.parts):
        raise GitSnapshotError('Controller/Git internals are not publication paths')
    return value


def read_regular(path: Path, *, limit: int = MAX_FILE_BYTES) -> tuple[bytes, int] | None:
    """Read one no-follow handle, rejecting a change during the bounded read."""
    try:
        with safe_io.open_file(path, 'rb') as stream:
            before = os.fstat(stream.fileno())
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
    except FileNotFoundError:
        # A missing parent is an ordinary deletion, never a followed link.
        safe_io.check_path(path)
        return None
    if len(content) > limit:
        raise GitSnapshotError(f'Git review snapshot file exceeds {limit} bytes: {path.name}')
    signature = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if signature(before) != signature(after) or len(content) != after.st_size:
        raise GitSnapshotError(f'File changed while capturing Git review candidate: {path.name}')
    return content, (0o100755 if os.name != 'nt' and after.st_mode & stat.S_IXUSR else 0o100644)


def new_request(state: Path, source: Path, paths: list[str], *, run: str, task: str,
                attempt: str, parent: str, modes: dict[str, int]) -> dict:
    source = source.resolve()
    state = safe_io.lexical_path(state)
    if _overlaps_workspace(state, source):
        raise GitSnapshotError('Git review candidates must be outside every model-writable workspace')
    directory = safe_io.unique_directory(state / 'git-reviews', 'attempt')
    request = {'schema_version': 'arquilo.git_review_request.v1', 'source': str(source),
               'directory': str(directory), 'paths': list(paths), 'modes': dict(modes),
               'binding': {'run': run, 'task': task, 'attempt': attempt, 'parent': parent,
                           'nonce': uuid.uuid4().hex}}
    validate_request(request)
    safe_io.write_bytes(directory / 'request.json', canonical_bytes(request), exclusive=True)
    return request


def validate_request(value: Any) -> dict:
    keys = {'schema_version', 'source', 'directory', 'paths', 'modes', 'binding'}
    if not isinstance(value, dict) or set(value) != keys or value['schema_version'] != 'arquilo.git_review_request.v1':
        raise GitSnapshotError('Invalid private Git review request')
    for key in ('source', 'directory'):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute() or '\0' in value[key]:
            raise GitSnapshotError('Git review roots must be absolute controller-selected paths')
        safe_io.check_path(Path(value[key]), missing_ok=False)
    if _overlaps_workspace(Path(value['directory']), Path(value['source'])):
        raise GitSnapshotError('Private Git review directory overlaps the source workspace')
    if (not isinstance(value['paths'], list) or not value['paths']
            or len(value['paths']) > MAX_FILES
            or any(not isinstance(name, str) for name in value['paths'])
            or len(set(value['paths'])) != len(value['paths'])):
        raise GitSnapshotError('Invalid Git publication selection')
    for name in value['paths']:
        relative_name(name)
    if not isinstance(value['modes'], dict) or any(
            name not in value['paths'] or type(mode) is not int or mode not in (0o100644, 0o100755)
            for name, mode in value['modes'].items()):
        raise GitSnapshotError('Invalid original Git modes')
    binding = value['binding']
    if (not isinstance(binding, dict) or set(binding) != {'run', 'task', 'attempt', 'parent', 'nonce'}
            or any(not isinstance(x, str) or not x or '\0' in x for x in binding.values())
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', binding['parent'])
            or not re.fullmatch(r'[0-9a-f]{32}', binding['nonce'])):
        raise GitSnapshotError('Invalid Git review attempt identity')
    return value


def _walk_files(root: Path, *, skip_controls: bool = True):
    count = 0
    def walk(directory: Path, depth: int):
        nonlocal count
        if depth > 64:
            raise GitSnapshotError('Git review snapshot nesting limit exceeded')
        with safe_io.directory(directory) as (base, fd):
            for name in sorted(os.listdir(base if fd is None else fd)):
                if skip_controls and (name.lower() in EXCLUDED or name.startswith('.arquilo-write-')):
                    continue
                count += 1
                if count > MAX_FILES:
                    raise GitSnapshotError('Git review snapshot entry limit exceeded; use a smaller workspace')
                path = base / name
                info = os.stat(path if fd is None else name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise safe_io.UnsafePathError(f'Linked entry in Git review workspace: {path}')
                if stat.S_ISDIR(info.st_mode):
                    yield from walk(path, depth + 1)
                else:
                    safe_io._regular(info, path)
                    yield path, info
    yield from walk(root, 0)


def capture(request: dict, active_workspace: Path, review_index: int) -> tuple[dict, Path]:
    validate_request(request)
    if type(review_index) is not int or review_index < 1:
        raise GitSnapshotError('Invalid Git review round')
    root = Path(request['source'])
    active = active_workspace.resolve()
    if not active.is_relative_to(root):
        raise GitSnapshotError('Review working directory is outside the captured workspace')
    saved_request = read_regular(Path(request['directory']) / 'request.json', limit=MAX_MANIFEST_BYTES)
    if saved_request is None or saved_request[0] != canonical_bytes(request):
        raise GitSnapshotError('Private Git review request changed')
    candidate = safe_io.unique_directory(Path(request['directory']), 'review')
    mirror = candidate / 'workspace'
    safe_io.mkdir(mirror)
    records, total, entries = {}, 0, set()
    # Publication owns only explicitly selected outputs. Do not traverse an
    # unrelated virtualenv, link, large context tree or model run archive merely
    # because the owner requested publication of one small deliverable. The
    # ordinary read-only review retains its original cwd and full context.
    for name in request['paths']:
        path = root / name
        try:
            value = read_regular(path, limit=min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total))
        except (OSError, ValueError) as exc:
            raise GitSnapshotUnavailable('Selected Git output cannot be captured: ' + name) from exc
        if value is None:
            continue  # An explicit selected deletion is part of the candidate.
        parts = PurePosixPath(name).parts
        entries.update('/'.join(parts[:length]) for length in range(1, len(parts) + 1))
        if len(entries) > MAX_FILES:
            raise GitSnapshotUnavailable('Git review snapshot entry limit exceeded')
        content, mode = value
        total += len(content)
        if os.name == 'nt':
            mode = request['modes'].get(name, mode)
        safe_io.write_bytes(mirror / name, content, exclusive=True)
        if os.name != 'nt':
            os.chmod(mirror / name, 0o500 if mode == 0o100755 else 0o400)
        records[name] = {'sha256': digest(content), 'bytes': len(content), 'mode': mode}
    for name in request['paths']:
        if name not in records and os.path.lexists(root / name):
            raise GitSnapshotUnavailable(f'Selected path is not a captured regular file: {name}')
    manifest = {'schema_version': 'arquilo.git_review_snapshot.v1', 'request': request,
                'review_index': review_index, 'files': records,
                'selection': {name: records.get(name) for name in request['paths']}}
    raw = canonical_bytes(manifest)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise GitSnapshotError('Git snapshot manifest size limit exceeded')
    safe_io.write_bytes(candidate / 'manifest.json', raw, exclusive=True)
    token = {'candidate': candidate.name, 'sha256': digest(raw), 'review_index': review_index,
             'binding': dict(request['binding'])}
    return token, active


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GitSnapshotError('Duplicate key in Git review manifest')
        value[key] = item
    return value


@dataclass(frozen=True)
class ReviewedCandidate:
    request: dict
    token: dict

    def contents(self) -> dict[str, tuple[bytes, int] | None]:
        return verify(self.request, self.token, self.token['review_index'])


def verify(request: dict, token: Any, review_index: int) -> dict[str, tuple[bytes, int] | None]:
    validate_request(request)
    saved_request = read_regular(Path(request['directory']) / 'request.json', limit=MAX_MANIFEST_BYTES)
    if saved_request is None or saved_request[0] != canonical_bytes(request):
        raise GitSnapshotError('Private Git review request changed')
    if (not isinstance(token, dict) or set(token) != {'candidate', 'sha256', 'review_index', 'binding'}
            or not isinstance(token['candidate'], str) or not re.fullmatch(r'review-[0-9a-f]{32}', token['candidate'])
            or not isinstance(token['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', token['sha256'])
            or type(token['review_index']) is not int or token['review_index'] != review_index
            or type(review_index) is not int or review_index < 1 or token['binding'] != request['binding']):
        raise GitSnapshotError('Git snapshot does not match this accepted task/run/attempt/review')
    directory = Path(request['directory']) / token['candidate']
    raw = read_regular(directory / 'manifest.json', limit=MAX_MANIFEST_BYTES)
    if raw is None or digest(raw[0]) != token['sha256']:
        raise GitSnapshotError('Git review manifest missing or changed')
    try:
        manifest = json.loads(raw[0], object_pairs_hook=_json_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(GitSnapshotError('Nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise GitSnapshotError('Invalid Git review manifest') from exc
    if (not isinstance(manifest, dict)
            or set(manifest) != {'schema_version', 'request', 'review_index', 'files', 'selection'}
            or manifest['schema_version'] != 'arquilo.git_review_snapshot.v1'
            or manifest['request'] != request or manifest['review_index'] != review_index
            or not isinstance(manifest['files'], dict) or not isinstance(manifest['selection'], dict)
            or set(manifest['selection']) != set(request['paths'])):
        raise GitSnapshotError('Git review manifest contradicts controller request')
    mirror = directory / 'workspace'
    actual = {p.relative_to(mirror).as_posix() for p, _ in _walk_files(mirror, skip_controls=False)}
    if actual != set(manifest['files']):
        raise GitSnapshotError('Git review workspace inventory changed')
    result, total = {}, 0
    for name, record in manifest['files'].items():
        relative_name(name)
        if (not isinstance(record, dict) or set(record) != {'sha256', 'bytes', 'mode'}
                or type(record['bytes']) is not int or not 0 <= record['bytes'] <= MAX_FILE_BYTES
                or type(record['mode']) is not int or record['mode'] not in (0o100644, 0o100755)):
            raise GitSnapshotError('Invalid Git snapshot file record')
        value = read_regular(mirror / name, limit=min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total))
        if value is None or len(value[0]) != record['bytes'] or digest(value[0]) != record['sha256']:
            raise GitSnapshotError('Git review snapshot bytes changed')
        total += len(value[0])
        if os.name != 'nt' and value[1] != record['mode']:
            raise GitSnapshotError('Git review executable mode changed')
        if name in request['paths']:
            result[name] = (value[0], record['mode'])
    for name in request['paths']:
        if manifest['selection'][name] != manifest['files'].get(name):
            raise GitSnapshotError('Git review selection disagrees with snapshot files')
        result.setdefault(name, None)
    return result


def review_instructions(request: dict, token: dict) -> str:
    return ('\n\nCONTROLLER GIT PUBLICATION CANDIDATE\n'
            'Your working directory remains the ordinary project workspace. Review the task '
            'with all necessary original context; context has NOT been copied or silently omitted. '
            'A separate private directory contains ONLY the explicitly selected output bytes '
            'captured before this review. Read those frozen selected outputs as the authoritative '
            'publication candidate, not a later live version or producer claims. '
            'Review every explicitly selected output below against the task and report a blocker '
            'for an unexplained or unverified selected change. Publication will use these exact '
            'bytes/modes or deletions, not a later reread of live files. Consult the original '
            'workspace for other necessary context. The controller checks selected live outputs '
            'still match after review; the model judgment is still your responsibility.\n'
            + json.dumps({'paths_relative_to_snapshot_root': request['paths'],
                          'snapshot_root': str(Path(request['directory']) / token['candidate'] / 'workspace'),
                          'original_workspace_for_context': request['source'], 'manifest_sha256': token['sha256'],
                          'parent': request['binding']['parent']}, ensure_ascii=False) + '\n')


def verify_live(request: dict, token: Any, review_index: int) -> dict[str, tuple[bytes, int] | None]:
    """Bind successful review to unchanged selected bytes, including deletions."""
    contents = verify(request, token, review_index)
    root = Path(request['source'])
    for name, frozen in contents.items():
        live = read_regular(root / name)
        if live is not None and os.name == 'nt':
            live = live[0], request['modes'].get(name, live[1])
        if live != frozen:
            raise GitSnapshotError('Selected file changed after review; a fresh review is required: ' + name)
    return contents
