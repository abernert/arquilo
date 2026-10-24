# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Synthetic CLI protocol fixture; not Claude or a model. No external requests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time

FLAGS = '--print --output-format --verbose --session-id --no-session-persistence --permission-mode --tools --allowedTools --disallowedTools --strict-mcp-config --mcp-config --setting-sources --settings --disable-slash-commands --safe-mode --json-schema --effort'
PASS = {'verdict':'PASS','short_summary':'Verified fixture output.', 'blocking_issues':[],
        'non_blocking_observations':[], 'breakdown_recommended':False,'breakdown_reason':None}
FAIL = {**PASS, 'verdict':'FAIL', 'blocking_issues':[{'id':'ISSUE-1','type':'local_fix',
       'summary':'Required output is missing.','requirement':'Create output.',
       'acceptance_criterion':'The output exists.','references':[], 'fix_suggestion':'Create output.'}]}


def main():
    args=sys.argv[1:]
    mode=os.environ.get('CLAUDE_FIXTURE_MODE','success')
    def arg(name):
        return args[args.index(name)+1]
    if args==['--version']:
        print('2.1.999 (Claude Code)'); return 0
    if args==['--help']:
        print(FLAGS if mode!='old_cli' else '--print --version'); return 0
    sid=arg('--session-id')
    tools=arg('--tools').split(',') if arg('--tools') else []
    prompt=sys.stdin.read()
    audit=Path(os.environ['CLAUDE_FIXTURE_AUDIT'])
    # All fixture launches are sequential except deliberate parallel runner tests.
    with audit.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'argv':args,'cwd':str(Path.cwd()),'session_id':sid,'tools':tools,'prompt':prompt})+'\n')
    def emit(event):
        event['session_id']=sid
        print(json.dumps(event),flush=True)
    # Synthetic 2.1.310 startup metadata. Only the runtime's known builtin
    # identities are included; this does not execute native Claude plugins.
    plugins = []
    if mode == 'builtin_telemetry':
        plugins = [
            {'name': name, 'path': 'builtin', 'source': name + '@builtin'}
            for name in ('cc-plugin-agents-md', 'cc-plugin-telemetry',
                         'cc-plugin-plugin-authoring')
        ]
    elif mode == 'unqualified_builtin':
        plugins = [{'name': 'unexpected-plugin', 'path': 'builtin',
                    'source': 'unexpected-plugin@builtin'}]
    emit({'type':'system','subtype':'init','tools':tools,'mcp_servers':[], 'plugins':plugins,
          'permissionMode':'dontAsk','model':'fixture'})
    if mode in {'thinking_tokens', 'thinking_tokens_extra_field'}:
        # Headless 2.1.310 emits progress frames, not a tool call or answer.
        # Deliberately vary the running estimate to exercise repeated frames.
        for total, increment in ((64, 64), (112, 48)):
            frame={'type':'system', 'subtype':'thinking_tokens', 'uuid':sid,
                   'estimated_tokens':total, 'estimated_tokens_delta':increment}
            if mode=='thinking_tokens_extra_field':
                frame['hook_event']='PreToolUse'  # Must never be ignored.
            emit(frame)
    if mode=='foreign':
        print(json.dumps({'type':'result','session_id':'foreign','subtype':'success','is_error':False,'result':'Done'}),flush=True)
        return 0
    if mode=='invalid_json':
        print('{invalid JSON',flush=True); return 0
    if mode=='duplicate_key':
        print('{"type":"result","type":"assistant","session_id":"'+sid+'"}',flush=True);return 0
    if mode=='tool_violation':
        emit({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Agent','input':{}}]}})
    if mode=='hang':
        time.sleep(30)
    if mode=='missing_result':
        emit({'type':'assistant','message':{'content':[{'type':'text','text':'Done'}]}})
        return 0
    if mode=='long_line':
        print('X'*(9*1024*1024),flush=True);return 0
    if mode=='bad_utf8':
        sys.stdout.buffer.write(b'\xff\n');sys.stdout.buffer.flush();return 0
    if mode=='raw_stderr':
        print('fixture diagnostic',file=sys.stderr)
    structured=None
    if '--json-schema' in args:
        schema=json.loads(arg('--json-schema'))
        options=schema['properties']['option']['enum']
        chosen='FOUR' if 'FOUR' in options else 'COMPLETE' if 'COMPLETE' in options else options[0]
        structured={'option':chosen,'explanation':'Fixture chose the requested option.'}
        if mode=='wrong_option': structured['option']='NOT_AN_OPTION'
        text=''
    elif 'Write' in tools:
        text='Created output and fulfilled the task.'
        Path('hello.txt').write_text('',encoding='utf-8')
    else:
        text=json.dumps(PASS)
        if mode in {'review_fails','fix_cycle'}:
            marker=audit.with_suffix('.reviewed')
            first=not marker.exists();marker.touch()
            if mode=='review_fails' or first: text=json.dumps(FAIL)
        if mode=='legacy_review': text='The actual file has been inspected; all requirements are satisfied.'
        if mode=='review_missing_result': return 0
    event={'type':'result','subtype':'success','is_error':False,'result':text,'permission_denials':[],
           'usage':{'input_tokens':1,'output_tokens':1},'num_turns':1}
    if structured is not None: event['structured_output']=structured
    if mode=='result_error': event.update(subtype='error_during_execution',is_error=True)
    if mode=='truncated': event['stop_reason']='max_tokens'
    if mode=='denied': event['permission_denials']=[{'tool_name':'Bash'}]
    emit(event)
    if mode=='after_result': emit(event)
    if mode=='terminal_hang': time.sleep(30)
    return 7 if mode=='nonzero' else 0


if __name__=='__main__':
    raise SystemExit(main())
