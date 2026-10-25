# Claude Code backend qualification

`--backend codex` is the default. `--backend claude-code` selects Claude Code for
**the entire run**: production, fixes, reviews, parent reviews, semantic Decide,
standalone AutoBuild, and parallel Python workers. No Codex executable, login,
preflight, configuration-home lookup, or fallback is used on that path. Shared
Python result/policy helpers retain some historical names; that is not a Codex
process or provider dependency. OpenCode is reserved, **not implemented**.

Claude Code is an execution backend in ARQUILO 0.10.0. This release combines
the backend from PR #30, state-I/O repairs from PR #35, and reviewed Git publication
and the consolidated manuals from PR #37. The older v0.9.1 ZIP does not contain
these additions. See [release inputs and scope](integration-status.md). Native
compatibility evidence below qualifies specific adapter behavior; complete release
and live-host acceptance are separate checks. Use the [Operator Guide](guides/operator-guide.en.md#backends)
for normal configuration and the [Technical Guide](guides/technical-guide.en.md#transport)
for the integrated architecture.

## Security baseline and shared acceptance

Both backends use the same controller rules for original-task capture, accepted
plan bytes, physical state identity, spent budgets, mandatory review and final
DONE. FAIL or blocking findings veto completion even when a later Decide
response says COMPLETE. Opaque STOP sentinels still stop work; root and peer
signals, and the original launcher workspace, cross the private worker boundary.

The Claude launcher now uses the shared external-host path policy. Empty,
relative, project-local and physical aliases back into any writable workspace
cannot select `claude`, Node, npm entry points or a Decide executable. Trusted
absolute host PATH entries are retained; child PATH is sanitized and one resolved
launcher is used for version/help and that invocation. Normal `~/.local/bin`
installations are supported when outside the workspace; no additional CLI flag
is needed. Selecting your whole home directory as the workspace includes that
installation and is intentionally refused.

A rejected native stream stays rejected. The adapter continues draining and
archiving bytes, but a later well-formed terminal event cannot populate an
accepted answer or restore completion. This fixes the negative test introduced
with `thinking_tokens`; it is not solved by skipping or weakening its assertion.
Legacy prose must explicitly state no issues; ambiguous prose does not gain an
extra permissive Decide call. Valid no-issue prose still uses Claude Decide.

Metadata recognition is not pre-execution confinement. Native Claude roles and
sandbox limitations remain as documented below: no reviewer Bash, no named MCPs,
no automatic Codex fallback. More general process/output supervision, additional
resource isolation remain separate work. Version 0.10.0 includes the
reviewed-publication path; verify it with the common acceptance and delivery
regressions for both backends. [Git operation and retry](guides/operator-guide.en.md#git)
have the same controller-owned contract; no Claude reviewer Bash is enabled.

## Compatibility with ARQUILO 0.10.0

- `--prompt-config default|de|en|FILE` works across production, fixes, reviews,
  parent-review calls, Decide, doctor and worker serialization. Omission selects
  `default`. Each run retains the same immutable catalog snapshot; workers do
  not reopen an edited or deleted custom source file.
- `--skills`, `--skill-dir`, list `DEFAULTS` and task `CFG` retain the 0.8.0
  inheritance/ceiling rules. Selected `SKILL.md` text and hashes are bound to the
  original request, not installed or executed as Claude tools. Claude defaults
  to `.agents/skills` and `.claude/skills` under the workspace and user home;
  **no `CODEX_HOME` or `.codex/skills` discovery**. Explicit roots replace these
  defaults. Duplicate skill names fail rather than choosing arbitrary precedence.
- `--mcp none` and `--review-mcp none` are supported. **Named MCP servers remain
  unsupported by this deliberately restricted Claude adapter.** Named selections
  in CLI/list/task settings fail before model execution, including a named MCP
  requested only by a later task. Omission still means no native Claude MCPs;
  it does not inherit Codex or Claude project MCP configuration. Capability
  metadata reports this limitation rather than claiming feature parity.
- `--agent` / `CFG agent` are Codex profile selectors, not Claude subagents.
  They are rejected for Claude, as are Codex-only provider/profile overrides.
- Historical `tasklist resume-review` remains Codex-only; native Claude session resume
  and cross-backend recovery are not added in this release.

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
  --prompt-config de --mcp none --review-mcp none \
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

Codex model/effort settings, `CODEX_HOME`, and the historical decision-model
default are not translated into Claude provider settings. The common transport
timeouts retain their historical `ARQUILO_CODEX_*_SECONDS` names for both
backends; see the [environment reference](guides/operator-guide.en.md#environment-reference). Omit model/effort to leave selection to the
trusted native Claude configuration. Unsupported explicit effort values fail;
they are not guessed. `--codex-profile`, Codex provider overrides and raw extra
arguments are rejected for Claude. Native proxy, certificate and authentication
environment values are retained, but not dumped to the logs.

## Safety contract and intentional restrictions

Every invocation uses a fresh UUID session and UTF-8 stdin. The adapter requests
native stream-json output, no session persistence, `dontAsk` permission handling,
explicit built-in tools, no arbitrary MCP servers, and safe mode. Project/local
settings, CLAUDE.md, native skill discovery, custom agents and installed plugins
are not used by this adapter. Relevant project instructions must be in the captured task, an explicitly
bound skill instruction snapshot, or an additive ARQUILO runtime profile. Trusted user authentication/model/provider
settings are retained. Mandatory corporate policy can still apply; a company
policy is not silently bypassed. Unknown integration or tool events fail the
invocation, but post-event validation cannot undo a tool already executed.

| Role | Available built-in task tools |
| --- | --- |
| Production and fix | Read, Glob, Grep, Edit, Write, Bash |
| Review and parent review | Read, Glob, Grep; **no Bash or write tools** |
| Decide | No task tools; only the native structured-output mechanism when needed |

Claude 2.1.303 emits a `ui_invalidate`/`ui.render` diagnostic before init.
It is retained but never treated as success. The exact observed built-in
identities are `cc-plugin-agents-md@builtin` and
`cc-plugin-plugin-authoring@builtin` (2.1.303), plus
`cc-plugin-telemetry@builtin` (observed in 2.1.310 on macOS). For each, the
`name`, `path=builtin`, and `source=name@builtin` fields must match exactly.
Unknown, duplicate, malformed or installed plugin identities still fail closed;
neither named MCPs nor new model tools are authorized by this update.
The `cc-plugin-telemetry` component is built into Claude Code: accepting its
metadata does **not** disable its telemetry behavior or certify provider privacy
settings. This check is not a pre-execution interceptor. `disableAllHooks`
does not disable bundled runtime components. A fresh user profile does not prove
that every mandatory managed integration is absent.

On Linux, production requires the native sandbox prerequisites `bubblewrap` and
`socat` and OS permission to use them. Have IT install/approve these as required;
do not disable `failIfUnavailable` or operating-system protections to run a task.

File-edit auto-approval is scoped to working-directory paths. Production Bash
requires Claude's native sandbox with `failIfUnavailable` and no unsandboxed
escape. By default its shell network is denied. `--network-access` removes that
additional deny; it does **not** automatically grant destinations prohibited by
the trusted host policy. Provider/model communication is separate from shell
networking. Web search/fetch, external MCP, native skill tools and subagents remain disabled.
Explicit ARQUILO skill text bindings do not enable those tools.
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

## Claude Code 2.1.310 thinking progress

Native 2.1.310 may emit `type=system, subtype=thinking_tokens` while the
model is thinking. This is **progress metadata only**, not a tool, a review
verdict, a final answer or authoritative token billing. An owner macOS run
contained two such frames with exactly `type`, `subtype`, `session_id`,
`uuid`, `estimated_tokens`, and `estimated_tokens_delta`. The Claude Agent
SDK also defines optional `user_message_uuid` on this frame.

ARQUILO admits this subtype **only after the correlated init and before a
terminal result**. It validates an exact field set, bounded string identifiers,
and finite non-negative numeric estimates; it does not grant new task tools,
allow new hooks or change completion authority. Unrecognized extra fields,
negative/non-numeric estimates, foreign sessions or post-result events fail
closed. The raw frame is archived as before; the estimates are deliberately
not treated as accepted model output or a billable usage counter.

## Diagnosing unexpected system events

If a current Claude CLI emits `Unexpected Claude system event: subtype=...`,
ARQUILO has refused an event type outside the permitted protocol. In particular,
`hook_started`, `hook_progress` and `hook_response` are **not** automatically
treated as safe diagnostics: they can indicate actual user/managed hooks ran.
The reported subtype is a bounded identifier; hook commands, output, arbitrary
metadata and credentials are not included in the exception. Read the saved
`001-production/stdout.bin` locally and extract only `type`, `subtype`,
field names and, for hooks, the `hook_event` category. Do not paste the raw
stdout/stderr archive into an issue; it may contain prompts and outputs.

An interactive `claude` session and a native synthetic-provider CI run can
have different managed/user hook settings. This adapter passes `disableAllHooks`
and restricts tools/settings, but it cannot prove that all mandatory or bundled
host hooks are disabled. If an actual hook is observed, investigate its source
and policy rather than whitelisting `hook_*` events globally. No further model
calls are necessary to classify already archived event metadata.

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

The existing `tasklist resume-review` command validates **historical Codex reconnect archives**;
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
python3 -B -m unittest discover -s tests -p 'test_claude_backend*.py' -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

Offline fixtures exercise real local subprocess I/O with **synthetic CLI
messages**, not a native Claude model session. Tests poison Codex process and
configuration entry points and install a sentinel executable for child-process
regressions. They check production/review/fix/Decide, worker serialization,
full task-list status, cancellation, timeouts, malformed output, archive failure,
unsupported CLI contracts and independent model configuration. The maintained native fixture tests Claude Code 2.1.303 on Linux and
2.1.310 on macOS, against a synthetic loopback provider rather than a real model.
The Linux GitHub-hosted runner does not currently support 2.1.310's sandboxed
Bash under its AppArmor/user-namespace restrictions: this is reported as a
native environment limitation, not solved by disabling the required sandbox.
Offline protocol and subprocess fixtures exercise the exact three built-in
identities and reject untrusted substitutions. Native CLI tests
and real-model/client-host tests are distinct levels; passing an offline suite
does not establish native tool isolation or model quality.

The current native fixture has seven scenarios, including `read_private_output`:
the reviewer retains the live workspace as cwd and reads an explicit private
selected-output snapshot without Bash or write tools. Earlier six-case native
results did not test this new review/publication boundary. Record the actual
seven-case native result for the combined checkout separately from those
historical runs; this paragraph is a test requirement, not a claim that an
unobserved native run passed.

The 0.9.0 integration regression suite additionally covers all built-in catalogs,
custom/frozen catalogs through correction loops and actual Python workers,
Claude doctor prompt selection, legacy-review Decide, explicit empty MCPs,
fail-closed named MCP requests, and skill instruction bindings without Codex
home discovery. These fixtures are not real-model quality evidence.

## Isolated owner smoke test of a selected revision

Use a separate installation of the exact revision being qualified and a new
disposable workspace. Keep the stable runner and existing client workspaces
separate. Use the v0.10.0 tag or an explicitly recorded commit rather than assuming an old feature-branch name identifies the intended version.
From the selected installation, check:

```bash
python3 -B arquilo.py --version
claude --version
```

On macOS or Linux/WSL, create a disposable task workspace:

```bash
SMOKE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arquilo-claude-smoke.XXXXXX")"
printf '%s\n' '1. ***TASK***: Create hello.txt containing exactly Hello from ARQUILO.' > "$SMOKE_DIR/tasks.md"
python3 -B arquilo.py doctor --backend claude-code --workdir "$SMOKE_DIR" --prompt-config de
```

Only after doctor passes, run the model-backed smoke test below. It uses your
existing Claude authentication and may incur provider charges. Use a disposable
host/account where required by the safety boundaries above.

```bash
python3 -B arquilo.py tasklist run --backend claude-code \
  --workdir "$SMOKE_DIR" --todo-file "$SMOKE_DIR/tasks.md" \
  --prompt-config de --mcp none --review-mcp none \
  --process-stop-policy controller-only --max-calls 12
cat "$SMOKE_DIR/hello.txt"
cat "$SMOKE_DIR/tasks.md"
```

Check the actual output, the separate review evidence and the final task status.
A missing, failed or invalid review must never mark the task `DONE`. A green
metadata-only doctor does not prove that the model provider, native sandbox or
client-host permissions work. Do not remove a failure/stop marker blindly.

Official CLI reference rechecked 2026-10-22; safety references from the original
backend qualification (2026-10-19):
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/plugins/mods/admin
