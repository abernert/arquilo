# Compatibility and naming history

## Current names (ARQUILO 0.2.0)

ARQUILO is the only active project name. Use `arquilo.py` and
`arquilo_doctor.py`, `ARQUILO_*` configuration names and `arquilo.*` schema
identifiers. The public package version is 0.2.0. Individual schema version
suffixes still describe their unchanged payload contracts, not the package version.

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
`autobuild.py`, `decide.py`, `.codex_runs` and Markdown task syntax stay intact.
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
