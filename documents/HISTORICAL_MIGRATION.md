# Historical migration notes — former DORA runtime

DORA is the historical project name, not an active ARQUILO product or mode. The settings and development identifiers below describe retired predecessor features. They are rejected, not supported configuration examples. Current configuration is documented in [CONFIGURATION.md](CONFIGURATION.md).

## Archived notes for removed features

ACE has been removed. `AGENT_SYSTEM_ACE_CONTEXT` and `AGENT_SYSTEM_ACE_RUN_LOGGING` must be removed from the environment even when set to `off`, `false`, or an empty value. Runner and AutoBuild reject them before model startup with a migration message. `--ace-mode`, Python/worker `ace_mode`, and corresponding CFG/profile fields are also removed; old playbooks and ACE exports are not processed.

OpenClaw/Computer-Use/Bridge has been removed since 1031. `--openclaw-bridge`, Python/worker `bridge_enabled`, and corresponding CFG/profile fields are rejected even when `false`/`null`. The following environment variables were genuinely evaluated by the predecessor and must be removed; their mere presence is an error:

- `DORA_CUA_APPROVE_ALL`, `DORA_CUA_APPROVED_ACTIONS`
- `DORA_CUA_PREFLIGHT_HOST_OS_DARWIN`, `DORA_CUA_PREFLIGHT_PLAYWRIGHT`
- `DORA_CUA_PREFLIGHT_OSASCRIPT`, `DORA_CUA_PREFLIGHT_ACCESSIBILITY`
- `DORA_CUA_PREFLIGHT_AUTOMATION`, `DORA_CUA_PREFLIGHT_TESSERACT`
- `DORA_CUA_PREFLIGHT_SCREEN_RECORDING`

Old `.bridge/` files are not read, modified, or migrated. Bridge WAIT conditions must be changed in the task input; ordinary ToDo/group/agent WAIT conditions, STOP, and `process_stop` remain available.

IACT has been removed since 1032. `--iact`, `--iact-retention-runs`, `--iact-max-events`, `--iact-max-log-bytes`, and `--iact-max-tree-bytes` are errors even with zero, negative, or empty values. Python `iact_enabled` and the four corresponding underscore-style limit parameters are removed as well; `None` and `False` are not silently ignored. This also applies to worker, CFG, and profile fields, including `iact`, `iact_lite`, and `iact_limits`.

The old export did not itself evaluate IACT environment variables. To prevent wrappers from appearing to activate it, the corresponding DORA names are additionally rejected whenever present: `DORA_IACT`, `DORA_IACT_ENABLED`, `DORA_IACT_RETENTION_RUNS`, `DORA_IACT_MAX_EVENTS`, `DORA_IACT_MAX_LOG_BYTES`, and `DORA_IACT_MAX_TREE_BYTES`. Their values are not interpreted.

For direct `TodoRunner` use, the first 15 positional parameters remain. Old positional arguments at positions 16 (formerly `iact_enabled`) and 17 (formerly `bridge_enabled`) are explicitly rejected. Retained later options such as `breakdown_policy` and `max_calls` should be passed as keyword arguments. There is no replacement export and no automatic migration, retention, or deletion of old IACT files; core logs remain intact.

AutoBuild queue and HTTP/Prometheus services have been removed since 1033. `autobuild.py queue`, including `enqueue`, `list`, `show`, `cancel`, and `run-worker`, exits with code 2 before any file or model access. The same applies to `--queue-state`, `--prometheus-port`, `--poll-interval`, and `--max-jobs`. Python/worker/CFG/profile fields `queue`, `queue_state`, `prometheus_port`, `poll_interval`, and `max_jobs` are rejected even when `False`, `None`, zero, or empty. Former Python exports `queue_main`, `QueuedJob`, `QueueState`, `QueueWorker`, and `TelemetryMetrics` are no longer available; access through `autobuild` produces an explanatory `ImportError`.

The old services did not have their own environment-variable evaluation. For corresponding wrappers, `DORA_QUEUE_STATE` and `DORA_PROMETHEUS_PORT` are rejected whenever present, including during profile preflight. Existing queue state remains untouched. Standalone AutoBuild, direct `autobuild.start`, parallel CFG with Python workers, full logs, mandatory reviews, process stopping, and shared budgets remain available. `--max-retries` remains the separate runner option described in [WORKFLOW_LIMITS.md](WORKFLOW_LIMITS.md).

The former API-key/base-URL variables for DORA Decide are no longer evaluated. Removed Evidence, Logician, YOLO, and No-Check switches continue to be explicitly rejected. Old alias names are a migration path only; new configurations use current ARQUILO options.
