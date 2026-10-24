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
from host_launcher import launcher_environment


def execute_attempt(request, *, project_root, env, raw_log, pretty_log, temp_root=None,
                    launcher=None, output_schema=None, output_last_message=None,
                    timeouts=None, process_stop_path=None, cancel_requested=None,
                    launcher_workspace=None):
    from decision_exec import DecisionAttempt
    prompt=request.to_prompt()
    project=safe_io.lexical_path(project_root)
    base=safe_io.lexical_path(temp_root or tempfile.gettempdir())
    if base.is_relative_to(project) or not base.is_dir():
        raise ValueError("Claude Decide temp root must exist outside the project")
    for parent in (base,*base.parents):
        if (parent/'.git').exists():
            raise ValueError("Claude Decide temp root must not inherit a repository")
    root = safe_io.lexical_path(launcher_workspace) if launcher_workspace is not None else project
    environment = launcher_environment(launcher_environment(env, workspace=root), workspace=project)
    if launcher is not None:
        if Path(launcher).name.lower() in {'codex','codex.exe','codex.cmd'}:
            raise ValueError("Codex is forbidden for a Claude decision")
        environment['ARQUILO_CLAUDE_CODE_COMMAND']=launcher
    selected=resolve_launcher(environment.get('ARQUILO_CLAUDE_CODE_COMMAND','claude'),
        cwd=base, env=environment, workspace=root, additional_workspace=project)
    # Keep the selected host entry point when the invocation moves to its empty
    # non-project working directory. No workspace or Codex fallback is allowed.
    environment['ARQUILO_CLAUDE_CODE_COMMAND'] = selected.source
    cwd=Path(tempfile.mkdtemp(prefix='arquilo-claude-decide-',dir=base)).resolve()
    for path in (raw_log,pretty_log,output_schema,output_last_message):
        if path is not None and (cwd/Path(path)).is_relative_to(cwd):
            raise ValueError("Claude Decide outputs must be outside its empty working directory")
    call=ClaudeRequest(prompt=prompt,cwd=cwd,env=environment,raw_log=raw_log,pretty_log=pretty_log,
        model=resolve_model(request.model,backend='claude-code',environ=environment),
        reasoning_effort=resolve_effort(request.reasoning_effort,backend='claude-code',environ=environment),
        phase=request.phase,sandbox='read-only',decision_only=True,network_access=False,
        output_schema=output_schema,output_last_message=output_last_message,
        timeouts=timeouts or TransportTimeouts(total=120),process_stop_path=process_stop_path,
        cancel_requested=cancel_requested, launcher_workspace=root)
    return DecisionAttempt(cwd,execute(call))
