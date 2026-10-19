# Claude Code backend (experimental branch)

`--backend codex` is the default. `--backend claude-code` selects Claude Code for
**the entire run**: production, fixes, reviews, parent reviews, semantic Decide,
standalone AutoBuild, and parallel Python workers. No Codex executable, login,
preflight, configuration-home lookup, or fallback is used on that path. Shared
Python result/policy helpers retain some historical names; that is not a Codex
process or provider dependency. OpenCode is reserved, **not implemented**.

This is unreleased work based on 0.7.4. Do not treat it as client-production
qualification or as a data-residency guarantee. `VERSION` was not released or
retagged for this feature branch.

## Install and select

Install and authenticate a recent official **Claude Code CLI** separately. Use
its normal trusted user provider/authentication configuration. ARQUILO never
installs a runtime, signs in, changes your global configuration or chooses a
model automatically. Your paid subscription or API arrangement remains with the
provider. A Claude API key alone is not a replacement for installing Claude Code.

```bash
# No model call: executable/version/required-option checks only.
python3 -B arquilo.py doctor --backend claude-code --workdir /path/to/project

# Explicit one-call functional Decide probe: may incur provider charges.
python3 -B arquilo.py doctor --backend claude-code --workdir /path/to/project --check-decide

# Same task list, different execution runtime.
python3 -B arquilo.py tasklist run --backend claude-code \
  --workdir /path/to/project --todo-file /path/to/project/tasks.md \
  --process-stop-policy controller-only --max-calls 12

# Returning to Codex is explicit; omitting --backend also means Codex.
python3 -B arquilo.py tasklist run --backend codex \
  --workdir /path/to/project --todo-file /path/to/project/tasks.md
```

A dry run does not need either agent installed. Use a new `--dry-run-file` path
for each preview. `--skip-backend-preflight` only skips the runner-level check;
each actual Claude attempt still validates its executable contract. The existing
`--skip-codex-preflight` remains Codex-only and is rejected in a Claude run.

Optional **trusted host** variables (never set from agent-controlled task text):

| Variable | Meaning |
| --- | --- |
| `ARQUILO_CLAUDE_CODE_COMMAND` | Executable path, no shell command or arguments; default `claude` on PATH. |
| `ARQUILO_CLAUDE_CODE_MODEL` | Optional Claude-native model selection. CLI `--model` takes precedence. |
| `ARQUILO_CLAUDE_CODE_REASONING_EFFORT` | Optional `low`, `medium`, `high`, `xhigh`, or `max`. CLI `--reasoning-effort` wins. |

No `ARQUILO_CODEX_*`, `CODEX_HOME`, or historical decision-model default is
translated into Claude settings. Omit model/effort to leave selection to the
trusted native Claude configuration. Unsupported explicit effort values fail;
they are not guessed. `--codex-profile`, Codex provider overrides and raw extra
arguments are rejected for Claude. Native proxy, certificate and authentication
environment values are retained, but not dumped to the logs.

## Safety contract and intentional restrictions

Every invocation uses a fresh UUID session and UTF-8 stdin. The adapter requests
native stream-json output, no session persistence, `dontAsk` permission handling,
explicit built-in tools, no arbitrary MCP servers, and safe mode. Project/local
settings, CLAUDE.md, skills, custom agents and plugins are not used by this
initial integration. Relevant project instructions must be in the captured task
or additive ARQUILO runtime profile. Trusted user authentication/model/provider
settings are retained. Mandatory corporate policy can still apply; a company
policy is not silently bypassed. Unknown integration or tool events fail the
invocation, but post-event validation cannot undo a tool already executed.

| Role | Available built-in task tools |
| --- | --- |
| Production and fix | Read, Glob, Grep, Edit, Write, Bash |
| Review and parent review | Read, Glob, Grep; **no Bash or write tools** |
| Decide | No task tools; only the native structured-output mechanism when needed |

File-edit auto-approval is scoped to working-directory paths. Production Bash
requires Claude's native sandbox with `failIfUnavailable` and no unsandboxed
escape. By default its shell network is denied. `--network-access` removes that
additional deny; it does **not** automatically grant destinations prohibited by
the trusted host policy. Provider/model communication is separate from shell
networking. Web search/fetch, external MCP, skills and subagents remain disabled.
Tests that require shell execution should be performed in production/fix and
produce evidence for the file-reading reviewer. This first reviewer deliberately
cannot re-run a test command itself.

These tool rules are **not a whole-process OS isolation boundary**. In
particular, native file tools, the CLI's own storage, auth helpers and mandatory
managed integrations are not all covered by the shell sandbox. Existing trusted
user/corporate permissions may grant wider file access. A client pilot still
needs an isolated account/container/VM, controlled egress, protection of the
controller state and a verified provider deployment. Never put credentials or
other clients' work beside the agent workspace.

For production on Windows use WSL2 with a Linux Claude installation: Claude's
shell sandbox is not supported on native Windows. Read-only calls can use a
supported Windows native executable. The Python launcher also accepts the
strictly validated legacy npm `claude.cmd`/`cli.js` layout; it does not interpret
arbitrary `.cmd`, `.bat`, `.ps1` or command-string wrappers. If a newer npm layout
is refused, use the official native executable, not an unsafe shell workaround.

## Completion, cancellation and evidence

Success requires correlated init and terminal result events from the selected
session, a complete usable answer, a natural zero process exit and retained
input/output evidence. A success-looking text, missing result, permission denial,
truncation, malformed/foreign event, nonzero exit or forced terminal cleanup is
not success. A review must then pass the unchanged common review contract.
A missing or invalid review cannot cause `DONE`. No model-generated task status
is accepted as controller authority.

The adapter does not retry a model request after a technical failure and never
falls back to another backend. Partial edits may remain after an error or stop;
inspect them before explicitly restarting. Shared call reservations and review
requirements remain unchanged. A call budget counts agent invocations, not every
internal provider request or dollar of cost. An explicitly requested Decide
format repair uses a new correlated session and consumes its own reservation.

Raw prompts, stdout, stderr and the selected terminal response are retained in
the normal project evidence layout. Standalone Claude diagnostics default to
`.arquilo_runs`, not `.codex_runs`. Archives include backend/session/model/tool
metadata but are not encrypted and are not safe to publish unreviewed.
`--no-session-persistence` is not a promise of zero native logs or zero retention
at the model provider. Set client-specific retention and deletion rules.

The 0.7.4 `review resume` command validates **historical Codex reconnect archives**;
it remains Codex-specific and refuses `--backend claude-code` before dispatch.
No Claude request is silently converted into a Codex recovery. Native Claude
session resume/mixed-runtime review routing are not part of this first backend.

## Python entry points

```python
from pathlib import Path
import os
from autobuild import start
from autobuild_contract import AutoBuildOptions
from decision_exec import DecisionExecSettings
from decide import decide

project = Path('/path/to/project').resolve()
summary = start(task='Create the specified report.', workdir=project,
                options=AutoBuildOptions(backend='claude-code', max_calls=12))

settings = DecisionExecSettings(
    backend='claude-code', project_root=project, env=dict(os.environ),
    log_root=project / '.arquilo_runs' / 'decisions')
option, explanation = decide('Is 2 + 2 equal to 4?', ['YES', 'NO'], settings=settings)
```

## Validation and upstream documentation

```bash
python3 -B -m unittest discover -s tests -p 'test_claude_backend.py' -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

Offline fixtures exercise real local subprocess I/O with **synthetic CLI
messages**, not a native Claude model session. Tests poison Codex process and
configuration entry points and install a sentinel executable for child-process
regressions. They check production/review/fix/Decide, worker serialization,
full task-list status, cancellation, timeouts, malformed output, archive failure,
unsupported CLI contracts and independent model configuration. Native CLI tests
and real-model/client-host tests are distinct levels; passing an offline suite
does not establish native tool isolation or model quality.

Official references checked 2026-10-19:
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/sandboxing
