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

- Production is constrained to Codex `workspace-write`; review requests use
  `read-only`. ARQUILO is not itself an OS sandbox. Native enforcement and setup
  depend on Codex and the host. A fresh directory does not imply full read isolation.
- Decide inherits trusted host Codex configuration/environment (including provider,
  proxy and credential dependencies) and requests `read-only`/`never`. It rejects
  tool/unknown events, but this is an acceptance gate, not a pre-tool interceptor.
  Configured tools, MCP servers, hooks and auth/notification commands may start
  under Codex's own rules. Do not treat config inheritance as zero side effects
  or a blanket tool-disable mechanism. See [Decide configuration](docs/decide-configuration.md).
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
restricted, user-owned directory with appropriate ACLs. Do not grant Codex,
external tools or other users extra access to the state root. Profiles with
`preflight.command` are **trusted executable code with host permissions**, not
untrusted configuration; do not run downloaded profiles without inspection.

`--git` requires literal owner-selected files; selected files must initially be
clean or absent. A local commit does not imply authorization to publish it.
Only `--git-push` enables a push, and unrelated unpushed commits are refused.
Do not edit the selected files, Git index or branch concurrently with a run.
The allowlist is not a content/secret scanner or proof that every output is
correct. Inspect sensitive deliverables before publishing.

See [controller safety](docs/controller-safety.md) for migration and recovery.

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
changes Codex permission settings. See [details](docs/operator-controls.md).

## Workbench and evidence-only Ask preview

The feature-branch Workbench binds only to loopback, authenticates every API action,
validates Host/Origin and request sizes, and keeps owner edits separate from review
and controller adoption. It is not a public web service. Keep its URL secret and
installed runtime code outside model-writable production workspaces.

Ask requires explicit provider consent and uses a bounded no-follow text broker,
an empty Codex cwd and a fixed restricted-tool preset. Required metadata failures
refuse the model call. Post-event rejection of tools does not undo execution, and
trusted global/managed Codex configuration, authentication hooks and the host remain
security boundaries. Read-only is not offline or confidential. Source citations
prove valid anchors, not correct interpretation. See [the detailed limits](docs/workbench.md).
