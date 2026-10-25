# Security policy

ARQUILO is an experimental public preview. Evaluate it under supervision
in disposable, least-privilege workspaces. No production security certification
or support SLA is implied.

## Report privately

Do not publish credentials, personal/client data, full run archives or a working
exploit in an issue. Use the repository's private “Report a vulnerability” route
if it is enabled. Otherwise open an issue containing only a request for a private
security contact, without vulnerability details, and wait for the maintainer to
provide a private channel. See the maintainer at https://github.com/abernert.
Only the current preview line receives best-effort fixes; archived versions do
not have a separate maintenance commitment.

## Trust boundaries

- With the default Codex backend, production uses `workspace-write`; review requests use `read-only`.
  ARQUILO does not add filesystem hardening inside `workspace-write`: it keeps
  Codex exec-policy rules and Codex's standard/configured writable roots, including
  normal temporary-directory handling. ARQUILO is not itself an OS sandbox. Native
  enforcement and setup depend on Codex and the host. A fresh directory does not
  imply full read isolation.
- Controller-owned task/status/log/Git paths still use ARQUILO's no-follow,
  atomic-write and path-integrity checks. Those checks protect controller authority;
  they are not injected into Codex, do not filter worker shell commands, and do not
  restrict ordinary project files inside the Codex workspace.
- Codex, Claude Code and controller Git launchers must be installed outside the workspace.
  Resolution uses only absolute host PATH entries; empty, relative and
  workspace-contained entries, including aliases into the workspace, are
  excluded. Explicit launcher paths must also be absolute and external. The
  child PATH follows the same rule so a host npm launcher cannot find a
  workspace Node executable. Standard Windows npm `codex.cmd` is checked and
  started through external `node.exe` and `codex.js`, without a shell. Keep
  project-local tool installations out of the controller launcher configuration.
  Host installations, configuration and other environment values remain
  trusted; this does not protect against concurrent replacement of host tools
  or constrain commands deliberately started by those tools.
- Decide inherits trusted host Codex configuration/environment (including provider,
  proxy and credential dependencies) and requests `read-only`/`never`. It rejects
  tool/unknown events, but this is an acceptance gate, not a pre-tool interceptor.
  Configured tools, MCP servers, hooks and auth/notification commands may start
  under Codex's own rules. Do not treat config inheritance as zero side effects
  or a blanket tool-disable mechanism. See [Decide configuration](docs/guides/operator-guide.en.md#decide-reference).
  Never populate its host settings/environment from model-controlled input.
- Shell network access and Git operations are explicit opt-ins. Disabling shell
  networking does not disable model-provider communication or prove that every
  other integration is offline. Inspect the effective configuration.
- Markdown, source documents and model output may contain prompt injection.
  Separate review can repeat the producer's mistake. Require deterministic tests
  and human review where consequences warrant them.
- Run archives retain raw prompts, outputs and selected files. Pretty-log
  redaction is not a guarantee that an entire archive is safe to disclose.
  Archives are not encrypted, tamper-proof storage or full workspace backups.
- Call budgets are not spending caps. The preliminary Codex probe is outside the
  per-task call budget. Provider limits and billing are separate controls.

## Controller records and local trust

The task runner stores plan authority, call counters and run evidence outside
its production workspaces. Ordinary model output cannot authorize task status
changes. Only validated open child additions and controller-approved completions
change the persisted plan; owner adoption is an explicit, auditable override.
Controller file operations reject links/reparse points and hardlinked files.
POSIX writes use directory-relative descriptors; Windows holds parent-directory
handles without delete sharing while reading or writing. These are not a new OS
sandbox or protection against arbitrary code with the user's credentials.

Use local, user-owned state storage. POSIX state roots require user ownership and
mode 0700; on Windows use the default private LocalAppData or an equivalently
restricted, user-owned directory with appropriate ACLs. Do not grant agent runtimes,
external tools or other users extra access to the state root. Profiles with
`preflight.command` are **trusted executable code with host permissions**, not
untrusted configuration; do not run downloaded profiles without inspection.

`--git` requires literal owner-selected files; selected files must initially be
clean or absent. A local commit does not imply authorization to publish it.
Only `--git-push` enables a push, and unrelated unpushed commits are refused.
Do not edit the selected files, Git index or branch concurrently with a run.
The allowlist is not a content/secret scanner or proof that every output is
correct. Inspect sensitive deliverables before publishing.

See [controller safety](docs/guides/technical-guide.en.md#controller-reference) for migration and recovery.

## Operational baseline

Run as an ordinary user. Do not disable UAC, broadly grant filesystem permissions,
use unrestricted sandbox modes, or execute arbitrary user-submitted tasks on a
shared production host. Keep credentials outside project workspaces and logs.
Use user-owned temporary directories, backups and explicit least-privilege inputs.
Review local runtime profiles and Codex integrations before granting access.

CI deliberately has no model credentials and never runs live agent workloads.
Its tests do not establish that the native sandbox correctly enforces every
boundary on a user's installation.

## Operator-selected trust boundaries

Unlimited is the default call-count policy (`--max-calls 0`), not an assurance
against provider cost. Configure a positive limit or provider-side caps when
needed. The owner may change limits on continuation without resetting counters.
`process_stop`, other loop limits and review requirements remain independent.

`--logs-in-workdir` makes diagnostics agent-readable/writable. They are not
tamper-proof evidence. Authoritative plan/budget/worker IPC stays external.
`--allow-todo-modifications` permits observed valid task-plan edits, including
statuses/removal. It does not certify those edits as reviewed work. Use the
original-assignment `reviewed_this_run` and recorded plan mutations, and perform
human review of generated plans. Both switches are off by default and neither
changes Codex permission settings. See [details](docs/guides/operator-guide.en.md#operator-controls-reference).


## Claude Code backend

`--backend claude-code` selects an independent path for all phases, without a
Codex executable/configuration lookup or fallback. Claude uses the shared
external-launcher, accepted-plan, STOP, budget and review/DONE controls. Review
and parent review exclude Bash and write tools; Decide excludes task tools.
Production Bash requires native sandbox availability with no unsandboxed escape.
Linux needs the native sandbox prerequisites; Windows production uses WSL2/Linux.
Named MCP selections fail before model calls. Explicit ARQUILO skill text does
not enable native Claude plugins, skills, subagents or external MCP tools.

Native file tools, mandatory managed integrations, authentication and provider
behavior are not a whole-process sandbox. Event validation is an acceptance
gate, not a pre-tool interceptor. Accepting a known built-in telemetry identity
does not disable telemetry. See [backend permissions](docs/guides/operator-guide.en.md#backends)
and [Claude qualification](docs/claude-code-backend.md).

## Acceptance and optional publication

A publication error does not invalidate an otherwise accepted task. `--git`
records delivery separately; `--git-required` makes unfinished delivery stop
the run while keeping the task's accepted state. Neither mode permits a changed
snapshot, forged token or modified selected output to masquerade as the bytes
that passed review. Model-free publication retry uses retained private evidence
and reconciles uncertain local/remote outcomes; it does not rerun production or
approve new content. See [Git operations](docs/guides/operator-guide.en.md#git).
