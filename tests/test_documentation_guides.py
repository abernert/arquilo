# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline handbook checks; no model, remote service or shell example execution."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_todos
from runtime_profile import load_runtime_profile
from todo_lint import lint_todo_file


def without_fences(text: str) -> str:
    return re.sub(r"^(```|~~~)[^\n]*\n.*?^\1[^\n]*$", "", text, flags=re.M | re.S)


def anchors(text: str) -> set[str]:
    visible = without_fences(text)
    found = set(re.findall(r'<a\s+id="([^"]+)"\s*></a>', visible))
    for heading in re.findall(r"^#{1,6}\s+(.+)$", visible, flags=re.M):
        heading = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        found.add(heading)
    return found


def named_examples(text: str) -> dict[str, str]:
    pairs = re.findall(r"<!-- example: ([a-z0-9-]+) -->\s*```[^\n]*\n(.*?)\n```", text, flags=re.S)
    if len({name for name, _ in pairs}) != len(pairs):
        raise ValueError("Duplicate named documentation example")
    return dict(pairs)


class DocumentationGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "docs/guides/manifest.json").read_text(encoding="utf-8"))
        cls.package = json.loads((ROOT / "documents/lean_package.json").read_text(encoding="utf-8"))
        cls.guides = {g["path"]: (ROOT / g["path"]).read_text(encoding="utf-8")
                      for g in cls.manifest["guides"]}

    def test_inventory_and_runtime_baseline(self):
        self.assertEqual(self.manifest["schema_version"], "arquilo.documentation.v1")
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(self.manifest["runtime_version"], version)
        self.assertRegex(self.manifest["source_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual({(g["id"], g["language"]) for g in self.manifest["guides"]},
                         {("user", "de"), ("user", "en"), ("operator", "en"), ("technical", "en")})
        for path, text in self.guides.items():
            with self.subTest(path=path):
                self.assertIn(version, text)
                self.assertGreater(len(text.split()), 1500)

    def test_guides_and_examples_are_shipped(self):
        names = self.package["runtime_files"]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(self.package["runtime_file_count"], len(names))
        required = set(self.guides) | set(self.manifest["synthetic_examples"]) | {
            "docs/README.md", "docs/guides/manifest.json", "docs/guides/cli-reference.json"}
        self.assertTrue(required.issubset(names), sorted(required - set(names)))
        self.assertNotIn("tests/test_documentation_guides.py", names)

    def test_user_chapter_parity(self):
        for language in ("en", "de"):
            text = self.guides[f"docs/guides/user-guide.{language}.md"]
            actual = re.findall(r'<a id="([^"]+)"></a>', text)
            self.assertEqual(actual, self.manifest["user_chapters"])

    def test_user_operational_examples_are_identical(self):
        english = named_examples(self.guides["docs/guides/user-guide.en.md"])
        german = named_examples(self.guides["docs/guides/user-guide.de.md"])
        self.assertEqual(set(english), set(self.manifest["shared_user_examples"]))
        self.assertEqual(english, german)

    def test_packaged_documentation_links_and_guide_anchors(self):
        names = set(self.package["runtime_files"])
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            text = without_fences((ROOT / name).read_text(encoding="utf-8"))
            for target in re.findall(r"(?<!!)\[[^]\n]*\]\(([^)\s]+)\)", text):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc:
                    continue
                destination = ((ROOT / name).parent / unquote(parsed.path)).resolve() if parsed.path else ROOT / name
                with self.subTest(document=name, target=target):
                    self.assertTrue(destination.is_relative_to(ROOT))
                    self.assertTrue(destination.is_file())
                    relative = destination.relative_to(ROOT).as_posix()
                    self.assertIn(relative, names)
                    # Explicit guide anchors are part of the maintained interface.
                    if parsed.fragment and relative.startswith("docs/guides/"):
                        self.assertIn(unquote(parsed.fragment), anchors(destination.read_text(encoding="utf-8")))

    def test_documented_runner_selectors_exist(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                run_todos.parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        # Parse, but do not run, the supported advanced selection example.
        parsed = run_todos.parse_args(["--agent", "example-profile", "--mcp", "none",
            "--review-mcp", "none", "--skills", "none", "--skill-dir", str(ROOT / "examples"),
            "--prompt-config", "en", "--max-calls", "8", "--process-stop-policy", "controller-only",
            "--allow-todo-modifications", "--accept-plan-changes"])
        self.assertEqual(parsed.max_calls, 8)
        self.assertEqual(parsed.agent, "example-profile")
        config = (ROOT / "docs/guides/operator-guide.en.md").read_text(encoding="utf-8")
        for flag in self.manifest["runner_selectors"]:
            # Some core controls have their canonical reference in linked safety/operator pages.
            self.assertIn(flag, config + (ROOT / "docs/guides/technical-guide.en.md").read_text(encoding="utf-8"))

    def test_synthetic_tasklists_lint_and_dry_run_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            for number, name in enumerate(self.manifest["synthetic_examples"]):
                with self.subTest(example=name):
                    work = base / f"work-{number}"
                    work.mkdir()
                    todo = work / "tasks.md"
                    shutil.copyfile(ROOT / name, todo)
                    shutil.copyfile(ROOT / "examples/brief.md", work / "brief.md")
                    original = todo.read_bytes()
                    self.assertEqual(lint_todo_file(todo, workdir=work), [])
                    preview = work / "preview.md"
                    state = base / f"state-{number}"
                    args = ["--workdir", str(work), "--todo-file", str(todo), "--state-dir", str(state),
                            "--dry-run", "--dry-run-file", str(preview), "--max-calls", "12",
                            "--mcp", "none", "--skills", "none", "--process-stop-policy", "controller-only"]
                    if name.endswith("planning_todo.md"):
                        args += ["--allow-todo-modifications", "--stop", "2"]
                    with patch("subprocess.Popen", side_effect=AssertionError("No subprocess in documentation dry run")), \
                         redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(run_todos.main(args), 0)
                    self.assertEqual(todo.read_bytes(), original)
                    self.assertTrue(preview.is_file())
                    self.assertFalse(state.exists())

    def test_runtime_profile_example_is_complete_and_loadable(self):
        text = self.guides["docs/guides/operator-guide.en.md"]
        profiles = re.findall(r"```json\n(.*?)\n```", text, flags=re.S)
        self.assertEqual(len(profiles), 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(profiles[0], encoding="utf-8")
            profile = load_runtime_profile(path, environ={})
            self.assertEqual(profile.profile_id, "example.source-review")
            self.assertEqual(len(profile.autobuild_review_rules), 2)
            self.assertIsNone(profile.preflight)

    def test_technical_python_example_is_configuration_only(self):
        from autobuild_contract import AutoBuildContext, AutoBuildOptions
        text = self.guides["docs/guides/technical-guide.en.md"]
        snippets = re.findall(r"```python\n(.*?)\n```", text, flags=re.S)
        self.assertEqual(len(snippets), 1)
        namespace = {}
        with patch("subprocess.Popen", side_effect=AssertionError("Configuration must not start processes")):
            exec(compile(snippets[0], "technical-guide.en.md", "exec"), namespace)
        self.assertIsInstance(namespace["options"], AutoBuildOptions)
        self.assertIsInstance(namespace["context"], AutoBuildContext)
        self.assertEqual(namespace["options"].mcp, ())


if __name__ == "__main__":
    unittest.main()
