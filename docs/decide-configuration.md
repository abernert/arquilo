# Decide uses your Codex configuration (0.4.0)

Decide no longer replaces model/provider settings or disables user configuration.
It delegates provisioning to the installed Codex CLI, just as a normal local
Codex call does. This includes custom providers such as a company Databricks
gateway, their authentication commands/environment variables, endpoints, HTTP
headers, proxy and certificate configuration. ARQUILO does not implement a
Databricks adapter, choose a deployment, acquire credentials, or rewrite TOML.
Your endpoint must already be compatible with the installed Codex CLI.

## Default and explicit overrides

The normal command remains:

```sh
python3 arquilo_doctor.py --check-decide
```

With no model, provider, profile or reasoning-effort argument, **none of these
selectors is sent to Codex**. Their effective defaults come from the trusted
Codex user/managed configuration, and its normal configuration precedence.
`CODEX_HOME` is inherited when present; otherwise Codex uses its normal home.
There is no required OpenAI login or `auth.json` check for an external provider.
The parent environment is copied without discarding custom token names,
`HTTPS_PROXY`, `NO_PROXY`, CA variables or provider authentication dependencies.
No `.env` file is loaded by ARQUILO.

When needed, select only the value(s) to override:

```sh
python3 arquilo_doctor.py --check-decide --model my-approved-deployment
python3 arquilo_doctor.py --check-decide --model-provider databricks
python3 arquilo_doctor.py --check-decide --profile corporate
```

These are examples of **already configured** names, not built-in defaults.
`--model-provider` selects a provider ID; it does not define a URL or credentials.
A model override does not also change the provider; a provider override does not
also select a model. Reasoning effort is forwarded only when supplied.

Python callers can use `decide(..., model=..., model_provider=...,
config_profile=...)`, `decide_bool(...)`, `evaluate(...)`, or
`run_decision(request, model_provider=..., config_profile=...)`.
Host-only `DecisionExecSettings` can also carry provider/profile selectors.
Explicit per-call non-None selectors take precedence over those settings;
None means do not override. Models and effort remain part of DecisionRequest.
AutoBuild passes its explicitly selected Codex profile to Decide as well.
Existing explicit `ARQUILO_DECISION_MODEL`/task model settings still apply.

ARQUILO **does not parse config.toml itself**, infer a provider from a model name,
fall back to OpenAI, select a new model when a provider fails, or copy credentials
into the prompt/argv. Model/provider fields in its diagnostic records describe
explicit overrides only. A null value means inherited, not a guessed effective
model. Inspect Codex locally when you need to know the effective configuration.

## What is still passed

A default internal call has this shape (paths vary by attempt):

```text
codex exec --json --output-schema schema.json --output-last-message response.json
  --skip-git-repo-check --sandbox read-only -c approval_policy="never" -
```

The actual process receives absolute output paths and its cwd separately; this
is an argv illustration, not a shell command requiring multiline copy/paste.
The prompt is UTF-8 on stdin. JSON/schema/output flags are needed to validate the
response and retain evidence. The read-only/never pair keeps the call
non-writing and non-interactive at the requested sandbox/approval level.
No extra write roots or sandbox/network bypasses are granted. Codex/admin
requirements still determine effective enforcement and can reject a request.
Provider network access is not the same thing as granting shell network access.

There are no ARQUILO-generated `features.*` overrides, no feature-table probes,
no `model_provider="openai"`, no `--ignore-user-config`, no `--ignore-rules`,
no `--strict-config`, and no forced `--ephemeral`. Codex session persistence
therefore follows Codex's configured behavior too. The Doctor only asks for
`--version` and `exec --help` before an optional model test. Each real Decide
call checks the required Exec flags without an implicit version pin.

## Trust boundary and limits

**Configuration inheritance is intentional, and is a different trust boundary
from the former isolated-feature policy.** The Codex configuration and process
environment must be trusted host inputs, not values supplied by a model or task.
Configured hooks, MCP servers, skills, notification commands and other runtime
integrations may initialize or run according to Codex's own rules. ARQUILO no
longer disables them en masse. Read-only is not a complete read/network or
host-hook sandbox. This is not an assertion of zero side effects.

Decide still asks the model not to use tools and rejects tool/unknown events
instead of accepting their result. That event check happens after events are
emitted: it is **not** preventive authorization and cannot undo a tool or hook
that already ran. If a trusted configuration presents unnecessary tools or
hooks, use an IT-approved Codex profile that restricts them; ARQUILO will not
invent one or edit your configuration. Timeouts, process-tree cleanup, call
budgets, schema/option validation and complete-archive requirements remain.
There is no automatic retry with a different provider or more permissions.

The attempt cwd is still a fresh directory outside the task repository. This
intentionally avoids inheriting model-editable project configuration. Provider
settings belong in Codex user/managed configuration or a named trusted profile.
A model/provider choice made only in a live VS Code session is not necessarily a
saved CLI default: select an approved profile or supply the needed override.
Relative credential commands should be configured so Codex can resolve them
independently of the task workspace. CLI and extension processes must have the
same approved environment for the same provisioning behavior.

## Evidence, compatibility and testing

No environment values, tokens, complete configuration files, or hashes of
credentials are added to diagnostics. Codex's own raw output can still contain
sensitive text, so run archives remain private. Explicit selectors and argv are
recorded, and the configuration is never rewritten by ARQUILO (Codex itself may
maintain its normal session/cache/authentication state).

The Doctor and decision-attempt archive use `arquilo.doctor.v2` and
`arquilo.decision_attempt.v2`: obsolete feature-negotiation fields are replaced
by `configuration_policy` and actual CLI capability metadata. Decision request
and result schemas are otherwise unchanged; old archives are not rewritten.

`tests/test_decide_configuration.py` covers default/explicit precedence, token,
proxy and certificate inheritance, CODEX_HOME, minimal argv, immutable inputs,
error/no-fallback behavior, schema-only retries, cancellations and archival.
The existing controller hardening and event-policy tests remain. Real upstream
CLI tests use synthetic provider configuration, not company credentials or
inference. A real Databricks deployment and native sandbox still need local
acceptance; an offline test is not proof of either.
