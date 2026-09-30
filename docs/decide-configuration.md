# Decide: use the owner's Codex configuration (0.3.2)

## Routing is not ARQUILO policy

Decide, including `arquilo_doctor.py --check-decide`, does not choose a model,
provider, endpoint, credential scheme or reasoning effort by default. With no
explicit override, Codex loads the configured values in its normal user/managed
configuration. An existing `CODEX_HOME` is honored, otherwise the user's `.codex`
is used. ARQUILO does not parse/copy that configuration or create a replacement.

This matters for corporate gateways such as Databricks: deployment names,
provider IDs, base URLs, headers, arbitrary `env_key` names, proxy variables and
CA/certificate settings must remain under the existing Codex/IT configuration.
ARQUILO preserves the host process environment, without loading a project `.env`
or dumping its values. Authentication is Codex's responsibility; no `auth.json`
is required merely to use a provider configured with environment credentials.

```powershell
# Existing Codex config, including its configured provider/model:
python arquilo_doctor.py --check-decide

# Change only the model, leaving the configured provider unchanged:
python arquilo_doctor.py --check-decide --model "approved-deployment"

# Only when explicitly desired: select a provider ID already defined in Codex:
python arquilo_doctor.py --check-decide --model-provider "company-gateway"
```

The Python `decide`, `decide_bool`, `evaluate` and `DecisionRequest` APIs accept
optional `model` and `model_provider`. Unspecified values remain `None`, not a
hard-coded product/model name. The runner continues to forward explicitly
selected task/Decide models. A provider error does not trigger an alternate
model, alternate provider, new login or automatic configuration edit.

An archive's `model: null`/`model_provider: null` means **no override**; it does
not pretend that ARQUILO knows which model Codex resolved internally. Archives
record selection origin and the actual argv. Treat raw CLI streams as sensitive.

## Remaining arguments have a purpose

Decide needs JSON events, an output schema, an output file and stdin for its
structured request. A fresh temporary cwd avoids task-repository configuration;
`--skip-git-repo-check` permits it and `--ephemeral` avoids a reusable session.
The cwd is still outside the task workspace, so project-local model settings
are not imported. Put provider provisioning in the user/managed Codex config.
There is no new ARQUILO profile/config-file dialect or automatic profile choice.

The remaining fixed overrides restrict tools: read-only sandbox, no approval
escalation, disabled web search, no AGENTS document discovery/notify hook, and
the existing disabled tool features grouped in **one** TOML `features` table.
Features are still discovered and their effective values verified per call.
No `model_provider="openai"`, `--ignore-user-config`, `--ignore-rules`, or
`--strict-config` is added to Decide. Production/review policies are unchanged.

Loading normal config also exposes configured MCP integrations. Merely passing
`mcp_servers={}` would not clear them: Codex merges configuration tables.
Decide therefore asks Codex for `mcp list --json`, adds one compact table that
disables the listed servers for this call, and verifies the disabled state when
servers exist. Missing/invalid introspection or ineffective disable controls
stop before the model starts. Raw MCP configuration is neither displayed nor
archived; it may contain headers or credentials. No provider parsing is needed.

These metadata checks make no model request, but Codex may consult configured
MCP authentication endpoints or trusted credential helpers. They are not
promised to be offline or free of every host-side effect. Trusted configuration
and host environment are intentional inputs, not an isolation boundary from the
machine owner. Do not run untrusted Codex configurations or edit them mid-call.
An unexpected tool event is rejected, but event validation is not a pre-tool
interceptor or substitute for Codex's native sandbox.

## Testing limits

Offline tests cover forwarding, environment preservation, no-fallback behavior,
redacted metadata failures and retained acceptance/tool controls. The opt-in
`scripts/check_codex_provider.py` runs real Codex against a local fake gateway
with dummy credentials. It checks configured endpoint/model/header selection,
explicit overrides, disabled MCP, response validation and a rejected request.
It does not use a real model or validate your Databricks account, corporate
proxy, certificate chain, Windows install layout or every native sandbox path.
