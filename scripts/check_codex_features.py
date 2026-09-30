# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Opt-in installed-CLI metadata check: no authentication or model calls."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arquilo_doctor
import codex_policy
import codex_transport


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', type=Path, required=True)
    parser.add_argument('--expect-daemon', choices=('present', 'absent'), required=True)
    args = parser.parse_args()
    binary = args.codex.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='arquilo-compat-') as temporary:
        root = Path(temporary).resolve()
        home, work = root/'home', root/'work'
        auth = home/'.codex'
        auth.mkdir(parents=True); work.mkdir()
        # Do not inherit provider keys/tokens/profiles, or edit the caller's home.
        keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'APPDATA', 'LOCALAPPDATA'}
        env = {key.upper(): value for key, value in os.environ.items() if key.upper() in keep}
        env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(auth),
                   TMPDIR=str(root), TEMP=str(root), TMP=str(root), PYTHONUTF8='1')
        env['PATH'] = str(binary.parent) + os.pathsep + env.get('PATH', '')
        report = arquilo_doctor.collect_report(workdir=work, env=env)
        print(json.dumps({'python': sys.version.split()[0], 'codex': report['codex_version'],
                          'checks_status': report['checks_status'], 'model_calls': report['model_calls'],
                          'checks': report['checks'], 'features': report['decision_feature_details']}, indent=2))
        if report['checks_status'] != 'PASS' or report['model_calls'] != 0:
            return 1
        absent = args.expect_daemon == 'absent'
        row = report['decision_feature_details']['daemon_auto_start']
        if row['status'] != ('unavailable_optional' if absent else 'verified'):
            return 1
        selected = tuple(name for name, row in report['decision_feature_details'].items() if row['available'])
        request = codex_transport.CodexExecRequest(prompt='Not executed.', cwd=work, env=env,
                   raw_log=work/'events.jsonl', pretty_log=work/'pretty.log',
                   launcher=(str(binary),), decision_only=True)
        command = codex_transport.build_command(request, decision_features=selected)
        if ('features.daemon_auto_start=false' in command) == absent:
            return 1
        if not {'--strict-config', '--ignore-user-config', 'features.shell_tool=false'}.issubset(command):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
