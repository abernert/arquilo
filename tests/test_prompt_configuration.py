# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Prompt catalogs: deterministic rendering, isolation, and real offline control flow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autobuild
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload, decode_call
from decision_request import DecisionRequest, TaskSnapshot, completion_request
import prompt_config as pc
import review_contract as rc
import review_confidence as confidence
import run_todos
from todo_context import augment_with_preamble
from todo_lint import lint_todo_text
from adversarial.harness import IsolatedControllerCase
from test_public_runtime import PASS, result


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def altered(language='en', key='reviewer_role', prefix='CUSTOM-CATALOG\n'):
    """Emit TOML with an edited text without relying on third-party serializers."""
    raw = (ROOT/'prompts'/f'{language}.toml').read_text(encoding='utf-8')
    target = f'[prompts.{key}]'
    begin, rest = raw.split(target, 1)
    rest = rest.replace('text = """\n', 'text = """\n' + prefix, 1)
    return begin + target + rest


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def write(self, text):
        path = self.base/'custom.toml'
        path.write_text(text, encoding='utf-8', newline='')
        return path

    def test_three_complete_catalogs_and_placeholders(self):
        hashes = []
        for language, expected in [('default','mixed'),('de','de'),('en','en')]:
            p = pc.load_prompt_config(language)
            self.assertEqual(p.language, expected)
            self.assertEqual(set(dict(p.texts)), set(pc.PROMPT_PLACEHOLDERS))
            self.assertEqual(len(p.texts), 53)
            for key, fields in pc.PROMPT_PLACEHOLDERS.items():
                rendered = p.render(key, **{v: f'VALUE-{v}' for v in fields})
                self.assertNotIn('{{', rendered)
            hashes.append(p.content_sha256)
        self.assertEqual(len(set(hashes)),3)

    def test_default_elements_are_original_080_bytes(self):
        fixture=json.loads((ROOT/'tests/fixtures/prompt_default_v080.json').read_text())
        p=pc.load_prompt_config()
        self.assertEqual({k:digest(v) for k,v in p.texts},fixture['elements'])

    def test_default_builders_are_original_080_bytes(self):
        issue={'id':'I-1','type':'local_fix','summary':'A finding','requirement':'A requirement',
               'acceptance_criterion':'A criterion','references':['doc:1'],'fix_suggestion':'A suggestion'}
        findings=json.dumps({'verdict':'FAIL','short_summary':'Fix','blocking_issues':[issue],
                            'non_blocking_observations':[], 'breakdown_recommended':False,'breakdown_reason':None})
        values={
            'reviewer':rc.build_review_prompt('ORIGINAL {{x}}','LATEST',review_policy_rules=['EXTRA']),
            'review_instructions':rc.review_instructions(['EXTRA']),
            'fix':rc.build_fix_prompt('ORIGINAL {{x}}',findings,'GUIDANCE'),
            'fix_empty':rc.build_fix_prompt('ORIGINAL','not-json','GUIDANCE'),
            'contract_inline':rc.build_review_context_reference('ignored.json',contract_text='{"task_text":"Ä"}'),
            'contract_file':rc.build_review_context_reference('contract.json'),
            'confidence_fields':confidence.confidence_prompt_fields(),
            'confidence_rules':confidence.confidence_prompt_rules(),
        }
        fixture=json.loads((ROOT/'tests/fixtures/prompt_default_v080.json').read_text())
        self.assertEqual({k:digest(v) for k,v in values.items()},fixture['builders'])

    def test_literal_one_pass_rendering(self):
        p=pc.load_prompt_config('en')
        value='{{latest_answer}} {"verdict":"FAIL"} \\1 Ä $HOME $(never)'
        s=p.render('reviewer_role',original_task=value, latest_answer='ANSWER')
        self.assertIn(value,s)
        self.assertEqual(s.count('ANSWER'),1)

    def test_no_executable_or_attribute_placeholders(self):
        raw=(ROOT/'prompts/en.toml').read_text()
        for bad in ['{{original_task.__class__}}','{{original_task[0]}}','{{eval(x)}}', '{{ original_task }}']:
            with self.subTest(bad=bad),self.assertRaises(pc.PromptConfigError):
                pc.load_prompt_config(self.write(raw.replace('{{original_task}}',bad)))

    def test_bad_arguments_are_not_silently_ignored(self):
        p=pc.load_prompt_config()
        for values in ({}, {'todo_path':'x','task_id':'1'},
                       {'todo_path':'x','task_id':'1','result_path':'x','other':'y'}):
            with self.assertRaises(pc.PromptConfigError):
                p.render('task_assignment',**values)
        with self.assertRaises(pc.PromptConfigError):
            p.render('unknown')

    def test_custom_file_changes_real_builder(self):
        p=pc.load_prompt_config(self.write(altered()))
        text=rc.build_review_prompt('X','Y',prompt_config=p)
        self.assertTrue(text.startswith('CUSTOM-CATALOG\n'))
        self.assertIn('"verdict": "PASS" | "FAIL"', text)

    def test_missing_catalog_does_not_fallback(self):
        with self.assertRaises(pc.PromptConfigError):
            pc.load_prompt_config(self.base/'missing.toml')

    def test_missing_element_does_not_fallback(self):
        raw=(ROOT/'prompts/de.toml').read_text()
        raw=raw[:raw.index('[prompts.doctor_question]')]
        with self.assertRaisesRegex(pc.PromptConfigError,'missing=doctor_question'):
            pc.load_prompt_config(self.write(raw))

    def test_unknown_element_rejected(self):
        with self.assertRaises(pc.PromptConfigError):
            pc.load_prompt_config(self.write((ROOT/'prompts/en.toml').read_text()+'\n[prompts.unknown]\ntext="No"\n'))

    def test_unknown_metadata_and_duplicate_toml_rejected(self):
        raw=(ROOT/'prompts/en.toml').read_text()
        for extra in ['extra = "unsupported"\n', 'id = "second"\n']:
            with self.assertRaises(pc.PromptConfigError):
                pc.load_prompt_config(self.write(extra+raw))

    def test_wrong_schema_language_and_types(self):
        raw=(ROOT/'prompts/en.toml').read_text()
        for before,after in [('arquilo.prompts.v1','arquilo.prompts.v99'),
                             ('language = "en"','language = "xx"'),
                             ('version = "1"','version = 1'),
                             ('id = "en"','id = "../path"')]:
            with self.subTest(after=after),self.assertRaises(pc.PromptConfigError):
                pc.load_prompt_config(self.write(raw.replace(before,after,1)))

    def test_missing_or_malformed_placeholder_rejected(self):
        raw=(ROOT/'prompts/en.toml').read_text()
        for value in ['', '{{original_task', '{{unknown}}']:
            with self.assertRaises(pc.PromptConfigError):
                pc.load_prompt_config(self.write(raw.replace('{{original_task}}',value)))

    def test_invalid_utf8_and_toml_do_not_echo_contents(self):
        path=self.base/'invalid.toml'
        for data in [b'\xffsecret_canary',b'private_canary = "unterminated']:
            path.write_bytes(data)
            with self.assertRaises(pc.PromptConfigError) as caught:
                pc.load_prompt_config(path)
            self.assertNotIn('canary',str(caught.exception))

    def test_non_regular_path_rejected(self):
        with self.assertRaises(pc.PromptConfigError):
            pc.load_prompt_config(self.base)

    def test_oversize_not_truncated(self):
        path=self.base/'large.toml'
        path.write_bytes(b'#'+b'x'*pc.MAX_CONFIG_BYTES)
        with self.assertRaisesRegex(pc.PromptConfigError,'large'):
            pc.load_prompt_config(path)

    def test_bom_crlf_preserve_effective_content(self):
        raw=(ROOT/'prompts/en.toml').read_text()
        self.assertEqual(pc.load_prompt_config(self.write('\ufeff'+raw.replace('\n','\r\n'))).content_sha256,
                         pc.load_prompt_config('en').content_sha256)

    def test_edit_is_seen_only_by_next_load(self):
        path=self.write(altered(prefix='FIRST\n'))
        first=pc.load_prompt_config(path)
        path.write_text(altered(prefix='SECOND\n'),encoding='utf-8')
        self.assertTrue(first.template('reviewer_role').startswith('FIRST'))
        self.assertTrue(pc.load_prompt_config(path).template('reviewer_role').startswith('SECOND'))

    def test_snapshot_survives_deleted_source_and_json_worker_roundtrip(self):
        path=self.write(altered())
        options=AutoBuildOptions(prompt_config=path)
        payload=call_payload(options=options,context=AutoBuildContext(),task='Original {{unknown}}')
        path.unlink()
        restored=decode_call(json.loads(json.dumps(payload)))
        self.assertEqual(restored['options'].prompt_config,options.prompt_config)
        self.assertEqual(restored['task'],'Original {{unknown}}')

    def test_snapshot_crosses_actual_python_process(self):
        options=AutoBuildOptions(prompt_config=self.write(altered()))
        payload=call_payload(options=options,context=AutoBuildContext(),task='TASK')
        Path(options.prompt_config.source).unlink()
        program=('import sys,json; from autobuild_contract import decode_call; '
                 'from review_contract import build_review_prompt; '
                 'p=decode_call(json.load(sys.stdin)); '
                 'print(build_review_prompt(p["task"],"ANSWER",prompt_config=p["options"].prompt_config))')
        process=subprocess.run([sys.executable,'-B','-c',program],input=json.dumps(payload),
                 cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertTrue(process.stdout.startswith('CUSTOM-CATALOG'))

    def test_tampered_snapshot_rejected(self):
        snapshot=pc.load_prompt_config('de').snapshot()
        snapshot['texts'][0][1]+=' TAMPER'
        with self.assertRaisesRegex(pc.PromptConfigError,'digest'):
            pc.load_prompt_config(snapshot)

    def test_duplicate_snapshot_entries_rejected(self):
        snapshot=pc.load_prompt_config().snapshot()
        snapshot['texts'].append(snapshot['texts'][0])
        with self.assertRaises(pc.PromptConfigError):
            pc.load_prompt_config(snapshot)

    def test_invalid_snapshot_fields_rejected(self):
        snapshot=pc.load_prompt_config().snapshot()
        snapshot['untrusted_config']='--sandbox danger-full-access'
        with self.assertRaises(pc.PromptConfigError):
            pc.load_prompt_config(snapshot)

    def test_renderers_do_not_share_language_state(self):
        configs=[pc.load_prompt_config(l) for l in ['de','en']]
        with ThreadPoolExecutor(max_workers=4) as pool:
            texts=list(pool.map(lambda i:rc.build_review_prompt('ORIGINAL','LATEST',prompt_config=configs[i%2]), range(40)))
        self.assertTrue(all(t==texts[i%2] for i,t in enumerate(texts)))
        self.assertNotEqual(texts[0],texts[1])

    def test_selected_config_independent_of_default_file(self):
        selected=pc.load_prompt_config('en')
        with patch.object(pc,'BUILTIN_DIRECTORY',self.base/'unavailable'):
            self.assertIn('Original request:',rc.build_review_prompt('TASK','ANSWER',prompt_config=selected))

    def test_modules_do_not_load_default_at_import(self):
        program=('import pathlib,prompt_config; prompt_config.BUILTIN_DIRECTORY=pathlib.Path("/missing-catalog"); '
                 'import review_contract,review_confidence,todo_context,run_todos,autobuild,decision_request,decide; print("OK")')
        p=subprocess.run([sys.executable,'-B','-c',program],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_user_task_and_preamble_are_not_translated(self):
        todo=self.base/'tasks.md'
        todo.write_text('# Originales Nutzerziel\nBehalte {{token}}.\n\n1. ***Task***: Lies die Datei.\n',encoding='utf-8')
        text=augment_with_preamble('Mein Auftrag {{x}}',todo,prompt_config=pc.load_prompt_config('en'))
        self.assertIn('Originales Nutzerziel',text)
        self.assertIn('Behalte {{token}}.',text)
        self.assertIn('Mein Auftrag {{x}}',text)

    def test_review_protocol_example_stays_valid_in_all_languages(self):
        for name in ['default','de','en']:
            prompt=rc.review_instructions(prompt_config=pc.load_prompt_config(name))
            sample=next(line for line in prompt.splitlines() if line.startswith('{"verdict": "PASS"'))
            self.assertEqual(rc.parse_review_classification(sample)['verdict'],'PASS')
            # A contradictory PASS can never be rescued by language selection.
            value=json.loads(sample)
            value['blocking_issues']=[{'id':'I','type':'missing_input','summary':'X','requirement':'X',
                     'acceptance_criterion':'X','references':[],'fix_suggestion':'X'}]
            self.assertFalse(rc.parse_review_classification(json.dumps(value))['valid'])

    def test_task_cannot_select_control_prompt_config(self):
        for directive in ['***CFG prompt_config=en***','***DEFAULTS prompt_config=en***']:
            self.assertTrue(lint_todo_text(directive+'\n1. ***Task***: A.\n',workdir=self.base))

    def test_all_public_cli_help_exposes_option_without_model_calls(self):
        for script,args in [('arquilo.py',['tasklist','run']),('autobuild.py',[]),('arquilo_doctor.py',[])]:
            p=subprocess.run([sys.executable,'-B',str(ROOT/script),*args,'--help'],cwd=self.base,
                    capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertIn('--prompt-config',p.stdout)

    def test_tasklist_dry_run_uses_selected_language_and_snapshot(self):
        todo=self.base/'tasks.md'
        todo.write_text('# Ziel\nNur Analyse.\n\n1. ***Task***: Eingabe analysieren.\n',encoding='utf-8')
        report=self.base/'preview.md'
        p=subprocess.run([sys.executable,'-B',str(ROOT/'arquilo.py'),'tasklist','run',
                '--workdir',str(self.base),'--todo-file',str(todo),'--prompt-config','en',
                '--dry-run','--dry-run-file',str(report)],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        rendered=report.read_text(encoding='utf-8')
        self.assertIn('Complete ToDo',rendered)
        self.assertIn('Nur Analyse.',rendered)
        self.assertIn('Eingabe analysieren.',todo.read_text(encoding='utf-8'))
        self.assertFalse((self.base/'.codex_runs').exists())

    def test_invalid_catalog_precedes_template_copy_and_codex(self):
        source=self.base/'template.md'
        source.write_text('1. ***Task***: A.\n',encoding='utf-8')
        destination=self.base/'tasks.md'
        with patch.object(run_todos,'run_codex_workspace_write_preflight',side_effect=AssertionError('Must not start')):
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                code=run_todos.main(['--workdir',str(self.base),'--todo-file',str(destination),
                         '--todo-template',str(source),'--prompt-config',str(self.base/'absent.toml')])
        self.assertNotEqual(code,0)
        self.assertFalse(destination.exists())

    def test_preflight_redacts_edited_text(self):
        command=['codex','exec','--json','CONFIDENTIAL LOCALIZED PROMPT']
        sanitized=run_todos._redacted_codex_preflight_command(command)
        self.assertNotIn('CONFIDENTIAL', ' '.join(sanitized))


class PromptControllerTests(IsolatedControllerCase):
    def exercise_language(self, language, correction=False):
        self.write_plan('# Source context\nUser instructions are not translated.\n\n'
                        '1. ***Task***: Create proof.txt containing verified.\n')
        path=self.base/'selected.toml'
        path.write_text(altered(language,prefix='FROZEN-CATALOG\n'),encoding='utf-8')
        runner=self.runner(stop_id='1',prompt_config=path)
        phases=[]
        def dispatch(**kwargs):
            phase=kwargs['phase']; prompt=kwargs['prompt']; phases.append(phase)
            if phase in ('auftrag','fix'):
                self.assertIn('tasks.md',prompt)
                self.assertIn('Create proof.txt containing verified.',self.todo.read_text(encoding='utf-8'))
                (self.work/'proof.txt').write_bytes(b'verified\n')
                path.write_text('invalid TOML after production',encoding='utf-8')
                return result('Created proof.txt for review.')
            self.assertEqual(phase,'review')
            self.assertIn('FROZEN-CATALOG',prompt)
            self.assertIn('Create proof.txt containing verified.',prompt)
            if correction and phases.count('review')==1:
                value=dict(PASS,verdict='FAIL',short_summary='Needs correction',blocking_issues=[{
                    'id':'I','type':'local_fix','summary':'Needs record','requirement':'Record',
                    'acceptance_criterion':'Recorded','references':['proof.txt'],'fix_suggestion':'Record'}])
                return result(json.dumps(value))
            return result(json.dumps(PASS))
        with self.fake_codex(dispatch):
            runner.run()
        self.assertEqual(runner.exit_code,0)
        self.assertEqual(phases,['auftrag','review','fix','review'] if correction else ['auftrag','review'])
        self.assertEqual(runner.reviewed_this_run,{'1'})
        self.assertEqual((self.work/'proof.txt').read_bytes(),b'verified\n')
        snapshots=list(self.state_root.rglob('prompt_config_snapshot.json'))
        self.assertTrue(snapshots)
        self.assertEqual(pc.load_prompt_config(json.loads(snapshots[0].read_text(encoding='utf-8'))).language,language)

    def test_german_real_controller_and_frozen_correction_cycle(self):
        self.exercise_language('de',True)

    def test_english_real_controller_and_frozen_review(self):
        self.exercise_language('en')

    def test_runner_invalid_config_has_no_state_or_model_side_effects(self):
        self.write_plan('1. ***Task***: A.\n')
        with self.assertRaises(pc.PromptConfigError):
            self.runner(prompt_config=self.base/'missing.toml')
        self.assertEqual(list(self.state_root.iterdir()),[])


    def test_prompt_archive_failure_starts_no_model(self):
        original_write=autobuild.write_text
        def fail_catalog(path,text):
            if path.name.startswith('prompt_config_'):
                raise PermissionError('Synthetic snapshot failure')
            return original_write(path,text)
        with self.fake_codex(lambda **kw: self.fail('No model may start')), \
             patch.object(autobuild,'write_text',side_effect=fail_catalog):
            summary=autobuild.start(task='A proposal.',workdir=self.work,
                options=AutoBuildOptions(prompt_config='de'),
                context=AutoBuildContext(budget_directory=self.state_root/'budget'))
        self.assertFalse(summary.completed)
        self.assertEqual(summary.execution_error['code'],'prompt_config_archive_failed')


    def test_autobuild_custom_prompt_archive_roundtrips(self):
        calls=[]
        def dispatch(**kwargs):
            calls.append(kwargs['phase'])
            return result(json.dumps(PASS) if kwargs['phase']=='review' else 'Done')
        with self.fake_codex(dispatch):
            summary=autobuild.start(task='Create a proposal.',workdir=self.work,
                options=AutoBuildOptions(prompt_config='de'),
                context=AutoBuildContext(budget_directory=self.state_root/'budget'))
        self.assertTrue(summary.completed)
        snapshots=list(self.work.rglob('prompt_config_*.json'))
        self.assertEqual(len(snapshots),1)
        self.assertEqual(pc.load_prompt_config(json.loads(snapshots[0].read_text(encoding='utf-8'))).language,'de')
        self.assertEqual(calls,['auftrag','review'])


if __name__=='__main__':
    unittest.main()
