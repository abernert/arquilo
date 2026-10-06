# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Standalone OpenCode 1.18.34 spike; canned loopback provider, never a real LLM.

Not an ARQUILO backend. Only synthetic disposable files and owned processes.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

VERSION = '1.18.34'
LIMIT = 8 * 1024 * 1024
EXPECTED = {'answer': 42}
SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'integer', 'const': 42}},
          'required': ['answer'], 'additionalProperties': False}


def require(value, message):
    if not value:
        raise AssertionError(message)


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


def terminal(message, session):
    """An idle event alone is NOT success, nor is an arbitrary last text part."""
    info = message.get('info', {})
    tools = [p for p in message.get('parts', []) if p.get('type') == 'tool']
    structured_finish = (info.get('finish') == 'tool-calls' and info.get('structured') is not None
                         and bool(tools) and all(p.get('tool') == 'StructuredOutput'
                         and p.get('state', {}).get('status') == 'completed' for p in tools))
    return (info.get('role') == 'assistant' and info.get('sessionID') == session
            and bool(info.get('time', {}).get('completed')) and not info.get('error')
            and (info.get('finish') == 'stop' or structured_finish)
            and all(p.get('state', {}).get('status') not in ('pending', 'running') for p in tools))


def test_environment(root):
    # Test-fixture isolation only: intentionally do not copy personal provider credentials.
    # Admin-managed OpenCode policy is NOT disabled or bypassed.
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE',
            'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    locations = {'HOME': 'home', 'USERPROFILE': 'home', 'XDG_CONFIG_HOME': 'config',
                 'XDG_DATA_HOME': 'data', 'XDG_CACHE_HOME': 'cache', 'XDG_STATE_HOME': 'state',
                 'APPDATA': 'appdata', 'LOCALAPPDATA': 'localappdata', 'TEMP': 'tmp',
                 'TMP': 'tmp', 'TMPDIR': 'tmp'}
    for key, child in locations.items():
        target = root / child
        target.mkdir(exist_ok=True)
        env[key] = str(target)
    env.update(NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost',
               DO_NOT_TRACK='1', NO_COLOR='1')
    return env


class Fixture(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, work, logs):
        super().__init__(('127.0.0.1', 0), FixtureHandler)
        self.work, self.logs = work, logs
        self.lock = threading.Lock()
        self.counts = {}
        self.abort_seen = threading.Event()
        self.release_wait = threading.Event()
        self.records = []


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            require(0 < n <= LIMIT, 'Unexpected provider request size')
            body = json.loads(self.rfile.read(n))
            messages = body.get('messages', [])
            users = [m.get('content') for m in messages if m.get('role') == 'user']
            found = re.findall(r'SPIKE_CASE=([a-z_]+)', json.dumps(users))
            case = found[-1] if found else 'auxiliary'
            with self.server.lock:
                seq = len(self.server.records) + 1
                self.server.counts[case] = self.server.counts.get(case, 0) + 1
                self.server.records.append({'n': seq, 'case': case, 'path': self.path,
                                            'body': body})
                save(self.server.logs / 'provider-requests.json', self.server.records)
            require(seq <= 40, 'Fixture runaway: more than 40 synthetic requests')
            require(self.path == '/v1/chat/completions', 'Unexpected provider endpoint: ' + self.path)
            if case == 'provider_error':
                raw = json.dumps({'error': {'message': 'SPIKE_EXPECTED_PROVIDER_ERROR',
                                           'type': 'invalid_request_error'}}).encode()
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            def emit(delta, finish=None):
                payload = {'id': f'chatcmpl-spike-{seq}', 'object': 'chat.completion.chunk',
                           'created': 1, 'model': body.get('model', 'fixture'),
                           'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                self.wfile.flush()
            emit({'role': 'assistant'})
            if case == 'abort':
                self.server.abort_seen.set()
                while not self.server.release_wait.wait(0.2):
                    self.wfile.write(b': waiting for controlled abort\n\n'); self.wfile.flush()
                return
            had_tool = any(m.get('role') == 'tool' for m in messages)
            tool = None
            if case == 'structured' and not had_tool:
                available = [t.get('function', {}).get('name') for t in body.get('tools', [])]
                if 'StructuredOutput' in available:
                    tool = ('StructuredOutput', EXPECTED)
            elif case in ('read', 'write', 'deny', 'ask') and not had_tool:
                if case == 'read':
                    tool = ('read', {'filePath': str(self.server.work / 'input.txt')})
                else:
                    target = 'output.txt' if case == 'write' else case + '-forbidden.txt'
                    tool = ('write', {'filePath': str(self.server.work / target),
                                      'content': 'fixture-produced\n'})
            if tool:
                emit({'tool_calls': [{'index': 0, 'id': f'call_{seq}', 'type': 'function',
                                     'function': {'name': tool[0], 'arguments': json.dumps(tool[1])}}]})
                emit({}, 'tool_calls')
            else:
                emit({'content': 'SPIKE_OK_' + case})
                emit({}, 'stop')
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            with self.server.lock:
                self.server.records.append({'fixture_error': repr(exc)})
                save(self.server.logs / 'provider-requests.json', self.server.records)
            self.close_connection = True


class Client:
    def __init__(self, url, password):
        self.url = url
        self.logs = None
        self.auth = 'Basic ' + base64.b64encode(('opencode:' + password).encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def open(self, path, method='GET', data=None, timeout=30, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['Authorization'] = self.auth
        request = urllib.request.Request(self.url + path, headers=headers, method=method,
                    data=None if data is None else json.dumps(data).encode())
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read(LIMIT + 1)
            detail = {'path': path, 'method': method, 'status': exc.code,
                      'body': raw[:LIMIT].decode('utf-8', errors='replace')}
            if self.logs is not None:
                save(self.logs / ('http-error-' + str(time.time_ns()) + '.json'), detail)
            # Keep HTTPError identity for the expected unauthenticated-401 probe.
            exc.msg = str(exc.reason) + ' ' + detail['body'][:2000]
            raise

    def call(self, path, method='GET', data=None, timeout=30):
        with self.open(path, method, data, timeout) as response:
            raw = response.read(LIMIT + 1)
            require(len(raw) <= LIMIT, 'Oversized API response')
            return json.loads(raw) if raw else None


class Events:
    def __init__(self, client, path):
        self.client, self.path = client, path
        self.rows, self.errors = [], []
        self.ready, self.stop = threading.Event(), threading.Event()
        self.response = None
        self.thread = threading.Thread(target=self.read, daemon=True)

    def read(self):
        try:
            with self.client.open('/event', timeout=120) as response:
                self.response = response
                with self.path.open('w', encoding='utf-8') as output:
                    total, fields = 0, []
                    self.ready.set()
                    while not self.stop.is_set():
                        raw = response.readline(LIMIT + 1)
                        if not raw:
                            break
                        total += len(raw)
                        require(total <= LIMIT, 'Oversized event stream')
                        line = raw.decode('utf-8').rstrip('\r\n')
                        if line.startswith('data:'):
                            fields.append(line[5:].lstrip())
                        elif not line and fields:
                            event = json.loads('\n'.join(fields)); fields = []
                            self.rows.append(event)
                            output.write(json.dumps(event, ensure_ascii=True) + '\n'); output.flush()
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(repr(exc))
            self.ready.set()

    def start(self):
        self.thread.start()
        require(self.ready.wait(30) and not self.errors, 'Cannot subscribe to SSE: ' + repr(self.errors))

    def close(self):
        self.stop.set()
        # Own server termination closes this stream; never dispose a shared instance.
        self.thread.join(timeout=3)


def configuration(port):
    base = {'mode': 'primary', 'steps': 4}
    return {
        'model': 'spike/fixture', 'small_model': 'spike/fixture', 'enabled_providers': ['spike'],
        'provider': {'spike': {'npm': '@ai-sdk/openai-compatible', 'name': 'Loopback fixture',
            'options': {'baseURL': f'http://127.0.0.1:{port}/v1', 'apiKey': 'synthetic-not-a-secret'},
            'models': {'fixture': {'name': 'Canned transport fixture', 'tool_call': True,
                        'limit': {'context': 131072, 'output': 4096}}}}},
        'autoupdate': False, 'share': 'disabled', 'snapshot': False,
        'lsp': False, 'formatter': False, 'mcp': {}, 'plugin': [],
        'compaction': {'auto': False}, 'default_agent': 'spike_read',
        'permission': {'*': 'deny'},
        'agent': {
            'spike_read': {**base, 'permission': {'*': 'deny', 'read': 'allow'}},
            'spike_write': {**base, 'permission': {'*': 'deny', 'read': 'allow', 'edit': 'allow'}},
            'spike_ask': {**base, 'permission': {'*': 'deny', 'read': 'allow', 'edit': 'ask'}},
            'spike_decide': {**base, 'permission': {'*': 'deny', 'StructuredOutput': 'allow'}},
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--opencode', required=True, help='Approved native executable, not a .cmd/.ps1 wrapper')
    parser.add_argument('--out', required=True, type=Path, help='New diagnostic directory; must not exist')
    args = parser.parse_args(argv)
    binary = shutil.which(args.opencode) or str(Path(args.opencode).expanduser().resolve())
    require(Path(binary).is_file(), 'OpenCode executable was not found')
    require(Path(binary).suffix.lower() not in ('.cmd', '.bat', '.ps1'), 'Use the native opencode executable')
    root = args.out.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    work = root / 'workspace with spaces'; work.mkdir()
    logs = root / 'logs'; logs.mkdir()
    (work / 'input.txt').write_text('ARQUILO synthetic input: ü €\n', encoding='utf-8')
    env = test_environment(root)
    report = {'schema_version': 'arquilo.opencode.spike.v1', 'status': 'RUNNING',
              'expected_version': VERSION, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'platform': sys.platform, 'python': sys.version.split()[0], 'tests': [],
              'scope': 'Real OpenCode / canned local provider. No real model, ARQUILO integration or sandbox certification.'}
    fixture, process, events, handles = None, None, None, []
    sessions = []
    def check(name, fn, *, critical=False):
        try:
            detail = fn()
            report['tests'].append({'name': name, 'status': 'PASS', 'detail': detail})
            print('PASS', name, flush=True)
        except Exception as exc:
            report['tests'].append({'name': name, 'status': 'FAIL', 'detail': repr(exc)})
            print('FAIL', name, repr(exc), flush=True)
            if critical:
                raise
        finally:
            save(root / 'report.json', report)
    try:
        result = subprocess.run([binary, '--version'], cwd=work, env=env,
                      capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
        report['version'] = result.stdout.strip()
        require(report['version'] == VERSION, f'Expected reviewed OpenCode {VERSION}; got {report["version"]!r}')
        report['executable_sha256'] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        fixture = Fixture(work, logs)
        threading.Thread(target=fixture.serve_forever, daemon=True).start()
        config = configuration(fixture.server_port)
        config_path = root / 'fixture-opencode.json'; save(config_path, config)
        env['OPENCODE_CONFIG'] = str(config_path)
        password = secrets.token_urlsafe(24)
        env['OPENCODE_SERVER_PASSWORD'] = password
        env['OPENCODE_SERVER_USERNAME'] = 'opencode'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        # Bind race is detected by process exit/authenticated health; no existing server is reused.
        handles = [(logs / 'server.stdout').open('wb'), (logs / 'server.stderr').open('wb')]
        process = subprocess.Popen([binary, 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
                    cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=handles[0], stderr=handles[1],
                    start_new_session=os.name != 'nt')
        client = Client(f'http://127.0.0.1:{port}', password)
        client.logs = logs
        deadline = time.monotonic() + 60
        while True:
            require(process.poll() is None, 'OpenCode server exited; see logs/server.stderr')
            try:
                health = client.call('/global/health', timeout=2)
                if health.get('healthy') is True:
                    break
            except (OSError, ValueError):
                pass
            require(time.monotonic() < deadline, 'Server startup timed out')
            time.sleep(0.2)
        def infrastructure():
            require(health.get('version') == VERSION, 'Server/CLI version mismatch')
            try:
                with client.open('/session', auth=False):
                    raise AssertionError('Protected endpoint accepted an unauthenticated request')
            except urllib.error.HTTPError as exc:
                require(exc.code == 401, 'Expected 401 for unauthenticated request')
            spec = client.call('/doc'); save(logs / 'openapi.json', spec)
            require('paths' in spec, 'No native OpenAPI document')
            effective = client.call('/config')
            require(effective.get('model') == 'spike/fixture', 'Fixture model overridden; do not continue')
            require(effective.get('small_model') == 'spike/fixture', 'Auxiliary model is not the fixture')
            require(not effective.get('mcp') and not effective.get('plugin'), 'Unexpected MCP/plugin configuration')
            provider = effective.get('provider', {}).get('spike', {})
            require(provider.get('options', {}).get('baseURL') == config['provider']['spike']['options']['baseURL'],
                    'Provider URL changed; do not continue')
            return {'healthy': health, 'openapi_sha256': hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()}
        check('authenticated_native_api_and_fixture_config', infrastructure, critical=True)
        events = Events(client, logs / 'events.jsonl'); events.start()
        def new_session(case):
            session = client.call('/session', 'POST', {'title': 'ARQUILO spike ' + case})['id']
            sessions.append(session)
            return session
        def start(case, agent='spike_read', extra=None):
            session = new_session(case)
            body = {'agent': agent, 'parts': [{'type': 'text', 'text': 'SPIKE_CASE=' + case}]}
            if extra:
                body.update(extra)
            # Deliberately OMIT model; test native configured default inheritance.
            save(logs / (case + '-request.json'), {'session': session, 'body': body})
            return session, body
        def all_messages(session):
            messages = client.call(f'/session/{session}/message')
            save(logs / (session + '-messages.json'), messages)
            return messages
        def run_case(case, agent='spike_read', extra=None):
            session, body = start(case, agent, extra)
            message = client.call(f'/session/{session}/message', 'POST', body, timeout=40)
            save(logs / (case + '-response.json'), message)
            require(terminal(message, session), 'No verified terminal assistant: ' + json.dumps(message.get('info')))
            stored = all_messages(session)
            require(any(m['info']['id'] == message['info']['id'] for m in stored), 'Response not persisted in its session')
            return session, message, stored
        def text():
            session, message, _ = run_case('text')
            require(any(p.get('text') == 'SPIKE_OK_text' for p in message['parts']), 'Text roundtrip mismatch')
            return {'session': session, 'message': message['info']['id']}
        check('text_and_session_result_correlation', text)
        def tool_roundtrip(case, agent):
            session, message, stored = run_case(case, agent)
            parts = [p for m in stored for p in m['parts'] if p.get('type') == 'tool']
            require(any(p['state']['status'] == 'completed' for p in parts), 'No completed native tool')
            if case == 'read':
                require('synthetic input' in json.dumps(parts), 'Read did not return actual fixture content')
            else:
                require((work / 'output.txt').read_text() == 'fixture-produced\n', 'Native write did not produce file')
            require(any(m.get('role') == 'tool' for r in fixture.records if r.get('case') == case
                        for m in r.get('body', {}).get('messages', [])), 'Tool result not sent back to provider')
            return {'session': session, 'tools': [p.get('tool') for p in parts]}
        check('native_read_tool_roundtrip', lambda: tool_roundtrip('read', 'spike_read'))
        check('native_write_tool_roundtrip', lambda: tool_roundtrip('write', 'spike_write'))
        def structured():
            session, message, stored = run_case('structured', 'spike_decide',
                      {'format': {'type': 'json_schema', 'schema': SCHEMA, 'retryCount': 0}})
            result = message['info'].get('structured')
            require(isinstance(result, dict) and set(result) == {'answer'} and type(result['answer']) is int
                    and result == EXPECTED, 'Structured result was missing or invalid')
            parts = [p for m in stored for p in m['parts'] if p.get('type') == 'tool']
            require(all(p.get('tool') == 'StructuredOutput' for p in parts), 'Business tool invoked in decision role')
            return {'session': session, 'structured': result, 'observed_tools': [p.get('tool') for p in parts]}
        check('structured_output_without_business_tools', structured)
        def denied():
            session, _, stored = run_case('deny')
            require(not (work / 'deny-forbidden.txt').exists(), 'Read role wrote forbidden file')
            parts = [p for m in stored for p in m['parts'] if p.get('type') == 'tool']
            require(any(p.get('state', {}).get('status') == 'error' for p in parts), 'No explicit denied/unknown tool result')
            return {'session': session, 'failure_tools': [p.get('tool') for p in parts]}
        check('denied_write_has_no_side_effect', denied)
        def provider_error():
            session, body = start('provider_error')
            message = client.call(f'/session/{session}/message', 'POST', body, timeout=40)
            save(logs / 'provider_error-response.json', message)
            require(message.get('info', {}).get('error'), 'Provider error was hidden')
            require(not terminal(message, session), 'Provider error was accepted as success')
            return {'session': session, 'error': message['info']['error']}
        check('provider_error_is_not_success', provider_error)
        def abort(case, agent):
            session, body = start(case, agent)
            client.call(f'/session/{session}/prompt_async', 'POST', body)
            end = time.monotonic() + 20
            while True:
                if case == 'abort' and fixture.abort_seen.is_set():
                    break
                if case == 'ask' and any(e.get('type') in ('permission.asked', 'permission.updated')
                       and e.get('properties', {}).get('sessionID') == session for e in events.rows):
                    break
                require(time.monotonic() < end, 'No active request / permission event before abort')
                time.sleep(0.1)
            require(client.call(f'/session/{session}/abort', 'POST') is True, 'Abort not acknowledged')
            end = time.monotonic() + 15
            while True:
                messages = all_messages(session)
                errors = [m['info']['error'] for m in messages if m['info'].get('error')]
                statuses = client.call('/session/status')
                idle = session not in statuses or statuses[session].get('type') == 'idle'
                if errors and idle:
                    break
                require(time.monotonic() < end, 'Abort did not reach terminal error/idle state')
                time.sleep(0.1)
            require(not any(terminal(m, session) for m in messages), 'Aborted session looked successful')
            require(not (work / 'ask-forbidden.txt').exists(), 'Pending permission was silently granted')
            return {'session': session, 'errors': errors, 'idle': idle}
        check('permission_request_can_be_aborted_without_autoapproval', lambda: abort('ask', 'spike_ask'))
        check('inflight_provider_request_can_be_aborted', lambda: abort('abort', 'spike_read'))
        time.sleep(0.3)
        require(events.rows and not events.errors, 'Missing or failed event capture')
        require(any(e.get('type') == 'message.updated' for e in events.rows), 'No message SSE events')
        report['event_types'] = sorted({e.get('type', '') for e in events.rows})
        report['provider_request_counts'] = fixture.counts
        require(not any('fixture_error' in r for r in fixture.records), 'Canned provider failed')
        report['status'] = 'PASS' if all(t['status'] == 'PASS' for t in report['tests']) else 'FAIL'
    except BaseException as exc:
        report['status'] = 'FAIL'
        report['failure'] = repr(exc)
        print('Diagnostic failure:', repr(exc), flush=True)
    finally:
        if fixture:
            fixture.release_wait.set()
        if events:
            events.stop.set()
        if process and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=15, check=False)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        if events:
            events.close()
        for handle in handles:
            handle.close()
        if fixture:
            fixture.shutdown(); fixture.server_close()
        report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        save(root / 'report.json', report)
        print('Report:', root / 'report.json', flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
