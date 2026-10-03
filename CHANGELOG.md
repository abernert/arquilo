# Changelog

## 0.6.1 — 2026-10-03 (public preview)

- Reorganize the README as a documentation entry point and add a repository-wide documentation map.
- Add platform installation guidance and an operator cookbook for common ARQUILO workflows.
- Translate the maintained runtime reference documentation to English while preserving legacy syntax literals where required for compatibility.
- Reframe older release-specific safety and Decide documentation as current guidance, with historical migration details kept explicitly separate.
- Correct runtime ZIP documentation to follow `VERSION` instead of a stale fixed 0.2.0 filename.
- Include the new documentation guide, installation guide and cookbook in the allowlisted runtime package manifest.
- No task execution, review, sandbox, model/provider, or other runtime behavior changes are intended in this release.


## 0.6.0 — 2026-10-02 (public preview)

- Default call budget to 0 (unlimited), including existing finite runner stores.
  Preserve counters/claims and audit owner limit changes; workers cannot reset
  or change limits. Emit budget/claim v2 and accept valid older finite records.
- Add independent --logs-in-workdir and --allow-todo-modifications opt-ins.
  Keep authoritative journals/budgets and worker IPC external; workspace logs
  are live diagnostics, not trusted controller authority.
- Support generating further tasks in the same primary file, followed by
  --stop 2 and human inspection. Retain original-assignment review snapshots;
  do not schedule generated tasks beyond the planning pause or parallel batch
  stop boundary. Record observed changes separately from reviewed completions.
- Keep strict plans/external logs by default, all stop instructions and other
  limits, and existing model/provider/sandbox/technical retry policy unchanged.
- Correct budget and log-location documentation and add operator regression
  coverage plus a synthetic single-file planning example.


## 0.5.0 — 2026-10-02 (public preview)

- Add optional `--project-id` for readable, workspace-bound log namespaces.
  Remember plan assignments without moving or resetting canonical state/budgets.
- Allocate one UTC-millisecond run directory, with short collision suffixes,
  latest-started text pointer, run status JSON and concise overview log.
- Flatten task/AutoBuild/Codex capture paths into numbered phase folders;
  retain identities inside manifests and keep old archives unchanged.
- Print exact stderr/capture paths for failed processes; record startup failure
  and caught cancellation without marking incomplete work successful.
- Keep legacy `run_log.json` consumers supported. Add project-layout, restart,
  concurrent-allocation and filesystem-boundary regression tests.
- No Codex model/provider/permission flags or existing release tags change.

## 0.4.0 — 2026-09-30 (public preview)

- Inherit trusted Codex user/managed configuration and host environment in Decide.
  Do not select a model, provider, endpoint, profile, auth mode or effort unless
  explicitly supplied. Honor CODEX_HOME and custom proxy/token/CA variables.
- Remove forced OpenAI provider, ignore-user-config/rules, strict-config and
  ephemeral flags, bulk feature overrides and feature-table negotiation.
- Keep only the structured-output flags and explicit read-only/never policy;
  preserve response/event validation, budgets, timeouts and complete archives.
- Add explicit-only provider/profile selectors to the Doctor and Decide API;
  forward AutoBuild's selected Codex profile. Do not copy/parse credentials/TOML.
- Document the changed trust boundary: configured integrations remain trusted;
  rejecting a tool event is not a pre-tool authorization mechanism.
- Replace retired feature tests with configuration/argv/environment regressions
  and real-CLI synthetic provider metadata checks. No real Databricks access is
  claimed. Diagnostic/attempt schemas advance to v2; old archives stay unchanged.


## 0.3.1 — 2026-09-30 (public preview)

- Remove ARQUILO's implicit `gpt-5.5` Decide default. When no task/Decide
  model is explicitly selected, ARQUILO now omits `--model` and lets Codex or
  the active provider choose its effective default. Explicit `--model` and
  per-call model selections remain unchanged.
- Clarify the Doctor behavior and add regressions proving that an unspecified
  model remains unspecified through the Decide transport.
- Diagnose the Windows `orchestrator_helper_launch_failed ... program not found`
  failure without weakening the sandbox, and document the known standalone
  launcher/resource-layout failure mode plus a safe version-matched diagnostic.

## 0.3.0 — 2026-09-30 (public preview)

- Keep authoritative task plans, call reservations and runner logs outside the
  model workspace. Reject unapproved status/removal/requirement changes, including
  on restart. Validate child insertion and retain mandatory parent review.
- Add no-follow controller I/O with anchored POSIX operations and Windows parent
  handle leases; reject symlink/reparse and hardlink redirection.
- Replace `git add -A` with required literal `--git-path` selections and a separate
  index. Preserve unrelated changes; `--git-push` separately authorizes publishing.
- Create dry-run reports exclusively; fail on an unreadable existing policy;
  preserve preflight argv exactly and reject nonfinite timeout values.
- Retain call reservations across restart and failed diagnostic writes; missing
  diagnostic claims do not refund the monotonic counter.
- Add negative regression tests and document migration/owner-adoption boundaries.
- Keep Codex 0.154.0/0.159.1 capability negotiation unchanged. No Codex update is
  required by this release. No claim of complete native sandbox certification.


## 0.2.1 — 2026-09-30 (public preview)

- Discover the installed Codex feature catalog before constructing Decide
  overrides; omit `daemon_auto_start=false` only when that reviewed optional
  feature is not advertised (e.g. Codex 0.154.0).
- Verify effective values in a second metadata probe. Present daemon auto-start
  must be disabled; missing required controls, malformed/duplicate entries and
  ignored overrides still fail before any model process starts.
- Apply the same capability negotiation in the Doctor AND the actual Decide
  transport, including direct calls that do not run the Doctor first.
- Preserve strict configuration, isolated environment, tool/event restrictions,
  call budgets and evidence. Record selected/effective settings in the archive;
  do not mutate user configuration or cache capabilities across calls.
- Explain optional absences and individual failures in text and JSON diagnostics.
- Add offline capability regressions and opt-in real-CLI metadata compatibility
  checks for upstream 0.154.0 and 0.159.1, without credentials or model usage.

## 0.2.0 — 2026-09-30 (public preview)

- Rename the direct diagnostic entry point to `arquilo_doctor.py`; update the
  CLI wrapper, examples, help, diagnostics, imports, tests and package manifest.
- Make `ARQUILO_*` environment names and `arquilo.*` JSON schemas canonical.
  Historical input aliases are documented and warn on use; matching original
  runtime-profile, package-manifest and call-budget inputs remain readable.
- Rename the doctor JSON version field to `arquilo_version`. Downstream output
  consumers and direct Python imports must follow the naming migration.
- Preserve existing call budgets, run archives, safety checks and mandatory
  review. No widening of sandbox permissions or automatic deletion of user data.
- Add naming and compatibility regressions and a release-time naming guard.
  Clearly separate historical notes from active configuration documentation.


## 0.1.0 — 2026-09-30 (public preview)

Initial public release as **ARQUILO**, a renamed continuation of DORA Lean.

- Markdown-task execution with separate review, bounded correction, decomposition,
  parent acceptance, shared call budgets and retained run evidence.
- Inline controller-captured review contracts for review/fix/parent paths, while
  preserving archived JSON evidence; no required sandboxed read of the archive.
- Nonfatal Codex diagnostic items supported in restricted Decide streams.
- Apache-2.0 licensing, copyright headers, attribution and contributor guidance.
- ARQUILO CLI wrapper; existing runtime files, variables and schemas retained.
- English quick start and architecture/security guides, German entry page,
  synthetic examples, offline regression tests and cross-platform CI.
- Allowlisted runtime ZIP with license/NOTICE inclusion and SHA-256 sidecar.

This is a preview, not a production or native-sandbox certification. Offline tests
and live model acceptance are distinct; see docs/testing.md.
