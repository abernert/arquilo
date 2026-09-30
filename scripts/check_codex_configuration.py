# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Opt-in real Codex metadata and synthetic provider-config parsing, no inference."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo_doctor
import codex_transport
import decision_exec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', type=Path, required=True)
    args = parser.parse_args()
    binary = args.codex.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='arquilo-config-compat-') as temporary:
        root = Path(temporary).resolve()
        home, work = root/'home', root/'work'
        config_home = home/'corporate-codex'
        config_home.mkdir(parents=True); work.mkdir()
        keep = {'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','APPDATA','LOCALAPPDATA'}
        env = {key.upper():value for key,value in os.environ.items() if key.upper() in keep}
        env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(config_home),
                   TMPDIR=str(root), TEMP=str(root), TMP=str(root), PYTHONUTF8='1',
                   ARQUILO_SYNTHETIC_PROVIDER_TOKEN='synthetic-not-a-real-token')
        env['PATH'] = str(binary.parent)+os.pathsep+env.get('PATH','')
        report = arquilo_doctor.collect_report(workdir=work,env=env)
        if report['checks_status'] != 'PASS' or report['model_calls'] != 0:
            print(json.dumps({'status':'FAIL','checks':report['checks']},indent=2));return 1
        req = codex_transport.CodexExecRequest(prompt='Not executed.',cwd=work,env=env,
            raw_log=work/'events.jsonl',pretty_log=work/'pretty.log',launcher=(str(binary),),
            decision_only=True,sandbox='read-only')
        argv = codex_transport.build_command(req)
        assert '--model' not in argv and '--ignore-user-config' not in argv
        assert not any(arg.startswith(('model_provider=', 'features.')) for arg in argv)
        assert decision_exec.decision_environment(env,project_root=work) == env
        # Use a loopback-only synthetic endpoint and no actual authentication.
        # features list loads configuration, not a model prompt. Never print its
        # output/config or inherit the runner's real provider keys.
        text = ('model = "fixture-deployment"\nmodel_provider = "databricks_fixture"\n'
                '[model_providers.databricks_fixture]\nname = "Synthetic fixture"\n'
                'base_url = "http://127.0.0.1:9/v1"\nwire_api = "responses"\n'
                'env_key = "ARQUILO_SYNTHETIC_PROVIDER_TOKEN"\n')
        config = config_home/'config.toml';config.write_text(text,encoding='utf-8')
        profile = config_home/'fixture.config.toml'
        profile.write_text('model = "profile-deployment"\n',encoding='utf-8')
        outcomes=[]
        for selectors in ([],['--profile','fixture']):
            result = subprocess.run([str(binary),*selectors,'features','list'],cwd=work,env=env,
                capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
            outcomes.append({'profile':bool(selectors),'returncode':result.returncode})
            if result.returncode:
                print(json.dumps({'status':'FAIL','stage':'synthetic-config-load','results':outcomes,
                    'fixture_error':result.stderr.replace('synthetic-not-a-real-token','<synthetic>')
                    .replace(str(root),'<fixture>')[-1500:]}));return 1
        assert config.read_text(encoding='utf-8') == text
        print(json.dumps({'status':'PASS','python':sys.version.split()[0],
            'codex':report['codex_version'],'configuration_policy':report['configuration_policy'],
            'model_calls':0,'synthetic_config_loads':outcomes},indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
