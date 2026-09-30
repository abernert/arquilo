# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline regressions. Fakes test orchestration, not real Codex/OS isolation."""
from __future__ import annotations
import ast
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo
import autobuild
from autobuild_contract import AutoBuildContext, AutoBuildOptions
import codex_policy
import codex_transport
import decide
from decision_request import DecisionRequest
import run_todos
from review_contract import build_review_context_reference, parse_review_classification
from scripts.build_runtime_zip import build_distribution
from scripts.check_release import check_release
from scripts.stage_lean import package_files, stage_package

BEGIN = "----- BEGIN ARQUILO REVIEW CONTRACT -----\n"
END = "\n----- END ARQUILO REVIEW CONTRACT -----"
CONTRACT = json.dumps({"schema_version": "arquilo.review_contract.v1", "task_text": "Create hello.txt; Prüfung.",
                       "original_request": "Create an empty file. Do not change task status.", "source": "tasks.md"}, ensure_ascii=False) + "\n"
PASS = {"verdict": "PASS", "short_summary": "Verified actual output.", "blocking_issues": [],
        "non_blocking_observations": [], "breakdown_recommended": False, "breakdown_reason": None}


def extract_contract(prompt):
    return json.loads(prompt.split(BEGIN, 1)[1].split(END, 1)[0])


def result(answer):
    return codex_transport.RunResult(assistant_messages=[answer], turn_completed=True, process_exit_code=0)


class DecideModelSelectionTests(unittest.TestCase):
    @staticmethod
    def request(model=None):
        return DecisionRequest(
            question="What is 2 + 2?",
            options=("FOUR", "FIVE"),
            context=(),
            run_id="test-run",
            task_id="test-task",
            phase="test",
            attempt_id="1",
            model=model,
        )

    def test_no_implicit_model_override(self):
        marker = object()
        settings = object()
        with patch.object(decide, "execute_decision", return_value=marker) as execute:
            self.assertIs(decide.run_decision(self.request(), settings=settings), marker)
        forwarded = execute.call_args.args[0]
        self.assertIsNone(forwarded.model)
        self.assertIs(execute.call_args.kwargs["settings"], settings)

    def test_explicit_model_override_is_preserved(self):
        marker = object()
        with patch.object(decide, "execute_decision", return_value=marker) as execute:
            self.assertIs(decide.run_decision(self.request("provider-specific-model"), settings=object()), marker)
        self.assertEqual(execute.call_args.args[0].model, "provider-specific-model")


class WindowsSandboxHintTests(unittest.TestCase):
    def test_missing_setup_helper_gets_specific_non_bypass_hint(self):
        output = (
            "windows sandbox: orchestrator_helper_launch_failed: setup refresh failed to launch helper: "
            "helper=codex-windows-sandbox-setup.exe, error=program not found"
        )
        hints = run_todos._codex_workspace_write_known_hints(output, platform_name="Windows")
        combined = "\n".join(hints)
        self.assertIn("versionierten Release-Verzeichnis", combined)
        self.assertIn("Kopiere keinen Helper aus einer anderen Version", combined)
        self.assertIn("umgehe die Sandbox nicht", combined)


class ContractTests(unittest.TestCase):
    def test_inline_unicode_is_preserved(self):
        prompt = build_review_context_reference(r"C:\hidden\contract.json", contract_text=CONTRACT)
        self.assertEqual(extract_contract(prompt), json.loads(CONTRACT))
        self.assertIn("Prüfung", prompt)

    def test_archive_path_is_not_a_required_input(self):
        prompt = build_review_context_reference(r"C:\hidden\contract.json", contract_text=CONTRACT)
        self.assertNotIn(r"C:\hidden", prompt)
        self.assertIn("do not use shell or filesystem access", prompt)
        self.assertIn("Inspect current artifacts", prompt)

    def test_inline_builder_does_not_read_files(self):
        with patch("pathlib.Path.read_text", side_effect=PermissionError("archive unavailable")):
            prompt = build_review_context_reference("unreadable.json", contract_text=CONTRACT)
        self.assertEqual(extract_contract(prompt), json.loads(CONTRACT))

    def test_legacy_path_form_remains_available(self):
        prompt = build_review_context_reference("legacy.json")
        self.assertIn("read this UTF-8 JSON file", prompt)
        self.assertIn("legacy.json", prompt)
        self.assertNotIn(BEGIN, prompt)

    def test_empty_inline_not_silently_replaced_by_file(self):
        prompt = build_review_context_reference("legacy.json", contract_text="")
        self.assertNotIn("legacy.json", prompt)
        self.assertIn("missing or malformed", prompt)

    def test_global_review_forwards_snapshot(self):
        prompt = autobuild._build_global_review_prompt(original_task="Task", latest_answer="Done",
                  contract_path=Path("inaccessible.json"), contract_text=CONTRACT)
        self.assertEqual(extract_contract(prompt), json.loads(CONTRACT))

    def test_every_runtime_reference_call_supplies_inline_text(self):
        count = 0
        for filename in ("autobuild.py", "run_todos.py"):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "build_review_context_reference":
                    count += 1
                    self.assertIn("contract_text", [kw.arg for kw in node.keywords], filename)
        self.assertEqual(count, 3)

    def test_contradictory_pass_with_blocker_is_not_valid_completion(self):
        value = dict(PASS, blocking_issues=[{"id":"ISSUE-1","type":"missing_input","summary":"Missing",
                    "requirement":"An input", "acceptance_criterion":"Input available", "references":[], "fix_suggestion":"Supply it"}])
        decision = autobuild.evaluate_completion_decision("Task", "Answer", json.dumps(value))
        self.assertFalse(decision.is_finished)


class EventPolicyTests(unittest.TestCase):
    def test_nonfatal_diagnostic_item_is_allowed(self):
        for kind in ("item.started", "item.updated", "item.completed"):
            self.assertIsNone(codex_policy.decision_event_violation({"type":kind,"item":{"type":"error","message":"Warning"}}))

    def test_tool_items_remain_forbidden(self):
        for kind in ("command_execution", "file_change", "mcp_tool_call", "collab_tool_call", "web_search", "todo_list", "future_tool"):
            with self.subTest(kind=kind):
                self.assertIsNotNone(codex_policy.decision_event_violation({"type":"item.completed","item":{"type":kind}}))

    def test_conflicting_type_labels_are_rejected(self):
        self.assertIsNotNone(codex_policy.decision_event_violation({"type":"item.completed","item":{"type":"error","kind":"command_execution"}}))

    def test_unknown_event_and_nonobject_are_rejected(self):
        for event in ([], None, {"type":"future.event"}, {"type":"item.completed","item":None}):
            self.assertIsNotNone(codex_policy.decision_event_violation(event))

    def test_duplicate_keys_fail_closed(self):
        with self.assertRaises(ValueError):
            codex_policy.parse_decision_event('{"type":"turn.started","type":"error"}')

    def test_decide_keeps_host_config_and_does_not_toggle_features(self):
        args = codex_policy.decision_arguments(network_access=False, config_profile=None, extra_args=())
        self.assertEqual(args, ["--sandbox", "read-only", "-c", 'approval_policy="never"'])
        self.assertNotIn("--ignore-user-config", args)
        self.assertFalse(any(arg.startswith("features.") for arg in args))

    def test_top_level_error_is_fatal_but_item_warning_is_not(self):
        with tempfile.TemporaryDirectory() as t, redirect_stdout(io.StringIO()):
            base = Path(t)
            acc = codex_transport.RunResult()
            codex_transport.handle_event({"type":"item.completed","item":{"type":"error","message":"Warning"}}, acc, base/'pretty.log', base/'raw.jsonl', False)
            self.assertEqual(acc.stream_errors, [])
            codex_transport.handle_event({"type":"error","message":"Fatal"}, acc, base/'pretty.log', base/'raw.jsonl', False)
            self.assertEqual(len(acc.stream_errors), 1)


class OrchestrationTests(unittest.TestCase):
    def run_fake(self, *, correction=False, archive_error=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        todo = base/'tasks.md'
        original = "1. ***TASK***: Create an empty hello.txt; retain this exact original criterion.\n"
        todo.write_text(original, encoding="utf-8")
        calls, seen_contracts = [], []
        expected_task = original.strip()
        def fake(prompt, cwd, **kwargs):
            phase = kwargs['phase']
            calls.append((phase, kwargs['sandbox']))
            if phase in {"auftrag", "fix"}:
                if phase == 'fix':
                    self.assertEqual(extract_contract(prompt), seen_contracts[0])
                (base/'hello.txt').write_bytes(b"")
                todo.write_text("1. ***TASK***: MUTATED requirements must not replace the snapshot.\n", encoding='utf-8')
                return result("Created hello.txt; no status change.")
            self.assertEqual(phase, "review")
            self.assertEqual(kwargs['sandbox'], "read-only")
            snapshot = extract_contract(prompt)
            self.assertIn("retain this exact original criterion", snapshot['task_text'])
            self.assertNotIn("MUTATED", snapshot['task_text'])
            paths = list(base.rglob('review_contract_*.json'))
            self.assertEqual(len(paths), 1)
            self.assertEqual(json.loads(paths[0].read_text(encoding='utf-8')), snapshot)
            seen_contracts.append(snapshot)
            if correction and len(seen_contracts) == 1:
                value = dict(PASS, verdict='FAIL', short_summary='Report needs a local correction.', blocking_issues=[{
                    'id':'ISSUE-1', 'type':'local_fix', 'summary':'Missing verification in report', 'requirement':'Record verification',
                    'acceptance_criterion':'Verification is recorded', 'references':['todo_result_1.md'], 'fix_suggestion':'Add it'}])
                return result(json.dumps(value))
            self.assertEqual((base/'hello.txt').stat().st_size, 0)
            return result(json.dumps(PASS))
        original_write = autobuild.write_text
        def write(path, text):
            if archive_error and path.name.startswith('review_contract_'):
                raise PermissionError('Simulated archive write denial')
            return original_write(path, text)
        with patch.dict(os.environ, {}, clear=True), patch.object(autobuild, 'run_codex_exec_json', side_effect=fake), \
             patch.object(autobuild, 'write_text', side_effect=write), \
             patch.object(autobuild, 'run_semantic_decision', side_effect=AssertionError('No live model permitted')), \
             patch.object(autobuild, '_terminal_beep'), redirect_stdout(io.StringIO()):
            summary = autobuild.start(task='Read tasks.md and perform task 1.', workdir=base,
                options=AutoBuildOptions(max_steps=3, max_calls=8),
                context=AutoBuildContext(task_source='todo',todo_identifier='1',decision_todo_file=todo))
        return summary, calls, seen_contracts

    def test_production_and_readonly_review_complete_offline(self):
        summary, calls, _ = self.run_fake()
        self.assertTrue(summary.completed)
        self.assertEqual(calls, [('auftrag','workspace-write'), ('review','read-only')])
        self.assertEqual(summary.decision['source'], 'review_contract')

    def test_correction_and_second_review_keep_first_contract(self):
        summary, calls, snapshots = self.run_fake(correction=True)
        self.assertTrue(summary.completed)
        self.assertEqual([p for p, _ in calls], ['auftrag','review','fix','review'])
        self.assertEqual(snapshots[0], snapshots[1])

    def test_failed_archiving_does_not_certify_completion(self):
        summary, calls, _ = self.run_fake(archive_error=True)
        self.assertFalse(summary.completed)
        self.assertEqual(summary.execution_error['code'], 'review_context_failed')
        self.assertEqual(len(calls), 1)


class CliTests(unittest.TestCase):
    def test_version_matches_manifest(self):
        self.assertEqual(arquilo.__version__, (ROOT/'VERSION').read_text().strip())

    def test_run_dispatch_preserves_flags_and_exit_code(self):
        with patch('run_todos.main', return_value=7) as run:
            self.assertEqual(arquilo.main(['run','--workdir','somewhere']), 7)
        run.assert_called_once_with(['--workdir','somewhere'])

    def test_doctor_dispatch(self):
        with patch('arquilo_doctor.main', return_value=1) as run:
            self.assertEqual(arquilo.main(['doctor','--json']), 1)
        run.assert_called_once_with(['--json'])

    def test_capability_dispatch(self):
        with patch('run_todos.main', return_value=0) as run:
            self.assertEqual(arquilo.main(['capabilities']), 0)
        run.assert_called_once_with(['--print-capabilities'])

    def test_package_dispatch(self):
        with patch('scripts.build_runtime_zip.main', return_value=2) as run:
            self.assertEqual(arquilo.main(['package','example.zip']), 2)
        run.assert_called_once_with(['example.zip'])

    def test_help_and_capabilities_do_not_require_codex(self):
        for args in (['--help'], ['run','--help'], ['doctor','--help'], ['capabilities']):
            proc = subprocess.run([sys.executable,'-B',str(ROOT/'arquilo.py'),*args], cwd=ROOT,
                                  capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data['schema_version'], 'arquilo.capabilities.v1')

    def test_dry_run_does_not_execute_task(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            shutil.copyfile(ROOT/'examples/minimal_todo.md', base/'tasks.md')
            before=(base/'tasks.md').read_bytes()
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'arquilo.py'),'run','--workdir',str(base),
                '--todo-file',str(base/'tasks.md'),'--dry-run','--dry-run-file',str(base/'preview.md'),
                '--process-stop-policy','controller-only'],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            self.assertFalse((base/'hello.txt').exists())
            self.assertEqual((base/'tasks.md').read_bytes(),before)
            self.assertTrue((base/'preview.md').is_file())


class PackageTests(unittest.TestCase):
    def test_release_checks(self):
        self.assertEqual(check_release(ROOT)['status'],'PASS')

    def test_license_notice_and_new_cli_are_in_allowlist(self):
        names=package_files(ROOT)
        self.assertTrue({'LICENSE','NOTICE','arquilo.py','scripts/check_release.py'}.issubset(names))
        self.assertFalse(any(name.startswith(('tests/','.github/','.local-work/')) for name in names))

    def test_reproducible_zip_and_checksum(self):
        with tempfile.TemporaryDirectory() as t:
            a,b=Path(t)/'a.zip',Path(t)/'b.zip'
            build_distribution(a,source=ROOT)
            build_distribution(b,source=ROOT)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(Path(str(a)+'.sha256').read_text(),hashlib.sha256(a.read_bytes()).hexdigest()+'  a.zip\n')

    def test_zip_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'existing.zip'; p.write_bytes(b'do not overwrite')
            with self.assertRaises(FileExistsError): build_distribution(p,source=ROOT)
            self.assertEqual(p.read_bytes(),b'do not overwrite')

    def test_zip_refuses_existing_checksum(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'new.zip'; checksum=Path(str(p)+'.sha256'); checksum.write_text('keep')
            with self.assertRaises(FileExistsError): build_distribution(p,source=ROOT)
            self.assertFalse(p.exists()); self.assertEqual(checksum.read_text(),'keep')

    def test_extracted_distribution_can_validate_and_repackage(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t); package=base/'source.zip'
            build_distribution(package,source=ROOT)
            with zipfile.ZipFile(package) as z:
                self.assertEqual(sorted(z.namelist()),package_files(ROOT))
                z.extractall(base/'extracted')
            proc=subprocess.run([sys.executable,'-B','arquilo.py','package',str(base/'rebuilt.zip')],
                  cwd=base/'extracted',capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            self.assertEqual(package.read_bytes(),(base/'rebuilt.zip').read_bytes())

    def test_missing_license_file_fails_packaging(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)/'staged'; stage_package(base,source=ROOT); (base/'LICENSE').unlink()
            with self.assertRaises(ValueError): build_distribution(Path(t)/'invalid.zip',source=base)

    def test_mismatched_manifest_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)/'staged'; stage_package(base,source=ROOT)
            p=base/'documents/lean_package.json'; data=json.loads(p.read_text(encoding='utf-8'))
            data['runtime_file_count']+=1; p.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError): package_files(base)


if __name__ == '__main__':
    unittest.main()
