# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Disposable controller fixture; no real Codex execution or host-state writes."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import autobuild
import run_todos


class IsolatedControllerCase(unittest.TestCase):
    """Keep workspace, controller state and possible victims in one disposable root."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="arquilo-adversarial-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.work = self.base / "workspace"
        self.work.mkdir()
        self.state_root = self.base / "controller-state"
        self.state_root.mkdir(mode=0o700)
        self.victims = self.base / "victims"
        self.victims.mkdir()
        self.todo = self.work / "tasks.md"

    def write_plan(self, text: str) -> None:
        self.todo.write_text(text, encoding="utf-8")

    def runner(self, **overrides):
        options = dict(
            todo_file=self.todo, workdir=self.work, max_depth=5, max_retries=1,
            start_id=None, stop_id=None, dry_run=False,
            dry_run_recorder=run_todos.DryRunRecorder(None),
            simulated_incomplete=set(), max_steps=3, sandbox="workspace-write",
            run_id=None, state_dir=self.state_root,
            process_stop_policy="controller-only", network_access=False,
        )
        options.update(overrides)
        runner = run_todos.TodoRunner(**options)
        self.addCleanup(runner.close)
        return runner

    @contextmanager
    def scratch(self):
        """A nested root for link/race inputs; remove it even on exceptions."""
        with tempfile.TemporaryDirectory(prefix="case-", dir=self.base) as name:
            yield Path(name)

    @contextmanager
    def fake_codex(self, dispatch):
        """Intercept the existing AutoBuild transport boundary, including Decide."""
        def invoke(**kwargs):
            self.assertTrue(Path(kwargs["cwd"]).resolve().is_relative_to(self.base))
            return dispatch(**kwargs)

        with patch.object(autobuild, "run_codex_exec_json", side_effect=invoke), \
             patch.object(autobuild, "run_semantic_decision",
                          side_effect=AssertionError("No live Decide call in adversarial tests")), \
             patch.object(autobuild, "_terminal_beep"), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield

    def assert_accepted_artifact(self, runner, *, plan: str, artifact: str, data: bytes):
        """Check physical output and external journal, independent of fake review text."""
        relative = Path(artifact)
        self.assertFalse(relative.is_absolute())
        self.assertNotIn("..", relative.parts)
        path = self.work / relative
        self.assertTrue(path.resolve().is_relative_to(self.base))
        self.assertTrue(path.is_file(), f"Missing artifact: {artifact}")
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.todo.read_text(encoding="utf-8"), plan)
        self.assertEqual(json.loads((runner.state_dir / "plan.json").read_text(
            encoding="utf-8"))["text"], plan)
        self.assertFalse(runner.state_dir.is_relative_to(self.work))
