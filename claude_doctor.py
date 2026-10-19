# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Claude-specific local capability report; no Codex executable or credentials."""
from __future__ import annotations
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import sys

from agent_types import TransportTimeouts
from claude_transport import probe_cli
from controller_state import default_state_root


def collect_report(*, workdir=None, todo_file=None, env=None, check_decide=False,model=None,
                   reasoning_effort=None, decide_timeout=120, **unused):
    from decision_exec import DecisionExecSettings, execute_decision
    from decision_request import DecisionRequest
    environment=dict(os.environ if env is None else env)
    workspace=Path(workdir or (Path(todo_file).parent if todo_file else Path.cwd())).expanduser().resolve()
    report={"schema_version":"arquilo.claude_code.doctor.v1", "backend":"claude-code", "status":"FAIL",
        "checks_status":"FAIL", "arquilo_version":(Path(__file__).parent/'VERSION').read_text().strip(),
        "python":{"version":platform.python_version(),"executable":sys.executable},
        "paths":{"workdir":str(workspace),"runner_state_root":str(default_state_root())},
        "checks":[],"model_calls":0,"decision_probe":{"status":"NOT_RUN","detail":"Use --check-decide for a paid functional probe."},
        "not_verified":["Native sandbox enforcement", "Production/review model quality", "Provider data residency"],
        "notes":["No Codex checks, model calls, login or configuration reads.",
                 "Claude uses trusted user auth/provider configuration; project settings/hooks/MCP/skills disabled.",
                 "Production Bash requires Claude native sandbox; on native Windows use WSL2 for production."]}
    if not workspace.is_dir() or (todo_file and not Path(todo_file).is_file()):
        report['checks'].append({'name':'paths','status':'FAIL','detail':'Workspace or task file missing'})
        return report
    probe=probe_cli(cwd=workspace,env=environment,require_schema=True,require_effort=reasoning_effort is not None)
    report.update(claude_code_version=probe.get('version'),launcher=probe.get('launcher'),probes=probe['probes'],exec_flags=probe['flags'])
    report['checks'].append({'name':'claude_cli','status':probe['status'],'detail':probe.get('detail','Required CLI flags available')})
    if probe['status'] != 'PASS':
        return report
    if check_decide:
        req=DecisionRequest(question='What is 2 + 2?',options=('FOUR','FIVE'),context=(),model=model,
            reasoning_effort=reasoning_effort,run_id='doctor',task_id='probe',phase='decide',attempt_id='1')
        settings=DecisionExecSettings(backend='claude-code',project_root=workspace,env=environment,
            log_root=workspace/'.arquilo_runs'/'doctor',timeouts=TransportTimeouts(total=decide_timeout))
        call=execute_decision(req,settings=settings)
        passed=call.result.valid and call.result.option == 'FOUR'
        report['model_calls']=sum(row.attempt is not None and 'launcher' in row.attempt.result.trace.capture for row in call.attempts)
        report['decision_probe']={'status':'PASS' if passed else 'FAIL','archive':str(call.directory),
                                  'detail':'One tool-free Claude decision; result and archive validated.',
                                  'result':asdict(call.result)}
        report['checks'].append({'name':'decide','status':'PASS' if passed else 'FAIL','detail':'Expected FOUR'})
    if all(c['status']=='PASS' for c in report['checks']):
        report.update(status='QUALIFIED',checks_status='PASS')
    return report
