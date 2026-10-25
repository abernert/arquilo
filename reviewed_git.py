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
import git_publication_state as publication_state
from process_tree import ProcessTree, InterruptiblePipe

MAX_PACK_BYTES = 128 * 1024 * 1024
PACK_TIMEOUT_SECONDS = 60
from controller_state import _overlaps_workspace
from host_launcher import launcher_environment, resolve_executable


class ReviewedGitError(RuntimeError):
    pass


class PublicationUnavailable(ReviewedGitError):
    """A verified review cannot currently be persisted for optional publication."""


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
        # Preparing optional publication must not transfer potentially large Git
        # history or contact the remote before ordinary production and review.
        self._publication_ready = False
        self.remote = self.remote_branch = self.push_destination = None
        if self.push:
            self.remote = self.git('config', '--get', 'branch.' + self.branch[11:] + '.remote').strip().decode()
            self.remote_branch = self.git('config', '--get', 'branch.' + self.branch[11:] + '.merge').strip().decode()
            if not self.remote or self.remote == '.' or not self.remote_branch.startswith('refs/heads/'):
                raise ReviewedGitError('--git-push requires a configured external remote branch.')
            self.git('check-ref-format', self.remote_branch)
            self.push_destination = self._push_destination()
            self._validate_destination(self.push_destination)
        self._requests: dict[str, bytes] = {}
        self._accepted: set[bytes] = set()
        self._candidate_publications: dict[bytes, str] = {}
        self.last_publication = None

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
        # Private state paths include plan/run identities and can exceed MAX_PATH.
        # This is a per-command override, not a mutation of the user's Git config.
        command = [self.executable, '-c', 'core.longpaths=true', '-c', 'core.fsmonitor=false',
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
            # Git validates the literal GIT_DIR length before long-path expansion.
            # Resolve a short relative name from the pinned private parent, not
            # from the task workspace; do not relocate state or alter host config.
            command += ['--git-dir=' + self.publication.relative_to(self.directory).as_posix()]
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
        # The review itself does not depend on the current index or transport.
        # Publication later compares them with the pinned pre-task baseline.
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
        key = git_snapshot.canonical_bytes({'request': request, 'token': token})
        publication_id = 'publication-' + hashlib.sha256(key).hexdigest()[:32]
        record = {'schema_version': 'arquilo.git_publication.v2', 'id': publication_id,
            'workspace': str(self.workspace), 'session': self.directory.name,
            'request': candidate.request, 'token': candidate.token,
            'branch': self.branch, 'parent': self.head, 'object_format': self.object_format,
            'paths': list(self.paths), 'modes': dict(self.modes),
            'baseline': {name: publication_state.fingerprint(value) for name, value in self.baseline.items()},
            'before_index_sha256': None if self.index_bytes is None else git_snapshot.digest(self.index_bytes),
            'before_listing_sha256': git_snapshot.digest(self.initial_index), 'after_index_sha256': None,
            'push': self.push, 'remote': self.remote, 'remote_branch': self.remote_branch,
            'destination_sha256': git_snapshot.digest(self.push_destination) if self.push else None,
            'status': 'accepted', 'commit': None, 'tree': None, 'selected_paths': [],
            'message': None, 'error_type': None, 'supersedes': []}
        try:
            record['supersedes'] = publication_state.eligible_blocks(self.state, self.workspace, record)
            if self.index_bytes is not None:
                safe_io.write_bytes(self.directory / (publication_id + '.index.before'), self.index_bytes, exclusive=True)
            publication_state.save(record, self.state, self.workspace, create=True)
        except FileExistsError as exc:
            raise ReviewedGitError('Publication acceptance already exists; use its recorded identity.') from exc
        except OSError as exc:
            raise PublicationUnavailable('Cannot persist accepted Git publication; ordinary review remains separate.') from exc
        self._accepted.add(key)
        self._candidate_publications[key] = publication_id
        self.last_publication = publication_state.summary(record)
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

    def _save_publication(self, record):
        publication_state.save(record, self.state, self.workspace)
        self.last_publication = publication_state.summary(record)

    def _publication_failed(self, record, exc):
        # Never store transport stderr, credentials or arbitrary exception text.
        record['error_type'] = type(exc).__name__
        self.last_publication = publication_state.summary(record)
        try:
            publication_state.save(record, self.state, self.workspace)
        except (OSError, ValueError):
            pass  # Keep the original failure and the last durable phase.

    def _check_publication_stop(self):
        if os.path.lexists(self.workspace / 'process_stop'):
            raise ReviewedGitError('process_stop blocks a new Git publication operation.')

    def _ensure_history(self, parent):
        if self._publication_ready:
            return
        try:
            present = self.git('cat-file', '-t', parent, private=True).strip() == b'commit'
        except ReviewedGitError:
            present = False
        if not present:
            # No fetch/upload-pack from mutable workspace configuration.
            pack = self.git('pack-objects', '--stdout', '--revs', data=(parent + '\n').encode())
            self.git('index-pack', '--stdin', data=pack, private=True)
        self._publication_ready = True

    def _saved_index(self, record, kind):
        expected = record[kind + '_index_sha256']
        value = git_snapshot.read_regular(self.directory / (record['id'] + '.index.' + kind),
                                         limit=64 * 1024 * 1024)
        if expected is None:
            if value is not None:
                raise ReviewedGitError('Unexpected private publication index snapshot.')
            return None
        if value is None or git_snapshot.digest(value[0]) != expected:
            raise ReviewedGitError('Private publication index snapshot missing or changed.')
        return value[0]

    def _save_index(self, record, kind, data):
        destination = self.directory / (record['id'] + '.index.' + kind)
        try:
            safe_io.write_bytes(destination, data, exclusive=True)
        except FileExistsError:
            existing = git_snapshot.read_regular(destination, limit=64 * 1024 * 1024)
            if existing is None or existing[0] != data:
                raise ReviewedGitError('Private publication index contradicts prepared recovery.')
        record[kind + '_index_sha256'] = git_snapshot.digest(data)

    def _prepare_publication(self, record, contents):
        selected = [name for name in self.paths
                    if publication_state.fingerprint(contents[name]) != record['baseline'][name]]
        if record['selected_paths'] and selected != record['selected_paths']:
            raise ReviewedGitError('Prepared selection contradicts the accepted snapshot.')
        record['selected_paths'] = selected
        if not selected:
            record.update(status='noop', error_type=None)
            self._save_publication(record)
            return False
        self._ensure_history(record['parent'])
        private_index = self.directory / ('candidate-index-' + uuid.uuid4().hex)
        self.git('read-tree', record['parent'], index=private_index, private=True)
        changes = []
        for name in selected:
            value = contents[name]
            if value is None:
                changes.append(b'0 ' + b'0' * len(record['parent']) + b'\t' + os.fsencode(name) + b'\0')
            else:
                content, mode = value
                oid = self.git('hash-object', '-w', '--stdin', data=content, private=True).strip()
                changes.append(f'{mode:o} '.encode() + oid + b'\t' + os.fsencode(name) + b'\0')
        changes = b''.join(changes)
        self.git('update-index', '-z', '--index-info', data=changes, index=private_index, private=True)
        tree = self._oid(self.git('write-tree', index=private_index, private=True))
        if record['tree'] is not None and tree != record['tree']:
            raise ReviewedGitError('Prepared Git tree is not the reviewed selected content.')
        if record['commit'] is None:
            self._check_publication_stop()
            record['commit'] = self._oid(self.git('commit-tree', tree, '-p', record['parent'],
                data=(record['message'] + '\n').encode('utf-8'), private=True))
            record['tree'] = tree
            self._save_publication(record)  # Pin the exact SHA before any local reference changes.
        parents = self.git('rev-list', '--parents', '-n', '1', record['commit'], private=True).split()
        actual_tree = self._oid(self.git('rev-parse', record['commit'] + '^{tree}', private=True))
        if parents != [record['commit'].encode(), record['parent'].encode()] or actual_tree != tree:
            raise ReviewedGitError('Publication commit is not the exact single-parent reviewed candidate.')
        # Copy objects only, never refs; publication is still recoverably pending.
        pack = self.git('pack-objects', '--stdout', '--revs',
            data=(record['commit'] + '\n^' + record['parent'] + '\n').encode(), private=True)
        self.git('index-pack', '--stdin', data=pack)
        if record['after_index_sha256'] is None:
            before = self._saved_index(record, 'before')
            new_real_index = self.directory / ('real-index-' + uuid.uuid4().hex)
            if before is not None:
                safe_io.write_bytes(new_real_index, before, exclusive=True)
            else:
                self.git('read-tree', record['parent'], index=new_real_index)
            if self.git('rev-parse', '--shared-index-path').strip():
                raise ReviewedGitError('Split indexes are not supported for automatic Git publication.')
            self.git('update-index', '-z', '--index-info', data=changes, index=new_real_index)
            after = git_snapshot.read_regular(new_real_index, limit=64 * 1024 * 1024)
            if after is None:
                raise ReviewedGitError('Prepared publication index disappeared.')
            self._save_index(record, 'after', after[0])
            record['status'] = 'prepared'
            self._save_publication(record)
        else:
            self._saved_index(record, 'after')
        return True

    def _apply_local_publication(self, record, contents):
        parent, new = record['parent'], record['commit']
        after = self._saved_index(record, 'after')
        branch = self.git('symbolic-ref', '-q', 'HEAD').strip().decode()
        head = self._oid(self.git('rev-parse', 'HEAD'))
        current = self._index_bytes()
        current_hash = None if current is None else git_snapshot.digest(current)
        if branch != record['branch']:
            raise ReviewedGitError('Publication source branch changed; no automatic recovery.')
        if head == new and current_hash == record['after_index_sha256']:
            pass  # A prior call completed the local transaction; do not create another commit.
        elif head == parent and current_hash == record['before_index_sha256']:
            listing = self.git('ls-files', '--stage', '-z')
            if git_snapshot.digest(listing) != record['before_listing_sha256']:
                raise ReviewedGitError('Git index changed outside ARQUILO; no automatic recovery.')
            self.head, self.index_bytes, self.initial_index = parent, current, listing
            self._check_live_selection(contents)
            self._check_publication_stop()
            with self._source_locks():
                self._check_source()
                def publish_index():
                    self._check_publication_stop()
                    self._check_source()
                    safe_io.atomic_write(self.index_path, after)
                try:
                    self._check_publication_stop()
                    self.git('update-ref', '-m', 'ARQUILO reviewed output', '--stdin',
                        data=f'start\nupdate HEAD {new} {parent}\nprepare\n'.encode(),
                        prepared=publish_index)
                except BaseException as exc:
                    try:
                        unchanged_ref = (self._oid(self.git('rev-parse', 'HEAD')) == parent
                            and self.git('symbolic-ref', '-q', 'HEAD').strip().decode() == self.branch)
                        if unchanged_ref and self._index_bytes() == after and current is not None:
                            safe_io.atomic_write(self.index_path, current)
                    except Exception:
                        pass
                    raise ReviewedGitError('Git transaction result is uncertain; publication ' + record['id']
                        + ' retains the exact candidate and index snapshots for explicit retry.') from exc
        else:
            raise ReviewedGitError('Git HEAD/index differ from both verified publication states; inspect before retrying.')
        self.head = new
        self.index_bytes = after
        self.initial_index = self.git('ls-files', '--stage', '-z')
        for name in record['selected_paths']:
            self.baseline[name] = contents[name]
            if contents[name] is not None:
                self.modes[name] = contents[name][1]
        record.update(status='push_pending' if self.push else 'published', error_type=None)
        self._save_publication(record)

    def _verify_prepared_publication(self, record, contents):
        """Reconcile an existing candidate without writing objects or an index."""
        self._saved_index(record, 'after')
        parents = self.git('rev-list', '--parents', '-n', '1', record['commit'], private=True).split()
        tree = self._oid(self.git('rev-parse', record['commit'] + '^{tree}', private=True))
        if parents != [record['commit'].encode(), record['parent'].encode()] or tree != record['tree']:
            raise ReviewedGitError('Prepared publication commit identity changed.')
        def entries(revision):
            result = {}
            for row in self.git('ls-tree', '-rz', revision, private=True).split(b'\0'):
                if row:
                    header, name = row.split(b'\t', 1)
                    result[os.fsdecode(name)] = tuple(header.split(b' '))
            return result
        expected = entries(record['parent'])
        for name in record['selected_paths']:
            value = contents[name]
            if value is None:
                expected.pop(name, None)
            else:
                data, mode = value
                oid = self.git('hash-object', '--stdin', data=data, private=True).strip()
                expected[name] = (f'{mode:o}'.encode(), b'blob', oid)
        selected = [name for name in self.paths
                    if publication_state.fingerprint(contents[name]) != record['baseline'][name]]
        if selected != record['selected_paths'] or entries(record['commit']) != expected:
            raise ReviewedGitError('Prepared Git commit differs from the accepted selected outputs.')

    def _finish_push(self, record):
        self._check_push_destination()
        remote_head = self._remote_head()
        if remote_head == record['commit']:
            record.update(status='published', error_type=None)
            self._save_publication(record)
            return
        if remote_head != record['parent']:
            raise ReviewedGitError('Remote branch changed since the review candidate was selected.')
        self._check_source()
        self._check_publication_stop()
        self.git('push', '--porcelain', '--no-follow-tags', '--no-verify',
            '--recurse-submodules=no', '--force-with-lease=' + self.remote_branch + ':' + record['parent'],
            '--', os.fsdecode(self.push_destination), record['commit'] + ':' + self.remote_branch, private=True)
        if self._remote_head() != record['commit']:
            raise ReviewedGitError('Push completed without confirming the exact remote commit; retry reconciliation.')
        record.update(status='published', error_type=None)
        self._save_publication(record)

    def _publish(self, record, candidate):
        contents = candidate.contents()
        if record['status'] in {'published', 'noop'}:
            self.last_publication = publication_state.summary(record)
            return self.last_publication
        if record['status'] in {'accepted', 'preparing'}:
            self._check_source()
            self._check_live_selection(contents)
            self._check_publication_stop()
            record.update(status='preparing', error_type=None)
            self._save_publication(record)
            if self.push:
                remote_head = self._remote_head()
                if remote_head != record['parent'] and (record['commit'] is None or remote_head != record['commit']):
                    raise ReviewedGitError('--git-push requires the reviewed parent at the actual push destination; no unrelated commits are published.')
        if record['status'] in {'prepared', 'push_pending'}:
            self._verify_prepared_publication(record, contents)
        elif not self._prepare_publication(record, contents):
            return None
        if record['status'] != 'push_pending':
            self._apply_local_publication(record, contents)
        else:
            # Pin the expected local post-commit state. Read-only remote
            # reconciliation may succeed even if a later owner edit occurred;
            # a new push still requires _check_source() and a clear STOP gate.
            self.head = record['commit']
            self.index_bytes = self._saved_index(record, 'after')
            self.initial_index = self.git('ls-files', '--stage', '-z')
        if self.push:
            try:
                self._finish_push(record)
            except ReviewedGitError as exc:
                raise ReviewedGitError('Local reviewed commit ' + record['commit']
                    + ' retained; push was refused or its result is uncertain. Use git retry for publication '
                    + record['id'] + ' to reconcile the exact commit.') from exc
        return publication_state.summary(record)

    def commit(self, message: str, *, candidate: git_snapshot.ReviewedCandidate | None = None):
        if not isinstance(candidate, git_snapshot.ReviewedCandidate):
            raise ReviewedGitError('Git commit requires a controller-accepted pre-review snapshot.')
        key = git_snapshot.canonical_bytes({'request': candidate.request, 'token': candidate.token})
        if key not in self._accepted or candidate.request['binding']['parent'] != self.head:
            raise ReviewedGitError('Git review candidate is stale, foreign or already consumed.')
        publication_id = self._candidate_publications[key]
        with publication_state.lock(self.state, self.workspace):
            record = publication_state.load(self.state, self.workspace, publication_id)
            if record['request'] != candidate.request or record['token'] != candidate.token:
                raise ReviewedGitError('Publication receipt contradicts controller-accepted review.')
            self._accepted.remove(key)
            record['message'] = message
            try:
                result = self._publish(record, candidate)
                publication_state.resolve_blocks(self.state, self.workspace, publication_id)
                return result
            except BaseException as exc:
                self._publication_failed(record, exc)
                raise


def list_publications(state: Path, workspace: Path):
    """List private receipts by ID; never trust a workspace summary as authority."""
    return publication_state.list_records(Path(state), Path(workspace))


def record_publication_block(state: Path, workspace: Path, *, run, task, attempt,
                             paths, push, destination_sha256, branch, error):
    """Persist an unbound delivery obligation; never mint publication authority.

    The controller must call this before DONE and treat a write/validation
    failure as an authoritative state failure, not a memory-only warning.
    """
    state, workspace = Path(state), Path(workspace)
    with publication_state.lock(state, workspace):
        return publication_state.record_block(state, workspace, run=run, task=task,
            attempt=attempt, paths=paths, push=push, destination_sha256=destination_sha256,
            branch=branch, error=error)


def resolve_publication_blocks(state: Path, workspace: Path, publication_id: str):
    """Resolve only older obligations explicitly bound to a successful receipt."""
    state, workspace = Path(state), Path(workspace)
    with publication_state.lock(state, workspace):
        return publication_state.resolve_blocks(state, workspace, publication_id)


def _restore_publisher(record, workspace: Path, state: Path, executable=None):
    """Restore only publication state, without replaying production or review."""
    publisher = ReviewedGit.__new__(ReviewedGit)
    publisher.workspace = workspace.resolve()
    publisher.state = safe_io.lexical_path(state)
    publisher.paths = list(record['paths'])
    publisher.push = record['push']
    publisher.directory = publication_state.root(state, workspace) / record['session']
    publisher.empty = safe_io.check_path(publisher.directory / 'empty', missing_ok=False)
    try:
        publisher.executable = str(resolve_executable(executable or 'git',
            workspace=publisher.workspace, env=os.environ))
    except OSError as exc:
        raise ReviewedGitError('Git launcher unavailable during publication recovery.') from exc
    publisher.environment = launcher_environment(
        {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')},
        workspace=publisher.workspace, executable=publisher.executable)
    publisher.environment.update(GIT_LITERAL_PATHSPECS='1', GIT_OPTIONAL_LOCKS='0',
        GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
    publisher.git_directory = None
    publisher.publication = None
    publisher.identity = {}
    publisher.transport_config = []
    publisher._capture_host_transport_configuration()
    publisher.branch = record['branch']
    publisher.git('check-ref-format', publisher.branch)
    if Path(os.fsdecode(publisher.git('rev-parse', '--show-toplevel').strip())).resolve() != publisher.workspace:
        raise ReviewedGitError('Publication recovery requires the original repository root.')
    publisher.git_directory = safe_io.check_path(Path(os.fsdecode(
        publisher.git('rev-parse', '--absolute-git-dir').strip())), missing_ok=False)
    publisher.index_path = publisher._git_path('index')
    publisher.head_path = publisher._git_path('HEAD')
    publisher.head = record['parent']
    publisher.index_bytes = publisher._saved_index(record, 'before')
    publisher.initial_index = publisher.git('ls-files', '--stage', '-z')
    publisher.object_format = publisher.git('rev-parse', '--show-object-format').strip().decode()
    if publisher.object_format != record['object_format']:
        raise ReviewedGitError('Publication repository object format changed.')
    publisher.modes = dict(record['modes'])
    publisher.baseline = {name: None for name in publisher.paths}
    for field in ('name', 'email'):
        value = publisher.git('config', '--get', 'user.' + field, optional=True).strip()
        if value:
            publisher.identity[field] = value.decode('utf-8')
    publisher.publication = safe_io.check_path(publisher.directory / 'publication.git', missing_ok=False)
    publisher._publication_ready = False
    publisher.remote = record['remote']
    publisher.remote_branch = record['remote_branch']
    publisher.push_destination = None
    if publisher.push:
        publisher.git('check-ref-format', publisher.remote_branch)
        publisher.push_destination = publisher._push_destination()
        if git_snapshot.digest(publisher.push_destination) != record['destination_sha256']:
            raise ReviewedGitError('Git push destination changed outside ARQUILO; no recovery transport.')
        publisher._validate_destination(publisher.push_destination)
    publisher._requests = {}
    publisher._accepted = set()
    publisher._candidate_publications = {}
    publisher.last_publication = publication_state.summary(record)
    return publisher


def recover_publication(workspace: Path, state: Path, publication_id: str, executable=None):
    """Idempotent, model-free retry of one exact accepted publication receipt.

    A failed/uncertain push is reconciled against the pinned remote ref: the
    candidate means success, its parent permits retry of that same SHA, and any
    other head blocks publication. No task, model, Git reset or merge is run.
    """
    workspace, state = Path(workspace).resolve(), safe_io.lexical_path(Path(state))
    if isinstance(publication_id, str) and publication_id.startswith('obligation-'):
        publication_state.load_obligation(state, workspace, publication_id)
        raise ReviewedGitError('This publication obligation has no accepted immutable candidate. '
            'Explicitly reopen and adopt the owner task for a fresh reviewed attempt; git retry cannot authorize it.')
    publication_state.identifier(publication_id)
    with publication_state.lock(state, workspace):
        record = publication_state.load(state, workspace, publication_id)
        candidate = git_snapshot.ReviewedCandidate(record['request'], record['token'])
        candidate.contents()  # Even a retry cannot substitute later or forged bytes.
        if record['status'] in {'published', 'noop'}:
            publication_state.resolve_blocks(state, workspace, publication_id)
            return publication_state.summary(record)
        publisher = _restore_publisher(record, workspace, state, executable)
        if record['message'] is None:
            record['message'] = ('[run_todos:' + record['request']['binding']['run'] + '] '
                                 + record['request']['binding']['task'] + ' reviewed output')
        try:
            result = publisher._publish(record, candidate)
            publication_state.resolve_blocks(state, workspace, publication_id)
            return result if result is not None else publisher.last_publication
        except BaseException as exc:
            publisher._publication_failed(record, exc)
            raise
