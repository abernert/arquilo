# ARQUILO: configuration

The core uses the Python standard library, CLI arguments, and optionally a JSON runtime profile. ARQUILO loads no `.env` file; it requires no YAML, API key, or OpenAI Python SDK. Codex handles its own authentication. Importing the modules does not read run configuration; values are resolved for each invocation.

## Public core options

| Purpose | Option / default |
| --- | --- |
| Task list and workspace | `--todo-file <file>` and `--workdir <directory>`; without a workdir, the ToDo file's directory is used. Absolute paths remove ambiguity when starting elsewhere. |
| Model | `--model <id>`; without an override, the Codex default remains effective for production/review. |
| Reasoning | `--reasoning-effort <value>`; accepted values are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. Codex determines whether the selected model supports the value. |
| Shell network | `--network-access`; off by default. Sandbox is at most `workspace-write`, review is `read-only`. No network environment alias grants this permission. |
| Call budget | `--max-calls <number>`; default **0 = unlimited**, positive values apply per task tree across restarts. Previously stored finite budgets adopt the new default while preserving usage. [Details](WORKFLOW_LIMITS.md). |
| Workdir logs | `--logs-in-workdir`; off by default. Live diagnostics go to `<workdir>/.codex_runs/run_todos`; controller state/budgets stay external. |
| Mutable plan | `--allow-todo-modifications`; off by default. Permit and record valid changes in the same task file; `--stop 2` remains an execution boundary. [Examples](../docs/operator-controls.md). |
| Dry run | `--dry-run --dry-run-file <file>`; writes a command preview, runs neither Codex nor profile preflight, and changes no task status. |
| Diagnostics | `python arquilo_doctor.py --workdir <directory> --json`; free local metadata, no version pinning. Add `--check-decide` for a real functional probe that may incur one model call; `--model`, `--reasoning-effort`, and `--decide-timeout` apply only to that probe. [Usage and limits](QUICKSTART.md). |

AutoBuild has the same model/network options and accepts `--task` or `--task-file` instead of a ToDo list. Additional retained options for selection, preamble, continuation, and specialized paths are documented by `--help`. There is no new general configuration file duplicating CLI values.

## Precedence and normalization

`--model`, or the direct Python parameter, takes precedence over `ARQUILO_CODEX_MODEL`. A global model value takes precedence over `CFG model`; without a global value, the CFG model applies. `--reasoning-effort` takes precedence over `ARQUILO_CODEX_REASONING_EFFORT`.

Leading/trailing whitespace is removed, empty values count as unset, and effort values are lowercased and validated. Runner and AutoBuild use the same resolver in `runtime_config.py`. Values are passed per invocation; Codex configuration files are not modified.

ARQUILO explicitly selects `workspace-write` for executing workers, `read-only` for review/Decide, `approval_policy="never"` for unattended execution, and the runner's shell-network grant. It does **not** suppress Codex exec-policy `.rules`, force `sandbox_workspace_write.writable_roots=[]`, or exclude Codex's normal `$TMPDIR`/`/tmp` workspace-write roots. Trusted Codex user/project/profile configuration therefore remains effective within the selected sandbox mode. Task CFG/runtime-profile fields still cannot replace the selected sandbox/approval policy or smuggle arbitrary Codex CLI arguments.

Decide receives explicit task/decision model and effort values. Without an override, model, provider, endpoint, authentication, and other provisioning parameters remain the responsibility of the Codex host configuration. `CODEX_HOME` and the complete trusted process environment, including proxy/CA/provider tokens, remain effective; ARQUILO does not read or copy credentials or TOML files.

Doctor optionally supports `--model-provider <ID>` and `--profile <Name>` for `--check-decide`; without them, no corresponding override is generated. The same applies to `model_provider`/`config_profile` in the Decide Python API. An explicitly selected AutoBuild Codex profile is also passed to Decide.

The many historical feature overrides and duplicate feature queries were removed in 0.4.0. Decide uses a fresh working directory and `read-only`/`never`, validates response/schema/options, and rejects tool events. Configured integrations remain part of host trust, however; event validation does not proactively prevent a tool/hook call that has already fired. See [Decide configuration and boundaries](../docs/decide-configuration.md).

Retained specialized options:

- `--todo-syntax` / `ARQUILO_TODO_SYNTAX` and `--todo-preamble` / `ARQUILO_TODO_PREAMBLE`: CLI before environment, default `auto`.
- `--runtime-profile` / `ARQUILO_RUNTIME_PROFILE`: CLI before environment; optional declarative JSON for prompt rules and preflight, see the [profile contract](../RUNTIME_PROFILE_API.md). Its preflight remains mandatory in a real run; a dry run records that the check was skipped.
- `--git`: since 0.3.0, only with repeated `--git-path FILE`; commit selected files after successful acceptance. Push additionally requires `--git-push`. Without `--git`, ARQUILO does not require Git for execution.
- `CFG parallel` and Codex tool profiles remain available; see [Package scope](PACKAGE_SCOPE.md) and [ToDo directives](todo_directives.md). Web search, shell network, MCP, and provider communication are separate paths; network disabled does not mean offline.

There are no optional feature groups or activation configuration for removed features. `--print-capabilities` reports retained core options as `retained_core_options`; historical empty fields `optional_packages`, `optional_defaults`, and `retained_optional_paths` are gone. Versioned contracts under `features` remain. Package building accepts neither `--with-optional` nor Python `optional`, including empty values. See [Distribution](DISTRIBUTION.md).

## Expert options and historical input aliases

The following settings are expert options, not required configuration. Historical names remain accepted with `FutureWarning`; the full [naming map](../docs/compatibility.md) documents the predecessor prefix. A non-empty canonical value wins; if two old values are present, precedence follows the table. Warnings mention variable names only, never values. Settings or secrets are not automatically written to files.

| Canonical name | Old names (left-to-right precedence) | Default |
| --- | --- | --- |
| `ARQUILO_DECISION_MODEL` | `AUTOBUILD_DECISION_MODEL`, `METACODEX_DECISION_MODEL` | effective task model |
| `ARQUILO_DECISION_SYSTEM_PROMPT` | `AUTOBUILD_DECISION_SYSTEM_PROMPT`, `METACODEX_DECISION_SYSTEM_PROMPT` | existing decision instruction |
| `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | `AUTOBUILD_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | 120 seconds |
| `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS` | `AUTOBUILD_CODEX_STALL_TIMEOUT_SECONDS` | 7200 seconds |
| `ARQUILO_CODEX_KILL_GRACE_SECONDS` | `AUTOBUILD_CODEX_KILL_GRACE_SECONDS` | 10 seconds |

Timeout values must be finite and non-negative; invalid values are configuration errors. For the direct transport adapter, its explicit `env` replaces the process environment; explicit `TransportTimeouts` take precedence. These three environment options affect AutoBuild; Decide retains its own bounded `DecisionExecSettings`/timeouts.

## Historical migration

Removed predecessor features are not current ARQUILO options. The complete [historical migration notes](HISTORICAL_MIGRATION.md) remain for reference. For supported old environment names, see [Compatibility and naming migration](../docs/compatibility.md).

## Controller state and Git since 0.3.0

The authoritative reference is [Controller safety](../docs/controller-safety.md), including `--state-dir`, `--accept-plan-changes`, `--git-path`, and `--git-push`. Git push is no longer an automatic consequence of `--git`. Existing dry-run reports are never overwritten. Existing policy read failures stop the run.
