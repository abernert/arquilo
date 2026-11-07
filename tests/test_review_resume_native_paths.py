#!/usr/bin/env python3
"""Canonical native recovery paths without resolving away no-follow checks."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review_resume as recovery
import safe_io
import test_review_resume as legacy
import test_review_resume_network as network


class CheckedPathTests(unittest.TestCase):
    def test_no_follow_check_precedes_canonicalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'capture'
            path.mkdir()
            with patch.object(safe_io, 'check_path', wraps=safe_io.check_path) as checked:
                self.assertEqual(recovery._checked_path(path), path.resolve(strict=True))
            self.assertEqual(checked.call_count, 2)
            self.assertEqual(checked.call_args_list[0].args, (path,))
            self.assertEqual(checked.call_args_list[1].args, (path.resolve(strict=True),))

    def test_unsafe_input_is_refused_before_resolve(self):
        path = Path('unsafe-input')
        with patch.object(safe_io, 'check_path', side_effect=safe_io.UnsafePathError('linked')), \
                patch.object(Path, 'resolve', side_effect=AssertionError('resolved unsafe path')):
            with self.assertRaises(recovery.RecoveryRefused):
                recovery._checked_path(path)


def short_path(path: Path) -> Path:
    """Request an actual native alias, not a fabricated Windows path."""
    from ctypes import wintypes
    get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    get_short.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_short.restype = wintypes.DWORD
    needed = get_short(str(path), None, 0)
    if not needed:
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_unicode_buffer(needed)
    if not get_short(str(path), buf, needed):
        raise ctypes.WinError(ctypes.get_last_error())
    alias = Path(buf.value)
    if alias == path.resolve(strict=True):
        raise unittest.SkipTest('This volume does not supply an 8.3 alias for the fixture')
    return alias


@unittest.skipUnless(os.name == 'nt', 'Native Windows short-name aliases')
class WindowsLegacyAliasTests(legacy.Fixture):
    def test_short_capture_and_workspace_still_bind(self):
        evidence = recovery.load_verified_recovery(short_path(self.capture), short_path(self.work), '2')
        self.assertEqual(evidence.capture_dir, self.capture.resolve(strict=True))
        self.assertEqual(evidence.workdir, self.work.resolve(strict=True))


# Do not subclass the archive *test* classes here: that would collect the
# entire suite a second time. Reuse only the fixture setup and helper methods.
@unittest.skipUnless(os.name == 'nt', 'Native Windows short-name aliases')
class WindowsExternalAliasTests(unittest.TestCase):
    def setUp(self):
        # The superclass method in ExternalArchiveTests requires its original
        # MRO, so construct and register a real fixture instead of rebinding it.
        self.fixture = network.ExternalArchiveTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_short_external_inputs_match_long_record_paths(self):
        f = self.fixture
        evidence = recovery.load_verified_recovery(short_path(f.capture), short_path(f.work), '2',
            todo_file=short_path(f.todo), state_root=short_path(f.root))
        self.assertEqual(evidence.capture_dir, f.capture.resolve(strict=True))

    def test_short_task_log_record_matches_canonical_capture(self):
        f = self.fixture
        f.run_info['tasks'] = [str(short_path(f.capture.parent / 'task_log.json'))]
        f.write_run()
        evidence = f.recover()
        self.assertEqual(evidence.capture_dir, f.capture.resolve(strict=True))


if __name__ == '__main__':
    unittest.main()
