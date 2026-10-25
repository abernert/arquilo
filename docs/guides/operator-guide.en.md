# ARQUILO Advanced / Operator Guide

**English · runtime 0.9.1 · integration checkout 2026-10-25**
[Guide index](../README.md) · [User Guide](user-guide.en.md) · [Technical Guide](technical-guide.en.md)

> **Unreleased integration checkout, not the published v0.9.1 ZIP.** The version string remains 0.9.1. This edition combines the consolidated manuals/Git work from PR #37 with the current main runtime, including Claude Code and state-I/O repairs, and separates task acceptance from optional publication. See [source commits and remaining limits](../integration-status.md). An existing release ZIP does not acquire these changes automatically.

Use this handbook to configure, run, diagnose and integrate ARQUILO. Part I follows the operating workflow. Part II is the complete reference for public commands, environment settings, task directives, runtime-profile fields and prompt catalogs in this checkout. Follow the [User Guide](user-guide.en.md) for installation and the first run. Native Codex and Claude provider settings are separate configuration layers, not additional ARQUILO parameters.

## Part I — operating procedures

### Contents

[Operating contract](#operating-contract) · [Configuration layers](#configuration) · [Task design](#tasks) · [Resources](#resources) · [Parallel work and WAIT](#parallel) · [Breakdown](#breakdown) · [Planning pause](#planning) · [Runtime profiles](#profiles) · [Prompt catalogs](#prompts) · [Budgets and stops](#budgets) · [State and diagnosis](#state) · [Git](#git) · [Integration](#integration) · [Limitations](#limitations) · [Operating checklist](#checklist)

<a id="operating-contract"></a>
## 1. Establish the operating contract

Before a run, identify its approved inputs, allowed external effects, provider, model availability, resource ceiling, acceptance criteria and stopping conditions. Use a bounded synthetic example to validate the environment. A successful doctor check is not a substitute for a producer/reviewer run; neither proves complete sandbox enforcement.

Keep the installation, writable workspace and private controller-state root distinct. Update the controller and Python workers together. Record the ARQUILO revision, selected backend, native CLI version and model/provider configuration without copying credentials into logs or reports.

Use strict plan handling unless the job explicitly involves generating a plan for later human approval. Use automatic Git only within the documented snapshot/host trust boundaries; do not treat it as isolation from arbitrary hostile same-user processes. Treat runtime-profile preflight commands and host installations as trusted code. A read-only reviewer filesystem does not make every remote tool read-only.

The canonical interface is `python3 -B arquilo.py tasklist run ...`. On native Windows substitute an installed interpreter such as `py -3.11 -B .\arquilo.py ...`; WSL uses Linux commands and paths. All relative CLI file paths are relative to the invocation directory. Task `workspace=` directives, by contrast, select subdirectories of the main workspace.

<a id="configuration"></a>
## 2. Configuration layers and precedence

| Layer | Purpose | Rule to remember |
| --- | --- | --- |
| Native backend host configuration | Provider, endpoint, authentication, proxy/CA setup | Use the selected runtime's approved settings. Claude does not read Codex configuration or fall back to Codex. |
| Codex profile / `--agent` | Native named model/tool profile and prompt hint | Codex only; task `CFG agent` can override the run default. Claude rejects it. This is not a team definition. |
| Run CLI / environment | Operator choices for this invocation | Rules vary by option; distinguish defaults, ceilings and permissions. |
| Task preamble and directives | Shared project instructions and next-task settings | CFG is local to the following task; one DEFAULTS block supplies supported resource defaults. |
| JSON runtime profile | Domain-specific instruction slots, guards and trusted preflight | CLI `--runtime-profile` wins over `ARQUILO_RUNTIME_PROFILE`. |
| TOML prompt catalog | Built-in ARQUILO instruction wording | Operator selects once per run; no task-controlled catalog selection. |
| Explicit skills | Captured procedure text | Instructions, not permissions or independent agents. |

For models, global `--model` precedes the selected backend's environment variable (`ARQUILO_CODEX_MODEL` or `ARQUILO_CLAUDE_CODE_MODEL`); that effective global choice precedes task `CFG model`. With neither, the selected native runtime chooses its configured default. `--reasoning-effort` similarly precedes `ARQUILO_CODEX_REASONING_EFFORT` or `ARQUILO_CLAUDE_CODE_REASONING_EFFORT`. Codex model/effort variables are not translated into Claude settings. Claude accepts `low`, `medium`, `high`, `xhigh` or `max`; Codex also accepts `none` and `minimal`. Native provider/model support is still required.

A CLI MCP/skill selection is a **default and ceiling**. A descendant may narrow the set, not broaden it. Shell-network access instead requires a runner-level grant; a task can restrict an existing grant but cannot create one. These are different from a plain “last value wins” rule.

With no explicit resource selection, native Codex integrations can remain inherited. Do not interpret an omitted option as `none`. `CODEX_HOME` and the trusted process environment remain part of provider provisioning. ARQUILO does not load a workspace `.env` automatically. The [configuration reference](#cli-reference) is the detailed option map.

<a id="backends"></a>
### Select the execution backend

Use `--backend codex` (default) or `--backend claude-code` after `tasklist run`, `doctor`, or with standalone AutoBuild. The selection covers production, fixes, reviews, parent reviews, Decide and parallel workers. There is no task-level backend switch, mixed-backend review or automatic fallback. A dry run needs neither CLI; actual execution needs the selected CLI and its approved authentication.

| Capability | Codex | Claude Code in this checkout |
| --- | --- | --- |
| Provider/model configuration | Trusted Codex host configuration, optional native profile | Trusted Claude user/provider configuration; no Codex discovery |
| Production/fix tools | Native Codex policy and declared sandbox | Read, Glob, Grep, Edit, Write and sandboxed Bash |
| Review/parent review | Native read-only policy | Read, Glob, Grep; no Bash or writes |
| Decide | Restricted Codex decision path | No task tools; native structured terminal result |
| Named MCP services | Explicit verified selection and ceilings | Unsupported; only none/omission, both with no native MCP inheritance |
| Explicit ARQUILO skills | Frozen SKILL.md text and hashes | Same binding contract; default roots under .agents/skills and .claude/skills, no Codex home lookup |
| Native skills/plugins/subagents | Subject to Codex configuration and the documented selection mode | Disabled by the restricted adapter; explicitly bound text does not enable them |
| Native profiles / `--agent` | Supported | Rejected, including task CFG agent |
| Historical reconnect `resume-review` | Narrow evidence-validated recovery | Unsupported; no session or cross-backend recovery |
| Windows production | Follow the native Codex setup | WSL2/Linux required; read-only native calls are a different capability |

Install the selected CLI and any required Node launcher outside all writable task workspaces, including resolved targets. Linux Claude production requires `bubblewrap`, `socat` and permission to use its native sandbox; no unsandboxed escape is provided. The Claude reviewer cannot independently rerun a shell test, so production/fix must supply the test evidence for inspection. Native file access, mandatory managed integration and provider processing remain host/provider boundaries.

`--skip-backend-preflight` skips only the runner's selected-backend preflight. It does not bypass mandatory review, per-call executable/protocol checks or sandbox requirements. `--skip-codex-preflight` is a Codex-only compatibility selector and is rejected in a Claude run. `--model-provider`, native `--profile`/`--codex-profile`, `--agent` and raw `--extra-arg` overrides are not accepted for Claude. See [Claude qualification](../claude-code-backend.md) for native protocol versions and diagnostics.

<a id="tasks"></a>
## 3. Design tasks as testable contracts

Separate the requested deliverable, required checks, permissible sources and allowed uncertainty. A report may legitimately identify missing information without being blocked, provided the task's acceptance criteria allow that. Conversely, a pleasant summary cannot satisfy a requirement for a working executable or a reconciled numerical result.

Use unique numeric IDs. Children such as `2.1` belong to root `2`; independent root `3` has a separate call budget. Four-space/tab-indented code examples, fenced blocks and HTML comments are not executable tasks. Up to three leading spaces can still be executable, so do not rely on decorative indentation for safety.

`--todo-preamble auto` includes the visible preamble when present; `required` refuses a missing preamble and `off` omits that wrapper. A preamble is shared request context, not an authorization mechanism. Keep machine-readable syntax unlocalized even when task prose is German.

Keep an immutable clean template and a distinct working list. `--todo-template` copies only a missing list, including in dry-run mode; it never resets statuses or copies dependencies. A missing list with existing controller state is recovery, not permission to reinitialize. [Preamble reference](#task-format-reference) · [Directive grammar](#task-directive-reference)

### Workspace policy file

`<workdir>/config/policy.md` is shared instruction text. At real-run setup, an absent workspace policy is initialized from the installation's `config/policy.md` (the supplied default is empty). An existing policy is read, not overwritten. A dry run does not create the default. Missing/unreadable policy data after setup is an error rather than silent absence. The file contributes instructions; it cannot override controller state, mandatory reviews, sandbox rules or resource ceilings. There is no public `--policy-file` flag in this checkout.

<a id="resources"></a>
## 4. MCP, skills and network paths

### Explicit MCP selection

The named-server configuration in this section applies to Codex. Claude rejects every named selection before model work; omission and explicit `none` both enable no native MCPs.

A resource-controlled invocation might select `--mcp issues,docs --review-mcp docs`. The names must already exist and be enabled in trusted native Codex configuration. These are illustrative aliases, not servers installed by ARQUILO. The review set must be a subset of production. Supplying `--mcp` without `--review-mcp` defaults the review selection to none.

The adapter discovers configured direct servers, generates temporary overrides, disables unselected servers and plugin/app integrations, and verifies the effective selection. It refuses missing, disabled, unsupported or policy-denied selections instead of silently enabling or dropping them. Metadata inspection does not initialize STDIO servers, but it may query native authentication metadata.

Production resource settings do not automatically apply to every other phase: preflight does not inherit production MCPs in resource-controlled mode, and Decide is MCP-free when MCP selection is explicit. Remote credentials and tool permissions still determine what a selected server can do. Configure read-only credentials/server capabilities for review; local read-only sandboxing alone is insufficient.

Portable server aliases use letters, digits, underscores and hyphens. The first adapter supports direct STDIO and Streamable HTTP definitions; dotted aliases and plugin-bundled server selection are not supported here. Do not change native configuration concurrently with the run.

### Skills

The native-discovery behavior differs by backend; explicitly bound ARQUILO text follows the same shared resource contract.

Use `--skills procedure-name` and repeatable `--skill-dir /approved/root` to choose procedures from known roots. Each root contains skill directories with a `SKILL.md`, YAML frontmatter and a simple name. Duplicate names require disambiguation. The no-extra-dependency loader is not a general YAML configuration engine.

For Codex, default lookup includes the workspace `.agents/skills`, the user's `.agents/skills` and the Codex home skills directory. Claude uses workspace/user `.agents/skills` and `.claude/skills`, without accessing Codex home. Explicit roots replace that lookup set. Selected instruction text and its hashes are captured for production, review and corrections. Referenced scripts/assets are **not** snapshotted or automatically run at binding time. Keep them stable and trusted. `--skills none` adds no explicit bindings, but does not disable native implicit discovery or normal file access.

A list can narrow operator-approved resources:

```md
***DEFAULTS mcp=issues,docs skills=ticket-draft***

***CFG mcp=issues***
1. ***Task***: Prepare a local issue proposal from input.json; do not submit it.
    Acceptance: proposal.md identifies evidence and unresolved questions.

***CFG mcp=none skills=none***
2. ***Task***: Review proposal.md for internal consistency and write consistency.md.
    Acceptance: Report contradictions without inventing missing source facts.
```

This named-server example is Codex-only. Run it only with matching approved servers, skills and inputs. A dry run can validate syntax and bound skill text; it cannot establish remote permissions or authenticate MCP servers.

### Four separate network paths

Shell-network access (`--network-access` and task restriction), integrated web search (`web_search=`), MCP/app tools and provider communication are distinct. Turning off one does not turn off all four. `network_access=false` is not an offline or data-residency guarantee. A prompt saying “do not send data” is not a substitute for technical authorization and approved provider configuration.

<a id="parallel"></a>
## 5. Parallel workspaces and WAIT

Adjacent compatible tasks sharing a `parallel=` group can run as separate Python workers. Each must have a distinct, non-overlapping subworkspace; root-equal, equal and nested parallel paths are refused. Separate directories prevent the known path-overlap case but are not hostile-agent OS isolation.

```md
***CFG parallel=analysis workspace=parts/one network_access=false web_search=disabled***
1. ***Task***: Analyze the supplied local input.md and write findings.md plus todo_result_1.md.
    Acceptance: Each finding identifies a source passage or is labeled uncertain.

***CFG parallel=analysis workspace=parts/two network_access=false web_search=disabled***
2. ***Task***: Analyze the supplied local input.md and write findings.md plus todo_result_2.md.
    Acceptance: Each finding identifies a source passage or is labeled uncertain.

***WAIT on=todo:1,todo:2 mode=all timeout=0s on_timeout=stop***
3. ***Task***: Compare parts/one/findings.md and parts/two/findings.md in comparison.md.
    Acceptance: Preserve disagreements and cite each originating finding.
```

Prepare both subdirectories and their inputs before the run. ARQUILO does not automatically clone every project input into them. Work products remain where tasks write them; report/question synchronization is not a general artifact merger. The example deliberately names both subworkspace artifacts in the integration task.

WAIT supports `todo:ID`, `group:NAME` and `agent:NAME`, with `all`/`any` for comma-separated conditions. Stored DONE satisfies task dependencies after restart; OBSOLETE does not. Group/agent conditions depend on runtime state, so explicit task IDs are clearer for durable continuation.

Omitted timeout and `timeout=0s` inspect current state immediately; they do not mean wait forever. `on_timeout=continue` deliberately permits work despite an unmet dependency, but cannot override an observed process stop. WAIT cannot launch work that has never been scheduled; do not place a dependency before its producer and expect a separate global DAG scheduler.

<a id="breakdown"></a>
## 6. Correction, decomposition and parent acceptance

A valid domain FAIL differs from a technical failure. Local fixable issues can produce a targeted correction followed by another mandatory review. Missing inputs, scope conflicts and external blockers need explicit handling; technical errors do not authorize replaying a whole task indefinitely.

The default breakdown policy is `minimal`: create the smallest necessary remaining work rather than a new unrestricted project. `legacy` retains older freer decomposition; `off` disables automatic decomposition. Defaults are maximum depth 3, maximum 4 direct children and 2 focused breakdown rounds. Supported child/round ranges are documented by CLI help and the directive reference.

In the task runner, `max_steps × max_retries` bounds production/correction steps (defaults 3 × 2). Reviews and other calls consume budget too; the product is not the total count of billed model requests. Completing children does not certify the original parent request: a separate parent review must succeed. A review can be technically valid while failing its subject.

Use explicit acceptance criteria and root-level budgets rather than relying on depth alone to bound work. A shallow tree can still have many children and repeated calls. [Review reference](../../documents/REVIEW_CORE.md)

<a id="planning"></a>
## 7. Generate a plan, then pause for human approval

The shipped `examples/planning_todo.md` creates a brief in task 1 and appends future open tasks in task 2. Copy it to `tasks.md` in a fresh disposable workspace. A POSIX example, from the installation root:

```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/planning'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/planning_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/planning --todo-file .local-work/planning/tasks.md --allow-todo-modifications --stop 2 --max-calls 12 --mcp none --skills none --process-stop-policy controller-only
```

This is a live model invocation, not a dry run. Task 2 must pass its own review, and the runner stops before executing the newly generated work. Inspect the full resulting plan: IDs, requirements, permissions, source assumptions and effects. A plan-generation review is not human approval of each generated task.

For continuation omit `--allow-todo-modifications` and `--stop 2` to restore strict mode, and preserve your finite limit. `--start 3` is optional when deliberately selecting that range. When you have manually changed the generated plan, use `--accept-plan-changes` once after inspection; otherwise omit it. Keep all project/state paths. An existing process-stop file is a separate instruction and is not removed by these options.

Mutable-plan mode is intentionally weaker: model-written DONE statuses, removed tasks or lowered future requirements can alter scheduling. The run metadata distinguishes original assignments reviewed in this run from observed, non-independently-verified mutations. Do not report every DONE in a mutable plan as verified work. [Detailed planning and metadata semantics](#operator-controls-reference)

<a id="profiles"></a>
## 8. Configure a JSON runtime profile

Use this profile schema with the documented runtime. A runtime profile contributes
operator-trusted domain instructions and preflight behavior. It cannot directly
set controller run state, approve a review or authorize task completion. JSON
runtime profiles are part of the core; no additional Python package is needed.

### Activation

```sh
python3 -B arquilo.py tasklist run --todo-file /project/tasks.md --workdir /project --runtime-profile /approved/profile.json
```

On native Windows substitute an installed Python interpreter and native paths.
The public CLI option precedes `ARQUILO_RUNTIME_PROFILE`. Relative file paths are
relative to the invocation directory. Inspect a profile and any executable
preflight before using it; task instructions are not authority to select trusted
host code.

### Profile fields

The JSON object requires `schema_version: "arquilo.runtime_profile.v1"` and a
nonempty `profile_id`. `profile_version` defaults to `"1"` and is a string.

| Field | Meaning |
| --- | --- |
| `schema_version` | Required string: `arquilo.runtime_profile.v1`. |
| `profile_id` | Required nonempty string identifying the profile. |
| `profile_version` | String; default `"1"`. |
| `activation_markers` | List of strings; all must occur for text-dependent profile activation. An empty list is active by default. |
| `scope_activation_markers` | Separate all-markers condition for relevant scope/protected-block checks. |
| `protected_markers` | Names of marked blocks that applicable guards expect to preserve byte-exactly. |
| `prompt_policy` | Supported instruction slots described below. |
| `preflight` | Optional ordered host command, timeout, working directory and environment overlay. |
| `metadata` | Operator metadata object, not interpreted as runtime authority. |

The implementation checks selected policy/removed fields and supported values;
it is not a universal strict rejection of every unknown JSON key. Use the known
fields and verify behavior rather than relying on ignored misspellings.

### Prompt policy

Every supported `prompt_policy` field is listed here:

| Field | Type / purpose |
| --- | --- |
| `controller_only_instruction` | String; replacement instruction slot when controller-only stop handling is selected. |
| `task_contract_instruction` | String; original-assignment instruction slot. |
| `breakdown_scope_guard` | String; scope guidance during decomposition. |
| `legacy_review_boundary` | String; boundary guidance for legacy review interpretation. |
| `parent_review_scope_guard` | String; scope guidance for the parent review. |
| `parent_review_terminal_rule` | String; terminal rule in the parent-review instructions. |
| `autobuild_review_rules` | Array of strings appended to the normal AutoBuild review requirements. |

Optional unset/empty instruction slots use their normal implementation fallback. Activation lists are arrays of nonempty strings; all listed markers must match. Metadata does not grant controller authority.

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

### Preflight trust boundary

`preflight.command` is a nonempty array of argument strings, not a shell command
string. It is executed as **owner-trusted host code**, outside the model sandbox.
Argument order, repetitions, empty values and whitespace are preserved. The
executable must be nonempty and arguments cannot contain NUL.

All supported `preflight` keys are `command` (ordered argument array, required within a preflight), `timeout_seconds` (default 30), `cwd` (optional working directory) and `environment` (string-to-string environment overlay; default empty). `preflight` itself may be omitted or null.

Supported substitutions are `{python}`, `{workdir}`, `{todo_file}`,
`{profile_path}` and `{profile_dir}`. `timeout_seconds` defaults to 30 and must be
finite, greater than 0 and at most 3600. Optional `cwd` and an `environment` map
configure the trusted process. Do not embed credentials in a distributable
profile or use untrusted model text to construct executable commands.

A real run executes the applicable preflight; a dry run records that it was
skipped. A startup stop prevents new preflight execution. This is not a promise
of immediate termination of arbitrary already-running preflight code.

### Capability contract

```sh
python3 -B arquilo.py capabilities
```

This returns `arquilo.capabilities.v1` JSON. Integrators should inspect declared
feature versions rather than infer support from filenames, private constants or
an unmerged design. Feature versions describe contracts; they are not the same
as the product version. [Configuration](#cli-reference)

### Neighboring configuration layers

A JSON runtime profile is not a native Codex profile selected with `--agent`, and
not the TOML catalog selected with `--prompt-config default|de|en|FILE`. Catalogs
provide built-in wording; profile additions/slots and user-authored tasks retain
their own text and are not automatically translated.

See [prompt configuration](#prompts),
[Operator Guide profiles](#profiles),
[configuration layers](#configuration), and
[the implementation](../../runtime_profile.py). The [migration reference](#migration-reference)
documents rejected retired fields; no profile can re-enable them.

<a id="prompts"></a>
## 9. Configure built-in prompt wording

Introduced in 0.9.0; applicable to the documented 0.9.1 runtime.

**Public preview.** This feature moves ARQUILO's
built-in model-facing instruction texts into complete, editable TOML catalogs.
The Python core, parser contracts and authorization checks remain separate.
Python 3.11's standard `tomllib` is sufficient; no new package is required.

### Three supplied files

| Selection | File | Texts |
| --- | --- | --- |
| `default` (also the omitted option) | [default.toml](../../prompts/default.toml) | The original 0.8.0 wording, including its German/English mixture. |
| `de` | [de.toml](../../prompts/de.toml) | German built-in instructions. |
| `en` | [en.toml](../../prompts/en.toml) | English built-in instructions. |

Each file contains all 53 elements. The files have the same keys and placeholder
contracts, so an editor or translation program can work element by element.
There is no silent fallback from a missing German element to an English default.

### Select a catalog

Select once for the invocation. The same catalog serves all tasks, parallel
workers and their review/correction calls during that run.

```bash
python3 -B /path/to/arquilo/arquilo.py tasklist run \
  --workdir /path/to/project \
  --todo-file /path/to/project/tasks.md \
  --prompt-config de
```

Use `--prompt-config en` for English, `--prompt-config default` for the original
wording, or a file path for a complete custom catalog. Relative file paths refer
to the invocation directory, not the work directory. On Windows, use your
Python 3.11+ command (for example `py -3.11`), native paths and your shell's
line-continuation convention. In WSL, the example above uses Linux paths.

The direct AutoBuild entrypoint supports the same option:

```bash
python3 -B autobuild.py \
  --workdir /path/to/project \
  --task "Analyze input.md and write an evidence-based summary to analysis.md." \
  --prompt-config en
```

A task-list `--dry-run --dry-run-file /path/to/new-preview.md` shows the actual
expanded assignment without executing the task. It does not validate model
behavior or authorize external effects. `arquilo.py doctor --prompt-config de`
validates the catalog selection as part of diagnostics; an actual diagnostic
model call still requires the existing explicit `--check-decide` option.

Prompt selection is an operator-level option, not a `CFG` or `DEFAULTS` field
that a task or an agent-generated child can change. There is no implicit
workspace file search or automatic environment-variable selection.

### Edit a complete copy

Copy one supplied file outside the application checkout, for example:

```bash
cp prompts/de.toml /path/to/my-prompts.toml
```

Then edit the copy and select `--prompt-config /path/to/my-prompts.toml`.
A typical element looks like this (the actual file contains the full catalog):

```toml
schema_version = "arquilo.prompts.v1"
id = "my-team-de"
version = "1"
language = "de"

[prompts.task_assignment]
# Keep these placeholder names unchanged.
text = """
Bearbeite die Aufgabe {{task_id}} aus `{{todo_path}}`.
Dokumentiere das Ergebnis in `{{result_path}}`.
"""
```

The example is a fragment for explanation, not a runnable partial configuration.
Use a complete file. Change `id` and increase `version` when maintaining your
own variants. `language` is descriptive metadata (`mixed`, `de` or `en`); it does
not translate text at runtime and is not an automatic language detector.

The supplied files use TOML multiline strings. A backslash at the end of a
source line joins the next line without adding whitespace; this lets the
default preserve the old rendered bytes while remaining readable. Ordinary
newlines can be used when intentionally changing a prompt. Escape literal
backslashes and double quotes according to TOML basic-string syntax.

Only `{{name}}` tokens listed in each element's comment are substitutions.
Retain their names, but move them as grammar requires. Every required token must
remain present and no new token may be introduced. There are no expressions,
attribute access, shell expansion, template includes or executable code. Values
are inserted once: braces inside a task, source text or model answer are not
interpreted again as template syntax.

Validation rejects unknown/missing elements, malformed TOML, unsupported schema,
invalid placeholder sets, empty texts, NUL bytes and oversized catalogs. Limits
are 512 KiB per file/combined text and 128 KiB per element. Nothing is silently
truncated. UTF-8 with an optional leading BOM and LF/CRLF is accepted.

### Coverage and language boundaries

The catalogs cover task assignment, subworkspace/agent hints, status/stop rules,
policy wrappers, the preamble wrapper and work-plan semantics, reviewer role and
response instructions, confidence guidance, correction requests, minimal and
legacy decomposition, parent review, decision questions/instructions and system
text, skill-binding wrappers, question-file headings and the diagnostic probe.

A language choice changes **ARQUILO-authored instructions**, not all bytes in a
model conversation. The following deliberately retain their original form:

- User tasks and task-list preambles, `AGENTS.md`, selected skills, runtime-profile
  additions, source documents, prior model answers, filenames and tool output.
- Machine-readable JSON keys, enum values and sentinel markers such as `verdict`,
  `PASS`, `FAIL`, `COMPLETE` and the review-contract delimiters. These are protocol,
  not translatable prose. Likewise, executable task syntax remains unchanged.
- CLI help, console messages, technical exception/validation diagnostics and
  existing log field names. This change is not a full user-interface localization.

The `ARQUILO_DECISION_SYSTEM_PROMPT` override and an explicitly supplied Python
`system_prompt` retain their existing precedence; they are owner-authored text,
not automatically translated. To use only the supplied built-in system wording,
do not set that override. A model's output language is not guaranteed merely by
translating its instructions; put any required output language into the task or
preamble and verify it at review.

### Configuration layers

| Layer | Responsibility |
| --- | --- |
| Prompt catalog (`--prompt-config`) | Built-in wording, reusable elements and language. |
| Runtime profile (`--runtime-profile`, JSON) | Existing domain-specific additions and supported single-slot overrides. Those contributions remain unchanged and can be in another language. |
| Codex profile (`--agent`) | Native model/provider/tool configuration. It is not a prompt-catalog selector. |
| Task-list preamble and tasks | Concrete project goal, inputs, work and acceptance criteria. |
| Skills | Explicitly selected procedure text; its user-authored content is not translated. |
| MCP selection | Available configured tools, independent of prompt wording. |

The feature does not weaken sandbox selection, tool permissions, review-required
rules, parser validation, call budgets, stop handling or controller ownership of
`DONE`. A template cannot change those executable checks. However, changing the
substantive reviewer wording can change review quality. Inspect custom prompts
as trusted operator configuration, test them, and do not treat successful TOML
validation as proof of a good or safe review policy.

### Snapshots and reproducibility

A catalog is loaded and validated once by the run owner. Its immutable text
snapshot is passed through Python and serialized into each worker request.
Workers validate the snapshot instead of reopening the source file. Editing or
deleting the source file after the run starts does not alter that run's catalog;
a later invocation loads the new file. Two concurrent runs can use different
catalogs without process-global language switches.

Task-list run archives contain catalog metadata in `run_config.json` and the
complete `prompt_config_snapshot.json`. Direct AutoBuild archives use a unique
`prompt_config_<id>.json`; standalone decision archives also retain a snapshot.
Source-byte and canonical-content SHA-256 digests distinguish the loaded file
from its effective text contents. These are reproducibility records, not signed
or tamper-proof evidence. Prompt files and archives must not contain secrets.

Task/prelude capture and exact-original-request recovery checks continue to
apply. Selecting a different catalog in a later recovery invocation does not
retroactively translate an archived assignment or bypass a mismatch. This
feature does not freeze all workspace, reference, skill-script or Codex files.

### Python use

```python
from pathlib import Path
from prompt_config import load_prompt_config
from autobuild_contract import AutoBuildOptions

catalog = load_prompt_config(Path("/path/to/my-prompts.toml"))
options = AutoBuildOptions(prompt_config=catalog)
```

`TodoRunner(prompt_config=...)`, `AutoBuildOptions(prompt_config=...)`,
`DecisionRequest(prompt_config=...)` and the public `decide`/`evaluate` helpers
accept the selector or loaded catalog. Existing calls that omit it use `default`.
A snapshot includes its original source metadata but is validated without
requiring that source path to exist on a worker.

### Validation

Offline tests cover exact default text, all catalog keys, translation selection,
custom edits, placeholder failures, literal user inputs, parallel language
isolation, worker serialization, archived snapshots, and real production/review/
correction controller flows with a fake model transport. Native response parsers
are unchanged. No live model API or customer service is used by these tests.

See [task directives](#task-directive-reference),
[task preambles](#task-format-reference) and the
[Runtime Profile API](#profiles) for the neighboring interfaces.

### Complete prompt-catalog field reference

The TOML top level contains exactly `schema_version`, `id`, `version`, `language` and `prompts`. `schema_version` is `arquilo.prompts.v1`; `id` is a portable identifier of 1–128 characters; `version` is a nonempty string of at most 64 characters; `language` is `mixed`, `de` or `en`. Each `prompts.NAME` table has exactly a `text` string. All 53 named elements below are required; unknown/missing elements and invalid placeholder sets are errors. Their actual wording belongs in the selected TOML file, not in a second copy of the manual.

| Element (`prompts.NAME.text`) | Required placeholders |
| --- | --- |
| `review_policy_rules` | None |
| `reviewer_role` | `{{latest_answer}}`, `{{original_task}}` |
| `review_instructions` | `{{confidence_fields}}`, `{{confidence_rules}}`, `{{policy_rules}}` |
| `fix_no_blockers` | None |
| `fix_assignment` | `{{blocking_issues}}`, `{{decision_text}}`, `{{original_task}}` |
| `review_contract_inline` | `{{contract}}` |
| `review_contract_file` | `{{path}}` |
| `confidence_fields` | None |
| `confidence_rules` | `{{max_items}}`, `{{max_text}}` |
| `task_controller_only` | `{{process_stop_path}}`, `{{question_path}}` |
| `task_contract` | None |
| `parent_terminal` | None |
| `preflight` | None |
| `task_agent_stop` | `{{process_stop_path}}`, `{{question_path}}` |
| `task_policy_intro` | `{{policy_path}}`, `{{policy_text}}` |
| `task_mutable_plan` | None |
| `task_guarded_plan` | None |
| `task_stop_boundary` | `{{stop_id}}` |
| `task_marked_syntax` | None |
| `task_agent_hint` | `{{agent}}` |
| `task_policy_controller` | None |
| `task_policy_agent` | `{{process_stop_path}}` |
| `task_assignment` | `{{result_path}}`, `{{task_id}}`, `{{todo_path}}` |
| `task_subworkspace` | `{{workspace}}` |
| `breakdown_legacy_boundary` | None |
| `breakdown_legacy` | `{{result_path}}`, `{{review_boundary}}`, `{{scope_guard}}`, `{{task_command}}`, `{{task_id}}`, `{{todo_path}}` |
| `breakdown_single` | None |
| `breakdown_multiple` | `{{max_children}}` |
| `breakdown_minimal` | `{{issues}}`, `{{mode_instruction}}`, `{{result_path}}`, `{{round_number}}`, `{{scope_guard}}`, `{{task_command}}`, `{{task_id}}`, `{{todo_path}}` |
| `parent_assignment` | `{{parent_id}}`, `{{result_path}}`, `{{scope_guard}}`, `{{todo_path}}` |
| `preamble_semantics` | None |
| `preamble_envelope` | `{{byte_count}}`, `{{preamble}}`, `{{semantics}}`, `{{separator}}`, `{{task}}`, `{{todo_filename}}` |
| `decision_instructions` | None |
| `decision_completion` | None |
| `decision_plan_step` | None |
| `decision_plan_final` | None |
| `decision_system` | None |
| `resource_header` | None |
| `resource_instructions` | None |
| `questions_document` | None |
| `issue_missing_summary` | None |
| `fix_issue_requirement` | `{{value}}` |
| `breakdown_issue_requirement` | `{{value}}` |
| `fix_issue_criterion` | `{{value}}` |
| `breakdown_issue_criterion` | `{{value}}` |
| `fix_issue_references` | `{{value}}` |
| `breakdown_issue_references` | `{{value}}` |
| `fix_issue_suggestion` | `{{value}}` |
| `breakdown_issue_suggestion` | `{{value}}` |
| `breakdown_no_issues` | None |
| `decision_result_complete` | None |
| `decision_result_incomplete` | `{{count}}` |
| `doctor_question` | None |

<a id="budgets"></a>
## 10. Budgets, deadlines and stops are different controls

`--max-calls N` reserves execution attempts per numeric root tree. Production, fixes, reviews, breakdown and Decide share that root's persistent counter; an independent root has its own. Reservations survive failed starts and missing diagnostic claims. CLI metadata queries and the separate sandbox preflight are outside the counter.

Default `0` is unlimited. On continuation, the runner applies the chosen limit to existing budgets, preserving consumption; omitting the option can therefore remove an earlier finite ceiling. Positive limits cannot be lower than already consumed usage. A new timestamp or readable project ID is not a fresh budget. Changing the state root to avoid exhaustion destroys the intended continuity.

Per-call stall/cleanup timeouts are not a global deadline. Existing AutoBuild environment controls include `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS`, `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` and `ARQUILO_CODEX_KILL_GRACE_SECONDS`. They have different purposes and do not promise that an actively emitting process finishes in bounded total time. Do not set arbitrary very short values merely to make a test pass. The comprehensive supervisor/output-quota work remains open.

Use `--stop ID` for a planned selected boundary, a prearranged `***STOP***` immediately before a task for a list barrier, and `process_stop` for a cooperative run stop. An observed sentinel is latched for the current run even if removed later. Empty, unsafe or unreadable sentinel contents do not cancel the stop signal. `controller-only` is an instruction/control convention about who requests stop; it does not make the model physically incapable of writing a file.

A genuine error plus a stop remains an error with stop metadata, not a clean cancellation. Existing partial artifacts are retained for inspection. Read [workflow limits](#limits-reference) before integrating exit codes into automation.

<a id="state"></a>
## 11. State, log layout and diagnosis

Keep the authoritative state outside and separate from the workspace. Preserve paths, ownership and private permissions. `--state-dir` selects a trusted local root; it is not a cache you may delete after each run. The 0.9.1 identity checks reject alternate spellings that would split state/budgets and physical overlap through aliases.

A named project groups logs, while plan-specific directories retain authority. `run.json`, `run_log.json`, `overview.log`, task logs and numbered phase captures help locate a failure. Prefer the recorded error/capture path to a guessed directory suffix. `terminal_attempt` identifies the actual terminal call; the historical `execution_attempts` array is grouped by call type, not a chronological event list.

`--logs-in-workdir` moves diagnostic logs into the workspace but not plan journals, budgets, breakdown state or private worker request/results. Public summaries are not control input. A hard kill can leave nonterminal logs; absence of a failure message is not proof of successful completion. Use run identity, exit status, review validity and actual artifacts together.

For diagnosis, preserve the original error, exact versions and invocation without secrets. Distinguish technical failure, invalid review, domain FAIL, deliberate stop, unmet WAIT and integrity refusal. Inspect side effects before replay. Ordinary restart may reexecute an open task; the narrow [review-only recovery](#recovery-reference) path has stronger, specific prerequisites.

Raw archives are not encrypted, append-only evidence stores or sanitized support bundles. Share a reviewed minimal diagnostic extract, not the whole state root. [Project logs](#logs-reference) · [Controller safety](technical-guide.en.md#controller-reference)

`run.json` reports `publication_required`, `publication_status` and `publication_records` separately from task completion. The aggregate publication status is `not_requested`, `complete` or `pending`; a verified no-change publication is successful. A pending/blocked delivery can coexist with DONE tasks. Private pending receipts and blocked obligations remain visible when a later run has no unfinished tasks; merely restarting does not mark them delivered. An obligation records an unmet delivery request without authorizing publication. Only an accepted private receipt authorizes model-free retry; mutable run summaries do not.

<a id="git"></a>
## 12. Automatic Git: acceptance and publication are separate

`--git` opts into a local commit of explicitly selected `--git-path` output files. `--git-push` additionally requests delivery to the approved upstream. Both are off by default. The reviewed task and its delivery have separate outcomes: optional Git failure cannot turn a valid review into a model failure or force production to run again.

Before review, the controller freezes **selected outputs only** and binds their identity and bytes to that review. The reviewer remains in the normal workspace and receives explicit instructions to judge the frozen output references; other context remains accessible under the normal review policy. There is no full-workspace copy. An unrelated linked `.venv` or large unselected context file does not make publication capture fail merely by existing.

The `--git-path` selections form a run-wide publication allowlist; they do not add deliverables to each task. If task 1 creates `result.txt` and task 2 will create `second.txt`, selecting both files is valid while `second.txt` is still absent during task 1. A `null` snapshot selection records absence, not automatically a deletion. The review contract distinguishes an absent path that was already absent in the bound Git baseline (`absent_unchanged`) from removal of a tracked baseline file (`deleted`). An unchanged absent path alone is no reason to reject the task or alter private controller state. A file actually required by the current task must still exist and satisfy that task's acceptance criteria; real selected changes still require review.

If publication setup, selected-output capture before review or accepted-receipt persistence is unavailable, ordinary review may still accept the work. Before DONE, the controller must durably record the blocked obligation in private state. It remains visible across restarts without supplying publication authority. If neither an accepted receipt nor the blocked obligation can be persisted, controller persistence failure prevents DONE. A snapshot, token or selected-live-output mismatch still vetoes acceptance when discovered after review. Optional publication never authorizes substituting unreviewed live bytes.

| Result | Default `--git` | With `--git-required` |
| --- | --- | --- |
| Review rejects or its binding is invalid | Task remains incomplete; no publication | Same |
| Task accepted and requested delivery succeeds | DONE; continue | DONE; continue |
| Task accepted but capture/commit/push cannot complete | DONE; record delivery separately and continue within normal run controls | DONE; stop the run with incomplete delivery (exit 9) |
| Push outcome is uncertain | Preserve the reviewed commit and recovery evidence; inspect/reconcile | Same evidence retained; required delivery remains incomplete |
| Neither receipt nor blocked obligation can be durably recorded | Controller persistence failure; no DONE | Same |

`--git-required` requires `--git`. A successful local commit satisfies a commit-only request; a request containing `--git-push` also requires the requested remote delivery. Automatic Git is **serial only**: `CFG parallel` with Git remains an unsupported configuration, not a reason to weaken workspace ownership. Task plans and rewritten result reports are not selectable publication outputs. Existing selected files must meet the documented starting conditions; unrelated staging is preserved.

### Read the delivery state

A receipt with `published` has satisfied the requested delivery: a local commit
when no push was requested, or the required remote update when `--git-push` was
selected. It is not an unconditional claim of remote publication. `noop` is a
successful verified no-change outcome. `accepted`, `preparing`, `prepared` and
`push_pending` are unfinished delivery states, even when the task is already
DONE. The run-level aggregate remains `pending` while required recorded work is
unfinished; restarting a DONE-only plan does not erase old pending receipts.
An `obligation-<32hex>` record with status `blocked` represents delivery without
an authorizing candidate and also keeps the selected scope pending. A
`superseded` obligation retains its history and identifies its successful
replacement through `resolved_by`; it no longer blocks delivery.

### Inspect and retry publication without model work

Use the same workspace, task-list path and state root as the original run:

```sh
python3 -B arquilo.py git status --workdir /path/to/project --todo-file /path/to/project/tasks.md
python3 -B arquilo.py git retry --workdir /path/to/project --todo-file /path/to/project/tasks.md --publication PUBLICATION_ID
```

Replace `PUBLICATION_ID` with an accepted `publication-<32hex>` identifier shown by status. Add the original `--state-dir` when a custom state root was used. These commands do not call a model, rerun production or perform another review. Retry uses private retained evidence and the exact reviewed commit. It reconciles current HEAD/index and the actual remote before proceeding; it does not blindly create another commit or push a changed branch. An already delivered request must not be duplicated. Retry refuses `obligation-<32hex>` identifiers because those records contain no accepted candidate.

A missing or invalid accepted candidate cannot be repaired by snapshotting current live files after the review. To resolve an unbound block, fix its recorded cause, inspect and preserve the existing outputs, and prepare a valid clean Git baseline for the selected files. The normal clean-selection starting condition still applies. Then deliberately change the affected task from DONE to its open Task/Auftrag status, inspect the plan and adopt that change with `--accept-plan-changes`. Run that task with ordinary optional `--git` and the intended output selection, keeping the original workspace, task-list path and state root. This is an explicitly requested new production/review attempt. Do not add `--git-required` to that recovery attempt: the existing required-delivery barrier otherwise stops it before fresh model work. A matching new receipt supersedes the recorded block only after successful `published` or `noop` delivery; the old record remains in history. New unrelated publications cannot clear it.

Do not clear controller state, overwrite the receipt, switch branches or reset an index just to make retry proceed. A failed/uncertain push may already have created a valid local commit or reached the remote; an existing accepted receipt still uses the model-free retry procedure above.

The selected-file allowlist is not a secret scanner. Native Git/authentication and remote behavior remain trusted boundaries; local state, index, branch and remote are not one distributed transaction. See [implementation and recovery](technical-guide.en.md#git-reference).

<a id="integration"></a>
## 13. Calling ARQUILO from another process

Prefer the public CLI and `capabilities` output for an external launcher. Use explicit working directories, argument arrays rather than interpolated shell strings, finite limits and captured exit status. Keep stdout and stderr separate because compatibility notices can appear on stderr. The old `run` command is an alias; new integrations should use `tasklist run`.

Check declared feature contract versions rather than searching source filenames for guessed capabilities. The presence of a design document does not create a command. Private worker payloads and `TodoRunner` internals are not a promised stable remote-service API. An external scheduler should record the command, run identity and outcome and avoid blind whole-task retries after possible side effects.

Running ARQUILO as a daemon, serving it over MCP, recursive suborders and team configuration require separate implemented contracts. Backend selection is already implemented as described [above](#backends); it is not a team or service interface. For internal extension boundaries read the [Technical Guide](technical-guide.en.md).

<a id="limitations"></a>
## 14. Known limitations of the documented baseline

| Area | Operator implication |
| --- | --- |
| State-I/O repairs #32/#34 | Included in this integration through PR #35, not in the existing v0.9.1 release asset. State keys, journals and spent budgets are preserved; unsupported atomic Windows filesystem operations fail closed. |
| Git scope and delivery | Selected outputs are bound to review; the reviewer retains ordinary context access. Publication is separate, optional by default and serial only; --git-required makes incomplete delivery stop the run. |
| Process supervision | Detached descendants, full-run deadlines, output quotas and active preflight cancellation are not comprehensively solved. |
| Legacy state | Old budget-only stores without recoverable identity still need original paths and manual inspection. Historical invalid DONE values are not automatically repaired. |
| Configuration and resources | Trusted native configuration, profile definitions and skill helper files are not a fully immutable capability snapshot. Profile names are not themselves a permissions ceiling. |
| Evidence and quality | Archives are not tamper-proof or automatically redacted. A formal model PASS is not an independent truth oracle. |
| Release process | The baseline regular tag workflow has a single-platform release job; the one-time 0.9.1 publisher's full gate is not a permanent general release mechanism. |

These limitations are separate from the foundational control fixes already implemented. See [Security](../../SECURITY.md), [controller safety](technical-guide.en.md#controller-reference) and the source-linked boundaries in the Technical Guide. This integration does not repair the remaining process, resource, legacy-recovery or release-gate issues.

<a id="checklist"></a>
## 15. A repeatable operating checklist

Before starting, verify paths, host tooling, provider approval, input classification, explicit resource ceilings, finite limits, stable configuration and observable acceptance criteria. Preview the actual plan, not just a template. Record which side effects require human approval outside ARQUILO.

During execution, follow the printed run path and actual terminal attempt. Use a cooperative stop rather than live plan surgery. Do not edit the index, remote configuration, prompt sources or skill helper assets concurrently.

Before continuing or publishing, inspect partial files and external effects, explain the previous failure, preserve authority/budgets, rerun the appropriate acceptance checks and review the resulting diff. Separate “controller accepted the result” from “the organization authorizes its use.”

## Part II — command and configuration reference

This is the authoritative operator reference in this edition. Defaults in the CLI inventory are captured from the actual parsers in a clean environment, then checked against the code by tests. Per-option descriptions explain effective fallback and precedence. The machine-readable companion is [cli-reference.json](cli-reference.json); normal users do not need to edit it.

[All CLI parameters](#cli-reference) · [Environment](#environment-reference) · [Task syntax](#task-format-reference) · [CFG/WAIT/DEFAULTS](#task-directive-reference) · [Budget/stop semantics](#limits-reference) · [Editable plans and log placement](#operator-controls-reference) · [Log paths](#logs-reference) · [Decide configuration](#decide-reference) · [Review-only recovery](#recovery-reference) · [Troubleshooting](#troubleshooting-reference) · [Migration](#migration-reference)

<a id="cli-reference"></a>
## 16. Complete command-line reference

<!-- BEGIN GENERATED CLI REFERENCE -->
<a id="cli-entry"></a>
### `arquilo`

Use `python3 -B arquilo.py COMMAND`. `--version` is a top-level option. Place --backend after tasklist run or doctor; it is not a top-level option. The git group performs model-free publication operations.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--version` | Action | Print the runtime version and exit. For development checkouts also record the commit. |
| `command` | Not set; one of `tasklist`, `run`, `resume-review`, `doctor`, `git`, `capabilities`, `package` | Select a subcommand. Options belong after their owning subcommand. |

<a id="cli-tasklist"></a>
### `tasklist`

The tasklist group selects `run` or `resume-review`; options belong to the selected subcommand.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `command` | Not set; one of `run`, `resume-review` | Select a subcommand. Options belong after their owning subcommand. |

<a id="cli-run"></a>
### `tasklist run`

Use `python3 -B arquilo.py tasklist run OPTIONS`. The table lists every public runner option. Defaults below are parser defaults in a clean environment; environment/native fallbacks are explained in each description and the configuration chapter.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--todo-syntax` | `auto`; one of `auto`, `legacy`, `marked-en` | Choose the spelling used when writing new task headers; existing supported spellings remain readable. CLI overrides ARQUILO_TODO_SYNTAX. |
| `--todo-preamble` | `auto`; one of `auto`, `off`, `required` | Include the visible project preamble when present (auto), omit it (off), or require it (required). CLI overrides ARQUILO_TODO_PREAMBLE. |
| `--todo-file` | Not set | Working UTF-8 Markdown task list. Required for execution; not needed for help/capabilities. An existing list is resumed, not replaced. |
| `--todo-template` | Not set | Initialize a missing task list from this local template. Never overwrite an existing list. The destination must be inside the workspace. Explicit initialization also writes in dry-run mode. |
| `--workdir` | Not set | Workspace. In the task runner, defaults to the task-list directory; Doctor uses the task-list directory or current directory. Use a narrow project directory, not your entire home. |
| `--start` | Not set | Start selection at this task ID, for example 3 or 3.1. Already terminal tasks are not rerun. Earlier tasks lie outside the explicitly selected scope. |
| `--stop` | Not set | Stop scheduling after this task and its required acceptance. It is not cancellation of the current model call. |
| `--max-depth` | `3` | Maximum numeric task depth; 3 includes IDs such as 2.1.1. This does not disable a STOP barrier. |
| `--max-retries` | `2` | Continuation multiplier for production/correction steps: max-steps times max-retries. It is not whole-task replay after a technical failure. |
| `--max-calls` | `0` | Persistent invocation budget per top-level task tree, shared with descendants/reviews/Decide; 0 means unlimited. Counts attempts, not tokens, money or all internal provider requests. |
| `--breakdown-policy` | `minimal`; one of `minimal`, `legacy`, `off` | Decompose unfinished work using a minimal residual contract, the legacy free decomposition, or no automatic decomposition. |
| `--breakdown-max-children` | `4` | Maximum direct children in minimal decomposition. Valid range: 1 to 12. |
| `--breakdown-max-rounds` | `2` | Maximum focused decomposition/repair rounds including the first child wave. Valid range: 1 to 8. |
| `--process-stop-policy` | `model`; one of `model`, `controller-only` | model allows the task to request a stop; controller-only instructs it to return structured feedback and leave stop decisions to the controller. Existing stop signals still apply. |
| `--max-steps` | `3` | Production/correction-step limit for AutoBuild. The task runner combines this with max-retries; mandatory reviews also use call budget. |
| `--sandbox` | `workspace-write`; one of `workspace-write` | Explicit execution policy. The task runner only accepts workspace-write; standalone AutoBuild also accepts read-only. Mandatory review/Decide remain read-only. |
| `--network-access` | Off | Grant shell-network access within workspace-write. A task may restrict this grant, not create it. Does not control provider, MCP or web-search traffic. |
| `--model` | Not set | Explicit model/deployment identifier. Task runs: CLI, selected-backend environment (ARQUILO_CODEX_MODEL or ARQUILO_CLAUDE_CODE_MODEL), CFG model, native configuration. Doctor overrides require --check-decide. |
| `--reasoning-effort` | Not set; one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | Request supported effort; provider/model support is required. CLI precedes the selected-backend environment. Claude accepts low/medium/high/xhigh/max; Codex also none/minimal. Doctor requires --check-decide. |
| `--backend` | `codex`; one of `codex`, `claude-code` | Select codex (default) or claude-code for production, fixes, review, parent review and Decide. No implicit fallback or mixed-backend run. |
| `--skip-backend-preflight` | Off | Skip only the selected-backend runner preflight. Per-call executable/protocol checks, sandbox requirements and mandatory reviews remain. |
| `--skip-codex-preflight` | Off | Skip the runner workspace-write functional probe only after that environment has been checked separately. Does not skip mandatory task reviews. |
| `--dry-run` | Off | Lint and render planned work without model calls. Explicit --todo-template can still create the missing list. Does not certify provider permissions or Git snapshot suitability. |
| `--dry-run-file` | `run_todos_dry_run.md` | New output file for the dry-run report, relative to the invocation directory. Existing output is refused rather than overwritten. |
| `--simulate-incomplete` | Empty list; repeatable | In dry run only, mark the supplied task ID as incomplete for simulation; repeat for multiple IDs. |
| `--run-id` | Not set | Optional run identifier; a new identifier is generated when omitted. Changing the identifier does not reset task state or consumed budgets. |
| `--git` | Off | Request commits of explicit selected outputs bound to their review; no implicit push. Capture only selected files; task acceptance and optional publication have separate outcomes. |
| `--git-path` | Empty list; repeatable | One literal relative output filename per occurrence, not a glob or directory. Requires --git. Do not select task plans, rewritten reports or controller logs. |
| `--git-push` | Off | Additionally publish reviewed commits to the approved existing upstream. Requires --git and the documented remote/serial-execution conditions. |
| `--git-required` | Off | Require successful requested Git delivery before the run continues; requires --git. Accepted tasks remain DONE, but pending delivery yields incomplete exit 9. |
| `--state-dir` | Not set | Trusted external controller-state root. Defaults: ~/Library/Application Support/ARQUILO/controller on macOS, ~/.local/state/arquilo/controller on Linux/WSL, LOCALAPPDATA/ARQUILO/controller on Windows. Keep the same root when resuming. |
| `--project-id` | Not set | Readable log grouping identifier, 1 to 48 characters, validated as a portable name. Bound to workspace/plan; does not merge independent budgets. |
| `--logs-in-workdir` | Off | Place new diagnostic run logs in the workspace under the selected backend log directory. Authoritative journals, budgets and worker returns remain external. |
| `--allow-todo-modifications` | Off | Explicitly permit and record valid primary-plan edits during this run. Model-written statuses are not independent review evidence. Permission is not sticky across runs. |
| `--accept-plan-changes` | Off | Adopt owner-inspected external plan changes on restart. Preserve consumption/history. Not a generic repair for an unexplained integrity failure. |
| `--runtime-profile` | Not set | Load an operator-trusted JSON runtime profile. CLI precedes ARQUILO_RUNTIME_PROFILE. A real run may execute its host preflight command. |
| `--print-capabilities` | Off | Print the core capability/contract JSON without model execution; also available through arquilo.py capabilities. |
| `--prompt-config` | `default` | Use the complete built-in default, de or en TOML catalog, or an explicit file. Frozen for the invocation; not a task-controlled selector. |
| `--mcp` | Not set | Comma-separated explicit server selection/ceiling, or none. Codex omission inherits native configuration. Claude accepts only none/omission; no named servers or native MCP inheritance. |
| `--review-mcp` | Not set | Subset of production MCP servers for review, or none. Explicit --mcp defaults review to none. Local read-only policy does not make remote tools read-only. |
| `--skills` | Not set | Comma-separated skill names, or none for no explicit bindings. Instruction snapshots, not permission grants. Does not disable native implicit discovery. |
| `--skill-dir` | Empty list; repeatable | Approved root containing skill directories with SKILL.md; repeatable. Explicit roots replace default discovery roots. |
| `--agent` | Not set | Native Codex profile name and agent hint, not a team definition. Local CFG agent can override it. Rejected for Claude. |

<a id="cli-doctor"></a>
### `doctor`

Use `python3 -B arquilo.py doctor OPTIONS`. Model/provider/profile/effort/timeout overrides require `--check-decide`; metadata-only checks do not call a model.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--backend` | `codex`; one of `codex`, `claude-code` | Select codex (default) or claude-code for production, fixes, review, parent review and Decide. No implicit fallback or mixed-backend run. |
| `--workdir` | Not set | Workspace. In the task runner, defaults to the task-list directory; Doctor uses the task-list directory or current directory. Use a narrow project directory, not your entire home. |
| `--todo-file` | Not set | Working UTF-8 Markdown task list. Required for execution; not needed for help/capabilities. An existing list is resumed, not replaced. |
| `--json` | Off | Emit the Doctor report as JSON on stdout, including failures; not a request for model-generated JSON. |
| `--check-decide` | Off | Opt in to one live diagnostic model call after metadata checks; may incur provider charges. Default Doctor is metadata-only. |
| `--model` | Not set | Explicit model/deployment identifier. Task runs: CLI, selected-backend environment (ARQUILO_CODEX_MODEL or ARQUILO_CLAUDE_CODE_MODEL), CFG model, native configuration. Doctor overrides require --check-decide. |
| `--model-provider` | Not set | Existing native Codex provider for the live Doctor probe; requires --check-decide. Does not define credentials or a URL. Rejected for Claude. |
| `--profile` | Not set | Existing native Codex profile for the live Doctor probe; requires --check-decide. Tasklist run uses --agent. Rejected for Claude. |
| `--reasoning-effort` | Not set; one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | Request supported effort; provider/model support is required. CLI precedes the selected-backend environment. Claude accepts low/medium/high/xhigh/max; Codex also none/minimal. Doctor requires --check-decide. |
| `--decide-timeout` | Not set | Positive finite timeout for the live Doctor probe. Effective default is 120 seconds, plus metadata/cleanup. Requires --check-decide. |
| `--prompt-config` | `default` | Use the complete built-in default, de or en TOML catalog, or an explicit file. Frozen for the invocation; not a task-controlled selector. |

<a id="cli-resume"></a>
### `tasklist resume-review`

Use `python3 -B arquilo.py tasklist resume-review --todo ID --capture-dir DIR -- tasklist run ORIGINAL_OPTIONS`. Recovery requires `--start ID --stop ID` after the separator; the original workspace/task contract must match. All following runner options are listed above.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--todo` | Required | Required exact task ID for narrow review-only recovery; must match the single task selected after the -- separator. |
| `--capture-dir` | Required | Required original archived production-capture directory. Evidence is verified before any model call; an arbitrary folder of outputs is insufficient. |

<a id="cli-git"></a>
### `git`

Use `python3 -B arquilo.py git status --workdir DIR --todo-file FILE` or `git retry` with the same paths and --publication ID. Reuse the original --state-dir when set. Status/retry never run a model or review; retry retains normal STOP and controller-lock checks.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `command` | Required; one of `status`, `retry` | status lists retained publication records; retry reconciles one exact recorded publication. Both print JSON and make no model/review calls. |
| `--workdir` | Required | Required original Git working-tree root; use the same path as the task run. |
| `--todo-file` | Required | Required original task-list path selecting existing private state. Relative paths are relative to the shell working directory, as in tasklist run. |
| `--state-dir` | Not set | Original private state base, if the task run used a custom --state-dir. Do not select a new state root to retry publication. |
| `--publication` | Not set | Exact existing publication ID returned by git status. Required for git retry and rejected for status; no model or review call. |

<a id="cli-package"></a>
### `package`

Use `python3 -B arquilo.py package [NEW_ZIP_PATH]`. This creates an archive and checksum, not a release.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `destination` | Not set | Optional NEW ZIP filename. Default: dist/arquilo-VERSION.zip. Both archive and checksum must be absent. Building does not tag or publish a release. |

<a id="cli-confidence"></a>
### `review_confidence.py`

Use `python3 -B review_confidence.py SUMMARY_JSON`. Confidence is advisory, not an acceptance threshold.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `summary` | Required | Existing AutoBuild summary JSON or structured review JSON. Print advisory confidence; do not modify the file or infer a new PASS. |

<a id="cli-autobuild"></a>
### `autobuild.py`

Use `python3 -B autobuild.py OPTIONS`. Exactly one task source (`--task` or `--task-file`) AND one target (`--workdir` or `--file`) are required. This is a single-assignment interface, not a second task-list scheduler.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--backend` | `codex`; one of `codex`, `claude-code` | Select codex (default) or claude-code for production, fixes, review, parent review and Decide. No implicit fallback or mixed-backend run. |
| `--task` | Not set | Standalone assignment text. Supply exactly one of --task or --task-file. |
| `--task-file` | Not set | UTF-8 file containing the standalone assignment; mutually exclusive with --task. |
| `--workdir` | Not set | Workspace. In the task runner, defaults to the task-list directory; Doctor uses the task-list directory or current directory. Use a narrow project directory, not your entire home. |
| `--file` | Not set | Standalone single-file mode in an isolated workspace, mutually exclusive with --workdir. Inspect the returned output path; do not assume in-place publication. |
| `--sandbox` | `workspace-write`; one of `workspace-write`, `read-only` | Explicit execution policy. The task runner only accepts workspace-write; standalone AutoBuild also accepts read-only. Mandatory review/Decide remain read-only. |
| `--network-access` | Off | Grant shell-network access within workspace-write. A task may restrict this grant, not create it. Does not control provider, MCP or web-search traffic. |
| `--codex-profile` | Not set | Existing native Codex profile for standalone AutoBuild; tasklist run calls this --agent. Rejected for Claude. |
| `--mcp` | Not set | Comma-separated explicit server selection/ceiling, or none. Codex omission inherits native configuration. Claude accepts only none/omission; no named servers or native MCP inheritance. |
| `--review-mcp` | Not set | Subset of production MCP servers for review, or none. Explicit --mcp defaults review to none. Local read-only policy does not make remote tools read-only. |
| `--skills` | Not set | Comma-separated skill names, or none for no explicit bindings. Instruction snapshots, not permission grants. Does not disable native implicit discovery. |
| `--skill-dir` | Empty list; repeatable | Approved root containing skill directories with SKILL.md; repeatable. Explicit roots replace default discovery roots. |
| `--prompt-config` | `default` | Use the complete built-in default, de or en TOML catalog, or an explicit file. Frozen for the invocation; not a task-controlled selector. |
| `--model` | Not set | Explicit model/deployment identifier. Task runs: CLI, selected-backend environment (ARQUILO_CODEX_MODEL or ARQUILO_CLAUDE_CODE_MODEL), CFG model, native configuration. Doctor overrides require --check-decide. |
| `--reasoning-effort` | Not set; one of `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | Request supported effort; provider/model support is required. CLI precedes the selected-backend environment. Claude accepts low/medium/high/xhigh/max; Codex also none/minimal. Doctor requires --check-decide. |
| `--extra-arg` | Empty list; repeatable | Repeatable validated additional Codex argument for standalone use. Policy-changing or conflicting arguments are rejected; not a sandbox bypass. |
| `--logfile` | Not set | Standalone readable log path; omitted paths are allocated for the run. |
| `--rawlog` | Not set | Standalone raw event log path; raw content can contain sensitive data. |
| `--summary-json` | Not set | Optional standalone machine-readable result path. A workspace summary is diagnostic, not a private worker-authority channel. |
| `--process-stop` | Not set | Optional standalone stop-signal path. Inspect an existing stop before explicitly resuming. |
| `--todo-identifier` | Not set | Task identity attached to standalone diagnostics and decision context, when integrating with a controller. |
| `--decision-todo-file` | Not set | Task-list reference for standalone decision context; not permission to replace the original task contract. |
| `--decision-run-id` | Not set | Run identity for standalone decision context; does not create a new shared budget. |
| `--max-steps` | `3` | Production/correction-step limit for AutoBuild. The task runner combines this with max-retries; mandatory reviews also use call budget. |
| `--max-calls` | `0` | Persistent invocation budget per top-level task tree, shared with descendants/reviews/Decide; 0 means unlimited. Counts attempts, not tokens, money or all internal provider requests. |
| `--auto-continue` | Off | Compatibility/progress flag: in this implementation it adds an automatic-continuation log message; it does not change the correction loop or require/skip a confirmation. Mandatory review and limits remain in force. |
| `--print-end-answer` | Off | Also print the final standalone assistant answer. |
| `--verbose` | Off | Print detailed standalone progress. Keep potentially sensitive output private. |

### Maintainer and synthetic test utilities

These are separate from task execution. Repository-only test utilities are not normal runtime configuration. Their parameters are included here for a complete command reference.

<a id="cli-scripts-check_release-py"></a>
### `scripts/check_release.py`

Offline source/package validation. `--source` can point at an extracted runtime; no publication is performed.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--source` | `<checkout-root>` | Source checkout or extracted runtime to validate offline; defaults to this script's checkout root. No model or network call. |

<a id="cli-scripts-stage_lean-py"></a>
### `scripts/stage_lean.py`

Lower-level allowlist staging. Prefer the `package` command for the standard runtime ZIP plus checksum.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `destination` | Required | Required NEW output directory, or ZIP path with --zip. |
| `--zip` | Off | Stage an allowlisted ZIP rather than a new directory; this lower-level utility does not publish a release. |

<a id="cli-scripts-install_test_codex-py"></a>
### `scripts/install_test_codex.py`

Repository-only CI utility: downloads an exact upstream binary into a new directory. This uses the network, but does not install globally, log in or call a model.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `version` | Required; one of `0.154.0`, `0.159.1` | Required exact test-binary version from the listed choices, not a model name. The downloader uses the upstream release service and verifies its digest. |
| `destination` | Required | Required NEW destination directory. |

<a id="cli-scripts-check_codex_configuration-py"></a>
### `scripts/check_codex_configuration.py`

Repository-only synthetic configuration/metadata compatibility probe; starts the specified local CLI in disposable directories. Not a production task.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--codex` | Required | Required path to the trusted Codex binary used by the synthetic compatibility check. Not a task runner option; no production credentials are needed. |

<a id="cli-scripts-check_codex_provider-py"></a>
### `scripts/check_codex_provider.py`

Repository-only synthetic loopback-provider probe. Starts the supplied CLI and a local test server; no live model provider is used.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--codex` | Required | Required path to the trusted Codex binary used by the synthetic compatibility check. Not a task runner option; no production credentials are needed. |

<a id="cli-scripts-check_resource_configuration-py"></a>
### `scripts/check_resource_configuration.py`

Repository-only synthetic MCP configuration/startup probe. Uses local test processes, not customer MCP servers or live model credentials.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--codex` | Required | Required path to the trusted Codex binary used by the synthetic compatibility check. Not a task runner option; no production credentials are needed. |

<a id="cli-scripts-documentation_reference-py"></a>
### `scripts/documentation_reference.py`

Repository-only handbook maintenance. --check and --write are mutually exclusive; omission checks without writing.

| Parameter / argument | Value / default | Meaning |
| --- | --- | --- |
| `-h` / `--help` | Action | Show the help for this command and exit; no model call. |
| `--write` | Off | Regenerate the documentation CLI catalog and tables after reviewing an intentional parser change; modifies documentation files only. |
| `--check` | Off | Verify the generated documentation against the parsers without writing; this is also the default. |

### Aliases and excluded internal arguments

Use the canonical commands in new scripts. `run` is a compatibility alias for `tasklist run`; `resume-review` aliases `tasklist resume-review`. `run_todos.py`, `arquilo_doctor.py` and `scripts/build_runtime_zip.py` expose the corresponding parser directly. `capabilities` forwards to the runner with `--print-capabilities`; model/run selectors do not turn that metadata request into execution.

`autobuild.py --request-json`, `--decision-attempt-id` and `--decision-phase` are private worker/controller transport fields, not supported user configuration. Rejection-only removed switches (for example `--full-auto`, `--no-check`, `--yolo` and task-runner `--profile`) do not enable hidden modes. Standalone AutoBuild has no `--max-retries`; use the runner for task-list continuation.

`decide.py` provides a Python API, not a standalone argument parser. `scripts/check_naming.py` has no argument parser and checks its own source tree; `scripts/check_release.py --source` is listed above. No CLI setting for teams, an MCP service or a GUI is supplied by this checkout.
<!-- END GENERATED CLI REFERENCE -->

<a id="environment-reference"></a>
## 17. Environment variables and fixed settings

ARQUILO reads the following ten current configuration variables. A nonempty canonical value takes precedence over supported historical aliases; empty values do not set a default. No workspace `.env` is loaded. CLI paths and explicit options override only the documented corresponding default, not every other configuration layer.

| Variable | Default when absent | Purpose and precedence |
| --- | --- | --- |
| `ARQUILO_CLAUDE_CODE_COMMAND` | `claude` from approved host PATH | Trusted executable path/name, never a shell command string; resolved outside writable workspaces. |
| `ARQUILO_CLAUDE_CODE_MODEL` | No global model override | Claude model fallback after `--model`, before task `CFG model`; no Codex model fallback. |
| `ARQUILO_CLAUDE_CODE_REASONING_EFFORT` | No effort override | Claude effort fallback after the CLI; `low`, `medium`, `high`, `xhigh`, `max`. |
| `ARQUILO_CODEX_MODEL` | No global model override | Fallback for task-run/AutoBuild model selection; explicit `--model` wins. The effective global value precedes `CFG model`. |
| `ARQUILO_CODEX_REASONING_EFFORT` | No effort override | Fallback for task-run/AutoBuild effort; explicit `--reasoning-effort` wins. Same seven supported strings as the CLI. |
| `ARQUILO_TODO_SYNTAX` | `auto` | Runner emitted task syntax; overridden by `--todo-syntax`. |
| `ARQUILO_TODO_PREAMBLE` | `auto` | Runner preamble inclusion; overridden by `--todo-preamble`. |
| `ARQUILO_RUNTIME_PROFILE` | No custom profile | JSON profile path; overridden by `--runtime-profile`. |
| `ARQUILO_DECISION_MODEL` | Effective task model, otherwise native selection | Codex internal AutoBuild Decide model override, not a change to production/review model; not implicitly used for Claude. Standalone Doctor has its own explicit selectors. |
| `ARQUILO_DECISION_SYSTEM_PROMPT` | Selected catalog's `decision_system` | Owner-authored AutoBuild decision instruction; not automatically translated. Do not use prose to override executable acceptance rules. |
| `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | `120` seconds | Shared AutoBuild transport wait after a terminal turn; the historical variable name is retained for both backends. |
| `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS` | `7200` seconds | Shared AutoBuild inactivity timeout for either backend; not a complete task/run deadline. |
| `ARQUILO_CODEX_KILL_GRACE_SECONDS` | `10` seconds | Shared AutoBuild transport shutdown grace for either backend before escalation. |

The three timeout values must be finite and nonnegative. `0` is an allowed numeric value, not a universal synonym for unlimited; consult the transport behavior before using zero. Explicit Python transport settings can supersede these values. Decide uses its own bounded settings rather than assuming these AutoBuild timeouts apply.

`CODEX_HOME`, `PATH`, the user's home, platform application-data location, provider authentication variables, proxies and certificate settings are **host inputs**, not extra ARQUILO feature switches. Default controller roots are `~/Library/Application Support/ARQUILO/controller` on macOS, `~/.local/state/arquilo/controller` on Linux/WSL and `%LOCALAPPDATA%\ARQUILO\controller` on Windows (with the registered local app-data folder as fallback). `--state-dir` is the supported override; there is no general ARQUILO state-root environment option. Native configuration is not rewritten and secrets must not be included in distributable profiles.

The compatibility layer accepts the historical prefix for retained options with warnings; the [repository-only naming map](https://github.com/abernert/arquilo/blob/integration/hardening-guides-091-20261024/docs/compatibility.md) lists those aliases. In addition, `AUTOBUILD_DECISION_MODEL` / `METACODEX_DECISION_MODEL`, `AUTOBUILD_DECISION_SYSTEM_PROMPT` / `METACODEX_DECISION_SYSTEM_PROMPT` and the three corresponding `AUTOBUILD_CODEX_*_SECONDS` names remain compatibility inputs, in that order after canonical/historical-prefix names. New scripts should use only canonical names.

### Values that are not configurable CLI options

The Git snapshot's 32 MiB/file, 128 MiB total, 20,000 entries, depth 64 and 8 MiB manifest are implementation limits. Preamble input is limited to 65,536 UTF-8 bytes. Prompt catalogs use 512 KiB file/combined-text and 128 KiB per-element bounds. No documented flag silently raises these limits. Full-run deadlines and output quotas remain development work, not available parameters.

<a id="task-format-reference"></a>
## 18. Task file, preamble and status syntax

A normal non-Git run uses a shared workspace. Plan edits are subject to strict authority checks unless the operator explicitly selects mutable-plan mode. With automatic Git, mandatory reviews use the private snapshot described in the Git chapter. The production agent and reviewer can read project files, earlier `todo_result` reports, and new artifacts. The production request continues to reference the ToDo file, task number, and result file; the runner does not replace it with an extracted standalone task.

### Preamble

Text before the first real Task/Auftrag/DONE/OBSOLETE entry is the project preamble. Already completed or obsolete entries also delimit it. Task examples inside backtick/tilde code fences and HTML comments are not executable entries. A bare `***SYNTAX marked-en***` line, control directives, separators, or exclusively invisible examples do not count as substantive preamble content. A file with no task header also has no preamble.

```markdown
***SYNTAX marked-en***

# Project goal
Develop a verifiable result from the available project files.

# Working method
Task 1 should perform a bounded work step and create concrete follow-up tasks.
The overall project goal is not yet its acceptance criterion.

1. ***Task***: Inspect the inputs and plan the next work steps.
    Result: A documented finding and two to four concrete follow-up tasks.
    Acceptance: The next steps have unambiguous deliverables.
```

`run_todos.py --todo-preamble auto|off|required` controls embedding:

| Mode | Behavior |
| --- | --- |
| `auto` (default) | Embed a substantive preamble plus neutral file semantics; otherwise retain the existing reference prompt. |
| `off` | No automatic embedding. The reference prompt and Markdown checks remain active. |
| `required` | Missing substantive preamble is an error before the model call. |

The CLI overrides `ARQUILO_TODO_PREAMBLE`; direct Python calls use `TodoRunner(..., todo_preamble="auto")` and do not implicitly read that environment variable. Unknown modes are rejected. On the CLI path, prevalidation occurs even before the optional Codex preflight. The capability is `run_todos.preamble: 1`; the effective mode is recorded as `todo_directives.todo_preamble` in `run_config.json`.

Example for an already configured target system; on Windows use the appropriate Python command instead of `python3`:

```text
python3 run_todos.py --todo-file documents/todos/todo.md --workdir . --todo-preamble required
```

Before each central AutoBuild call, the controller validates the active plan and binds the accepted original assignment. The same embedded original request reaches production, review, correction, and subsequent review. Breakdown, children, parent review, and the optional Python worker also receive the preamble. For a subworkspace, its active ToDo copy is used.

Within one central invocation, including its bounded attempts, this preamble remains fixed. The next central invocation reads changes again; the review of an already-started attempt does not receive a retroactively changed prompt. Standalone AutoBuild receives exactly the task passed to it and does not load a preamble automatically.

UTF-8, a single BOM at the start of the file, and LF/CRLF are supported. The embedded prefix is preserved including whitespace and line endings; the BOM is not part of the context text. More than **65,536 UTF-8 bytes**, read errors, or invalid encoding cause an error; there is no silent truncation. Referenced files are not automatically expanded into the prefix. Text and byte count are logged without hash labels, signatures, or additional access rights. Full prompts also appear in the normal run archive and dry-run preview.

### Existing task semantics

- `<id>. Auftrag: ...`, `<id>. Task: ...`, and `<id>. ***Task***: ...` remain readable. New marked entries use `<id>. ***Task***: ...`. `***SYNTAX marked-en***` and `--todo-syntax` control emitted spelling; examples or comments do not change it.
- Unique, ascending IDs and the existing numbering remain in force. Only the controller marks a successful task DONE. OBSOLETE is not successful completion and does not satisfy a WAIT dependency.
- The runner rereads the file during a run. An authorized planning task can add follow-up tasks; they are discovered and processed in the same workspace. A deliberate `--stop` boundary limits the run. Completion of a planning task does not prove completion of later work.
- CFG/WAIT apply to the immediately following entry. STOP must appear directly before the affected open task. Grammar is validated before selection, including WAIT/STOP, and before AutoBuild. Removed features or invalid directives are reported explicitly even when the remaining task list would otherwise be closed.
- Stored DONE entries satisfy `WAIT on=todo:<id>` or `WAIT on=<id>` after restart. Mere attempts and OBSOLETE do not. `group:`/`agent:` retain their existing runtime states; those states are not invented from DONE entries. Bridge WAIT conditions have been removed since 1031 and are rejected with a migration message.

The complete directive reference is [todo_directives.md](#task-directive-reference). There is no new board, mandatory `mission.md`, or new status database. Preamble embedding does not replace mandatory reviews or inspection of the actual artifacts.

<a id="task-directive-reference"></a>
## 19. Complete CFG, WAIT and DEFAULTS reference

This document describes the backward-compatible directive format implemented by `run_todos.py`.

### Purpose

- Run tasks in parallel subworkspaces.
- Apply different agent/model hints per task.
- Control sequencing through wait conditions.
- Configure model and web-research behavior per task.

### Backward compatibility

- Existing lines in the form `<id>. Auftrag: ...` remain valid.
- Without directives, `run_todos.py` behaves as before.
- `***STOP***` remains active and must appear directly before the affected task.

### Directive syntax

Directive lines appear directly above a task:

```text
***CFG key=value key2=value2***
***WAIT on=... mode=... timeout=... on_timeout=...***
<id>. ***Task***: ...
```

- Values may be quoted when needed.
- Multiple `CFG`/`WAIT` lines may precede the same task.
- `CFG` values are merged for the next task.
- Code examples and HTML comments remain invisible to scheduling. A trailing HTML note after a real directive does not hide the directive.
- The complete current file is validated before selection, including WAIT/STOP, and before AutoBuild. Invalid or removed keys are errors; they are not treated as defaults or successful no-ops.
- Quoting uses the existing POSIX text grammar on every platform; it is not shell execution. Quote Windows backslash paths, for example `workspace='C:\Project Space\Part'`, or use forward slashes. The path must match the host and remain inside the main workspace. The quote grammar performs no variable, tilde, or command substitution.

### Indented examples and existing plans

For scheduling, ARQUILO ignores lines beginning with four ASCII spaces or a tab
preceded by zero to three ASCII spaces. This applies to task headers, CFG, WAIT,
STOP and fence markers. Lines with up to three leading spaces remain eligible.
This is an explicit lexical task-file rule, not a complete Markdown renderer.
A closing HTML comment is still processed so later real tasks remain visible.

Before updating an existing plan, inspect any task headers or directives indented
by four columns: these now count as examples, not executable entries. Use
unindented headers/directives for executable work. Do not automatically reset a
controller journal or adopt changed task requirements to suppress a mismatch.

### Complete directive field index

| Directive | Every supported field | Default / scope |
| --- | --- | --- |
| `CFG` | `workspace`, `parallel`, `agent`, `model`, `web_search`, `websearch`, `network_access`, `result_file`, `completion_anchor`, `breakdown`, `breakdown_max_children`, `breakdown_max_rounds`, `mcp`, `review_mcp`, `skills` | Immediately following task only; details below. |
| `WAIT` | `on`, `mode`, `timeout`, `on_timeout` | `on` required; mode `all`, timeout omitted means immediate current-state check, on_timeout `stop`. |
| `DEFAULTS` | `mcp`, `review_mcp`, `skills` | At most one directive before the first real task; supplied values are list defaults within CLI ceilings. |
| `SYNTAX` | Bare syntax name `marked-en` or `legacy` | Controls emitted task spelling; no key-value configuration object. |
| `STOP` | No fields | Barrier before the associated task, within the explicitly selected scope. |

No other `CFG` fields select reasoning effort, prompt catalogs, budgets, runtime profiles, state roots or permission bypasses. Keep those operator choices at the CLI/configuration layer.

### CFG options

Supported keys:

- `workspace=<relative_path>`: subworkspace for this task. Default: the main `--workdir`.
- `parallel=<group_name>`: marks the task as part of a parallel group. Default: unset/sequential.
- `agent=<name>`: agent hint for this task's prompt. Default: unset.
  - The same validated name is passed as `config_profile`, producing `codex exec --profile <name>`. ARQUILO does not blacklist Codex profile names: historical-looking names such as `dev` or `yolo` are ordinary profile identifiers here. The worker sandbox mode is still explicitly `workspace-write` (review/Decide: `read-only`), while Codex's normal profile/rules/workspace-write configuration remains effective within that mode.
- `model=<model_id>`: per-task model override. An explicit global model from `run_todos.py --model` or its environment default takes precedence; otherwise the CFG model applies.
- `web_search=live|cached|disabled`: per-task web-search mode. Default: no task override; the global Codex configuration remains effective.
- `websearch=live|cached|disabled`: alias for `web_search`.
- `network_access=true|false`: shell-network permission for `sandbox_workspace_write` via a configuration override. Default follows the runner grant; without `--network-access` it is explicitly false. `true` requires the runner-level grant; `false` may restrict it per task. Network permission does not expand file-write permissions.
- `result_file=<todo_result_*.md>`: local result filename.
- `completion_anchor=<todo_result_*.md>`: alternative result filename; `result_file` wins when both are set. No path components.
- `breakdown=minimal|legacy|off`: decomposition policy. Aliases: `structured` for minimal and `none|disabled|false` for off.
- `breakdown_max_children=1..12`, `breakdown_max_rounds=1..8`: decomposition bounds; these are not new scheduler budgets.

### WAIT options

Supported keys:

- `on=<expression>`: wait condition. Allowed prefixes:
  - `todo:<id>`
  - `<id>` as shorthand for `todo:<id>`
  - `group:<group_name>`
  - `agent:<agent_name>`
- `mode=all|any`: for comma-separated conditions, require all or any.
- `timeout=<duration>`: for example `30s`, `5m`, `1h`, `1d`.
- `on_timeout=stop|continue`: timeout behavior.

Stored DONE entries satisfy ToDo dependencies after restart. OBSOLETE, an incomplete task, or attempted work does not. Group/agent conditions use their existing runtime state. Multiple WAIT lines are evaluated in sequence. `timeout=0s` checks immediately; omitting timeout also checks only the current state. An unmet condition exits with code 9 unless `on_timeout=continue` is explicit. Empty list items, unknown IDs, and invalid modes are grammar errors. STOP is not a WAIT state and does not create a `process_stop` file.

Bridge WAIT conditions (`bridge:resume[:token]`, `bridge:retry[:token]`, `bridge:escalation`, and `bridge:escalated`) are not supported. Linter and runner report them as configuration errors before the affected model call, including dynamically added tasks, mixed WAIT conditions, `mode=any`, and `on_timeout=continue`. There is no activation option. See [Migration](#migration-reference).

### Execution rules

- Directives apply only to the immediately following task.
- Parallel execution remains optional and requires no separate mode switch.
- Every task in a parallel group must use its own `workspace`.
- WAIT directives in parallel groups are checked for each task before the group starts.
- Resolved `workspace` paths must remain inside the main workspace.
- Retired ARQUILO YOLO/Full-Auto/No-Check and historical security-profile *fields* are rejected, including historical `false` defaults. This does not blacklist ordinary Codex `--profile` names. Mandatory reviews apply to sequential and parallel flows.
- All `logician`/`logician_*` directives have been removed, including former `off`/`lite` defaults. Remove them; normal reviews and audits do not require a ledger. See [Migration](#migration-reference).
- ACE, IACT, OpenClaw/Bridge, and service fields are also removed even when set to `false`, `off`, `null`, or empty. No optional group re-enables them. Parallel CFG, general runtime profiles, and explicit Git opt-in remain core features.
- Sync-back from subworkspaces is non-destructive: results/questions are merged instead of replacing the whole file.
- `WAIT ... on_timeout=stop` ends the run in a controlled manner.

### Web research

Integrated web search is configured separately through `web_search=live|cached|disabled`. `network_access` concerns shell commands started by the agent in `workspace-write`; provider communication and MCP/apps are separate paths. Therefore `network_access=false` does not claim fully offline execution. ARQUILO has no unrestricted sandbox mode.

Notes:

- `web_search` and `network_access` are passed as temporary Codex configuration overrides (`-c ...`) per task.
- `agent=<name>` selects a Codex model/tool profile (`--profile <name>`). The explicit CLI sandbox policy remains effective even when profile defaults differ.
- Global/isolated configuration through `CODEX_HOME/config.toml` remains possible.

### Example

```md
***CFG parallel=grp_mod workspace=workspaces/analysis agent=analyst web_search=disabled network_access=false***
21.8.1. ***Task***: Analyze the affected modules and document risks.

***CFG parallel=grp_mod workspace=workspaces/tests agent=tester web_search=disabled network_access=false***
21.8.2. ***Task***: Add regression tests for the same modules.

***WAIT on=group:grp_mod mode=all timeout=120m on_timeout=stop***
21.8.3. ***Task***: Integrate the results from analysis and tests.
```

### Recommended invocation

```text
python3 /path/to/arquilo/run_todos.py --todo-file /project/tasks.md --workdir /project
```

Native Windows/PowerShell:

```powershell
py -3.11 C:\Arquilo\run_todos.py --todo-file C:\Project\tasks.md --workdir C:\Project
```

Shell network access additionally requires `--network-access` on the runner. [Migration](#migration-reference) explains removed switches and the distinction between approval policy and sandbox. [Project preamble](#task-format-reference) explains `auto|off|required`, reference prompts, Markdown visibility, and dynamic follow-up tasks.

### Explicit resources (0.8.0)

`CFG mcp=... review_mcp=... skills=...` accepts comma-separated, case-sensitive
names, or `none`. The equivalent run flags are `--mcp`, `--review-mcp` and
`--skills`. A run-level `--agent` supplies the default for existing `CFG agent`.
One `***DEFAULTS mcp=... skills=...***` before the first real task supplies
list-wide resource defaults. It is machine-readable metadata, not a new source
of authority; ordinary preamble text keeps its existing meaning. CFG remains
local to the immediately following task. Examples/comments stay non-executable.

Example (server and skill names must already exist on the operator's system):

```md
# Goal
Prepare proposals only; do not publish externally.

***DEFAULTS mcp=issues,docs skills=ticket-draft***

***CFG mcp=issues***
1. ***Task***: Prepare a proposal from input.json and identify open questions.

***CFG mcp=none skills=none***
2. ***Task***: Summarize the accepted local proposal.
```

Selections replace, rather than add to, the inherited set. A CLI selection is
both a default and a ceiling; list defaults and task/descendant selections may
only narrow it. A task's initial selection also bounds model-edited task lists
within that run. Omitting all resource settings preserves the old behavior.
In explicit MCP mode, missing/disabled/policy-denied servers cause an error,
not re-enablement or silent omission. Server definitions, authentication and
per-tool permissions remain in the operator's trusted Codex configuration.

Explicit `mcp` defaults the review to no MCP. `review_mcp=issues` can provide a
subset to reviewers; server-side credentials/tool permissions must enforce any
remote read-only restriction. Preflight does not inherit production MCPs in
resource-controlled mode; Decide is MCP-free when MCP selection is explicit. MCP selection is not an offline mode: it does
not disable provider communication, shell access or separately allowed web search.
Plugin/app integrations are disabled for explicit MCP calls; this first adapter
selects direct servers, not plugin-bundled MCPs. Native config inspection may
query auth metadata, but never starts STDIO tools or model calls. Raw inventory
is withheld from logs. Do not change Codex configuration concurrently with a run.

Skills are explicitly bound instruction snapshots, not another agent or a
permission grant. Without `--skill-dir`, lookup uses `<workdir>/.agents/skills`,
`~/.agents/skills`, and `$CODEX_HOME/skills` (default `~/.codex/skills`). With one
or more `--skill-dir` arguments, only those roots are searched. Each root contains
skill directories with `SKILL.md`, YAML frontmatter and a simple `name` field.
Duplicate names, unsafe paths, missing definitions and oversized context fail
before the task model call. The operator can use `--skill-dir` to disambiguate.

Production, review and fixes receive the same captured skill instructions plus
the normal preamble and task. Scripts/references remain external files resolved
relative to the recorded skill directory; they are not copied or automatically
executed. Do not change those files while working. `skills=none` means no explicit
binding; it does not disable Codex's normal implicit skill discovery or file
access. Native `AGENTS.md` discovery is likewise unaffected.

A dry run validates task syntax and explicit skill bindings and shows the
selected names without launching Codex, MCP servers, scripts or model calls.
It cannot certify native MCP inventory, authentication or remote permissions.

The first explicit MCP adapter supports configured STDIO and Streamable HTTP
servers with portable IDs (letters, digits, underscores and hyphens). Dots in
server IDs are rejected: the tested native CLI override parser does not use
TOML key quoting for path components. Rename such a local alias before using
explicit selection; no transport or credentials are copied to command arguments.

<a id="limits-reference"></a>
## 20. Invocation budgets and continuation limits

`--max-calls 0` is the default: there is no ceiling on counted Codex execution attempts. A positive value limits each numeric root-task tree across restarts. `12`, `12.1`, their children, breakdown, corrections, reviews, and Decide share one counter; root task `13` receives its own.

The counter is reserved before an execution attempt, not for every internal model request made by Codex. Startup/provider/archive failures are not refunded. One `codex exec` may contain multiple model requests. The budget is not a money, token, or time limit. CLI metadata probes, pure Python worker startup, and JSON evaluation do not count. The separate sandbox preflight is outside the task-tree counter. Usage is still counted when the budget is unlimited.

### Already-started runs

At startup the runner applies the selected limit to existing budgets in the current controller state. With no parameter, previous limits such as 100, including exhausted limits, adopt **0 = unlimited** while preserving consumed reservations and claims. Changes are recorded under `limit_changes/`. Only the operator/runner may change limits, not a worker. An explicitly selected finite limit must be at least the amount already consumed. Damaged state is not automatically deleted or reset.

Keep the workspace, task-list path, and `--state-dir` unchanged when continuing. New runtime timestamps or different log locations do not create a new counter. Existing `process_stop` files remain separate stop instructions even when they were originally caused by an exhausted budget. Before deliberately removing one, inspect its cause, partial changes, and the intended continuation.

### Other loop and stop limits

`max_steps × max_retries` bounds the production/correction steps of an AutoBuild task in the runner (default 3 × 2). `max_retries` is a continuation factor, not a complete replay of the task. After a valid domain FAIL, a targeted correction against the original task may run followed by a new review. Standalone AutoBuild uses `max_steps`. Parallel CFG uses Python workers and controller-assigned shared budget directories.

`breakdown_max_rounds`, `breakdown_max_children`, `max_depth`, invocation timeouts, STOP/WAIT/questions, and `--stop` remain independent of the call budget. Unlimited does not mean endless technical retries or unlimited depth. Quota, authentication, transport, and protocol failures remain technical failures and do not automatically replay the entire task.

With an explicit finite budget, the next invocation is checked before it starts. A PASS on the last permitted invocation remains valid. If a mandatory review is still missing, partial results remain but the task stays open. AutoBuild reports `budget_exhausted` with exit 9; the runner reports `shared_call_budget_exhausted` with exit 6 and `process_stop`. Unlimited budgets do not exhaust.

### Data and operator options

Authoritative data remains in external `budget.json`, `reservations.json`, and numbered claims under `<controller-state>/<plan>/call_budgets/task_<root>/`. Reservation and file operations are locked across processes; a missing diagnostic claim does not release an invocation. The last reservation number continues to increase.

Current budget/claim schemas are `arquilo.call_budget.v2` and `arquilo.call_claim.v2`. For unlimited budgets, `limit=0`, `remaining=null`, `unlimited=true`; `used` remains numeric. Finite v1 data is still validated and read. JSON infinity is never written.

`--logs-in-workdir` moves only new diagnostic logs, not these counters. `--allow-todo-modifications` deliberately permits a mutable main plan. For planning in the same file, task 2 can create later open tasks; `--stop 2` pauses after task 2 has passed review and before those later tasks execute. The operator then inspects the plan and continues separately. Options and detailed PowerShell examples are in [Operator controls](#operator-controls-reference).

<a id="operator-controls-reference"></a>
## 21. Plan-generation and restart runbook

These settings are independent. They do not change the Codex model/provider,
credentials, sandbox, network permissions, mandatory review or retry policy.
They are operator CLI/API choices, not model-editable task directives.

| Option | Default | Effect |
| --- | --- | --- |
| `--max-calls N` | `0` (unlimited) | Bounds counted Codex execution attempts per top-level task tree only when N is positive. |
| `--logs-in-workdir` | Off | Writes live runner logs under `<workdir>/.codex_runs/run_todos/<UTC timestamp>/`. |
| `--allow-todo-modifications` | Off | Adopts and records valid edits to the primary task file, including new tasks. |

### Generate tasks in the same file, then stop for human review

A normal sequential task may generate the rest of its own task list. Use one
Markdown file and explicitly ask the generating task to append open tasks,
keep existing IDs and avoid executing the plan. A ready-to-copy synthetic
example is [planning_todo.md](../../examples/planning_todo.md).

For an existing project, keep its workdir, task-file path and **same state root**.
The following paths and project ID are examples, not deployment requirements:

```powershell
python .\arquilo.py tasklist run `
  --workdir 'D:\ExampleProject' `
  --todo-file 'D:\ExampleProject\tasks.md' `
  --project-id example-project `
  --allow-todo-modifications `
  --stop 2
```

No `--max-calls` is needed: the default is unlimited, including continuation
of an older finite budget. Add `--logs-in-workdir` only when desired.

Expected sequence: run the selected original tasks through task 2, review the
generator against its original requirements, mark that reviewed task done,
and stop scheduling before the generated work. Tasks 3, 4, etc. stay open.
New IDs inserted before the stop position are also excluded for this run.
Parallel batches cannot dispatch tasks beyond the explicit stop boundary.
The generator should be sequential on the primary task file: arbitrary edits
in independent CFG worker copies are not automatically merged into the plan.

The stop option is a runner scheduling boundary, **not** a preventive guard
against a model performing extra work inside an already running Codex call.
A required review still runs. If task 2 fails or its plan is malformed, the run
fails/stops rather than certifying a usable plan. If the stop ID is removed
before it can run, no subsequent work is scheduled. Removing the active stop
task does not cancel the stop after its original assignment is reviewed.

Inspect `tasks.md` after this first run. If you edit the plan yourself, the next
strict run can explicitly adopt those reviewed edits:

```powershell
python .\arquilo.py tasklist run `
  --workdir 'D:\ExampleProject' `
  --todo-file 'D:\ExampleProject\tasks.md' `
  --project-id example-project `
  --start 3 `
  --accept-plan-changes
```

Omit `--accept-plan-changes` if the generated file was not changed afterwards.
Omit `--stop 2` for the continuation. Omitting `--allow-todo-modifications`
restores the strict mode: this permission is **not sticky**. Omit `--start 3`
if you want the normal selection of all remaining open tasks instead.
Neither command clears an existing `process_stop`; inspect any such stop first.

### Budget semantics and existing runs

`--max-calls 0` and omitting the option mean unlimited. `--max-calls 500` allows
500 total reservations for each independent numeric top-level tree, including
its child tasks, production, correction, reviews, breakdown and Decide calls.
Negative/noninteger limits are invalid. A single Codex process can make several
provider requests; this counter is **not** tokens, money or exact billed calls.
A reservation precedes a start attempt, so a startup/logging failure can count
even when no model process successfully ran. The sandbox preflight is separate.

The owning runner adopts its selected limit on existing budget stores while
holding the plan lock, including exhausted and already-completed roots. The
default therefore changes an older limit of 100 to 0 automatically. Existing
claims and the monotonic consumed counter are retained, and `limit_changes/`
records the previous/new limit and count. Older claim-only stores migrate from
the highest reserved claim number, not the number of remaining files. Damaged
counters or inconsistent roots are errors, not invitations to reset data.

An explicit positive limit may be raised or reduced by the owner, but not below
the already consumed count. Workers cannot change limits; a stale worker stops
when its attached limit differs. A new timestamp, log location or project ID
does not reset consumption. Keep using the same authoritative state root.

If an older budget exhaustion already wrote `process_stop`, the budget becomes
unlimited but **that separate stop file remains effective**. Inspect the prior
failure and partial outputs; intentionally remove the stop only after deciding
to resume. No automatic deletion of stop instructions is performed. A changed
task file may separately need `--accept-plan-changes` after human inspection.

Other limits still apply: production/correction steps, task depth, breakdown
rounds/children, per-call timeouts, and explicit stop/wait instructions. Unlimited
calls do not enable whole-task replay or infinite retries on technical errors.

Machine consumers: new budget snapshots/contracts use `arquilo.call_budget.v2`,
new claims `arquilo.call_claim.v2`. Unlimited snapshots have `limit: 0`,
`remaining: null`, `unlimited: true`, and a numeric `used`. They never serialize
JSON Infinity. Valid finite v1 records remain readable; unchanged older budget
files/claims are not rewritten merely for renaming. Changing a limit writes a
v2 contract. Update consumers that require a positive limit or integer remaining.

### Logs for metarunners

```powershell
python .\arquilo.py tasklist run --workdir 'D:\ExampleProject' --todo-file 'D:\ExampleProject\tasks.md' --logs-in-workdir
```

Live logs use:

```text
<workdir>/.codex_runs/run_todos/
  latest-run.txt
  <UTC timestamp>/
    run.json
    run_log.json
    run_config.json
    overview.log
    task-2/
      task_log.json
      autobuild_raw.jsonl
      autobuild_pretty.log
      autobuild_summary.json
      001-production/{capture.json,stdout.bin,stderr.bin,...}
      002-review/{capture.json,stdout.bin,stderr.bin,...}
```

`latest-run.txt` here contains just the timestamp directory name, relative to
`.codex_runs/run_todos`, not an absolute path. The project ID remains metadata;
it adds no extra folder to this compatibility location. Multiple runs are kept.
`run.json` and the compatible `run_log.json` are updated during the run and on
caught completion/failure. Raw/Pretty logs are written live, not exported only
at exit. A hard-killed process can leave a nonterminal status; this is not PASS.

This restores the workspace location and common filenames, **not every older
nested path/schema**. Use the recorded paths, not a fixed `.jsonl.calls` suffix.
`--logs-in-workdir` must be supplied for each run that needs this location.
Without it the external project/timestamp layout remains the default.

Only logs move. Authoritative plan journals, budgets, locks, mutation audits,
breakdown state, and parallel-worker request/return files stay external. Worker
results are parsed from their private return and then published for metarunners.
No symlink/junction to controller state is created. All no-follow checks remain.

Workspace logs are readable/modifiable by the agent. Treat them as diagnostics,
not tamper-proof authority. They may expose prompts/project data to the agent or
unreviewed Git commits. Retain a private workspace and exclude `.codex_runs`
from your own version-control tooling. ARQUILO's explicit Git selection still
rejects internal logs. Metarunners must not treat model-edited logs as trusted
instructions, shell commands, or independent proof of success.

### Editable-plan trust boundary

With the opt-in, valid primary-file edits are observed and adopted, not rejected
solely for differing from the external snapshot. Syntax and duplicate-ID checks
remain; before/after text and changes are archived externally in `plan-mutations`.
The current assignment's original review contract/snapshot remains fixed across
corrections. Changed active requirements are not marked done as a new revision.

A model-written DONE, removed task or lowered future requirement may alter what
the scheduler runs. This is intentionally weaker than strict plan integrity.
`reviewed_this_run` lists independently reviewed **original assignments**;
`plan_mutations` distinguishes observed plan changes (`independently_verified:
false`). `completion_scope` / `todo_policy` in run metadata explain the mode.
Do not equate every DONE in a mutable file with an independent verification.
The legacy `completed` list also contains owner-provided initial DONE entries.
A plan-generation review is not human approval of every generated task.

Plan permission does not grant extra file/network rights or permit task content
to change operator controls. Strict mode remains the default. Use the generating
phase's opt-in and `--stop 2`, inspect the file, then continue strictly whenever
that fits the workflow. See [controller boundaries](technical-guide.en.md#controller-reference).

<a id="logs-reference"></a>
## 22. Project identities and log-file reference

Add `--project-id migration-pilot` to your **existing** task-runner command:

```powershell
python3.11 .\arquilo.py tasklist run `
  --project-id migration-pilot `
  --workdir 'D:\Migration' `
  --todo-file 'D:\Migration\tasks.md'
```

This is the same runner and the same Codex configuration. No new model,
provider, proxy, permissions or retry settings are supplied. Model calls may
incur usage as before. The Doctor is a separate diagnostic command and does not
accept `--project-id`.

### Find the logs

With the default Windows state root, new logs appear here:

```text
%LOCALAPPDATA%\ARQUILO\controller\
  migration-pilot\
    project.json
    latest-run.txt
    runs\
      2026-10-02T11-12-57.000Z\
        run.json
        run_log.json
        run_config.json
        overview.log
        task-2\
          task_log.json
          autobuild_pretty.log
          autobuild_raw.jsonl
          autobuild_summary.json
          001-production\
            capture.json
            prompt.utf8
            stdout.bin
            stderr.bin
            response.txt
          002-review\
            capture.json
            stdout.bin
            stderr.bin
```

The base directory is configurable with the existing `--state-dir`. For a
**new** project you may choose, for example,
`--state-dir "$env:USERPROFILE\ARQUILO-State"`. It must be a private local
directory outside the model workspace and not an ancestor of that workspace.
Do not change an existing plan's state root merely to move logs: that selects a
different persistent state store, not a migration. Keep the current root and
only add `--project-id` when continuing existing work.

IDs are 1-48 ASCII letters, digits, hyphens or underscores, beginning with a
letter or digit. They are normalized to lowercase on every OS. Paths, dots,
reserved Windows device names and the reserved ID `dry-run` are rejected.

One project ID is bound to one canonical workspace in the selected state root.
Several task files in that workspace can share the project ID and log view;
their plan journals, locks and call budgets stay separate. Reusing the ID for
another workspace fails explicitly. Once a task file is assigned to a project,
omitting the flag on a later run remembers that assignment. Changing its ID
silently is refused. No project ID is read from a task's model-editable text.

### Runs and attempts

A run folder uses its start time in UTC, with milliseconds. The `Z` marks UTC,
not the workstation's local time. Names sort chronologically. A collision gets
`-0002`, `-0003`, etc., allocated exclusively; no prior run is overwritten.
`--run-id`, when provided, remains a diagnostic label in the metadata rather
than determining a directory name. It does not select or resume an old run.

Inside a run, task calls use `task-2`, `task-2-0002`, etc. The task manifest
records the actual identifier/role (including parent review or breakdown).
Codex processes use sequential role folders, e.g. `001-production`,
`002-review`, `003-fix`, `004-review`. A legacy-text review requiring Decide
uses a numbered `decide` archive with its separate attempt manifest and I/O
capture below it. No repeated run/task UUID chains are added to that archive;
identities remain in JSON. External file snapshots retain their own necessary
relative paths; this does not flatten or rename user artifacts.

`latest-run.txt` is an ordinary text file containing a relative path such as
`runs/2026-10-02T11-12-57.000Z`. It identifies the **latest started** run, not the
last successful or last finished run. An older concurrent run finishing later
does not move this pointer backwards. It is informational, never plan authority.

`run.json` contains `status`, `started_at`, `finished_at`, `exit_code`, task log
paths and the controller state location. Status starts as `preparing`, becomes
`running`, and is finalized as `completed`, `failed`, `cancelled`, `stopped`,
`incomplete` or `aborted`, as applicable. A hard-killed process can leave
`preparing`/`running` with no end time: that is **not** a successful completion.
A caught preflight failure is recorded as failed. `overview.log` is a short
start/task/outcome index, not a duplicate transcript of every model message.

Technical failures print the exact captured `stderr.bin` path when a Codex
process capture exists; failures before process capture print the available
Pretty/Raw logs instead. Do not infer the cause from the most recently modified
file: check the recorded phase and the error's own path.

### Open the latest run on Windows

Use your selected state root, and a project ID that has already been assigned:

```powershell
$ProjectDir = Join-Path $env:LOCALAPPDATA 'ARQUILO\controller\migration-pilot'
$RelativeRun = (Get-Content -LiteralPath (Join-Path $ProjectDir 'latest-run.txt') -Raw -Encoding UTF8).Trim()
# This guard prevents treating an edited pointer as an arbitrary path.
if ($RelativeRun -notmatch '^runs/\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z(-\d{4})?$') {
    throw 'Invalid latest-run.txt. Inspect it without following the path.'
}
$RunDir = Join-Path $ProjectDir $RelativeRun
Get-Content -LiteralPath (Join-Path $RunDir 'overview.log') -Encoding UTF8
Get-Content -LiteralPath (Join-Path $RunDir 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json | Format-List
```

The run and capture metadata contain paths; raw stdout/stderr may contain
confidential project data. Keep the state root private. No symlink/junction to
controller records is created inside the agent workspace.

### Existing state is not moved or reset

The readable project folder is a log namespace, **not a fresh plan or budget**.
Authoritative records deliberately remain in the existing workspace+task keyed
state directory (`<state-root>/<hash>/...`). No files or absolute budget paths
are moved, copied, reset or reinterpreted. `project.json` lists each task file and
its exact controller state path; `projects.json` in the base directory records
the binding. This retains old runs as well, at their original locations.

This separation avoids an unsafe automatic state migration. Even if a readable
log folder is changed or removed, it does not refund calls or validate a changed
plan. A malformed registry, conflicting binding or redirected filesystem path
causes an error rather than silently inventing a replacement. The existing
owner-adoption rules in [controller safety](technical-guide.en.md#controller-reference) still apply.
Changing the base root or removing authoritative state is not a way to resume
safely and must not be used to bypass a failure.

Without `--project-id` and without a stored binding, the root stays compatible
with the existing `<hash>/runs` location, but new runs and captures still have
shorter names. Old archives are never rewritten. The original `run_log.json`
filename/schema remains as a compatibility snapshot; `run.json` uses
`arquilo.run_log.v2`. Code consuming capture paths should use `capture_directory`
/ `stderr_file` in errors or `CAPTURE:` in Pretty logs, not assume a `.calls`
subdirectory. Dry-runs do not create a project registry or run archive.

### Optional workspace log location

`--logs-in-workdir` selects `<workdir>/.codex_runs/run_todos/<timestamp>/`.
The timestamp goes directly below `run_todos`, even with a project ID. Its
`latest-run.txt` contains a timestamp directory name without `runs/`. Existing
external logs are untouched; the default remains external. Do not apply the
external-pointer regex above to a workspace pointer. The new mode is a live
log location, not an end-of-run export; common Raw/Pretty/Summary filenames are
retained, not every legacy nested path. Plan/budget state and worker IPC remain
external. See [operator controls](#operator-controls-reference) for scope and examples.

Changing log location or project ID never resets reservations. Independently,
the owning runner adopts `--max-calls` on continuation (default 0 removes older
finite limits), preserving counters and auditing limit changes.

<a id="decide-reference"></a>
## 23. Configure and diagnose Decide

The detailed Codex configuration and compatibility examples below apply to the Codex backend. With `--backend claude-code`, Decide uses the independent Claude path, trusted Claude model/provider settings and no task tools; it performs no Codex discovery or fallback. See [backend selection](#backends).

Current Decide behavior preserves model/provider provisioning from the trusted Codex host configuration unless an explicit override is supplied.
It delegates provisioning to the installed Codex CLI, just as a normal local
Codex call does. This includes custom providers such as a company Databricks
gateway, their authentication commands/environment variables, endpoints, HTTP
headers, proxy and certificate configuration. ARQUILO does not implement a
Databricks adapter, choose a deployment, acquire credentials, or rewrite TOML.
Your endpoint must already be compatible with the installed Codex CLI.

### Default and explicit overrides

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

### What is still passed

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

### Trust boundary and limits

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

### Evidence, compatibility and testing

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

<a id="recovery-reference"></a>
## 24. Verified review-only recovery

This procedure is Codex-specific. Claude session recovery and cross-backend reuse are not implemented; a Claude request is not converted into Codex recovery.

**Generic ARQUILO behavior** (independent of provider, proxy or employer).

### Transient stream retries vs. final failures

In non-interactive `codex exec --json`, Codex may report an interim event:

    {"type":"error","message":"Reconnecting... 1/12 (stream disconnected before completion: stream closed before response.completed)"}

ARQUILO treats a **well-formed, pre-terminal** `Reconnecting... n/m`
notice as a diagnostic, not an immediately fatal `stream_error`. The raw
JSONL, pretty log, capture `stream_diagnostics` and event index preserve it.
Variants include WebSocket disconnect and HTTP/SSE response-body decoding
errors. These notices do **not** count as a successful model answer.

Only a real `turn.completed`, nonempty final assistant answer, and successful
Codex process result can qualify as successful production. Real
`turn.failed`, unrelated `error` events, nonzero exits, decode/I/O failures,
missing completion, stop signals and process-cleanup errors remain fatal.
An interim reconnect **after** terminal completion is not suppressed.

An external proxy or LLM gateway can terminate a quiet CONNECT/SSE tunnel
independently of the Codex client. Diagnose long reasoning requests using the
**inactivity** timeout at each network hop, not just total response duration.

### Explicit review-only continuation of an archived production

This is for the narrow case where Codex actually finished a production turn
(`turn.completed` and exit code 0), but the older ARQUILO classified **only**
a recovered retry notice as `codex_stream_error` before its mandatory review
could start. It is **not** a general force-resume or DONE bypass.

Prerequisites:

- Operator has inspected the completed previous run and current artifacts.
- The same workspace, original task list, original task ID, unchanged task
  prompt, state root/project identity and task policy are retained.
- No competing run or active `process_stop` exists.
- The *original* complete capture, original contract, original AutoBuild
  summary and response are available in
  `<workdir>/.codex_runs/run_todos/<run>/task-<ID>/001-production/`.
- This command is an explicit operator choice. Archived logs inside a
  model-writable workspace are **not independent trusted evidence**.

Example from inside the original workspace:

~~~bash
SOURCE="$PWD/.codex_runs/run_todos/<RUN>/task-2/001-production"

python3 -B /path/to/arquilo/arquilo.py tasklist resume-review \
  --todo 2 --capture-dir "$SOURCE" -- \
  tasklist run \
  --workdir . \
  --todo-file tasks.md \
  --start 2 --stop 2 \
  --max-steps 1 --max-retries 1 \
  --breakdown-policy off \
  --logs-in-workdir
~~~

Restore any **same** custom `--state-dir`, `--project-id` and
`--runtime-profile` flags used for that workspace after `tasklist run`.
If you want to avoid a separate Codex workspace-write preflight model call,
`--skip-codex-preflight` requires your explicit prior confirmation that
workspace-write behavior was already validated. Never add
`--accept-plan-changes` to sidestep a changed plan.

#### Verification and no-replay guarantee

Before the tasklist runner is started, the recovery command verifies the
original capture directory belongs to the selected task, checks
`capture.json`, `stdout.bin`, original `prompt.utf8`, task-level
`prompt.md` and `original_contract.json`, `response.txt`, and
`autobuild_summary.json`:

- Exactly one terminal `turn.completed`, no `turn.failed`.
- Exit code 0, all input/output pipes fully captured, no process stop.
- The previous AutoBuild has one production call and zero review calls,
  failed only with `codex_stream_error`.
- Every prior stream error is a valid interim retry notice; other failures
  cause a refusal.
- The captured **actual input bytes**, task prompt/contract and final
  assistant answer agree.
- The first request in the new run must be the *identical* original task
  prompt and the same workspace and task ID; otherwise recovery refuses
  the request **without replaying production**.

For the matching first production invocation the completed result is supplied
from the validated archive; the Codex production subprocess is **not started
again**. Then an **entirely new, independent read-only review** runs using the
normal original-contract, model, tasklist and controller gates. A review PASS
can lead to DONE; a review FAIL leaves the task open. The one-task bounds
and breakdown=off prevent automatic fix or child-task expansion. No next
task runs due to `--stop`.

The regular AutoBuild call-budget bookkeeping may reserve one synthetic
production attempt even though it does not contact the model. Existing
budgets and controller state are not cleared, reset or guessed. The original
archive remains unchanged; new review logs are written to a new run.

**Fail closed**: If the source evidence is incomplete, different, untrusted,
or the task/prompt does not match, this mode refuses continuation.
It must never be used to mark partially completed production as approved.

Run offline regressions without credentials or model calls:

~~~bash
python3 -B -m unittest discover -s tests -v
~~~

<a id="troubleshooting-reference"></a>
## 25. Troubleshooting by symptom

Keep the original run evidence. Do not bypass a failing review, enable full
access, weaken ACLs globally, or blindly mark tasks DONE to get past an error.
The conditional owner recovery below applies only to an already passed review.

### Decide fails before a process starts

`decision_setup_failed` with zero started Exec processes indicates a preparation
failure. Inspect the reported attempt's `call.json`, specifically
`result.execution.failure.message`. This is not by itself proof of an invalid
Codex login. The start counter counts processes, not billable model requests.

An accidentally initialized Git repository at the OS user home can make the
normal temporary directory inherit a Git context. The Decide path intentionally
rejects that situation. Inspect the home `.git` before removing or renaming it;
never delete legitimate repository history blindly. Use a private, user-owned
temporary root outside such a repository when intentional isolation requires it.
Do not use a world-writable shared directory for sensitive workloads.

### A diagnostic `error` item aborts Decide

The runtime distinguishes a nonfatal item notification from a top-level fatal
error (apart from the narrow provisional reconnect notice described below). The public code includes the fix allowing diagnostic items without enabling the historical unstable host-skill-discovery setting.
Unknown items and tool execution events remain rejected for Decide.

### The file was created, but the review stopped

The review may have found a real blocker even when production exited normally.
Read the structured review before retrying. The inline-contract fix means that
the reviewer no longer has to open an archived `review_contract_*.json` through
PowerShell. Actual output files still need to be readable and verifiable.
A missing artifact or access failure is not automatically a semantic task defect.

### Review passed, but an edited task plan blocks DONE

In guarded-plan mode, editing the task file during a run (even inserting only
`***STOP***` before the next task) can fail the post-review integrity check.
A successful AutoBuild review is not yet controller acceptance: the task stays
open and the runner stops with `unapproved_plan_mutation`.

For a successfully completed ordinary task with a validated PASS review, the
runner now explicitly reports `Review für ToDo <id>: PASS` followed by conditional
manual-DONE guidance. The same text is retained in the terminal execution error
in `run.json` / `run_log.json`. It does not turn the run into a success, remove a
STOP, change a task status, or repeat production/review. No such hint is inferred
from a prose PASS, missing/invalid/failed reviews, technical execution failures,
unsafe/unreadable paths, breakdowns, parent-review subtasks or worker copies.

After the runner exits, compare the task file with the captured plan and inspect
the review and outputs. Only if your intended STOP/control edit is the sole plan
change and the reviewed assignment, requirements, context and outputs are
unchanged may you deliberately mark that task `***DONE***`. ARQUILO has not
verified those recovery conditions. Preserve the review's stated scope and any
non-blocking observations; this is owner adoption, not new independent evidence.

On the next run, retain the same workspace, task-file path and state root and
use `--accept-plan-changes` once to adopt the deliberately checked status/plan.
A STOP before the next task still pauses scheduling: remove it deliberately only
when ready to continue. Any separate `process_stop` must be inspected separately.
Do not delete controller state, edit its journal or use broad mutable-plan mode
merely to silence this error. Existing run logs are not rewritten retroactively.

### Native Windows encoding and access failures

Use explicit UTF-8 when creating text files. Mojibake in a terminal can originate
in file encoding, the shell's encoding, or its display; inspect the actual file
bytes before attributing it to the model. Do not globally change encodings or
permissions merely on the basis of a rendered console excerpt.

The native Codex sandbox must be set up for the current user. A Python unit test
on Linux, a successful login, and a WSL run do not prove native Windows sandbox
correctness. Follow the current vendor setup guidance linked in the quick start.

#### Windows: sandbox setup helper is reported as `program not found`

If a shell/file tool fails with `orchestrator_helper_launch_failed` and names
`codex-windows-sandbox-setup.exe` (or a versioned/helper-prefixed equivalent),
the model is not the cause: Codex could not start the Windows sandbox helper.

This is a known failure mode of some standalone Windows launcher layouts. In
particular, `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` can exist
and pass `codex --version` while the matching `codex-resources` live only in a
versioned standalone release. Do not copy a helper from another Codex version
and do not bypass the sandbox.

Inspect the launcher and installed releases first:

```powershell
(Get-Command codex).Source
Get-ChildItem "$HOME\.codex\packages\standalone\releases" -Directory
Get-ChildItem "$HOME\.codex\packages\standalone\releases" -Recurse `
  -Filter codex-windows-sandbox-setup.exe -ErrorAction SilentlyContinue
```

For diagnosis, invoke the `bin\codex.exe` from the matching complete versioned
release directly and repeat a tiny `exec --sandbox workspace-write` test. If
that works, repair/reinstall the public launcher or put that matching release's
`bin` directory first in the current process PATH. Do not silently select a
different release. Upstream examples include openai/codex issues #30829, #32359
and #38039.

### Find a run or failed Codex process

With `--project-id`, start with `<state-root>/<project-id>/latest-run.txt`,
then inspect that run's `run.json` and `overview.log`. The failure output names
its exact `stderr_file` / `capture_directory` when available. Each capture has
`capture.json`, `stdout.bin` and `stderr.bin` under a short numbered phase folder,
not an additional `.jsonl.calls/call-<uuid>` chain. `CAPTURE:` in the Pretty log
also gives the actual path. [PowerShell walkthrough](#logs-reference).

A run marked `preparing`/`running` without `finished_at` may have been killed;
do not count it as completed. The latest pointer means latest **started**, not
latest successful. Old archive locations and contents stay unchanged.

### Extract a small diagnostic locally

In PowerShell, from the failing workspace:

```powershell
$runDir = Read-Host "Paste the controller run directory printed by ARQUILO"
$raw = Get-ChildItem -LiteralPath $runDir -Recurse -Filter autobuild_raw.jsonl |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $raw) { throw 'No AutoBuild log found.' }
Get-Content -LiteralPath $raw.FullName -Encoding UTF8 | ForEach-Object {
    try { $e = $_ | ConvertFrom-Json } catch { return }
    if ($e.item.type -eq 'command_execution' -and $e.item.status -eq 'failed') {
        [PSCustomObject]@{ Command=$e.item.command; ExitCode=$e.item.exit_code; Output=$e.item.aggregated_output }
    }
} | Format-List
```

Review and redact this output before sharing. Pretty/JSONL views may redact
prompt fragments; the captured `stdout.bin`, `stderr.bin` and `prompt.utf8` are
sensitive raw evidence, not safe public attachments. Never upload a complete
`.codex_runs` directory or any Codex `auth.json`.

### Reconnect notices, stops and genuine failures

A pre-terminal top-level event with **exactly** `type="error"` and a string
`message` matching the following text is a provisional diagnostic, not a fatal
result on its own:

```text
Reconnecting... <k>/<n> (stream disconnected before completion: websocket closed by server before response.completed)
```

Only positive ASCII integers with `1 <= k <= n` are recognized; outer whitespace
is ignored for classification but retained in raw evidence. Even `5/5` describes
an attempt, not successful reconnection or definitive failure. Additional error
fields, another message (including `error decoding response body`), and any such
notice after `turn.completed` or `turn.failed` remain fatal.

| End of this invocation | Result |
| --- | --- |
| Recognized notice, final answer, `turn.completed`, natural process exit 0 | Technical success; the normal independent review/acceptance still follows |
| Recognized notice, observed stop, evidenced controller termination | Cancelled/6; no DONE and no automatic retry |
| Terminal failure, I/O/archive/cleanup failure, timeout, or natural nonzero process exit | Failed/7, even when a stop was also observed |

An invalid review keeps its existing exit 8. A raw subprocess exit, such as
POSIX SIGTERM/-15, stays separate from the ARQUILO exit. Stop does not forgive
an archive failure or a process that naturally failed before the sentinel.
Only an actual stdin pipe break during already initiated controller shutdown
is treated as an expected abort; its diagnostic remains in the capture.

Inspect `stream_diagnostics` in the capture and returned `execution_attempts`.
These retain original notices with `event_index`, not a claim of recovery. A
capture uses `cancellation_reason`; summaries, task logs and both run-log filenames
use `process_stop_details` plus `process_stop_triggered`. A missing legacy reason
is explicitly labeled unavailable, never replaced with a technical error message.
For a pure stop, historical task/run statuses remain `incomplete`/`stopped` and
additive `termination_status` is `cancelled`. A failure with stop retains failed
status and both the real error and stop reason.

The returned `terminal_attempt` identifies the actual terminal captured invocation
by phase, index and capture directory. Do **not** take the last array element of
`execution_attempts`: a stopped correction can precede an older review in that
historically grouped array. The console prints the exact capture/stderr and
other diagnostic paths once per attempt; a different attempt is shown again.
Original archives are not rewritten. No task is retrospectively accepted.

Write a required handoff/report before creating `process_stop`: once the marker
is observed, the remaining commands in that process may be terminated.

### Resuming after `process_stop`

Correct the documented cause first. Preserve the marker as a timestamped file
outside the active marker path, then rerun consciously. A fresh test is often
best done in a new disposable workspace rather than by deleting evidence.

### Direct Codex works, but Decide fails (provider/model/proxy)

If you are still running ARQUILO 0.3.x or older, update to a current release. The pre-0.4 Decide path forced a provider, ignored user configuration and filtered provider/proxy/CA environment variables. Merely removing the model name in 0.3.1 did not fix these differences. Current Decide
inherits trusted host configuration without bulk feature overrides. Start it
from the same approved shell environment as the working CLI. Set `--profile`
only when a saved named profile is actually needed. No endpoint or model is
selected automatically. [Configuration details](#decide-reference).

`codex_decision_cli_failed` means required Exec flags could not be confirmed
before the model started. The Doctor no longer requires `features list` or
new experimental flags. `--model`/`--profile` support is needed only when those
selectors are used. Review the bounded diagnostics, not a complete config dump.

### Decide rejected a tool event under the configured provider

The prompt asks for a decision from supplied evidence only, and ARQUILO rejects
tool/unknown events. In the current configuration-inheritance model (introduced in 0.4.0), the host's configured integrations remain trusted;
the event gate cannot prevent or undo their execution. Inspect local Codex
configuration and use an IT-approved restricted profile where appropriate.
Do not bypass the sandbox or change a failed review to PASS.

### Controller integrity failures

Do not delete state or automatically accept modified plans. See
[controller safety and recovery](technical-guide.en.md#controller-reference) for the controller state roots,
explicit owner adoption, Git selection and no-overwrite dry-run reports.

### Old call budget blocks continuation

Use the same workspace, task path and state root. The current default
`--max-calls 0` adopts unlimited even for older exhausted budgets, preserving
their counters. Do not delete controller state. If a separate `process_stop`
file already exists, inspect its cause and partial work before deliberately
removing it. It is never automatically ignored. Human task edits may need
`--accept-plan-changes` for the next strict run.

For a generator task that writes the rest of the same task file, use
`--allow-todo-modifications --stop 2` for the planning phase. See
[operator controls](#operator-controls-reference).

### Interrupted streams and review-only recovery

A well-formed Codex `Reconnecting... n/m (stream disconnected before completion: ...)` is an interim diagnostic, not a terminal result. It remains visible in logs. Real `turn.failed`, unknown errors, missing `turn.completed` or nonzero exits still stop the run. For a known historical case where production completed with Codex exit 0 but an older controller stopped before mandatory review, see [guarded review-only recovery](#recovery-reference). Recovery is explicit, single-task, proof-checked and **does not bypass review or replay production**.

<a id="migration-reference"></a>
## 26. Migrate older invocations

Use `arquilo_doctor.py` or `arquilo.py doctor` for diagnostics. `run_todos.py`,
`autobuild.py`, `decide.py` and Markdown task syntax are retained.
Runner control data/logs are outside the workspace and Git requires explicit file selection; this behavior was introduced in 0.3.0. See [controller safety](technical-guide.en.md#controller-reference).
New configuration uses `ARQUILO_*` environment variables; newly emitted JSON
schema identifiers use `arquilo.*`. The naming change does not grant additional
sandbox, tool or network permissions and does not bypass review.

Supported predecessor inputs remain readable with a deprecation warning. The
[naming history and compatibility matrix](https://github.com/abernert/arquilo/blob/integration/hardening-guides-091-20261024/docs/compatibility.md) lists the old
spellings and the migration requirements for consumers of JSON output. Old
release archives and previous run logs are historical records and are not rewritten.

Use a new installation folder and a disposable workspace for the first run.
Preserve old logs and do not merge an extracted ZIP into a live installation.
Verify capabilities, perform a dry run, then explicitly opt into the doctor
functional test and a real task. See [quick start](user-guide.en.md#preview).

Removed predecessor options remain rejected rather than silently ignored; see
[historical migration notes](https://github.com/abernert/arquilo/blob/integration/hardening-guides-091-20261024/documents/HISTORICAL_MIGRATION.md). There are no optional
add-on groups in the public runtime package.


<a id="recipes"></a>
## 27. Choose the right procedure

| Goal | Procedure |
| --- | --- |
| Install and complete a first reviewed task | [User Guide: installation](user-guide.en.md#installation) and [first run](user-guide.en.md#first-run). |
| Select a different model or reasoning effort | [User Guide: configuration](user-guide.en.md#options); [complete runner options](#cli-run). |
| Use a reusable local template | `--todo-template` in [runner options](#cli-run); [task format](#task-format-reference). |
| Generate a plan and ask a human to approve it | [Planning pause](#planning) and [restart runbook](#operator-controls-reference). |
| Use different profiles or MCPs for different tasks | [Configuration layers](#configuration), [resources](#resources) and [directives](#task-directive-reference). |
| Run independent tasks concurrently and wait for their results | [Parallel workspaces](#parallel) and [WAIT reference](#task-directive-reference). |
| Review an already completed, narrowly qualified production attempt | [Review-only recovery](#recovery-reference), not a generic skip-review switch. |
| Inspect errors without sharing private archives | [Log reference](#logs-reference) and [troubleshooting](#troubleshooting-reference). |
| Publish only reviewed files | [Git workflow and limitations](#git); keep Git off when ordinary review must not depend on snapshot capacity. |
| Package or extend ARQUILO | [Technical Guide](technical-guide.en.md#test-reference). |
