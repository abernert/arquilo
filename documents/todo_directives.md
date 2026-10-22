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

## Indented examples and existing plans

For scheduling, ARQUILO ignores lines beginning with four ASCII spaces or a tab
preceded by zero to three ASCII spaces. This applies to task headers, CFG, WAIT,
STOP and fence markers. Lines with up to three leading spaces remain eligible.
This is an explicit lexical task-file rule, not a complete Markdown renderer.
A closing HTML comment is still processed so later real tasks remain visible.

Before updating an existing plan, inspect any task headers or directives indented
by four columns: these now count as examples, not executable entries. Use
unindented headers/directives for executable work. Do not automatically reset a
controller journal or adopt changed task requirements to suppress a mismatch.

## CFG options

Supported keys:

- `workspace=<relative_path>`: subworkspace for this task. Default: the main `--workdir`.
- `parallel=<group_name>`: marks the task as part of a parallel group. Default: unset/sequential.
- `agent=<name>`: agent hint for this task's prompt. Default: unset.
  - The same validated name is passed as `config_profile`, producing `codex exec --profile <name>`. ARQUILO does not blacklist Codex profile names: historical-looking names such as `dev` or `yolo` are ordinary profile identifiers here. The worker sandbox mode is still explicitly `workspace-write` (review/Decide: `read-only`), while Codex's normal profile/rules/workspace-write configuration remains effective within that mode.
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
- Retired ARQUILO YOLO/Full-Auto/No-Check and historical security-profile *fields* are rejected, including historical `false` defaults. This does not blacklist ordinary Codex `--profile` names. Mandatory reviews apply to sequential and parallel flows.
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

## Explicit resources (0.8.0)

`CFG mcp=... review_mcp=... skills=...` accepts comma-separated, case-sensitive
names, or `none`. The equivalent run flags are `--mcp`, `--review-mcp` and
`--skills`. A run-level `--agent` supplies the default for existing `CFG agent`.
One `***DEFAULTS mcp=... skills=...***` before the first real task supplies
list-wide resource defaults. It is machine-readable metadata, not a new source
of authority; ordinary preamble text keeps its existing meaning. CFG remains
local to the immediately following task. Examples/comments stay non-executable.

Example (server and skill names must already exist on the operator's system):

```md
# Goal
Prepare proposals only; do not publish externally.

***DEFAULTS mcp=issues,docs skills=ticket-draft***

***CFG mcp=issues***
1. ***Task***: Prepare a proposal from input.json and identify open questions.

***CFG mcp=none skills=none***
2. ***Task***: Summarize the accepted local proposal.
```

Selections replace, rather than add to, the inherited set. A CLI selection is
both a default and a ceiling; list defaults and task/descendant selections may
only narrow it. A task's initial selection also bounds model-edited task lists
within that run. Omitting all resource settings preserves the old behavior.
In explicit MCP mode, missing/disabled/policy-denied servers cause an error,
not re-enablement or silent omission. Server definitions, authentication and
per-tool permissions remain in the operator's trusted Codex configuration.

Explicit `mcp` defaults the review to no MCP. `review_mcp=issues` can provide a
subset to reviewers; server-side credentials/tool permissions must enforce any
remote read-only restriction. Preflight does not inherit production MCPs in
resource-controlled mode; Decide is MCP-free when MCP selection is explicit. MCP selection is not an offline mode: it does
not disable provider communication, shell access or separately allowed web search.
Plugin/app integrations are disabled for explicit MCP calls; this first adapter
selects direct servers, not plugin-bundled MCPs. Native config inspection may
query auth metadata, but never starts STDIO tools or model calls. Raw inventory
is withheld from logs. Do not change Codex configuration concurrently with a run.

Skills are explicitly bound instruction snapshots, not another agent or a
permission grant. Without `--skill-dir`, lookup uses `<workdir>/.agents/skills`,
`~/.agents/skills`, and `$CODEX_HOME/skills` (default `~/.codex/skills`). With one
or more `--skill-dir` arguments, only those roots are searched. Each root contains
skill directories with `SKILL.md`, YAML frontmatter and a simple `name` field.
Duplicate names, unsafe paths, missing definitions and oversized context fail
before the task model call. The operator can use `--skill-dir` to disambiguate.

Production, review and fixes receive the same captured skill instructions plus
the normal preamble and task. Scripts/references remain external files resolved
relative to the recorded skill directory; they are not copied or automatically
executed. Do not change those files while working. `skills=none` means no explicit
binding; it does not disable Codex's normal implicit skill discovery or file
access. Native `AGENTS.md` discovery is likewise unaffected.

A dry run validates task syntax and explicit skill bindings and shows the
selected names without launching Codex, MCP servers, scripts or model calls.
It cannot certify native MCP inventory, authentication or remote permissions.

The first explicit MCP adapter supports configured STDIO and Streamable HTTP
servers with portable IDs (letters, digits, underscores and hyphens). Dots in
server IDs are rejected: the tested native CLI override parser does not use
TOML key quoting for path components. Rename such a local alias before using
explicit selection; no transport or credentials are copied to command arguments.
