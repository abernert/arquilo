# Changelog

## 0.3.2 — 2026-09-30 (public preview)

- Let Decide use normal Codex user/managed configuration and the configured
  CODEX_HOME. Preserve host provider credentials, proxy and CA environment.
  No forced provider, model, endpoint, authentication scheme or reasoning effort.
- Remove Decide-only user-config/rules suppression and strict-config override.
  Explicit model/provider selections still win; errors never select a fallback.
- Keep structured response validation, event controls, budgets and archival.
  Use read-only Decide sandbox and compact verified tool-feature restrictions.
  Disable configured MCP servers per invocation using Codex-native introspection,
  without copying configuration or recording raw MCP headers/environment.
- Add provider/configuration regressions and real-CLI loopback gateway tests.
  No claim of testing a real Databricks account or corporate Windows environment.

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
