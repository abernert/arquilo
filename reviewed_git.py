# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Publish an accepted immutable review candidate, never a live workspace reread.

Git's object plumbing runs without filters, hooks or fsmonitor. A private bare
repository builds the candidate and performs transport to one pinned endpoint.
The source branch and real index are guarded separately; publication is not a
transaction spanning the local repository and a remote server.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import queue
import threading
import time
import subprocess
from urllib.parse import urlsplit
import uuid

import safe_io
import git_snapshot
from process_tree import ProcessTree, InterruptiblePipe

MAX_PACK_BYTES = 128 * 1024 * 1024
PACK_TIMEOUT_SECONDS = 60
from controller_state import _overlaps_workspace
from host_launcher import launcher_environment, resolve_executable


class ReviewedGitError(RuntimeError):
    pass


class ReviewedGit:
    def __init__(self, workspace: Path, paths, state: Path, *, push=False,
                 executable: str | None = None):
        self.workspace = workspace.resolve()
        self.state = safe_io.lexical_path(state)
        self.push = bool(push)
        if _overlaps_workspace(self.state, self.workspace):
            raise ReviewedGitError('Git publication state must be outside the workspace.')
        if not paths:
            raise ReviewedGitError('--git requires explicit --git-path FILE selections; it never runs git add -A.')
        self.paths = []
        for name in paths:
            try:
                # Keep Path's native interpretation for Windows, then validate a
                # canonical literal name for storage and the index-info stream.
                value = Path(name)
                if value.is_absolute() or not name or '..' in value.parts:
                    raise ValueError('Not a relative file')
                literal = git_snapshot.relative_name(value.as_posix())
            except (ValueError, TypeError) as exc:
                raise ReviewedGitError(f'Not a permitted relative Git output path: {name!r}') from exc
            safe_io.check_path(self.workspace / literal)
            if literal not in self.paths:
                self.paths.append(literal)
        try:
            self.executable = str(resolve_executable(executable or 'git',
                workspace=self.workspace, env=os.environ))
        except OSError as exc:
            raise ReviewedGitError(f'Git launcher unavailable: {exc}') from exc
        self.environment = launcher_environment(
            {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')},
            workspace=self.workspace, executable=self.executable)
        self.environment.update(GIT_LITERAL_PATHSPECS='1', GIT_OPTIONAL_LOCKS='0',
                                GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
        self.directory = safe_io.unique_directory(self.state / 'git-publication', 'session')
        self.empty = self.directory / 'empty'
        safe_io.mkdir(self.empty)
        self.git_directory = None
        self.publication = None
        self.identity = {}
        self.transport_config = []
        self._capture_host_transport_configuration()
        self.branch = self.git('symbolic-ref', '-q', 'HEAD').strip().decode()
        if not self.branch.startswith('refs/heads/'):
            raise ReviewedGitError('Git publication requires an ordinary local branch.')
        self.git('check-ref-format', self.branch)
        self.head = self._oid(self.git('rev-parse', '--verify', 'HEAD'))
        if Path(os.fsdecode(self.git('rev-parse', '--show-toplevel').strip())).resolve() != self.workspace:
            raise ReviewedGitError('Automatic publication requires the Git working-tree root as workspace.')
        self.git_directory = safe_io.check_path(Path(os.fsdecode(
            self.git('rev-parse', '--absolute-git-dir').strip())), missing_ok=False)
        self.index_path = self._git_path('index')
        self.head_path = self._git_path('HEAD')
        self.index_bytes = self._index_bytes()
        self.initial_index = self.git('ls-files', '--stage', '-z')
        self.object_format = self.git('rev-parse', '--show-object-format').strip().decode()
        if self.object_format not in ('sha1', 'sha256'):
            raise ReviewedGitError('Unsupported Git object format.')
        self.modes, self.baseline = {}, {}
        self._check_initial_selection()
        for field in ('name', 'email'):
            value = self.git('config', '--get', 'user.' + field, optional=True).strip()
            if value:
                self.identity[field] = value.decode('utf-8')
        self.publication = self.directory / 'publication.git'
        self.git('init', '--bare', '--quiet', '--object-format=' + self.object_format,
                 '--template=' + str(self.empty), str(self.publication), private=True)
        # No fetch from the task repository: upload-pack hooks in its mutable
        # config must not execute in the controller. Pack exact objects instead.
        pack = self.git('pack-objects', '--stdout', '--revs', data=(self.head + '\n').encode())
        self.git('index-pack', '--stdin', data=pack, private=True)
        self.remote = self.remote_branch = self.push_destination = None
        if self.push:
            self.remote = self.git('config', '--get', 'branch.' + self.branch[11:] + '.remote').strip().decode()
            self.remote_branch = self.git('config', '--get', 'branch.' + self.branch[11:] + '.merge').strip().decode()
            if not self.remote or self.remote == '.' or not self.remote_branch.startswith('refs/heads/'):
                raise ReviewedGitError('--git-push requires a configured external remote branch.')
            self.git('check-ref-format', self.remote_branch)
            self.push_destination = self._push_destination()
            self._validate_destination(self.push_destination)
            if self._remote_head() != self.head:
                raise ReviewedGitError('--git-push requires HEAD at the actual push destination; push unrelated commits manually first.')
        self._requests: dict[str, bytes] = {}
        self._accepted: set[bytes] = set()

    def _capture_host_transport_configuration(self):
        # Snapshot only resolved host scopes before any task runs. Do not copy
        # repository/worktree settings, include directives or URL/remote rules
        # into the publisher. Values (possibly credentials) stay in memory and
        # the child environment; they are never put in a snapshot or report.
        fields = self.git('config', '--list', '--null', '--show-scope', '--includes').split(b'\0')
        if fields[-1] != b'' or (len(fields) - 1) % 2:
            raise ReviewedGitError('Cannot decode trusted Git host configuration.')
        for index in range(0, len(fields) - 1, 2):
            scope, entry = fields[index:index + 2]
            if scope not in (b'global', b'system'):
                continue
            key, _, value = entry.partition(b'\n')
            key = key.decode('utf-8')
            if (key.lower().startswith(('include.', 'includeif.', 'url.', 'remote.', 'branch.'))
                    or key.lower() in {'core.worktree', 'core.bare', 'core.repositoryformatversion'}):
                continue
            self.transport_config.append((key, value.decode('utf-8')))
        if len(self.transport_config) > 1024:
            raise ReviewedGitError('Git host configuration exceeds publication limit.')

    @staticmethod
    def _oid(value: bytes) -> str:
        text = value.strip().decode('ascii')
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', text):
            raise ReviewedGitError('Git returned an invalid object identity.')
        return text

    def _git_path(self, name: str) -> Path:
        raw = os.fsdecode(self.git('rev-parse', '--git-path', name).strip())
        path = Path(raw)
        return safe_io.check_path(path if path.is_absolute() else self.workspace / path)

    def _index_bytes(self) -> bytes | None:
        value = git_snapshot.read_regular(self.index_path, limit=64 * 1024 * 1024)
        return None if value is None else value[0]

    def git(self, *args, data=None, index=None, private=False, optional=False, prepared=None):
        """Literal plumbing; mutable task repository settings cannot run helpers.

        Transport uses only the private repository. Global/system host auth and
        transport settings are a pre-task snapshot, excluding URL rewrites and
        include directives. They remain trusted operator configuration.
        """
        env = dict(self.environment)
        if index is not None:
            env['GIT_INDEX_FILE'] = str(index)
        command = [self.executable, '-c', 'core.fsmonitor=false',
                   '-c', 'core.hooksPath=' + str(self.empty), '-c', 'core.untrackedCache=false',
                   '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'commit.gpgSign=false',
                   '-c', 'tag.gpgSign=false', '-c', 'push.followTags=false',
                   '-c', 'protocol.ext.allow=never']
        if private:
            env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_CONFIG_COUNT=str(len(self.transport_config)))
            for number, (key, value) in enumerate(self.transport_config):
                env[f'GIT_CONFIG_KEY_{number}'] = key
                env[f'GIT_CONFIG_VALUE_{number}'] = value
            if self.publication is None:
                raise ReviewedGitError('Private publication repository not initialized.')
            command += ['--git-dir=' + str(self.publication)]
            for key, value in self.identity.items():
                command += ['-c', 'user.' + key + '=' + value]
            cwd = self.directory
        else:
            if self.git_directory is not None:
                command += ['--git-dir=' + str(self.git_directory), '--work-tree=' + str(self.workspace)]
            cwd = self.workspace
        if prepared is not None:
            return self._transaction([*command, *args], cwd, env, data, prepared)
        try:
            if args[0] == 'pack-objects':
                result = self._bounded_pack([*command, *args], cwd, env, data)
            else:
                result = subprocess.run([*command, *args], cwd=cwd, env=env, input=data,
                                        capture_output=True, shell=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReviewedGitError(f'Git operation failed: {type(exc).__name__}') from exc
        if result.returncode and not (optional and result.returncode == 1):
            # Transport stderr may contain credentials embedded in URLs. It is
            # not suitable for a default console exception.
            raise ReviewedGitError('Git ' + args[0] + f' failed (exit {result.returncode}); inspect the repository and private publication state.')
        return result.stdout

    @staticmethod
    def _bounded_pack(command, cwd, env, data):
        """Bound potentially large history transfer before accumulating its bytes."""
        owner = ProcessTree()
        proc = None
        stop = threading.Event()
        errors = []
        output, diagnostics = bytearray(), bytearray()
        threads = []
        try:
            try:
                proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, shell=False,
                    **owner.popen_options)
                owner.bind(proc)
                owner.prepare_pipes()
            except BaseException:
                owner.abort_start(proc)
                raise
            def collect(stream, target, limit):
                try:
                    pipe = InterruptiblePipe(stream, stop)
                    while True:
                        chunk = pipe.read(65536)
                        if not chunk:
                            break
                        if len(target) + len(chunk) > limit:
                            errors.append('Git pack output limit exceeded')
                            stop.set()
                            break
                        target.extend(chunk)
                except OSError as exc:
                    if not stop.is_set():
                        errors.append('Git pack pipe read failed: ' + type(exc).__name__)
                        stop.set()
            def feed():
                try:
                    pipe = InterruptiblePipe(proc.stdin, stop)
                    remaining = memoryview(data or b'')
                    while remaining:
                        count = pipe.write(remaining[:65536])
                        if not count:
                            raise OSError('Incomplete Git pack input')
                        remaining = remaining[count:]
                except OSError as exc:
                    if not stop.is_set():
                        errors.append('Git pack input failed: ' + type(exc).__name__)
                        stop.set()
                finally:
                    proc.stdin.close()
            threads = [threading.Thread(target=collect, args=(proc.stdout, output, MAX_PACK_BYTES), daemon=True),
                       threading.Thread(target=collect, args=(proc.stderr, diagnostics, 65536), daemon=True),
                       threading.Thread(target=feed, daemon=True)]
            for thread in threads:
                thread.start()
            deadline = time.monotonic() + PACK_TIMEOUT_SECONDS
            while proc.poll() is None or any(thread.is_alive() for thread in threads):
                if stop.is_set():
                    break
                if time.monotonic() >= deadline:
                    errors.append('Git pack transfer deadline exceeded')
                    stop.set()
                    break
                time.sleep(.005)
            cleanup = owner.terminate(reason='git-pack-complete' if not errors else 'git-pack-failed', grace_seconds=.1)
            errors.extend(cleanup.errors)
            stop.set()
            for thread in threads:
                owner.cancel_io(thread)
                thread.join(timeout=3)
                if thread.is_alive():
                    errors.append('Git pack pipe did not finish')
            if errors:
                raise ReviewedGitError('; '.join(errors))
            return subprocess.CompletedProcess(command, proc.returncode, bytes(output), bytes(diagnostics))
        finally:
            stop.set()
            if owner.proc is not None and owner.cleanup is None:
                owner.terminate(reason='git-pack-aborted', grace_seconds=.1)
            for thread in threads:
                owner.cancel_io(thread)
                thread.join(timeout=3)
            owner.close()
            if proc is not None and not any(thread.is_alive() for thread in threads):
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    pipe.close()

    @staticmethod
    def _transaction(command, cwd, env, data, prepared):
        """Hold Git's own HEAD/branch transaction locks across index publication."""
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        lines = queue.Queue()
        def drain():
            try:
                for line in iter(process.stdout.readline, b''):
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        def expect(value):
            try:
                line = lines.get(timeout=60)
            except queue.Empty as exc:
                raise ReviewedGitError('Git reference transaction timed out.') from exc
            if line not in (value, value[:-1] + b'\r\n'):
                raise ReviewedGitError('Git reference transaction refused its expected phase.')
        try:
            process.stdin.write(data)
            process.stdin.flush()
            expect(b'start: ok\n')
            expect(b'prepare: ok\n')
            prepared()
            process.stdin.write(b'commit\n')
            process.stdin.flush()
            expect(b'commit: ok\n')
            process.stdin.close()
            if process.wait(timeout=60):
                raise ReviewedGitError('Git reference transaction did not exit successfully.')
            return b''
        finally:
            if process.poll() is None:
                # EOF/termination aborts an uncommitted prepared transaction;
                # Git owns and releases its locks, never our manual unlink.
                try:
                    process.stdin.close()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def _check_initial_selection(self):
        entries = {}
        for row in self.initial_index.split(b'\0'):
            if not row:
                continue
            header, name = row.split(b'\t', 1)
            mode, oid, stage = header.split(b' ')
            entries.setdefault(os.fsdecode(name), []).append((mode, oid, stage))
        tree = {}
        for row in self.git('ls-tree', '-rz', self.head).split(b'\0'):
            if row:
                header, name = row.split(b'\t', 1)
                mode, kind, oid = header.split(b' ')
                tree[os.fsdecode(name)] = (mode, oid, kind)
        for name in self.paths:
            current = git_snapshot.read_regular(self.workspace / name)
            tracked = tree.get(name)
            staged = entries.get(name, [])
            clean = not tracked and not staged and current is None
            if tracked is not None and current is not None:
                mode, oid, kind = tracked
                if kind != b'blob' or mode not in (b'100644', b'100755'):
                    raise ReviewedGitError('Selected paths must be ordinary files, not links or submodules.')
                self.modes[name] = int(mode, 8)
                content, physical_mode = current
                blob_size = int(self.git('cat-file', '-s', oid.decode()).strip())
                if blob_size > git_snapshot.MAX_FILE_BYTES:
                    raise ReviewedGitError('Selected baseline blob exceeds the Git review file limit.')
                blob = self.git('cat-file', 'blob', oid.decode())
                clean_bytes = content == blob
                # Account for Git's built-in checkout line endings only. Never
                # run a clean/smudge filter to decide whether a file is clean.
                if not clean_bytes and b'\0' not in content and content.replace(b'\r\n', b'\n') == blob:
                    attrs = self.git('check-attr', '-z', '--stdin', 'filter', 'working-tree-encoding', 'text', 'eol',
                                     data=os.fsencode(name) + b'\0').split(b'\0')
                    values = {attrs[i + 1]: attrs[i + 2] for i in range(0, len(attrs) - 2, 3)}
                    autocrlf = self.git('config', '--get', 'core.autocrlf', optional=True).strip().lower()
                    clean_bytes = (values.get(b'filter') in (b'unspecified', b'unset')
                        and values.get(b'working-tree-encoding') in (b'unspecified', b'unset')
                        and values.get(b'text') != b'unset'
                        and (values.get(b'eol') == b'crlf' or autocrlf == b'true'))
                clean = (staged == [(mode, oid, b'0')] and clean_bytes
                         and (os.name == 'nt' or physical_mode == int(mode, 8)))
                current = (content, self.modes[name] if os.name == 'nt' else physical_mode)
            if not clean:
                raise ReviewedGitError('Selected Git paths already have uncommitted changes; commit/stash them first: ' + name)
            self.baseline[name] = current

    def _push_destination(self):
        destinations = self.git('remote', 'get-url', '--push', '--all', '--', self.remote).splitlines()
        if len(destinations) != 1 or not destinations[0]:
            raise ReviewedGitError('--git-push requires exactly one configured push destination.')
        return destinations[0]

    def _validate_destination(self, raw: bytes):
        value = os.fsdecode(raw)
        if not value or value.startswith('-') or any(ord(c) < 32 for c in value) or '::' in value:
            raise ReviewedGitError('Unsupported Git transport destination.')
        if '://' in value:
            scheme = urlsplit(value).scheme
            if scheme not in ('https', 'http', 'ssh', 'git', 'file'):
                raise ReviewedGitError('Custom Git transport helpers are not allowed for automatic publication.')
            if scheme == 'file':
                parts = urlsplit(value)
                if parts.netloc not in ('', 'localhost'):
                    raise ReviewedGitError('Non-local file transport is not supported.')
                from urllib.parse import unquote
                local = Path(unquote(parts.path)).resolve()
            else:
                local = None
        elif re.match(r'^[^/\\:]+@[^/\\:]+:.+', value) or (':' in value and not Path(value).is_absolute()):
            # Ordinary scp-like SSH syntax; no external helper protocol.
            local = None
        else:
            local = Path(value)
            if not local.is_absolute():
                raise ReviewedGitError('Local push destinations must use an absolute path.')
            local = local.resolve()
        if local is not None and _overlaps_workspace(local, self.workspace):
            raise ReviewedGitError('Push destination must be outside the task workspace.')
        # Resolve any trusted host rewrite in the same private transport context
        # once, before pinning. A second different rewrite is refused, not guessed.
        effective = self.git('ls-remote', '--get-url', '--', value, private=True).strip()
        if effective != raw:
            raise ReviewedGitError('Push destination is rewritten again by host configuration; configure its final URL explicitly.')

    def _remote_head(self) -> str | None:
        output = self.git('ls-remote', '--refs', '--', os.fsdecode(self.push_destination),
                          self.remote_branch, private=True)
        rows = [row.split(b'\t') for row in output.splitlines() if row]
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1].decode() != self.remote_branch:
            raise ReviewedGitError('Ambiguous push destination reference.')
        return self._oid(rows[0][0])

    def _check_push_destination(self):
        if self.push and self._push_destination() != self.push_destination:
            raise ReviewedGitError('Git push destination changed outside ARQUILO; no automatic commit/push.')

    def _check_source(self):
        if (self.git('symbolic-ref', '-q', 'HEAD').strip().decode() != self.branch
                or self._oid(self.git('rev-parse', 'HEAD')) != self.head
                or self.git('ls-files', '--stage', '-z') != self.initial_index
                or self._index_bytes() != self.index_bytes):
            raise ReviewedGitError('Git HEAD/index changed outside ARQUILO; no automatic commit/push.')
        self._check_push_destination()

    def begin_review(self, *, run: str, task: str, attempt: str) -> dict:
        self._check_source()
        request = git_snapshot.new_request(self.state, self.workspace, self.paths,
            run=run, task=task, attempt=attempt, parent=self.head, modes=self.modes)
        self._requests[request['directory']] = git_snapshot.canonical_bytes(request)
        return request

    def accept_review(self, request: dict, token: dict, *, review_index: int) -> git_snapshot.ReviewedCandidate:
        # This call belongs AFTER validated successful review/worker completion.
        if (not isinstance(request, dict) or self._requests.get(request.get('directory'))
                != git_snapshot.canonical_bytes(request) or request['binding']['parent'] != self.head):
            raise ReviewedGitError('Git review request is not owned by this controller attempt.')
        contents = git_snapshot.verify(request, token, review_index)
        self._check_live_selection(contents)
        candidate = git_snapshot.ReviewedCandidate(json.loads(json.dumps(request)), json.loads(json.dumps(token)))
        self._accepted.add(git_snapshot.canonical_bytes({'request': request, 'token': token}))
        return candidate

    @contextmanager
    def _source_locks(self):
        # Cooperating Git writers reserve these same lock names. Never delete a
        # pre-existing lock, and keep directory handles leased/anchored throughout.
        with ExitStack() as stack:
            owned = []
            try:
                for path in (self.index_path.with_name(self.index_path.name + '.lock'),):
                    base, fd = stack.enter_context(safe_io.directory(path.parent))
                    with safe_io.open_file(path, 'xb') as stream:
                        marker = uuid.uuid4().hex.encode()
                        stream.write(marker)
                        stream.flush()
                        info = os.fstat(stream.fileno())
                    owned.append((path, fd, info.st_dev, info.st_ino, marker))
                yield
            except FileExistsError as exc:
                raise ReviewedGitError('Git HEAD/index lock already exists; another writer may be active.') from exc
            finally:
                for path, fd, device, inode, marker in reversed(owned):
                    try:
                        info = os.stat(path if fd is None else path.name, dir_fd=fd, follow_symlinks=False)
                        if (info.st_dev, info.st_ino) == (device, inode) and safe_io.read_bytes(path) == marker:
                            os.unlink(path if fd is None else path.name, dir_fd=fd)
                    except FileNotFoundError:
                        pass

    def _check_live_selection(self, contents):
        for name, frozen in contents.items():
            live = git_snapshot.read_regular(self.workspace / name)
            if live is not None and os.name == 'nt':
                live = live[0], self.modes.get(name, live[1])
            if live != frozen:
                raise ReviewedGitError('Selected file changed after review; a fresh review is required: ' + name)

    def commit(self, message: str, *, candidate: git_snapshot.ReviewedCandidate | None = None):
        self._check_source()
        if not isinstance(candidate, git_snapshot.ReviewedCandidate):
            raise ReviewedGitError('Git commit requires a controller-accepted pre-review snapshot.')
        key = git_snapshot.canonical_bytes({'request': candidate.request, 'token': candidate.token})
        if key not in self._accepted or candidate.request['binding']['parent'] != self.head:
            raise ReviewedGitError('Git review candidate is stale, foreign or already consumed.')
        contents = candidate.contents()
        self._check_live_selection(contents)
        selected = [name for name in self.paths if contents[name] != self.baseline[name]]
        self._accepted.remove(key)
        if not selected:
            return None
        private_index = self.directory / ('candidate-index-' + uuid.uuid4().hex)
        self.git('read-tree', self.head, index=private_index, private=True)
        changes = []
        for name in selected:
            value = contents[name]
            if value is None:
                changes.append(b'0 ' + b'0' * len(self.head) + b'\t' + os.fsencode(name) + b'\0')
            else:
                content, mode = value
                oid = self.git('hash-object', '-w', '--stdin', data=content, private=True).strip()
                changes.append(f'{mode:o} '.encode() + oid + b'\t' + os.fsencode(name) + b'\0')
        changes = b''.join(changes)
        self.git('update-index', '-z', '--index-info', data=changes, index=private_index, private=True)
        tree = self._oid(self.git('write-tree', index=private_index, private=True))
        old_head = self.head
        new = self._oid(self.git('commit-tree', tree, '-p', old_head,
                                data=(message + '\n').encode('utf-8'), private=True))
        parents = self.git('rev-list', '--parents', '-n', '1', new, private=True).split()
        if parents != [new.encode(), old_head.encode()]:
            raise ReviewedGitError('Publication commit is not the exact single-parent candidate.')
        # Bring only the candidate's new objects back; this does not update refs.
        pack = self.git('pack-objects', '--stdout', '--revs',
                        data=(new + '\n^' + old_head + '\n').encode(), private=True)
        self.git('index-pack', '--stdin', data=pack)
        new_real_index = self.directory / ('real-index-' + uuid.uuid4().hex)
        with self._source_locks():
            self._check_source()
            if self.index_bytes is not None:
                safe_io.write_bytes(new_real_index, self.index_bytes, exclusive=True)
            else:
                self.git('read-tree', old_head, index=new_real_index)
            # A copied split index points at sharedindex files relative to its
            # location. Refuse this uncommon layout instead of losing entries.
            if self.git('rev-parse', '--shared-index-path').strip():
                raise ReviewedGitError('Split indexes are not supported for automatic Git publication.')
            self.git('update-index', '-z', '--index-info', data=changes, index=new_real_index)
            index_bytes = safe_io.read_bytes(new_real_index)
            def publish_index():
                # update HEAD prepares a transaction locking both HEAD and its
                # actual branch. Check the symbolic identity AFTER preparation,
                # not merely the equal commit value of two different branches.
                self._check_source()
                safe_io.atomic_write(self.index_path, index_bytes)
            try:
                self.git('update-ref', '-m', 'ARQUILO reviewed output', '--stdin',
                    data=f'start\nupdate HEAD {new} {old_head}\nprepare\n'.encode(),
                    prepared=publish_index)
            except BaseException as exc:
                # Restore only our exact index bytes, under our still-held
                # index lock, if Git proves its reference update did not occur.
                # An ambiguous result is retained for explicit owner recovery.
                try:
                    unchanged_ref = (self._oid(self.git('rev-parse', 'HEAD')) == old_head
                        and self.git('symbolic-ref', '-q', 'HEAD').strip().decode() == self.branch)
                    if unchanged_ref and self._index_bytes() == index_bytes and self.index_bytes is not None:
                        safe_io.atomic_write(self.index_path, self.index_bytes)
                except Exception:
                    pass  # Preserve the original error and complete private index snapshots.
                raise ReviewedGitError(f'Git transaction failed; candidate {new} and index recovery files retained. Inspect local HEAD/index before continuing: {exc}') from exc
            self.head = new
            self.initial_index = self.git('ls-files', '--stage', '-z')
            self.index_bytes = index_bytes
            for name in selected:
                self.baseline[name] = contents[name]
                if contents[name] is not None:
                    self.modes[name] = contents[name][1]
        if self.push:
            try:
                self._check_push_destination()
                # Use an explicit expected OID, never a writable local tracking
                # ref. Even a fast-forward remote advance must not be overwritten.
                if self._remote_head() != old_head:
                    raise ReviewedGitError('Remote branch changed since the review candidate was selected.')
                self.git('push', '--porcelain', '--no-follow-tags', '--no-verify',
                    '--recurse-submodules=no', '--force-with-lease=' + self.remote_branch + ':' + old_head,
                    '--', os.fsdecode(self.push_destination), new + ':' + self.remote_branch, private=True)
            except ReviewedGitError as exc:
                raise ReviewedGitError(f'Local reviewed commit {new} retained; push was refused or its result is uncertain. Do not retry blindly: {exc}') from exc
        return {'commit': new, 'paths': selected, 'pushed': self.push,
                'review_snapshot': candidate.token['sha256'], 'parent': old_head}
