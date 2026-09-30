# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Explicit, literal-path commits; never sweep a user's index or workspace.

Only selected files that were clean at launch can be committed. Raw controller
logs are always excluded. The real index is not used to build the commit.
"""
from __future__ import annotations
import os
from pathlib import Path
import stat
import subprocess
import uuid

import safe_io


class ReviewedGitError(RuntimeError):
    pass


class ReviewedGit:
    def __init__(self, workspace: Path, paths, state: Path, *, push=False):
        self.workspace, self.state, self.push = workspace, state, push
        if not paths:
            raise ReviewedGitError('--git now requires explicit --git-path FILE selections; it never runs git add -A.')
        self.paths = []
        for name in paths:
            value = Path(name)
            if (value.is_absolute() or not value.parts or '..' in value.parts
                    or any(p.lower() in {'.git', '.codex_runs', '.arquilo', 'process_stop'} for p in value.parts)
                    or any(p.startswith('.arquilo-write-') for p in value.parts)):
                raise ReviewedGitError(f'Not a permitted relative Git output path: {name!r}')
            literal = value.as_posix()
            safe_io.check_path(workspace / value)
            if literal not in self.paths:
                self.paths.append(literal)
        self.branch = self.git('symbolic-ref', '-q', 'HEAD').strip().decode()
        self.head = self.git('rev-parse', '--verify', 'HEAD').strip().decode()
        self.initial_index = self.git('ls-files', '--stage', '-z')
        dirty = self._dirty()
        conflicts = sorted(set(self.paths) & dirty)
        if conflicts:
            raise ReviewedGitError('Selected Git paths already have uncommitted changes; commit/stash them first: ' + ', '.join(conflicts))
        self.remote = self.remote_branch = None
        if push:
            self.remote = self.git('config', '--get', 'branch.' + self.branch[11:] + '.remote').strip().decode()
            self.remote_branch = self.git('config', '--get', 'branch.' + self.branch[11:] + '.merge').strip().decode()
            upstream = self.git('rev-parse', '--verify', '@{upstream}').strip().decode()
            if upstream != self.head or not self.remote_branch.startswith('refs/heads/'):
                raise ReviewedGitError('--git-push requires HEAD at its configured upstream; push unrelated commits manually first.')

    def git(self, *args, data=None, index=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_LITERAL_PATHSPECS='1', GIT_OPTIONAL_LOCKS='0')
        if index:
            env['GIT_INDEX_FILE'] = str(index)
        try:
            result = subprocess.run(['git', *args], cwd=self.workspace, env=env,
                                    input=data, capture_output=True, shell=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReviewedGitError(f'Git operation failed: {exc}') from exc
        if result.returncode:
            raise ReviewedGitError('Git ' + args[0] + ' failed: ' + result.stderr.decode('utf-8', 'replace')[-1500:])
        return result.stdout

    def _dirty(self):
        fields = self.git('status', '--porcelain=v1', '-z', '--untracked-files=all').split(b'\0')
        result = set()
        i = 0
        while i < len(fields):
            entry = fields[i]
            i += 1
            if not entry:
                continue
            result.add(os.fsdecode(entry[3:]))
            if b'R' in entry[:2] or b'C' in entry[:2]:
                if i >= len(fields):
                    raise ReviewedGitError('Malformed Git rename status')
                result.add(os.fsdecode(fields[i]))
                i += 1
        return result

    def commit(self, message: str):
        # Refuse concurrent index/HEAD edits rather than committing somebody
        # else's staged content, reverting their index, or creating a wrong parent.
        if (self.git('symbolic-ref', '-q', 'HEAD').strip().decode() != self.branch
                or self.git('rev-parse', 'HEAD').strip().decode() != self.head
                or self.git('ls-files', '--stage', '-z') != self.initial_index):
            raise ReviewedGitError('Git HEAD/index changed outside ARQUILO; no automatic commit/push.')
        dirty = self._dirty()
        selected = sorted(set(self.paths) & dirty)
        if not selected:
            return None
        index = self.state / ('git-index-' + uuid.uuid4().hex)
        self.git('read-tree', self.head, index=index)
        entries = []
        for name in selected:
            path = self.workspace / name
            try:
                with safe_io.open_file(path, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    content = stream.read()
            except FileNotFoundError:
                entries.append(b'0 ' + b'0' * len(self.head) + b'\t' + os.fsencode(name) + b'\0')
                continue
            # Preserve exact reviewed bytes; do not execute clean filters or hooks.
            oid = self.git('hash-object', '-w', '--stdin', data=content).strip()
            mode = b'100755' if os.name != 'nt' and info.st_mode & stat.S_IXUSR else b'100644'
            if os.name == 'nt':
                for entry in self.initial_index.split(b'\0'):
                    if entry.endswith(b'\t' + os.fsencode(name)):
                        mode = entry.split(b' ', 1)[0]
                        break
            entries.append(mode + b' ' + oid + b'\t' + os.fsencode(name) + b'\0')
        changes = b''.join(entries)
        self.git('update-index', '-z', '--index-info', data=changes, index=index)
        tree = self.git('write-tree', index=index).strip().decode()
        if tree == self.git('rev-parse', self.head + '^{tree}').strip().decode():
            return None
        new = self.git('commit-tree', tree, '-p', self.head, data=(message + '\n').encode()).strip().decode()
        # Compare-and-swap the exact branch, never force a moving HEAD.
        self.git('update-ref', '-m', 'ARQUILO reviewed output', self.branch, new, self.head)
        self.head = new
        # Only selected entries change; unrelated staged and unstaged files remain.
        self.git('update-index', '-z', '--index-info', data=changes)
        self.initial_index = self.git('ls-files', '--stage', '-z')
        if self.push:
            self.git('push', '--porcelain', '--', self.remote, new + ':' + self.remote_branch)
        return {'commit': new, 'paths': selected, 'pushed': self.push}
