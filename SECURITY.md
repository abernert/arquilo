# Security policy

ARQUILO 0.1.0 is an experimental public preview. Evaluate it under supervision
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
- Decide runs with restricted configuration and rejects tool/unknown events.
  Its event validation is an acceptance gate, not a pre-tool security interceptor.
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

## Operational baseline

Run as an ordinary user. Do not disable UAC, broadly grant filesystem permissions,
use unrestricted sandbox modes, or execute arbitrary user-submitted tasks on a
shared production host. Keep credentials outside project workspaces and logs.
Use user-owned temporary directories, backups and explicit least-privilege inputs.
Review local runtime profiles and Codex integrations before granting access.

CI deliberately has no model credentials and never runs live agent workloads.
Its tests do not establish that the native sandbox correctly enforces every
boundary on a user's installation.
