# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Real Codex against a loopback fake provider; no real model or credentials.

Tests configured routing, auth and profiles, not Databricks or corporate TLS.
No MCP/tools/hooks are configured in this fixture. Those remain trusted Codex
configuration, not globally suppressed ARQUILO capabilities.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import decide
from decision_request import DecisionRequest
from codex_transport import TransportTimeouts


class FakeProvider(BaseHTTPRequestHandler):
    requests_seen = []
    reject = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_error(404)

    def do_POST(self):
        size = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(size)
        if self.headers.get('Content-Encoding') == 'zstd':
            self.send_error(415, 'Use uncompressed synthetic request')
            return
        request = json.loads(data)
        type(self).requests_seen.append({'path':self.path, 'request':request,
            'authorization':self.headers.get('Authorization'),
            'tenant':self.headers.get('X-Corp-Tenant'), 'fixed':self.headers.get('X-Fixed')})
        if type(self).reject:
            body = b'{"error":{"message":"synthetic provider rejection","type":"invalid_request_error"}}'
            self.send_response(400); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers()
            self.wfile.write(body)
            return
        answer = '{"option":"FOUR","explanation":"Synthetic provider returns 4."}'
        item = {'id':'msg_test','type':'message','role':'assistant','status':'completed',
                'phase':'final_answer','content':[{'type':'output_text','text':answer,'annotations':[]}]}
        events = [
            {'type':'response.created','response':{'id':'resp_test','object':'response','status':'in_progress','output':[]}},
            {'type':'response.output_item.added','output_index':0,'item':dict(item,status='in_progress',content=[])},
            {'type':'response.content_part.added','item_id':'msg_test','output_index':0,'content_index':0,
             'part':{'type':'output_text','text':'','annotations':[]}},
            {'type':'response.output_text.delta','item_id':'msg_test','output_index':0,'content_index':0,'delta':answer},
            {'type':'response.output_text.done','item_id':'msg_test','output_index':0,'content_index':0,'text':answer},
            {'type':'response.content_part.done','item_id':'msg_test','output_index':0,'content_index':0,'part':item['content'][0]},
            {'type':'response.output_item.done','output_index':0,'item':item},
            {'type':'response.completed','response':{'id':'resp_test','object':'response','status':'completed',
                'output':[item], 'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}},
        ]
        body = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
        self.send_response(200); self.send_header('Content-Type','text/event-stream')
        self.send_header('Content-Length',str(len(body))); self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True, type=Path)
    args = parser.parse_args()
    binary = args.codex.resolve(strict=True)
    server = ThreadingHTTPServer(('127.0.0.1',0),FakeProvider)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='arquilo-provider-test-') as temporary:
            base=Path(temporary).resolve(); home=base/'home'; auth=home/'.codex'
            auth.mkdir(parents=True); project=base/'project'; project.mkdir(); tmp=base/'temp';tmp.mkdir()
            source = 'model="corp-default"\nmodel_provider="corp-a"\nmodel_reasoning_effort="low"\n'
            for name in ('corp-a','corp-b'):
                source += f'''\n[model_providers."{name}"]
name = "Loopback synthetic corporate gateway"
base_url = "http://127.0.0.1:{server.server_port}/{name}"
env_key = "COMPANY_TEST_SECRET"
wire_api = "responses"
supports_websockets = false
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 5000
query_params = {{tenant = "test"}}
http_headers = {{"X-Fixed" = "kept"}}
env_http_headers = {{"X-Corp-Tenant" = "COMPANY_TEST_TENANT"}}
'''
            configfile=auth/'config.toml';configfile.write_text(source,encoding='utf-8');before=configfile.read_bytes()
            profile_source=source.replace('corp-default','profile-model').replace('model_provider="corp-a"', 'model_provider="corp-b"').replace('model_reasoning_effort="low"','model_reasoning_effort="medium"')
            profile_file=auth/'fixture.config.toml';profile_file.write_text(profile_source,encoding='utf-8')
            profile_before=profile_file.read_bytes()
            keep={'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','APPDATA','LOCALAPPDATA'}
            env={k.upper():v for k,v in os.environ.items() if k.upper() in keep}
            env.update(HOME=str(home),USERPROFILE=str(home),CODEX_HOME=str(auth),
                       TMPDIR=str(tmp),TEMP=str(tmp),TMP=str(tmp),
                       COMPANY_TEST_SECRET='synthetic-provider-key',COMPANY_TEST_TENANT='synthetic-tenant',
                       NO_PROXY='127.0.0.1,localhost')
            settings=decide.DecisionExecSettings(project_root=project,trusted_codex_home=auth,
                temp_root=tmp,env=env,log_root=base/'logs',launcher=str(binary),
                timeouts=TransportTimeouts(total=25,post_turn_grace=2,kill_grace=1),max_attempts=1)
            cases=((None,None,None,False),('corp-override',None,None,False),
                   (None,'corp-b',None,False),(None,None,'fixture',False),
                   ('override-with-profile','corp-a','fixture',False),(None,None,None,True))
            for number, (model, provider, profile, reject) in enumerate(cases):
                FakeProvider.requests_seen=[];FakeProvider.reject=reject
                req=DecisionRequest(question='What is 2+2?',options=('FOUR','FIVE'),context=(),
                    run_id=f'provider-{number}',task_id='1',phase='test',attempt_id='1',model=model)
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result=decide.run_decision(req,settings=settings,model_provider=provider,config_profile=profile)
                if result.result.valid == reject:
                    if result.directory:
                        for p in result.directory.rglob('stderr.bin'):
                            print(p.read_text(encoding='utf-8',errors='replace')[-6000:])
                        print(result.result)
                    raise AssertionError('Unexpected synthetic-provider decision result')
                seen=FakeProvider.requests_seen
                assert len(seen)==1, f'Expected one local request, got {len(seen)}'
                row=seen[0]
                effective_provider=provider or ('corp-b' if profile else 'corp-a')
                assert row['path'].startswith('/'+effective_provider+'/responses')
                assert 'tenant=test' in row['path']
                assert row['request']['model']==(model or ('profile-model' if profile else 'corp-default'))
                assert row['authorization']=='Bearer synthetic-provider-key'
                assert row['tenant']=='synthetic-tenant' and row['fixed']=='kept'
                assert row['request'].get('reasoning',{}).get('effort')==('medium' if profile else 'low')
                assert configfile.read_bytes()==before and profile_file.read_bytes()==profile_before
                print(json.dumps({'case':number,'status':'PASS','configured_gateway':True,
                                  'model_override':model is not None,'provider_override':provider is not None,
                                  'profile_selected':profile is not None,
                                  'synthetic_rejection':reject,'model_billing':False}))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
