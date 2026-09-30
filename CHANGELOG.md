# Changelog

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
