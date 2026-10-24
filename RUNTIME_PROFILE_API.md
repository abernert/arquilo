# ARQUILO Runtime Profile API v1

Applicable to the documented **0.9.1** runtime. A runtime profile contributes
operator-trusted domain instructions and preflight behavior. It cannot directly
set controller run state, approve a review or authorize task completion. JSON
runtime profiles are part of the core; no additional Python package is needed.

## Activation

```sh
python3 -B arquilo.py tasklist run --todo-file /project/tasks.md --workdir /project --runtime-profile /approved/profile.json
```

On native Windows substitute an installed Python interpreter and native paths.
The public CLI option precedes `ARQUILO_RUNTIME_PROFILE`. Relative file paths are
relative to the invocation directory. Inspect a profile and any executable
preflight before using it; task instructions are not authority to select trusted
host code.

## Profile fields

The JSON object requires `schema_version: "arquilo.runtime_profile.v1"` and a
nonempty `profile_id`. `profile_version` defaults to `"1"` and is a string.

| Field | Meaning |
| --- | --- |
| `activation_markers` | List of strings; all must occur for text-dependent profile activation. An empty list is active by default. |
| `scope_activation_markers` | Separate all-markers condition for relevant scope/protected-block checks. |
| `protected_markers` | Names of marked blocks that applicable guards expect to preserve byte-exactly. |
| `prompt_policy` | Supported instruction slots described below. |
| `preflight` | Optional ordered host command, timeout, working directory and environment overlay. |
| `metadata` | Operator metadata object, not interpreted as runtime authority. |

The implementation checks selected policy/removed fields and supported values;
it is not a universal strict rejection of every unknown JSON key. Use the known
fields and verify behavior rather than relying on ignored misspellings.

## Prompt policy

Supported fields are `controller_only_instruction`, `task_contract_instruction`,
`breakdown_scope_guard`, `legacy_review_boundary`, `parent_review_scope_guard`,
`parent_review_terminal_rule` and `autobuild_review_rules`.

`autobuild_review_rules` is a list of additive review instructions. Other fields
populate specific existing instruction/guard slots; some replace that slot's
built-in text. Do not describe every contribution as universally additive.
Placeholder availability is specific to the consuming call site. Keep the
controller's executable status, review and permission rules independent of prose.

A minimal complete example, with no executable preflight:

```json
{
  "schema_version": "arquilo.runtime_profile.v1",
  "profile_id": "example.source-review",
  "profile_version": "1",
  "prompt_policy": {
    "autobuild_review_rules": [
      "Distinguish supplied source facts from assumptions.",
      "Do not certify a factual claim without an identifiable source."
    ]
  },
  "metadata": {"purpose": "Synthetic documentation example"}
}
```

## Preflight trust boundary

`preflight.command` is a nonempty array of argument strings, not a shell command
string. It is executed as **owner-trusted host code**, outside the model sandbox.
Argument order, repetitions, empty values and whitespace are preserved. The
executable must be nonempty and arguments cannot contain NUL.

Supported substitutions are `{python}`, `{workdir}`, `{todo_file}`,
`{profile_path}` and `{profile_dir}`. `timeout_seconds` defaults to 30 and must be
finite, greater than 0 and at most 3600. Optional `cwd` and an `environment` map
configure the trusted process. Do not embed credentials in a distributable
profile or use untrusted model text to construct executable commands.

A real run executes the applicable preflight; a dry run records that it was
skipped. A startup stop prevents new preflight execution. This is not a promise
of immediate termination of arbitrary already-running preflight code.

## Capability contract

```sh
python3 -B arquilo.py capabilities
```

This returns `arquilo.capabilities.v1` JSON. Integrators should inspect declared
feature versions rather than infer support from filenames, private constants or
an unmerged design. Feature versions describe contracts; they are not the same
as the product version. [Configuration](documents/CONFIGURATION.md)

## Neighboring configuration layers

A JSON runtime profile is not a native Codex profile selected with `--agent`, and
not the TOML catalog selected with `--prompt-config default|de|en|FILE`. Catalogs
provide built-in wording; profile additions/slots and user-authored tasks retain
their own text and are not automatically translated.

See [prompt configuration](docs/prompt-configuration.md),
[Operator Guide profiles](docs/guides/operator-guide.en.md#profiles),
[configuration layers](docs/guides/operator-guide.en.md#configuration), and
[the implementation](runtime_profile.py). The [migration reference](documents/MIGRATION.md)
documents rejected retired fields; no profile can re-enable them.
