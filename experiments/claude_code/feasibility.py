# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Native CLI + local synthetic provider probe. No model/real credentials.

Opt-in: python experiments/claude_code/feasibility.py --claude /absolute/claude --out /new/path
This measures native adapter contracts, not real-model quality or client residency.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent_types import TransportTimeouts
from claude_transport import ClaudeRequest, execute, probe_cli


class Provider(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        super().__init__(('127.0.0.1',0), Handler)
        self.case='text';self.calls=[];self.outputs=[];self.workspace=None;self.step=0


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_error(404)
    def do_POST(self):
        n=int(self.headers.get('Content-Length',0))
        if n>2*1024*1024:
            self.send_error(413);return
        body=json.loads(self.rfile.read(n))
        server=self.server
        if self.path.split('?')[0] in {'/v1/messages/count_tokens','/v1/messages/count_tokens/'}:
            return self.reply({'input_tokens':10})
        if self.path.split('?')[0]!='/v1/messages' or len(server.calls)>=40:
            self.send_error(400);return
        server.calls.append({'case':server.case,'request':body})
        server.step+=1
        if server.case=='provider_error':
            return self.reply({'type':'error','error':{'type':'invalid_request_error','message':'synthetic provider error'}},400)
        names=[tool['name'] for tool in body.get('tools',[])]
        blocks=[{'type':'text','text':'Synthetic native execution completed.'}]
        stop='end_turn'
        if server.case in {'write','read','forbidden_write'} and server.step==1:
            tool='Read' if server.case=='read' else 'Write'
            inp={'file_path':str(server.workspace/('forbidden.txt' if server.case=='forbidden_write' else 'hello.txt'))}
            if tool=='Write':inp['content']='native fixture\n'
            blocks=[{'type':'tool_use','id':'toolu_fixture_1','name':tool,'input':inp}];stop='tool_use'
        elif server.case=='structured':
            result={'option':'FOUR','explanation':'Synthetic structured fixture.'}
            if 'StructuredOutput' in names and server.step==1:
                blocks=[{'type':'tool_use','id':'toolu_structured_1','name':'StructuredOutput','input':result}]
                stop='tool_use'
            else:
                blocks=[{'type':'text','text':json.dumps(result)}]
        reply={'id':'msg_fixture_'+str(len(server.calls)),'type':'message','role':'assistant',
            'model':body.get('model','fixture'),'content':blocks,'stop_reason':stop,'stop_sequence':None,
            'usage':{'input_tokens':10,'output_tokens':10}}
        server.outputs.append({'case':server.case,'response':reply})
        if not body.get('stream'):return self.reply(reply)
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        def event(kind,data):
            self.wfile.write(('event: '+kind+'\ndata: '+json.dumps({'type':kind,**data})+'\n\n').encode());self.wfile.flush()
        start={**reply,'content':[],'stop_reason':None};event('message_start',{'message':start})
        for i,block in enumerate(blocks):
            empty={**block,**({'text':''} if block['type']=='text' else {'input':{}})}
            event('content_block_start',{'index':i,'content_block':empty})
            delta=({'type':'text_delta','text':block['text']} if block['type']=='text' else
                   {'type':'input_json_delta','partial_json':json.dumps(block['input'])})
            event('content_block_delta',{'index':i,'delta':delta});event('content_block_stop',{'index':i})
        event('message_delta',{'delta':{'stop_reason':stop,'stop_sequence':None},'usage':{'output_tokens':10}})
        event('message_stop',{})
    def reply(self,body,status=200):
        data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)


def main():
    p=argparse.ArgumentParser();p.add_argument('--claude',required=True);p.add_argument('--out',required=True)
    args=p.parse_args();binary=Path(args.claude).resolve(strict=True);root=Path(args.out).resolve();root.mkdir(parents=True,exist_ok=False)
    work=root/'workspace';work.mkdir();logs=root/'logs';logs.mkdir();home=root/'home';home.mkdir()
    # Deliberately constructed isolated environment: no ambient client credentials,
    # provider keys, proxy overrides, shell hooks, npm scripts or tokens are copied.
    env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TMP','TEMP','TMPDIR','LANG','LC_ALL'}}
    env.update(HOME=str(home),USERPROFILE=str(home),CLAUDE_CONFIG_DIR=str(home/'.claude'),
        ARQUILO_CLAUDE_CODE_COMMAND=str(binary),ANTHROPIC_API_KEY='SYNTHETIC_LOCAL_FIXTURE_KEY',
        DISABLE_TELEMETRY='1',DISABLE_ERROR_REPORTING='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
        CLAUDE_CODE_DISABLE_AUTO_UPDATE='1',NO_PROXY='127.0.0.1,localhost')
    report={'status':'RUNNING','native_cli':str(binary),'real_model_calls':0,'tests':[],
            'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'limitations':['No real model or client authentication tested','No general OS sandbox certification']}
    server=Provider();server.workspace=work;env['ANTHROPIC_BASE_URL']=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def save(name,value):(root/name).write_text(json.dumps(value,indent=2,default=str)+'\n')
    try:
        report['metadata']=probe_cli(cwd=work,env=env,require_schema=True)
        if report['metadata']['status']!='PASS':raise RuntimeError('Native metadata contract failed')
        schema=logs/'schema.json';schema.write_text(json.dumps({'type':'object','properties':{
            'option':{'type':'string','enum':['FOUR','FIVE']},'explanation':{'type':'string'}},
            'required':['option','explanation'],'additionalProperties':False}))
        for case in ('text','write','read','structured','provider_error','forbidden_write'):
            server.case=case;server.step=0
            before=len(server.calls)
            request=ClaudeRequest(prompt='Synthetic contract test '+case+'. Follow the requested local fixture actions.',
                cwd=work,env=env,raw_log=logs/(case+'.jsonl'),pretty_log=logs/(case+'.log'),
                model='claude-sonnet-4-5-20250929',phase=case,
                sandbox='workspace-write' if case=='write' else 'read-only',
                decision_only=case in {'structured','forbidden_write'},
                output_schema=schema if case=='structured' else None,
                timeouts=TransportTimeouts(total=35,stall=20,kill_grace=1,post_turn_grace=5))
            result=execute(request)
            ok=(not result.execution.succeeded) if case in {'provider_error','forbidden_write'} else result.execution.succeeded
            if case=='write':ok=ok and (work/'hello.txt').read_text()=='native fixture\n'
            if case=='structured':ok=ok and json.loads(result.execution.answer).get('option')=='FOUR'
            if case=='read':ok=ok and any('native fixture' in json.dumps(row['request'].get('messages')) for row in server.calls[before:])
            if case=='forbidden_write':ok=ok and not (work/'forbidden.txt').exists()
            report['tests'].append({'name':case,'status':'PASS' if ok else 'FAIL','provider_requests':len(server.calls)-before,
                                    'execution':asdict(result.execution),'capture':str(result.trace.capture_dir)})
            save('report.json',report)
            print(case,report['tests'][-1]['status'],flush=True)
        report['status']='PASS' if all(row['status']=='PASS' for row in report['tests']) else 'FAIL'
    except Exception as exc:
        report.update(status='FAIL',error=f'{type(exc).__name__}: {exc}')
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
        # Requests are synthetic. Auth headers/environment are never archived.
        save('provider-requests.json',server.calls);save('provider-responses.json',server.outputs)
        report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());save('report.json',report)
    print(json.dumps(report,indent=2,default=str));return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
