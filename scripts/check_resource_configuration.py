# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Native MCP config/start checks with synthetic servers and loopback-only model.

No real model credentials, client MCP services or provider billing.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from mcp_selection import resolve_inventory
from task_resources import ResourceError


def check(codex: str) -> dict:
    codex = str(Path(codex).resolve())
    with tempfile.TemporaryDirectory(prefix="arquilo-mcp-metadata-") as tmp:
        root = Path(tmp)
        home = root / "codex-home"
        home.mkdir()
        marker = root / "unexpected-tool-start"
        command = "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"
        config = "model = \"synthetic-model\"\n"
        for name, enabled in (("issues", True), ("docs", True), ("disabled", False)):
            config += "\n[mcp_servers." + json.dumps(name) + "]\n"
            config += "command = " + json.dumps(sys.executable) + "\n"
            config += "args = " + json.dumps(["-c", command]) + "\n"
            config += "enabled = " + str(enabled).lower() + "\n"
        profile_path = home / "qa.config.toml"
        profile_text = config.replace("synthetic-model", "synthetic-qa")
        profile_text += '\n[mcp_servers.profile-only]\ncommand = ' + json.dumps(sys.executable) + '\nargs = ' + json.dumps(["-c", command]) + '\nenabled = true\n'
        profile_path.write_text(profile_text, encoding="utf-8")
        profile_original = profile_path.read_bytes()
        path = home / "config.toml"
        path.write_text(config, encoding="utf-8")
        original = path.read_bytes()
        env = dict(os.environ, CODEX_HOME=str(home))
        # Never inherit production model credentials into a synthetic fixture.
        for key in tuple(env):
            if key.endswith(("API_KEY", "ACCESS_TOKEN", "SUBSCRIPTION_KEY")):
                env.pop(key)
        calls = []

        def probe(args):
            calls.append(args)
            result = subprocess.run([codex, *args], cwd=root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=35, check=False)
            if result.returncode:
                raise RuntimeError("Native synthetic MCP inventory failed: " +
                                   result.stderr.decode("utf-8", errors="replace")[-3000:])
            return result.stdout

        for profile in (None, "qa"):
            for selected in ((), ("issues",), ("docs",), ("docs", "issues")):
                known = resolve_inventory(selected, profile=profile, probe=probe)
                expected = {"issues", "docs", "disabled"} | ({"profile-only"} if profile else set())
                if set(known) != expected:
                    raise AssertionError("Inventory lost a configured server")
        try:
            resolve_inventory(("disabled",), profile=None, probe=probe)
        except ResourceError:
            pass
        else:
            raise AssertionError("A task re-enabled an operator-disabled server")
        if path.read_bytes() != original or profile_path.read_bytes() != profile_original:
            raise AssertionError("Codex configuration was rewritten")
        if marker.exists():
            raise AssertionError("Metadata inspection started an MCP tool")
        return {"status": "PASS", "native_selections": 8, "metadata_calls": len(calls),
                "global_config_unchanged": True, "no_tool_processes": True,
                "live_model_calls": 0}


def check_execution(codex: str) -> dict:
    """Start only selected synthetic MCPs; the model provider is loopback-only."""
    from contextlib import redirect_stdout, redirect_stderr
    from http.server import ThreadingHTTPServer
    import io
    import threading
    from scripts.check_codex_provider import FakeProvider
    from codex_transport import CodexExecRequest, TransportTimeouts, execute
    from runtime_contracts import ExecutionStatus
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='arquilo-resource-exec-') as tmp:
            root = Path(tmp).resolve()
            home, work, logs = root/'home', root/'work', root/'logs'
            auth = home/'.codex'
            for path in (auth, work, logs):
                path.mkdir(parents=True)
            stub = root/'synthetic_mcp.py'
            stub.write_text('''import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text("started")
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "synthetic", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": []}
    elif method == "resources/list":
        result = {"resources": []}
    elif method == "prompts/list":
        result = {"prompts": []}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
''', encoding='utf-8')
            source = ('model="synthetic-model"\nmodel_provider="loopback"\nmodel_reasoning_effort="low"\n'
                      '[model_providers.loopback]\nname="Synthetic loopback only"\n'
                      f'base_url="http://127.0.0.1:{server.server_port}/v1"\n'
                      'wire_api="responses"\nenv_key="ARQUILO_FIXTURE_KEY"\n'
                      'requires_openai_auth=false\nsupports_websockets=false\n'
                      'request_max_retries=0\nstream_max_retries=0\nstream_idle_timeout_ms=5000\n')
            markers = {name:root/(name+'-started') for name in ('issues', 'docs')}
            for name, marker in markers.items():
                source += '\n[mcp_servers.' + name + ']\ncommand=' + json.dumps(sys.executable) + '\nargs=' + json.dumps(['-u', str(stub), str(marker)]) + '\nenabled=true\n'
            # Pre-trust only this synthetic workspace, so native first-use trust
            # bookkeeping cannot be confused with a resource config rewrite.
            source += '\n[projects.' + json.dumps(str(work)) + ']\ntrust_level = "trusted"\n'
            config = auth/'config.toml'
            config.write_text(source, encoding='utf-8')
            profile = auth/'qa.config.toml'
            profile.write_text(source.replace('synthetic-model', 'profile-model'), encoding='utf-8')
            original = (config.read_bytes(), profile.read_bytes())
            keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'APPDATA', 'LOCALAPPDATA'}
            env = {key.upper():value for key,value in os.environ.items() if key.upper() in keep}
            env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(auth),
                       TMPDIR=str(root), TEMP=str(root), TMP=str(root),
                       ARQUILO_FIXTURE_KEY='synthetic-not-a-real-key', NO_PROXY='127.0.0.1,localhost', PYTHONUTF8='1')
            cases = (((), None, 'workspace-write'), (('issues',), None, 'workspace-write'),
                     (('docs',), 'qa', 'read-only'))
            for index, (selected, config_profile, sandbox) in enumerate(cases):
                for marker in markers.values():
                    marker.unlink(missing_ok=True)
                FakeProvider.requests_seen = []
                FakeProvider.reject = False
                request = CodexExecRequest(prompt='Return FOUR as a synthetic test answer. Do not use tools.', cwd=work,
                    env=env, raw_log=logs/f'{index}.jsonl', pretty_log=logs/f'{index}.log',
                    launcher=(str(Path(codex).resolve()),), config_profile=config_profile,
                    mcp_servers=selected, sandbox=sandbox,
                    timeouts=TransportTimeouts(total=30, post_turn_grace=2, kill_grace=1))
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = execute(request)
                if result.execution.status is not ExecutionStatus.SUCCEEDED:
                    raise AssertionError(f'Synthetic selected-MCP execution failed: {result.execution}')
                started = {name for name, marker in markers.items() if marker.exists()}
                if started != set(selected):
                    raise AssertionError(f'MCP processes do not match selection: selected={selected}, started={started}')
                if len(FakeProvider.requests_seen) != 1:
                    raise AssertionError('Unexpected loopback provider call count')
                expected_model = 'profile-model' if config_profile else 'synthetic-model'
                if FakeProvider.requests_seen[0]['request']['model'] != expected_model:
                    raise AssertionError('MCP filtering changed the selected model profile')
                if (config.read_bytes(), profile.read_bytes()) != original:
                    raise AssertionError('Global or profile configuration changed')
            return {'status':'PASS', 'native_execution_cases':len(cases),
                    'exact_mcp_process_selection':True, 'live_model_calls':0,
                    'synthetic_loopback_requests':len(cases)}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.codex)))
    print(json.dumps(check_execution(args.codex)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
