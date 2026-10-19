# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Tool-free Claude decision execution using the common decision validator."""
from __future__ import annotations
from pathlib import Path
import tempfile

import safe_io
from agent_types import TransportTimeouts
from agent_backend import resolve_model, resolve_effort
from claude_transport import ClaudeRequest, execute
from claude_launcher import resolve_launcher


def execute_attempt(request, *, project_root, env, raw_log, pretty_log, temp_root=None,
                    launcher=None, output_schema=None, output_last_message=None,
                    timeouts=None, process_stop_path=None, cancel_requested=None):
    from decision_exec import DecisionAttempt
    prompt=request.to_prompt()
    project=safe_io.lexical_path(project_root)
    base=safe_io.lexical_path(temp_root or tempfile.gettempdir())
    if base.is_relative_to(project) or not base.is_dir():
        raise ValueError("Claude Decide temp root must exist outside the project")
    for parent in (base,*base.parents):
        if (parent/'.git').exists():
            raise ValueError("Claude Decide temp root must not inherit a repository")
    environment=dict(env)
    if launcher is not None:
        if Path(launcher).name.lower() in {'codex','codex.exe','codex.cmd'}:
            raise ValueError("Codex is forbidden for a Claude decision")
        environment['ARQUILO_CLAUDE_CODE_COMMAND']=launcher
    selected=resolve_launcher(environment.get('ARQUILO_CLAUDE_CODE_COMMAND','claude'),cwd=base,env=environment)
    for path in (selected.source,*selected.argv):
        if Path(path).resolve().is_relative_to(project):
            raise ValueError("Claude decision executable must be outside the project")
    cwd=Path(tempfile.mkdtemp(prefix='arquilo-claude-decide-',dir=base)).resolve()
    for path in (raw_log,pretty_log,output_schema,output_last_message):
        if path is not None and (cwd/Path(path)).is_relative_to(cwd):
            raise ValueError("Claude Decide outputs must be outside its empty working directory")
    call=ClaudeRequest(prompt=prompt,cwd=cwd,env=environment,raw_log=raw_log,pretty_log=pretty_log,
        model=resolve_model(request.model,backend='claude-code',environ=environment),
        reasoning_effort=resolve_effort(request.reasoning_effort,backend='claude-code',environ=environment),
        phase=request.phase,sandbox='read-only',decision_only=True,network_access=False,
        output_schema=output_schema,output_last_message=output_last_message,
        timeouts=timeouts or TransportTimeouts(total=120),process_stop_path=process_stop_path,cancel_requested=cancel_requested)
    return DecisionAttempt(cwd,execute(call))
