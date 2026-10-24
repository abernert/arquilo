# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Native snapshot/lock races for issues #32 and #34; no model calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import controller_state as state
import project_logs as logs
import safe_io
from execution_budget import CallBudget


class StateConcurrencyRepairs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='arquilo-state-repairs-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / 'work'
        self.work.mkdir()
        self.root = self.base / 'private'
        self.root.mkdir(mode=0o700)
        self.todo = self.work / 'tasks.md'
        self.todo.write_text('1. ***TASK***: Create result.txt.\n', encoding='utf-8')

    def test_snapshot_delete_sharing_is_read_only(self):
        p = self.root / 'data.json'
        p.write_bytes(b'{}')
        for mode in ('w', 'wb', 'a+b', 'r+b', 'xb'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                with safe_io.open_file(p, mode, share_delete=True):
                    pass
        with self.assertRaises(ValueError):
            with safe_io.open_file(p, 'rb', shared=True, share_delete=True):
                pass
        self.assertEqual(p.read_bytes(), b'{}')

    def test_open_snapshot_survives_atomic_replacement(self):
        p = self.root / 'data.json'
        p.write_bytes(b'{"generation":1}')
        with safe_io.open_file(p, 'rb', share_delete=True) as snapshot:
            safe_io.atomic_write(p, b'{"generation":2}')
            self.assertEqual(snapshot.read(), b'{"generation":1}')
        self.assertEqual(p.read_bytes(), b'{"generation":2}')

    @unittest.skipUnless(os.name == 'nt', 'native Windows sharing contract')
    def test_default_reader_still_blocks_delete_and_snapshot_blocks_inplace_write(self):
        p = self.root / 'data.json'
        p.write_bytes(b'original')
        with safe_io.open_file(p, 'rb'):
            with self.assertRaises(OSError):
                safe_io.atomic_write(p, b'replacement')
        self.assertEqual(p.read_bytes(), b'original')
        with safe_io.open_file(p, 'rb', share_delete=True):
            with self.assertRaises(OSError):
                safe_io.write_bytes(p, b'inplace')
        self.assertEqual(p.read_bytes(), b'original')

    def test_snapshot_keeps_link_and_size_boundaries(self):
        victim = self.base / 'victim'
        victim.write_bytes(b'{}')
        hard = self.root / 'hard.json'
        os.link(victim, hard)
        with self.assertRaises(safe_io.UnsafePathError):
            state._private_metadata(hard)
        hard.unlink()
        link = self.root / 'link.json'
        try:
            link.symlink_to(victim)
        except (OSError, NotImplementedError):
            link = None
        if link is not None:
            with self.assertRaises((OSError, safe_io.UnsafePathError)):
                state._private_metadata(link)
        large = self.root / 'large.json'
        large.write_bytes(b'{"x":"' + b'x'*65536 + b'"}')
        self.assertEqual(state._private_metadata(large), {})
        self.assertEqual(victim.read_bytes(), b'{}')

    def test_legacy_reader_and_registry_writer_overlap_without_losing_plans(self):
        first = state.state_directory(self.work, self.todo, self.root)
        logs.project_logs(first, self.work, self.todo, 'pilot')
        second_todo = self.work / 'second.md'
        second_todo.write_bytes(self.todo.read_bytes())
        second = state.state_directory(self.work, second_todo, self.root)
        budget = CallBudget(first / 'call_budgets' / 'task_1', 2, '1')
        budget.consume('1', 'test')
        opened, release = threading.Event(), threading.Event()
        original = safe_io.open_file
        reader_id = [None]

        class HeldReader:
            def __init__(self, stream):
                self.stream = stream
            def read(self, n=-1):
                opened.set()
                if not release.wait(10):
                    raise TimeoutError('Writer did not release metadata reader')
                return self.stream.read(n)

        @contextmanager
        def observed(path, *args, **kwargs):
            with original(path, *args, **kwargs) as stream:
                if Path(path).name == 'projects.json' and threading.get_ident() == reader_id[0]:
                    yield HeldReader(stream)
                else:
                    yield stream

        def read_hint():
            reader_id[0] = threading.get_ident()
            return state._legacy_identity_hint(first)

        with patch.object(safe_io, 'open_file', side_effect=observed):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(read_hint)
                try:
                    self.assertTrue(opened.wait(10), 'Reader did not open registry')
                    logs.project_logs(second, self.work, second_todo, 'pilot')
                finally:
                    release.set()
                hint = future.result(timeout=10)
        self.assertEqual(hint['todo'], str(self.todo))
        registry = json.loads((self.root / 'projects.json').read_text())
        record = json.loads((self.root / 'pilot' / 'project.json').read_text())
        self.assertEqual(set(registry['plans']), {first.name, second.name})
        self.assertEqual(set(record['plans']), {first.name, second.name})
        self.assertEqual(budget.snapshot()['used'], 1)

    @unittest.skipIf(os.name == 'nt', 'POSIX anchored create/open algorithm')
    def test_shared_lock_first_open_uses_exclusive_create(self):
        original = os.open
        seen = []
        def observed(path, flags, *args, **kwargs):
            if path == 'identity.lock':
                seen.append(flags)
            return original(path, flags, *args, **kwargs)
        with patch.object(safe_io.os, 'open', side_effect=observed):
            with safe_io.open_file(self.root / 'identity.lock', 'a+b', shared=True):
                pass
        self.assertEqual(len(seen), 2)
        self.assertFalse(seen[0] & os.O_CREAT)
        self.assertTrue(seen[1] & os.O_CREAT and seen[1] & os.O_EXCL)
        self.assertTrue(all(flags & os.O_NOFOLLOW for flags in seen))

    @unittest.skipIf(os.name == 'nt', 'POSIX competing exclusive creator')
    def test_shared_lock_competing_creator_opens_same_inode(self):
        p = self.root / 'identity.lock'
        original = os.open
        created = []
        def observed(path, flags, *args, **kwargs):
            if path == p.name and flags & os.O_EXCL:
                fd = original(path, flags, *args, **kwargs)
                created.append(os.fstat(fd).st_ino)
                os.close(fd)
                raise FileExistsError(errno.EEXIST, 'competing creator', path)
            return original(path, flags, *args, **kwargs)
        with patch.object(safe_io.os, 'open', side_effect=observed):
            with safe_io.open_file(p, 'a+b', shared=True) as stream:
                self.assertEqual(os.fstat(stream.fileno()).st_ino, created[0])
        self.assertEqual(p.stat().st_ino, created[0])

    @unittest.skipIf(os.name == 'nt', 'POSIX fail-closed lock race')
    def test_missing_after_competing_creation_is_not_silently_recreated(self):
        original = os.open
        calls = []
        def observed(path, flags, *args, **kwargs):
            if path == 'identity.lock':
                calls.append(flags)
                if flags & os.O_EXCL:
                    raise FileExistsError(errno.EEXIST, 'competing creator', path)
                raise FileNotFoundError(errno.ENOENT, 'removed lock', path)
            return original(path, flags, *args, **kwargs)
        with patch.object(safe_io.os, 'open', side_effect=observed):
            with self.assertRaises(FileNotFoundError):
                with safe_io.open_file(self.root / 'identity.lock', 'a+b', shared=True):
                    pass
        self.assertEqual(len(calls), 3)
        self.assertFalse(calls[-1] & os.O_CREAT)

    def test_shared_lock_rejects_hardlink(self):
        original = self.root / 'original'
        original.write_bytes(b'keep')
        os.link(original, self.root / 'identity.lock')
        with self.assertRaises(safe_io.UnsafePathError):
            with state._state_allocation_lock(self.root):
                self.fail('Unsafe lock accepted')
        self.assertEqual(original.read_bytes(), b'keep')

    def test_concurrent_alias_allocation_repeated_native(self):
        script = '''
import json, pathlib, sys, time
from controller_state import state_directory, PlanIntegrityError
work, todo, root, ready, start = map(pathlib.Path, sys.argv[1:])
ready.write_text('ready')
deadline = time.monotonic() + 20
while not start.exists():
    if time.monotonic() >= deadline: raise RuntimeError('barrier timeout')
    time.sleep(.005)
try: result = {'state': str(state_directory(work, todo, root))}
except PlanIntegrityError as exc: result = {'error': str(exc)}
print(json.dumps(result))
'''
        for n in range(8):
            with self.subTest(iteration=n):
                root = self.root / ('case-' + str(n))
                root.mkdir(mode=0o700)
                start = self.base / ('start-' + str(n))
                processes, readies = [], []
                try:
                    for k, todo in enumerate((self.todo, self.work / '..' / self.work.name / self.todo.name)):
                        ready = self.base / f'ready-{n}-{k}'
                        readies.append(ready)
                        processes.append(subprocess.Popen([sys.executable, '-B', '-c', script,
                            str(self.work), str(todo), str(root), str(ready), str(start)],
                            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                    import time
                    deadline = time.monotonic() + 20
                    while not all(p.exists() for p in readies):
                        self.assertLess(time.monotonic(), deadline, 'Children not ready')
                        time.sleep(.005)
                    start.touch()
                    values = []
                    for process in processes:
                        stdout, stderr = process.communicate(timeout=20)
                        self.assertEqual(process.returncode, 0, stderr)
                        values.append(json.loads(stdout))
                    self.assertEqual(sum('state' in x for x in values), 1, values)
                    self.assertEqual(sum('error' in x for x in values), 1, values)
                    self.assertEqual(len([p for p in root.iterdir() if p.is_dir() and len(p.name)==64]), 1)
                finally:
                    for process in processes:
                        if process.poll() is None: process.kill()
                        process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
