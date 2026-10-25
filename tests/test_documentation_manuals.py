# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Handbook completeness and consolidation; no provider calls or network."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import documentation_reference
from prompt_config import PROMPT_PLACEHOLDERS
from run_todos import TodoRunner
from task_resources import RESOURCE_KEYS


def visible(text):
    return re.sub(r'^(```|~~~)[^\n]*\n.*?^\1[^\n]*$', '', text, flags=re.M | re.S)


def anchors(text):
    text = visible(text)
    result = set(re.findall(r'<a\s+id="([^"]+)"', text))
    for value in re.findall(r'^#{1,6}\s+(.+)$', text, flags=re.M):
        result.add(re.sub(r'[^\w\- ]', '', value.lower()).replace(' ', '-'))
    return result


class HandbookConsolidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operator = (ROOT/'docs/guides/operator-guide.en.md').read_text(encoding='utf-8')
        cls.manifest = json.loads((ROOT/'docs/guides/manifest.json').read_text(encoding='utf-8'))
        cls.package = json.loads((ROOT/'documents/lean_package.json').read_text(encoding='utf-8'))

    def test_complete_public_cli_reference_matches_live_parsers(self):
        with patch('subprocess.Popen', side_effect=AssertionError('No process in a documentation check')):
            self.assertGreater(documentation_reference.check_or_write(), 80)
        inventory = json.loads((ROOT/'docs/guides/cli-reference.json').read_text(encoding='utf-8'))
        self.assertEqual(set(inventory['commands']), {'arquilo', 'tasklist', 'tasklist run', 'doctor',
            'tasklist resume-review', 'git', 'package', 'review_confidence.py', 'autobuild.py'})
        self.assertEqual(set(inventory['maintenance_commands']), {
            'scripts/check_release.py', 'scripts/stage_lean.py', 'scripts/install_test_codex.py',
            'scripts/check_codex_configuration.py', 'scripts/check_codex_provider.py',
            'scripts/check_resource_configuration.py', 'scripts/documentation_reference.py'})
        for command, actions in {**inventory['commands'], **inventory['maintenance_commands']}.items():
            for action in actions:
                with self.subTest(command=command, names=action['names']):
                    for name in action['names']:
                        self.assertIn('`'+name+'`', self.operator)
                    self.assertTrue(action['description'])
        self.assertNotIn('--request-json', {name for actions in inventory['commands'].values()
                                            for a in actions for name in a['names']})

    def test_missing_cli_description_fails_instead_of_omitting_option(self):
        descriptions = dict(documentation_reference.DESCRIPTIONS)
        descriptions.pop('--reasoning-effort')
        with patch.object(documentation_reference, 'DESCRIPTIONS', descriptions):
            with self.assertRaisesRegex(ValueError, 'Undocumented CLI option'):
                documentation_reference.parser_inventory()

    def test_all_active_arquilo_environment_settings_are_documented(self):
        names = set()
        for filename in ('runtime_config.py', 'runtime_profile.py', 'autobuild.py', 'run_todos.py',
                         'agent_backend.py', 'claude_transport.py'):
            tree = ast.parse((ROOT/filename).read_text(encoding='utf-8'))
            names.update(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                and isinstance(n.value, str) and re.fullmatch(r'ARQUILO_[A-Z0-9_]+', n.value))
        self.assertEqual(len(names), 13)
        for name in names:
            self.assertIn('| `'+name+'` |', self.operator)

    def test_every_task_directive_key_and_profile_field_is_in_manual(self):
        for key in TodoRunner.CFG_ALLOWED_KEYS | TodoRunner.WAIT_ALLOWED_KEYS | set(RESOURCE_KEYS):
            with self.subTest(key=key): self.assertIn('`'+key+'`', self.operator)
        for key in ('schema_version', 'profile_id', 'profile_version', 'activation_markers',
                    'scope_activation_markers', 'protected_markers', 'prompt_policy', 'preflight', 'metadata',
                    'controller_only_instruction', 'task_contract_instruction', 'breakdown_scope_guard',
                    'legacy_review_boundary', 'parent_review_scope_guard', 'parent_review_terminal_rule',
                    'autobuild_review_rules', 'command', 'timeout_seconds', 'cwd', 'environment'):
            with self.subTest(profile_field=key): self.assertIn('`'+key+'`', self.operator)

    def test_every_prompt_element_and_required_placeholder_is_documented(self):
        self.assertEqual(len(PROMPT_PLACEHOLDERS), 53)
        for name, parameters in PROMPT_PLACEHOLDERS.items():
            with self.subTest(element=name):
                self.assertIn('| `'+name+'` |', self.operator)
                for value in parameters:self.assertIn('`{{'+value+'}}`', self.operator)

    def test_user_manuals_explain_installation_and_everyday_options_without_chat_faq(self):
        for language in ('de', 'en'):
            text = (ROOT/f'docs/guides/user-guide.{language}.md').read_text(encoding='utf-8')
            self.assertNotIn('### Funktioniert `codex`', text)
            self.assertNotIn('### Does `codex`', text)
            self.assertIn('~/.local/bin', text)
            for flag in ('--backend', '--model', '--reasoning-effort', '--agent', '--max-calls', '--runtime-profile',
                         '--prompt-config', '--mcp', '--skills', '--state-dir', '--git-push', '--git-required'):
                self.assertIn(flag, text)
            self.assertIn('ARQUILO_CODEX_MODEL', text)
            self.assertIn('ARQUILO_CODEX_REASONING_EFFORT', text)
            self.assertIn('ARQUILO_CLAUDE_CODE_MODEL', text)
            self.assertIn('ARQUILO_CLAUDE_CODE_REASONING_EFFORT', text)
            self.assertIn('<!-- example: claude-doctor -->', text)
            self.assertIn('<!-- example: claude-run -->', text)
            self.assertIn('<!-- example: model-and-effort -->', text)
            self.assertIn('YOUR_MODEL_ID', text)

    def test_package_has_one_handbook_tree_not_retired_reference_pages(self):
        files = set(self.package['runtime_files'])
        self.assertEqual(len(files), self.package['runtime_file_count'])
        self.assertTrue({'docs/README.md', 'docs/guides/cli-reference.json',
                        'documents/REVIEW_CORE.md', 'documents/QUICKSTART.md', 'SECURITY.md'}.issubset(files))
        self.assertEqual(len([x for x in files if x.startswith('docs/guides/') and x.endswith('.md')]), 4)
        for retired in ('docs/installation.md','docs/quickstart.md','docs/cookbook.md',
                        'documents/CONFIGURATION.md','docs/troubleshooting.md','docs/git-publication.md',
                        'docs/pipeline-mvp-concept.md','docs/compatibility.md','documents/HISTORICAL_MIGRATION.md',
                        'RUNTIME_PROFILE_API.md','docs/guides/README.md','docs/documentation-maintenance.md'):
            self.assertNotIn(retired, files)
        self.assertFalse(any(x.startswith(('maintenance/', 'design/', 'tests/')) for x in files))
        self.assertNotIn('scripts/documentation_reference.py', files)

    def test_packaged_links_and_all_handbook_anchors_resolve(self):
        files = set(self.package['runtime_files'])
        for name in sorted(files):
            if not name.endswith('.md'):continue
            text = visible((ROOT/name).read_text(encoding='utf-8'))
            for target in re.findall(r'(?<!!)\[[^]\n]*\]\(([^)\s]+)\)', text):
                url = urlsplit(target)
                if url.scheme or url.netloc:continue
                path = ((ROOT/name).parent/unquote(url.path)).resolve() if url.path else ROOT/name
                with self.subTest(document=name, target=target):
                    self.assertTrue(path.is_relative_to(ROOT))
                    self.assertTrue(path.is_file())
                    self.assertIn(path.relative_to(ROOT).as_posix(), files)
                    if url.fragment and path.suffix=='.md':
                        self.assertIn(unquote(url.fragment), anchors(path.read_text(encoding='utf-8')))

    def test_git_delivery_and_acceptance_are_documented_separately(self):
        self.assertIn('`--git-required` requires `--git`', self.operator)
        self.assertIn('normal workspace', self.operator)
        self.assertIn('no full-workspace copy', self.operator)
        self.assertIn('mismatch still vetoes acceptance', self.operator)
        self.assertIn('git status --workdir', self.operator)
        self.assertIn('git retry --workdir', self.operator)
        self.assertIn('do not call a model', self.operator)
        self.assertIn('serial only', self.operator)
        self.assertEqual((ROOT/'VERSION').read_text().strip(), '0.9.1')


if __name__ == '__main__':
    unittest.main()
