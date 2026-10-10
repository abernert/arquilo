# Changelog

## 0.7.2 — 2026-10-10 (public preview)

- On macOS, reap a leader killed by this controller before checking an EPERM
  from a follow-up group signal. Ignore that race only when a new whole-group
  probe proves ESRCH; live/inaccessible groups and actual permission failures
  remain fatal. Never send a redundant SIGKILL after confirmed group absence.

- Classify only the documented pre-terminal WebSocket reconnect notice as a
  provisional diagnostic. Preserve its original event and ordinal; keep unknown
  errors, terminal failures, missing completion/answer and timeouts fatal.
- Preserve an observed stop and its first reason independently of execution
  failures, through collection/draining, AutoBuild and private Python workers.
  A clean controller stop is cancelled/6; a genuine failure plus a stop remains
  failed/7 with both facts retained. Natural nonzero exits are not excused by a
  later sentinel; only evidenced controller termination is expected.
- Add validated stop/diagnostic metadata and explicit terminal-attempt identity
  without changing existing schemas or positional arguments. Report the actual
  stopped fix/Decide capture rather than guessing from the grouped attempt list.
  Print each diagnostic path only once per attempt, including clean stops.
- Add offline synthetic subprocess, I/O-fault, controller and worker regressions.
  No original application logs or prompts are included. Do not replay tasks,
  reset budgets, change DONE/review rules or rewrite historical archives. This
  repairs local classification and reporting, not the network itself; other
  reconnect message formats still require their own compatibility evidence.

### Upgrade notes and scope

- Update the controller and workers together; retain the same workspace,
  task-file path and controller-state root. No state/budget reset or Codex
  reconfiguration is required. Existing logs and task states are not rewritten.
- Inspect partial results before explicitly restarting a stopped task. Stop
  instructions remain effective, and no task is automatically replayed or
  marked DONE. Mandatory reviews and all execution permissions are unchanged.
- Log readers may consume additive stop/diagnostic fields and `terminal_attempt`.
  Do not infer the terminal call from the last grouped `execution_attempts` item.
- Recognition remains limited to the evidenced WebSocket reconnect notice.
  Other formats, including `error decoding response body`, are not newly
  classified as provisional by this release.
- The full suite contains 480 test methods, including 49 new synthetic
  regressions. Cross-platform CI and loopback-provider checks are distinct
  from live MDE/Databricks acceptance or native sandbox certification.
- Public preview; no new runtime dependencies or original application
  handoff data, prompts, archives or project outputs are included.

## 0.7.1 — 2026-10-07 (public preview; hardening)

### Controller and publication hardening

- Integrate seven reproduced adversarial-audit repairs and an independently
  reproduced Git publication-scope repair from PR #21.
- Ignore Markdown task headers, directives and fences inside code examples
  indented by four or more columns, including tab indentation. Executable
  task entries with up to three leading spaces remain supported.
- Use the existing link-safe controller readers for breakdown-round metadata,
  workspace summary candidates and result-report feedback. Unsafe linked
  files fail rather than supplying trusted controller input.
- Require completed (`DONE`) children before parent acceptance; an obsolete
  child cannot substitute for a completed child. The separate parent review
  remains mandatory.
- Pin and recheck the configured Git push destination. Add `--no-follow-tags`
  so automatic publication does not include unrequested annotated tags when
  Git's `push.followTags` setting is enabled. Local tags and user Git
  configuration are not modified.
- Escape terminal control characters in the selected worker-event display
  path while retaining original evidence; this is not general log redaction.

### Regression evidence

- Add 99 adversarial test methods covering plan authority, linked files,
  review contracts, parent acceptance, crash/resume, budgets, Git publication,
  diagnostic boundaries and a small deterministic state/input fuzzer.
  The full suite discovers 431 test methods; platform-specific skips remain
  explicit and are not counted as passes.
- Isolate orchestration-test budgets from the user's default state directory.
  Keep test fixture bytes exact on Windows and preserve Git's configured
  checkout bytes during cleanup. No failing test or security check is disabled.
- The hardening PR passed all nine Linux/macOS/Windows × Python 3.11/3.12/3.13
  CI jobs and all six Codex metadata/loopback compatibility jobs (CLI 0.154.0
  and 0.159.1). The owner subsequently reported a successful supervised local
  smoke test and authorized merge and release. This is not a certification
  of live sandbox enforcement, model correctness or Daybreak entitlement.

### Upgrade notes and boundaries

- Start real task-list entries and control directives with no more than three
  leading spaces. Move executable entries out of four-column/tab-indented
  examples before relying on older task lists.
- No new installation, authentication, provider/model selection or controller
  state reset is required by this release. Native Codex worker permissions,
  the read-only review policy and verdict-based acceptance are not relaxed.
- The pipeline runtime remains unimplemented. A formal reviewer PASS is not
  proof of factual correctness; optional Git follow-up recovery is not fully
  idempotent; raw archives are not immutable, encrypted retention-managed
  storage. Push-destination checks are not atomic locks against concurrent
  host-level Git configuration changes. ARQUILO remains a public preview.

## 0.7.0 — 2026-10-06 (public preview)

- Align executing Codex calls with native `workspace-write` semantics: stop
  suppressing Codex exec-policy rules, stop forcing an empty additional
  writable-root list, and stop excluding `$TMPDIR` and `/tmp` from Codex's
  standard writable roots. Keep the explicit `workspace-write`/read-only split,
  unattended `approval_policy="never"`, and the existing shell-network control.
- Treat Codex profile names as ordinary Codex identifiers instead of blacklisting
  historical-looking names such as `dev` or `yolo`; the explicit sandbox mode
  still prevents a profile name from re-enabling retired ARQUILO YOLO behavior.
- Add advisory review confidence, evidence, uncertainties and optional follow-up
  suggestions, plus a read-only summary reporter. Legacy reviews remain valid;
  confidence is not calibrated and never changes verdict-based acceptance.

- Introduce `arquilo tasklist run` as the canonical task-list command. Keep
  `arquilo run` as an argument-preserving alias with a short stderr notice.
  Add offline dispatch, JSON, help, dry-run and removed-policy regressions.
- Update current CLI examples and document a proposed pipeline MVP, including
  artifact revisions/amendments, downstream revalidation, process journals and
  stage context/MCP boundaries. The pipeline runtime is not implemented.

- Explain when an ordinary task review passed but a later plan-integrity check
  blocked automatic DONE. Give conditional owner-recovery guidance without
  changing stop/status/acceptance rules or adding execution retries.

- Refresh pinned GitHub Actions for checkout (7.0.1), Python setup (7.0.0)
  and artifact upload (7.0.1); retain the existing multi-file artifact archive.

### Upgrade notes

- Use `python arquilo.py tasklist run ...`. Existing `run` commands still work;
  wrappers must tolerate the migration notice on stderr. Keep the same workdir,
  task-file path and state root when continuing existing work; no state or budget
  reset is required. The unlimited default budget remains unchanged.
- Update the controller, workers and review readers together. Older ARQUILO
  readers may reject the added confidence fields; historical reviews without
  confidence remain valid in 0.7.0. Scores are uncalibrated reviewer estimates,
  not correctness probabilities or new acceptance thresholds.
- Review trusted Codex user/project/profile settings before use: configured
  writable roots, temporary directories and exec-policy rules now remain
  effective. `workspace-write` is not a promise that only the workdir is writable.
  Production/review modes, unattended approvals, explicit shell-network grants,
  mandatory reviews and controller-owned state checks remain in place.
- A manual DONE adoption after a plan-mutation stop still requires operator
  inspection and one-time `--accept-plan-changes`; this release does not silently
  accept modified requirements or remove STOP markers.

### Scope

The pipeline document is a design proposal, not an implemented `pipeline run`.
Workbench/Ask from PR #12 is not included. Python 3.11+ and a separately installed
Codex CLI remain the prerequisites; there are no new Python runtime dependencies.
This is a public preview. Offline/controller and synthetic-provider checks do
not establish live Databricks/MDE acceptance, native sandbox certification or
empirical calibration of review confidence.

## 0.6.2 — 2026-10-04 (public preview)

- State the review verdict/breakdown field dependencies explicitly in the shared
  task and parent-review instructions, including JSON null when no breakdown is
  recommended. Add a valid PASS example and align the review reference.
- Add offline prompt/parser and parent-dispatch regressions for PASS, local-fix
  FAIL and decomposition FAIL, including rejection of a PASS review with a
  textual no-breakdown reason. Existing validation, completion gates, provider
  selection and sandbox policy remain unchanged.

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
