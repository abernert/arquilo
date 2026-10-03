# Extended ToDo format (directive mode)

This document describes the backward-compatible directive format implemented by `run_todos.py`.

## Purpose

- Run tasks in parallel subworkspaces.
- Apply different agent/model hints per task.
- Control sequencing through wait conditions.
- Configure model and web-research behavior per task.

## Backward compatibility

- Existing lines in the form `<id>. Auftrag: ...` remain valid.
- Without directives, `run_todos.py` behaves as before.
- `***STOP***` remains active and must appear directly before the affected task.

## Directive syntax

Directive lines appear directly above a task:

```text
***CFG key=value key2=value2***
***WAIT on=... mode=... timeout=... on_timeout=...***
<id>. ***Task***: ...
```

- Values may be quoted when needed.
- Multiple `CFG`/`WAIT` lines may precede the same task.
- `CFG` values are merged for the next task.
- Code examples and HTML comments remain invisible to scheduling. A trailing HTML note after a real directive does not hide the directive.
- The complete current file is validated before selection, including WAIT/STOP, and before AutoBuild. Invalid or removed keys are errors; they are not treated as defaults or successful no-ops.
- Quoting uses the existing POSIX text grammar on every platform; it is not shell execution. Quote Windows backslash paths, for example `workspace='C:\Project Space\Part'`, or use forward slashes. The path must match the host and remain inside the main workspace. The quote grammar performs no variable, tilde, or command substitution.

## CFG options

Supported keys:

- `workspace=<relative_path>`: subworkspace for this task. Default: the main `--workdir`.
- `parallel=<group_name>`: marks the task as part of a parallel group. Default: unset/sequential.
- `agent=<name>`: agent hint for this task's prompt. Default: unset.
  - The same validated name is passed as `config_profile`, producing `codex exec --profile <name>`. Historical security profiles from the predecessor project and names such as `dev`, `yolo`, `unsandboxed`, and Full-Access variants are rejected; see [Historical migration](HISTORICAL_MIGRATION.md). Other model/tool profiles cannot replace the fixed sandbox policy.
- `model=<model_id>`: per-task model override. An explicit global model from `run_todos.py --model` or its environment default takes precedence; otherwise the CFG model applies.
- `web_search=live|cached|disabled`: per-task web-search mode. Default: no task override; the global Codex configuration remains effective.
- `websearch=live|cached|disabled`: alias for `web_search`.
- `network_access=true|false`: shell-network permission for `sandbox_workspace_write` via a configuration override. Default follows the runner grant; without `--network-access` it is explicitly false. `true` requires the runner-level grant; `false` may restrict it per task. Network permission does not expand file-write permissions.
- `result_file=<todo_result_*.md>`: local result filename.
- `completion_anchor=<todo_result_*.md>`: alternative result filename; `result_file` wins when both are set. No path components.
- `breakdown=minimal|legacy|off`: decomposition policy. Aliases: `structured` for minimal and `none|disabled|false` for off.
- `breakdown_max_children=1..12`, `breakdown_max_rounds=1..8`: decomposition bounds; these are not new scheduler budgets.

## WAIT options

Supported keys:

- `on=<expression>`: wait condition. Allowed prefixes:
  - `todo:<id>`
  - `<id>` as shorthand for `todo:<id>`
  - `group:<group_name>`
  - `agent:<agent_name>`
- `mode=all|any`: for comma-separated conditions, require all or any.
- `timeout=<duration>`: for example `30s`, `5m`, `1h`, `1d`.
- `on_timeout=stop|continue`: timeout behavior.

Stored DONE entries satisfy ToDo dependencies after restart. OBSOLETE, an incomplete task, or attempted work does not. Group/agent conditions use their existing runtime state. Multiple WAIT lines are evaluated in sequence. `timeout=0s` checks immediately; omitting timeout also checks only the current state. An unmet condition exits with code 9 unless `on_timeout=continue` is explicit. Empty list items, unknown IDs, and invalid modes are grammar errors. STOP is not a WAIT state and does not create a `process_stop` file.

Bridge WAIT conditions (`bridge:resume[:token]`, `bridge:retry[:token]`, `bridge:escalation`, and `bridge:escalated`) have been removed since 1031. Linter and runner report them as configuration errors before the affected model call, including dynamically added tasks, mixed WAIT conditions, `mode=any`, and `on_timeout=continue`. There is no activation option. See [Migration](MIGRATION.md).

## Execution rules

- Directives apply only to the immediately following task.
- Parallel execution remains optional and requires no separate mode switch.
- Every task in a parallel group must use its own `workspace`.
- WAIT directives in parallel groups are checked for each task before the group starts.
- Resolved `workspace` paths must remain inside the main workspace.
- YOLO/Full-Auto/No-Check fields and security-profile fields are rejected, including historical `false` defaults. Mandatory reviews apply to sequential and parallel flows.
- All `logician`/`logician_*` directives have been removed, including former `off`/`lite` defaults. Remove them; normal reviews and audits do not require a ledger. See [Migration](MIGRATION.md).
- ACE, IACT, OpenClaw/Bridge, and service fields are also removed even when set to `false`, `off`, `null`, or empty. No optional group re-enables them. Parallel CFG, general runtime profiles, and explicit Git opt-in remain core features.
- Sync-back from subworkspaces is non-destructive: results/questions are merged instead of replacing the whole file.
- `WAIT ... on_timeout=stop` ends the run in a controlled manner.

## Web research

Integrated web search is configured separately through `web_search=live|cached|disabled`. `network_access` concerns shell commands started by the agent in `workspace-write`; provider communication and MCP/apps are separate paths. Therefore `network_access=false` does not claim fully offline execution. ARQUILO has no unrestricted sandbox mode.

Notes:

- `web_search` and `network_access` are passed as temporary Codex configuration overrides (`-c ...`) per task.
- `agent=<name>` selects a Codex model/tool profile (`--profile <name>`). The explicit CLI sandbox policy remains effective even when profile defaults differ.
- Global/isolated configuration through `CODEX_HOME/config.toml` remains possible.

## Example

```md
***CFG parallel=grp_mod workspace=workspaces/analysis agent=analyst web_search=disabled network_access=false***
21.8.1. ***Task***: Analyze the affected modules and document risks.

***CFG parallel=grp_mod workspace=workspaces/tests agent=tester web_search=disabled network_access=false***
21.8.2. ***Task***: Add regression tests for the same modules.

***WAIT on=group:grp_mod mode=all timeout=120m on_timeout=stop***
21.8.3. ***Task***: Integrate the results from analysis and tests.
```

## Recommended invocation

```text
python3 /path/to/arquilo/run_todos.py --todo-file /project/tasks.md --workdir /project
```

Native Windows/PowerShell:

```powershell
py -3.11 C:\Arquilo\run_todos.py --todo-file C:\Project\tasks.md --workdir C:\Project
```

Shell network access additionally requires `--network-access` on the runner. [Migration](MIGRATION.md) explains removed switches and the distinction between approval policy and sandbox. [Project preamble](TODO_PREAMBLE.md) explains `auto|off|required`, reference prompts, Markdown visibility, and dynamic follow-up tasks.
