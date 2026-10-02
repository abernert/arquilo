# Compatibility and naming history

## Current names (ARQUILO 0.6.0)

ARQUILO is the only active project name. Use `arquilo.py` and
`arquilo_doctor.py`, `ARQUILO_*` configuration names and `arquilo.*` schema
identifiers. The public package version is 0.6.0. Individual schema version
suffixes describe their payload contracts, not the package version; see the diagnostic migrations below.

## Historical project name — DORA Lean

DORA Lean was the predecessor project's name. ARQUILO 0.1.0 still retained some
of those spellings as active identifiers. From 0.2.0, the old name appears only
in explicitly historical records, input compatibility code and regression tests.
The previous internal version `1.0-rc5` was not public 1.0 stability.
Historical releases, tags and prior run archives are not rewritten.

| Historical name | Current name / migration |
| --- | --- |
| `dora_doctor.py` | `arquilo_doctor.py`; the old file is removed, not an active wrapper |
| `python arquilo.py doctor` | Unchanged public convenience command |
| `DORA_CODEX_MODEL` | `ARQUILO_CODEX_MODEL` |
| `DORA_CODEX_REASONING_EFFORT` | `ARQUILO_CODEX_REASONING_EFFORT` |
| `DORA_DECISION_MODEL` | `ARQUILO_DECISION_MODEL` |
| `DORA_DECISION_SYSTEM_PROMPT` | `ARQUILO_DECISION_SYSTEM_PROMPT` |
| `DORA_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` |
| `DORA_CODEX_STALL_TIMEOUT_SECONDS` | `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS` |
| `DORA_CODEX_KILL_GRACE_SECONDS` | `ARQUILO_CODEX_KILL_GRACE_SECONDS` |
| `DORA_TODO_SYNTAX` / `DORA_TODO_PREAMBLE` | `ARQUILO_TODO_SYNTAX` / `ARQUILO_TODO_PREAMBLE` |
| `DORA_RUNTIME_PROFILE` | `ARQUILO_RUNTIME_PROFILE` |
| `dora.runtime_profile.v1` | `arquilo.runtime_profile.v1` |
| `dora.lean.package.v1` | `arquilo.lean.package.v1` |
| `dora.call_budget.v1` | `arquilo.call_budget.v1` |
| Other emitted `dora.*` schema identifiers | Same payload and version suffix, now under `arquilo.*`; update downstream readers |
| Doctor JSON field `dora_version` | `arquilo_version`; no old-name field is emitted |
| `DORA_*` Python constants and `dora_capabilities_payload()` | `ARQUILO_*` constants and `arquilo_capabilities_payload()`; update direct imports |

### Input compatibility, not active branding

The supported historical environment names above are read with `FutureWarning`.
Precedence is: explicit CLI/API option, nonempty `ARQUILO_*` variable, its
historical `DORA_*` spelling, then any older `AUTOBUILD_*` / `METACODEX_*` alias
already supported for that setting. Warnings identify names only, never values.
The caller's environment and configuration files are not modified.

Runtime profiles, package manifests and existing call-budget records accept the
exact historical schema spelling at the same schema version, with a warning.
Unknown schemas and unsupported schema versions still fail closed. Runtime
profiles are normalized in memory; budget claim counts and limits are preserved;
old budget files and logs are not rewritten. New snapshots use current names.
Historical schema acceptance does not disable any content or policy validation.

This is a versioned migration, not a promise that every old JSON consumer can
read new output unchanged. Update readers that match schema strings, the doctor
version key, direct Python imports or old prompt markers. Existing `run_todos.py`,
`autobuild.py`, `decide.py` and Markdown task syntax stay intact.
Runner control records/logs moved outside the workspace in 0.3.0; see
[controller state and migration](controller-safety.md).
Doctor logs now use `.codex_runs/arquilo_doctor`; old diagnostic folders remain.

Removed predecessor features are still rejected, including both old and renamed
spellings where applicable. See the [historical migration notes](../documents/HISTORICAL_MIGRATION.md).

## Codex and preview policy

The runtime checks required CLI capabilities rather than trusting a version
string alone. Record Codex version, OS, Python version and model in bug reports.
No executable or authentication state is distributed. Production, review and
Decide have different policies; a successful Decide test does not attest to all
other paths. Offline regression tests do not certify native sandbox enforcement.
Expect documented changes during 0.x; use public entry points and capability
checks instead of private implementation details.

## Configuration inheritance (from 0.4.0)

The 0.2.1–0.3.1 feature-negotiation policy is historical. Decide now uses the
trusted Codex user/managed configuration and inherited process environment.
It omits model/provider/profile/effort unless explicitly selected. User config,
rules and integrations are no longer discarded or disabled with bulk feature
flags. See [Decide configuration and trust boundary](decide-configuration.md).

Only required Exec flags are checked (`--version` and `exec --help` in Doctor,
`exec --help` at the actual Decide start). Older CLIs are not rejected merely
because an unrelated feature is absent. Missing protocol flags, help failures
or cancellation still stop before a model call. No silent fallback is made.

Doctor output is now `arquilo.doctor.v2`, and decision attempt manifests use
`arquilo.decision_attempt.v2`. Update consumers of the removed feature metadata:
use `configuration_policy`/`cli_compatibility` instead. Core decision request and
result validation is unchanged. Old archives and release tags remain untouched.

## Readable project logs (from 0.5.0)

`--project-id` adds a workspace-bound readable log namespace while retaining
existing plan journals and budgets at their canonical paths. Keep the same
state root for an existing plan. See [project logs](project-logs.md).
New `run.json` uses `arquilo.run_log.v2`; `run_log.json` remains a v1-compatible
snapshot. Capture paths are numbered phase folders, not `.jsonl.calls/call-*`.
Use captured path metadata instead of hard-coded directory patterns. Old
archives are unchanged. No Codex invocation or provider policy changes here.

## Operator controls (from 0.6.0)

Default `--max-calls` is 0 (unlimited), including existing finite runner budgets.
Owner limit changes retain consumption; stale workers fail on a mismatch.
New budget and claim output uses `arquilo.call_budget.v2` and
`arquilo.call_claim.v2`. In v2 `limit=0`, `remaining=null`, `unlimited=true`
represents unlimited. Valid finite v1 data (including historical input aliases)
remains readable, without rewriting old claim files. Update summary consumers.

New opt-ins `--logs-in-workdir` and `--allow-todo-modifications` are false by
default. Run metadata adds `logs_location`, `todo_policy`, `plan_mutations`,
`reviewed_this_run`, `stop_id` and `completion_scope`. The compatible run_log
remains; model-written task statuses are not reviewed completions. A generated
plan can remain in the original task file and halt with `--stop 2` for human
inspection. See [operator controls](operator-controls.md) for exact semantics.
These controls do not restore other removed predecessor modules.
