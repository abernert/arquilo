# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Content identity for a fresh live review, independent of Git publication.

This is a before/after/final-acceptance drift guard, not hostile same-user OS
isolation. Dependency/cache exclusions are explicit in every manifest. It never
commits, stages, changes a task status, or regards historical tests as acceptance.
"""
from __future__ import annotations

import hashlib
import difflib
import re
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

import safe_io
from host_launcher import launcher_environment, resolve_executable

EXCLUDED_DIRS = frozenset({'.git', '.codex_runs', '.claude_runs', '.venv', 'venv',
    '.test-env', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache'})
MAX_ENTRIES = 100000
MAX_BYTES = 8 << 30
MAX_GIT_BYTES = 64 << 20


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, workspace: Path, args: list[str], *, absent_head: bool = False) -> bytes:
    env = launcher_environment(dict(os.environ), workspace=workspace)
    # Do not inherit redirections into unrelated repositories or external helpers.
    env = {k: v for k, v in env.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', GIT_ATTR_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
               GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='')
    exe = resolve_executable('git', workspace=workspace, env=env)
    cmd = [str(exe), '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
           '-c', 'diff.submodule=short', '--no-pager', '-C', str(root), *args]
    # Output is spooled outside the task workspace and size checked; it is never
    # a command source. The subprocess has an absolute timeout.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        result = subprocess.run(cmd, env=env, stdout=out, stderr=err, timeout=30, check=False)
        if absent_head and result.returncode == 1:
            return b""
        if result.returncode != 0:
            raise ValueError('Cannot bind Git candidate metadata; inspect repository: ' + str(root))
        if out.tell() > MAX_GIT_BYTES:
            raise ValueError('Git candidate diff exceeds the bounded archive limit')
        out.seek(0)
        return out.read(MAX_GIT_BYTES + 1)


def capture(workspace: Path) -> tuple[dict, dict[str, bytes]]:
    files, repos, excluded, total, count = {}, [], [], 0, 0
    def walk(folder: Path, depth: int):
        nonlocal total, count
        if depth > 64:
            raise ValueError('Review candidate exceeds directory-depth limit')
        with safe_io.directory(folder) as (base, fd):
            for name in sorted(os.listdir(base if fd is None else fd)):
                path = base / name
                rel = path.relative_to(workspace).as_posix()
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError('Review candidate exceeds entry limit')
                info = os.stat(path if fd is None else name, dir_fd=fd, follow_symlinks=False)
                if name == '.git':
                    # Git metadata are identified by HEAD and a full diff below.
                    # No .git directory traversal or local Git config execution.
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise ValueError('Linked Git metadata cannot bind a review candidate')
                    repos.append(base)
                    excluded.append(rel)
                    continue
                if name == 'process_stop':
                    raise ValueError('process_stop blocks review candidate capture: ' + rel)
                if name in EXCLUDED_DIRS and stat.S_ISDIR(info.st_mode):
                    excluded.append(rel)
                    continue
                if stat.S_ISDIR(info.st_mode):
                    walk(path, depth + 1)
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Linked candidate path requires explicit inspection: ' + rel)
                with safe_io.open_file(path, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    h, size = hashlib.sha256(), 0
                    for block in iter(lambda: stream.read(1 << 20), b''):
                        size += len(block); total += len(block)
                        if total > MAX_BYTES:
                            raise ValueError('Review candidate exceeds total-byte limit')
                        h.update(block)
                    after = os.fstat(stream.fileno())
                signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
                if signature(before) != signature(after) or size != after.st_size:
                    raise ValueError('Candidate changed during hashing: ' + rel)
                files[rel] = {'sha256': h.hexdigest(), 'bytes': size,
                              'executable': bool(after.st_mode & stat.S_IXUSR) if os.name != 'nt' else False}
    walk(workspace, 0)
    git_records, diffs = [], {}
    for i, root in enumerate(repos, 1):
        # Only object reads: a normal worktree `git diff` can invoke a local
        # clean filter. Never execute workspace-configured conversion helpers.
        head = _git(root, workspace, ['rev-parse', '--verify', '--quiet', 'HEAD'], absent_head=True).decode('ascii').strip()
        if head and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head):
            raise ValueError('Invalid Git HEAD object identity')
        tree = _git(root, workspace, ['ls-tree', '-r', '-z', '--full-tree', head]) if head else b''
        baseline = {}
        for row in tree.split(b'\0'):
            if not row:
                continue
            meta, raw_name = row.split(b'\t', 1)
            mode, kind, oid = meta.decode('ascii').split()
            name = raw_name.decode('utf-8')
            if (Path(name).is_absolute() or '..' in Path(name).parts
                    or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', oid)):
                raise ValueError('Unsafe Git tree entry')
            baseline[name] = (mode, kind, oid)
        prefix = root.relative_to(workspace)
        selected = {str(Path(name).relative_to(prefix)).replace(os.sep, '/'): record
                    for name, record in files.items() if Path(name).is_relative_to(prefix)}
        parts, diff_size = [], 0
        for name in sorted(set(baseline) | set(selected)):
            # Dependency/cache exclusions apply to baseline entries too and are
            # explicit in the candidate scope, not silently reclassified as deletions.
            if any(part in EXCLUDED_DIRS for part in Path(name).parts):
                continue
            old = baseline.get(name)
            new = selected.get(name)
            content = b''
            if new is not None:
                with safe_io.open_file(root / name, 'rb') as stream:
                    content = stream.read(MAX_GIT_BYTES + 1)
                if len(content) > MAX_GIT_BYTES:
                    raise ValueError('Changed Git file exceeds bounded diff size')
                if sha(content) != new['sha256']:
                    raise ValueError('File changed while constructing review diff: ' + name)
            if old and old[1] == 'blob' and new is not None:
                algorithm = hashlib.sha256 if len(old[2]) == 64 else hashlib.sha1
                oid = algorithm(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
                mode = '100755' if new['executable'] else '100644'
                if oid == old[2] and (os.name == 'nt' or mode == old[0]):
                    continue
            previous = _git(root, workspace, ['cat-file', 'blob', old[2]]) if old and old[1] == 'blob' else b''
            header = ('diff --review ' + json.dumps(name) + '\n'
                      + 'old=' + (old[2] if old else 'ABSENT') + ' new_sha256='
                      + (new['sha256'] if new else 'ABSENT') + '\n')
            try:
                if b'\0' in previous or b'\0' in content:
                    raise UnicodeError()
                delta = ''.join(difflib.unified_diff(previous.decode('utf-8').splitlines(keepends=True),
                    content.decode('utf-8').splitlines(keepends=True), fromfile='a/' + name, tofile='b/' + name))
            except UnicodeError:
                delta = 'Binary content differs; see original object ID and current SHA-256.\n'
            part = (header + delta + '\n').encode('utf-8')
            diff_size += len(part)
            if diff_size > MAX_GIT_BYTES:
                raise ValueError('Review candidate diff exceeds bounded size')
            parts.append(part)
        diff = b''.join(parts)
        name = f'git-{i:03d}.diff'
        diffs[name] = diff
        git_records.append({'root': root.relative_to(workspace).as_posix(), 'head': head or 'UNBORN',
                            'diff': name, 'diff_sha256': sha(diff)})
    manifest = {'schema_version': 'arquilo.review_candidate.v1', 'workspace': str(workspace),
                'files': files, 'repositories': git_records, 'excluded': sorted(excluded),
                'scope': 'All regular workspace files except listed dependency/cache/controller directories. '
                         'Excluded contents and external references are not byte-bound; reviewer must '
                         'report any reliance on them. Historical tests are not fresh acceptance.'}
    return manifest, diffs
