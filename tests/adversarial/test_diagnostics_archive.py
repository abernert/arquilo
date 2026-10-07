"""Synthetic diagnostic boundaries; no provider or external state access."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, UTC
import io
import json
from pathlib import Path
import tempfile
import unittest

import codex_transport
import project_logs
import runtime_logging


class DiagnosticArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="arquilo-diagnostic-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def test_worker_terminal_controls_are_escaped_but_source_is_retained(self):
        pretty = self.base / "pretty.log"
        raw = self.base / "raw.log"
        result = codex_transport.RunResult()
        hostile = "safe\x1b[2J\r[ok] forged\x07"
        with redirect_stdout(io.StringIO()) as terminal:
            codex_transport.handle_event(
                {"type": "item.completed", "item": {"type": "agent_message", "text": hostile}},
                result, pretty, raw, console_todo_id="10", timestamp=lambda: "T",
            )
        displayed = terminal.getvalue()
        self.assertNotIn("\x1b", displayed)
        self.assertNotIn("\r", displayed)
        self.assertNotIn("\x07", displayed)
        self.assertIn(r"\x1b", displayed)
        self.assertIn(r"\x0d", displayed)
        self.assertIn(r"\x07", displayed)
        self.assertIn("[10]", displayed)
        self.assertEqual(result.assistant_messages, [hostile])
        self.assertEqual(json.loads(raw.read_text(encoding="utf-8"))["item"]["text"], hostile)
        self.assertIn(hostile.encode("utf-8"), pretty.read_bytes())

    def test_plain_worker_message_remains_readable(self):
        result = codex_transport.RunResult()
        with redirect_stdout(io.StringIO()) as terminal:
            codex_transport.handle_event(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "ordinary answer"}},
                result, self.base / "pretty.log", self.base / "raw.log",
                console_todo_id="10", timestamp=lambda: "T",
            )
        self.assertIn("[10] [agent_message] ordinary answer", terminal.getvalue())
        self.assertEqual(result.assistant_messages, ["ordinary answer"])

    def test_non_ascii_c1_control_is_escaped_in_console_only(self):
        hostile = "before\u0085after"
        result = codex_transport.RunResult()
        raw = self.base / "raw-c1.log"
        with redirect_stdout(io.StringIO()) as terminal:
            codex_transport.handle_event(
                {"type": "item.completed", "item": {"type": "agent_message", "text": hostile}},
                result, self.base / "pretty-c1.log", raw,
                console_todo_id="10", timestamp=lambda: "T",
            )
        self.assertNotIn("\u0085", terminal.getvalue())
        self.assertIn(r"\x85", terminal.getvalue())
        self.assertEqual(result.assistant_messages, [hostile])
        self.assertEqual(json.loads(raw.read_text(encoding="utf-8"))["item"]["text"], hostile)

    def test_prompt_canary_is_intentionally_archived_but_env_canary_is_not(self):
        prompt_canary = "SYNTHETIC_PROMPT_CANARY_10"
        env_canary = "SYNTHETIC_AUTH_CANARY_10"
        proxy_canary = "http://synthetic.invalid:8080"
        work = self.base / "work"
        work.mkdir()
        request = codex_transport.CodexExecRequest(
            prompt=f"Use {prompt_canary}", cwd=work,
            env={"SYNTHETIC_AUTH_TOKEN": env_canary,
                 "HTTPS_PROXY": proxy_canary},
            raw_log=self.base / "logs" / "raw.jsonl",
            pretty_log=self.base / "logs" / "pretty.log",
        )
        result = codex_transport.RunResult()
        archived_prompt = codex_transport._prepare_capture(request, result)
        self.assertEqual(archived_prompt, (f"Use {prompt_canary}").encode())
        self.assertEqual((result.capture_dir / "prompt.utf8").read_bytes(), archived_prompt)
        for path in result.capture_dir.iterdir():
            if path.is_file():
                self.assertNotIn(env_canary.encode(), path.read_bytes(), str(path))
                self.assertNotIn(proxy_canary.encode(), path.read_bytes(), str(path))

    def test_same_named_external_inputs_get_distinct_byte_exact_copies(self):
        workspace = self.base / "work"
        workspace.mkdir()
        log_dir = self.base / "logs"
        first = self.base / "one" / "shared.md"
        second = self.base / "two" / "shared.md"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        records = runtime_logging.copy_log_files(log_dir, "inputs", [first, second], workspace=workspace)
        self.assertEqual([r["status"] for r in records], ["copied", "copied"])
        self.assertEqual([Path(r["path"]).read_bytes() for r in records], [b"one", b"two"])
        self.assertNotEqual(records[0]["path"], records[1]["path"])

    def test_run_directory_collision_keeps_old_record_and_pointer(self):
        root = self.base / "private"
        work = self.base / "work"
        work.mkdir()
        todo = work / "tasks.md"
        todo.write_text("1. ***Task***: Check.\n", encoding="utf-8")
        project = project_logs.ProjectLogs("audit", root / "audit", root / "state")
        started = datetime(2026, 10, 7, tzinfo=UTC)
        first = project.new_run(started, run_id="same", workspace=work, todo=todo)
        marker = first / "sentinel"
        marker.write_bytes(b"retained")
        second = project.new_run(started, run_id="same", workspace=work, todo=todo)
        self.assertNotEqual(first, second)
        self.assertEqual(marker.read_bytes(), b"retained")
        self.assertEqual(json.loads((first / "run.json").read_text())["run_id"], "same")
        self.assertEqual(json.loads((second / "run.json").read_text())["run_id"], "same")
        self.assertEqual((project.directory / "latest-run.txt").read_text().strip(),
                         "runs/" + second.name)


if __name__ == "__main__":
    unittest.main()
