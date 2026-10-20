# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Resource policy regressions; no credentials, network or real models."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from task_resources import (ResourceError, SkillCatalog, TaskResources, selection,
    resolve_task_resources, plan_resources, bind_resources)
from mcp_selection import config_values, parse_inventory, resolve_inventory
from codex_transport import CodexExecRequest, build_command
from autobuild_contract import AutoBuildOptions, AutoBuildContext, call_payload, decode_call
from todo_lint import lint_todo_text


class SelectionTests(unittest.TestCase):
    def test_inherit_and_empty_are_distinct(self):
        self.assertIsNone(selection(None))
        self.assertEqual(selection('none'), ())
        self.assertEqual(selection([]), ())
        self.assertEqual(selection('docs,issues'), ('docs', 'issues'))

    def test_invalid_selection_fails(self):
        for value in ('', 'docs,', 'docs,,issues', 'all', 'inherit', 'none,docs',
                      'docs,docs', '../bad', 'x".enabled=true', '--yolo', '$foo', ['a', 1]):
            with self.subTest(value=value), self.assertRaises(ResourceError):
                selection(value)

    def test_defaults_do_not_change_cfg_scope(self):
        text = '# Context\n***DEFAULTS mcp=docs,issues***\n\n***CFG mcp=docs***\n1. ***Task***: First\n\n2. ***Task***: Next\n'
        self.assertEqual(resolve_task_resources(text, '1').mcp, ('docs',))
        self.assertEqual(resolve_task_resources(text, '2').mcp, ('docs','issues'))
        self.assertEqual(lint_todo_text(text, workdir=Path.cwd()), [])

    def test_defaults_adjacent_to_task(self):
        text = '***DEFAULTS mcp=none***\n1. ***Task***: Work\n'
        self.assertEqual(lint_todo_text(text, workdir=Path.cwd()), [])
        self.assertEqual(resolve_task_resources(text,'1').mcp, ())

    def test_no_defaults_legacy_unchanged(self):
        self.assertFalse(resolve_task_resources('1. Task: Work\n', '1').explicit)
        self.assertEqual(lint_todo_text('1. Task: Work\n',workdir=Path.cwd()), [])

    def test_cli_ceiling(self):
        text = '***CFG mcp=issues***\n1. Task: Work\n'
        with self.assertRaises(ResourceError):
            resolve_task_resources(text, '1', mcp=('docs',))
        self.assertEqual(resolve_task_resources(text,'1',mcp=('issues','docs')).mcp,('issues',))

    def test_cli_none_cannot_be_broadened(self):
        with self.assertRaises(ResourceError):
            resolve_task_resources('***DEFAULTS mcp=docs***\n1. Task: W\n','1',mcp=())

    def test_child_inherits_done_parent(self):
        text='***CFG mcp=docs***\n1. DONE: Parent\n\n1.1. Task: Child\n'
        self.assertEqual(resolve_task_resources(text,'1.1').mcp,('docs',))

    def test_child_cannot_broaden_parent(self):
        text='***CFG mcp=docs***\n1. Task: Parent\n\n***CFG mcp=issues***\n1.1. Task: Child\n'
        with self.assertRaises(ResourceError):
            resolve_task_resources(text,'1.1')

    def test_siblings_are_independent(self):
        text='***CFG mcp=none***\n1. Task: A\n\n***CFG mcp=docs***\n2. Task: B\n'
        self.assertEqual(resolve_task_resources(text,'2').mcp,('docs',))

    def test_review_defaults_to_none_with_explicit_production(self):
        self.assertEqual(TaskResources(mcp=('docs',)).review_mcp,())
        self.assertIsNone(TaskResources().review_mcp)

    def test_review_cannot_exceed_production(self):
        with self.assertRaises(ResourceError):
            TaskResources(mcp=('docs',),review_mcp=('issues',))

    def test_explicit_review_only_is_allowed(self):
        self.assertEqual(TaskResources(review_mcp=('docs',)).review_mcp,('docs',))

    def test_hidden_examples_do_not_select_resources(self):
        text='```md\n***DEFAULTS mcp=bad***\n```\n<!-- ***DEFAULTS mcp=bad*** -->\n    ***DEFAULTS mcp=bad***\n1. Task: W\n'
        self.assertEqual(plan_resources(text)[0],{})

    def test_malformed_and_misplaced_defaults(self):
        for text in ('***DEFAULTS***\n1. Task: W\n',
                     '***DEFAULTS mcp=docs mcp=issues***\n1. Task: W\n',
                     '***DEFAULTS command=evil***\n1. Task: W\n',
                     '1. DONE: W\n***DEFAULTS mcp=docs***\n2. Task: X\n',
                     '***DEFAULTS mcp=docs***\n***DEFAULTS skills=foo***\n1. Task: W\n'):
            with self.subTest(text=text):
                self.assertTrue(lint_todo_text(text,workdir=Path.cwd()))

    def test_windows_quote_grammar(self):
        text='***CFG mcp="docs,issues" skills=none***\n1. Task: W\n'
        self.assertEqual(resolve_task_resources(text,'1').mcp,('docs','issues'))


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def skill(self, root, folder='draft', name='draft', body='Write a bounded draft.'):
        p=root/folder/'SKILL.md'; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(f'---\nname: {name}\ndescription: A test skill.\n---\n{body}\n',encoding='utf-8')
        return p

    def test_explicit_skill_is_frozen(self):
        p=self.skill(self.root)
        c=SkillCatalog(workdir=self.root,roots=[self.root])
        initial=c.get(('draft',))[0]
        p.write_text('changed',encoding='utf-8')
        self.assertEqual(c.get(('draft',))[0],initial)
        prompt=bind_resources('Original task',TaskResources(skills=('draft',)),c)
        self.assertIn(initial.sha256,prompt)
        self.assertIn('Write a bounded draft.',prompt)
        self.assertTrue(prompt.endswith('Original task'))

    def test_none_adds_no_skill_and_does_not_scan(self):
        c=SkillCatalog(workdir=self.root,roots=[self.root])
        self.skill(self.root,body='not used')
        with patch.object(c,'_load',side_effect=AssertionError('scanned')):
            self.assertEqual(c.get(()),())
        self.assertEqual(bind_resources('Task',TaskResources(),c),'Task')

    def test_unknown_skill(self):
        with self.assertRaises(ResourceError):
            SkillCatalog(workdir=self.root,roots=[self.root]).get(('missing',))

    def test_duplicate_names_require_disambiguation(self):
        self.skill(self.root,'one','same'); self.skill(self.root,'two','same')
        with self.assertRaises(ResourceError):
            SkillCatalog(workdir=self.root,roots=[self.root]).get(('same',))

    def test_auto_root(self):
        self.skill(self.root/'.agents/skills')
        c=SkillCatalog(workdir=self.root,env={'HOME':str(self.root/'home'),'USERPROFILE':str(self.root/'home')})
        self.assertEqual(c.get(('draft',))[0].name,'draft')

    def test_bom_crlf(self):
        p=self.skill(self.root)
        p.write_bytes(b'\xef\xbb\xbf---\r\nname: draft\r\ndescription: test\r\n---\r\nHello\r\n')
        self.assertIn('Hello',SkillCatalog(workdir=self.root,roots=[self.root]).get(('draft',))[0].text)

    def test_oversized_rejected(self):
        self.skill(self.root,body='x'*65537)
        with self.assertRaises(ResourceError):
            SkillCatalog(workdir=self.root,roots=[self.root]).get(('draft',))

    def test_no_script_execution(self):
        self.skill(self.root,body='Run scripts/check.py')
        script=self.root/'draft/scripts/check.py'; script.parent.mkdir()
        script.write_text('raise RuntimeError("must not execute")')
        self.assertEqual(len(SkillCatalog(workdir=self.root,roots=[self.root]).get(('draft',))),1)


class McpTests(unittest.TestCase):
    def inventory(self, **values):
        return json.dumps([{'name':k,'enabled':v,'transport':{'type':'stdio','env':{'SECRET':'never-log-this'}}}
                           for k,v in values.items()]).encode()

    def test_config_only_booleans_and_portable_names(self):
        values=config_values(('a-b',),('a-b','other'))
        self.assertIn('mcp_servers.a-b.enabled=true',values)
        self.assertIn('mcp_servers.other.enabled=false',values)
        self.assertIn('mcp_servers.other.required=false',values)
        self.assertIn('mcp_servers.a-b.required=true',values)
        self.assertEqual(config_values(None,()),())

    def test_native_inventory_and_filter_verified(self):
        calls=[]
        def probe(args):
            calls.append(args)
            return self.inventory(docs=True,issues=len(calls)==1)
        self.assertEqual(resolve_inventory(('docs',),profile='qa',probe=probe),('docs','issues'))
        self.assertEqual(calls[0][:2],["--profile","qa"])
        self.assertIn('mcp_servers.issues.enabled=false',calls[1])

    def test_dotted_mcp_alias_refused_without_config_injection(self):
        with self.assertRaises(ResourceError):
            config_values(('a.b',), ('a.b', 'other'))
        with self.assertRaises(ResourceError):
            config_values((), ('a.b',))

    def test_none_disables_all_known(self):
        calls=[]
        def probe(args):
            calls.append(args); return self.inventory(docs=len(calls)==1)
        self.assertEqual(resolve_inventory((),profile=None,probe=probe),('docs',))
        self.assertIn('mcp_servers.docs.enabled=false',calls[1])

    def test_unselected_server_remaining_enabled_fails(self):
        with self.assertRaises(ResourceError):
            resolve_inventory(('docs',),profile=None,probe=lambda a:self.inventory(docs=True,other=True))

    def test_missing_and_disabled_fail_without_enabling(self):
        for selected in (('missing',),('docs',)):
            calls=[]
            def probe(a): calls.append(a); return self.inventory(docs=False)
            with self.assertRaises(ResourceError):
                resolve_inventory(selected,profile=None,probe=probe)
            self.assertEqual(len(calls),1)

    def test_changed_inventory_refuses(self):
        values=iter([self.inventory(docs=True),self.inventory(docs=True,new=False)])
        with self.assertRaises(ResourceError):
            resolve_inventory(('docs',),profile=None,probe=lambda a:next(values))

    def test_invalid_inventory_hides_credentials(self):
        for raw in ('never-log-this', '[{"name":"x","enabled":"never-log-this"}]', '{}'):
            with self.assertRaises(ResourceError) as error:
                parse_inventory(raw)
            self.assertNotIn('never-log-this',str(error.exception))

    def test_duplicate_and_unsupported_records_fail(self):
        row={'name':'docs','enabled':True,'transport':{'type':'stdio'}}
        for raw in (json.dumps([row,row]),json.dumps([dict(row,transport={'type':'unknown'})])):
            with self.assertRaises(ResourceError): parse_inventory(raw)

    def test_legacy_does_not_probe(self):
        self.assertEqual(resolve_inventory(None,profile=None,probe=lambda _:self.fail('probe')),())

    def test_transport_arguments_and_provider_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()
            request=CodexExecRequest(prompt='W',cwd=p,env={'EXAMPLE':'same'},raw_log=p/'raw',pretty_log=p/'pretty',
                                     model_provider='gateway',config_profile='qa',mcp_servers=('docs',),mcp_inventory=('docs','issues'))
            argv=build_command(request)
            self.assertIn('mcp_servers.issues.enabled=false',argv)
            self.assertIn('model_provider="gateway"',argv)
            self.assertEqual(argv[argv.index('--profile')+1],'qa')
            self.assertEqual(dict(request.env),{'EXAMPLE':'same'})
            self.assertEqual(argv[-1],'-')

    def test_worker_json_roundtrip(self):
        options=AutoBuildOptions(mcp=('docs','issues'),review_mcp=('docs',),skills=('draft',),skill_dirs=('root',))
        payload=call_payload(task='Work',workdir='.',options=options,context=AutoBuildContext())
        decoded=decode_call(json.loads(json.dumps(payload)))
        self.assertEqual(decoded['options'],options)


if __name__=='__main__': unittest.main()
