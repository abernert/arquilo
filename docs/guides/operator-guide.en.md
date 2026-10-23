# ARQUILO Advanced / Operator Guide

**English · runtime 0.9.1 · documentation baseline 2026-10-23**
[Guide index](README.md) · [User Guide](user-guide.en.md) · [Technical Guide](technical-guide.en.md)

This guide is for workflow authors, power users and operators. It assumes you have completed a disposable task run. It explains the existing runtime, not a future team framework. Instructions here do not close the outstanding audit findings or certify a host sandbox.

## Contents

[Operating contract](#operating-contract) · [Configuration layers](#configuration) · [Task design](#tasks) · [Resources](#resources) · [Parallel work and WAIT](#parallel) · [Breakdown](#breakdown) · [Planning pause](#planning) · [Runtime profiles](#profiles) · [Prompt catalogs](#prompts) · [Budgets and stops](#budgets) · [State and diagnosis](#state) · [Git](#git) · [Integration](#integration) · [Limitations](#limitations) · [Operating checklist](#checklist)

<a id="operating-contract"></a>
## 1. Establish the operating contract

Before a run, identify its approved inputs, allowed external effects, provider, model availability, resource ceiling, acceptance criteria and stopping conditions. Use a bounded synthetic example to validate the environment. A successful doctor check is not a substitute for a producer/reviewer run; neither proves complete sandbox enforcement.

Keep the installation, writable workspace and private controller-state root distinct. Update the controller and Python workers together. Record the ARQUILO version, Codex version and selected model/provider configuration without copying credentials into logs or reports.

Use strict plan handling unless the job explicitly involves generating a plan for later human approval. Do not enable automatic Git publication on an untrusted or concurrently changing workspace. Treat runtime-profile preflight commands and host installations as trusted code. A read-only reviewer filesystem does not make every remote tool read-only.

The canonical interface is `python3 -B arquilo.py tasklist run ...`. On native Windows substitute an installed interpreter such as `py -3.11 -B .\arquilo.py ...`; WSL uses Linux commands and paths. All relative CLI file paths are relative to the invocation directory. Task `workspace=` directives, by contrast, select subdirectories of the main workspace.

<a id="configuration"></a>
## 2. Configuration layers and precedence

| Layer | Purpose | Rule to remember |
| --- | --- | --- |
| Codex host configuration | Provider, endpoint, authentication, proxy/CA setup and native integrations | Inherited unless an explicit supported selector overrides the relevant setting. ARQUILO does not promise an alternative provider fallback. |
| Codex profile / `--agent` | Native named model/tool profile and prompt hint | Task `CFG agent` can override the run default. This is not a team definition or a general profile allowlist. |
| Run CLI / environment | Operator choices for this invocation | Rules vary by option; distinguish defaults, ceilings and permissions. |
| Task preamble and directives | Shared project instructions and next-task settings | CFG is local to the following task; one DEFAULTS block supplies supported resource defaults. |
| JSON runtime profile | Domain-specific instruction slots, guards and trusted preflight | CLI `--runtime-profile` wins over `ARQUILO_RUNTIME_PROFILE`. |
| TOML prompt catalog | Built-in ARQUILO instruction wording | Operator selects once per run; no task-controlled catalog selection. |
| Explicit skills | Captured procedure text | Instructions, not permissions or independent agents. |

For models, an explicit global `--model` wins over `ARQUILO_CODEX_MODEL`; the resulting global model wins over `CFG model`. Only without a global model does the task model apply. `--reasoning-effort` similarly precedes `ARQUILO_CODEX_REASONING_EFFORT`. Supported effort strings are not a promise that every provider/model accepts them.

A CLI MCP/skill selection is a **default and ceiling**. A descendant may narrow the set, not broaden it. Shell-network access instead requires a runner-level grant; a task can restrict an existing grant but cannot create one. These are different from a plain “last value wins” rule.

With no explicit resource selection, native Codex integrations can remain inherited. Do not interpret an omitted option as `none`. `CODEX_HOME` and the trusted process environment remain part of provider provisioning. ARQUILO does not load a workspace `.env` automatically. The [configuration reference](../../documents/CONFIGURATION.md) is the detailed option map.

<a id="tasks"></a>
## 3. Design tasks as testable contracts

Separate the requested deliverable, required checks, permissible sources and allowed uncertainty. A report may legitimately identify missing information without being blocked, provided the task's acceptance criteria allow that. Conversely, a pleasant summary cannot satisfy a requirement for a working executable or a reconciled numerical result.

Use unique numeric IDs. Children such as `2.1` belong to root `2`; independent root `3` has a separate call budget. Four-space/tab-indented code examples, fenced blocks and HTML comments are not executable tasks. Up to three leading spaces can still be executable, so do not rely on decorative indentation for safety.

`--todo-preamble auto` includes the visible preamble when present; `required` refuses a missing preamble and `off` omits that wrapper. A preamble is shared request context, not an authorization mechanism. Keep machine-readable syntax unlocalized even when task prose is German.

Keep an immutable clean template and a distinct working list. `--todo-template` copies only a missing list, including in dry-run mode; it never resets statuses or copies dependencies. A missing list with existing controller state is recovery, not permission to reinitialize. [Preamble reference](../../documents/TODO_PREAMBLE.md) · [Directive grammar](../../documents/todo_directives.md)

<a id="resources"></a>
## 4. MCP, skills and network paths

### Explicit MCP selection

A resource-controlled invocation might select `--mcp issues,docs --review-mcp docs`. The names must already exist and be enabled in trusted native Codex configuration. These are illustrative aliases, not servers installed by ARQUILO. The review set must be a subset of production. Supplying `--mcp` without `--review-mcp` defaults the review selection to none.

The adapter discovers configured direct servers, generates temporary overrides, disables unselected servers and plugin/app integrations, and verifies the effective selection. It refuses missing, disabled, unsupported or policy-denied selections instead of silently enabling or dropping them. Metadata inspection does not initialize STDIO servers, but it may query native authentication metadata.

Production resource settings do not automatically apply to every other phase: preflight does not inherit production MCPs in resource-controlled mode, and Decide is MCP-free when MCP selection is explicit. Remote credentials and tool permissions still determine what a selected server can do. Configure read-only credentials/server capabilities for review; local read-only sandboxing alone is insufficient.

Portable server aliases use letters, digits, underscores and hyphens. The first adapter supports direct STDIO and Streamable HTTP definitions; dotted aliases and plugin-bundled server selection are not supported here. Do not change native configuration concurrently with the run.

### Skills

Use `--skills procedure-name` and repeatable `--skill-dir /approved/root` to choose procedures from known roots. Each root contains skill directories with a `SKILL.md`, YAML frontmatter and a simple name. Duplicate names require disambiguation. The no-extra-dependency loader is not a general YAML configuration engine.

Without explicit roots, lookup includes the workspace `.agents/skills`, the user's `.agents/skills` and the Codex home skills directory. Explicit roots replace that lookup set. Selected instruction text and its hashes are captured for production, review and corrections. Referenced scripts/assets are **not** snapshotted or automatically run at binding time. Keep them stable and trusted. `--skills none` adds no explicit bindings, but does not disable native implicit discovery or normal file access.

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

Run this only with matching approved servers, skills and inputs. A dry run can validate syntax and bound skill text; it cannot establish remote permissions or authenticate MCP servers.

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

Mutable-plan mode is intentionally weaker: model-written DONE statuses, removed tasks or lowered future requirements can alter scheduling. The run metadata distinguishes original assignments reviewed in this run from observed, non-independently-verified mutations. Do not report every DONE in a mutable plan as verified work. [Detailed planning and metadata semantics](../operator-controls.md)

<a id="profiles"></a>
## 8. Runtime profiles and trusted preflight

A runtime profile is an operator-selected JSON document, not a Codex profile. A minimal domain review profile is:

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

Save it as a real UTF-8 file and select `--runtime-profile /absolute/path/profile.json`. No activation markers means the profile is active for the relevant text by default. With markers present, activation requires all specified strings; scope activation has its own markers. Protected markers identify blocks that relevant guards expect to remain byte-exact.

Prefer additive `autobuild_review_rules` for simple extensions. Some existing instruction slots replace a specific built-in slot rather than appending universally. Do not assume every profile contribution is additive or that arbitrary unknown fields are rejected by a completely strict schema. Inspect the [Runtime Profile API](../../RUNTIME_PROFILE_API.md) and test the actual profile.

A `preflight.command` is an ordered argument array executed as **trusted host code**, not inside the model sandbox. It supports `{python}`, `{workdir}`, `{todo_file}`, `{profile_path}` and `{profile_dir}`. Its finite timeout must be greater than 0 and at most 3600 seconds; argument repetitions, empty values and whitespace are preserved. Never insert untrusted task text into a shell command. Keep scripts and credentials outside model-writable control.

A dry run records that preflight was not executed. Startup STOP prevents a new preflight, but the current runtime does not guarantee immediate cancellation of every already-running trusted preflight. Profiles cannot directly authorize DONE or disable mandatory controller checks.

<a id="prompts"></a>
## 9. Maintain prompt catalogs deliberately

`--prompt-config default|de|en|FILE` selects a complete TOML catalog. `default` preserves the older mixed-language wording; `de` and `en` provide translated built-in instructions. The three catalogs have the same 53 elements and placeholder contracts. Python's standard `tomllib` is sufficient.

Copy a complete catalog outside the application checkout, edit that copy, give it an appropriate ID/version, and select it explicitly. A fragment is not a complete configuration. Keep protocol keys, verdict enums and placeholders intact. The renderer substitutes approved `{{name}}` placeholders once; it does not evaluate expressions or recursively interpret inserted task text.

The run captures an immutable catalog snapshot and passes it to workers. Editing the source later affects a later invocation, not the current run. Task content, skill helper files, native configuration and the whole workspace are not frozen by this feature. Snapshot archives can themselves contain sensitive instruction text.

A syntactically valid prompt can be substantively poor. Test reviewer behavior with both acceptable and unacceptable artifacts; do not infer review quality from TOML validation. A prompt change cannot legally bypass executable FAIL/blocker vetoes, but can change what the model notices. [Catalog reference](../prompt-configuration.md)

<a id="budgets"></a>
## 10. Budgets, deadlines and stops are different controls

`--max-calls N` reserves execution attempts per numeric root tree. Production, fixes, reviews, breakdown and Decide share that root's persistent counter; an independent root has its own. Reservations survive failed starts and missing diagnostic claims. CLI metadata queries and the separate sandbox preflight are outside the counter.

Default `0` is unlimited. On continuation, the runner applies the chosen limit to existing budgets, preserving consumption; omitting the option can therefore remove an earlier finite ceiling. Positive limits cannot be lower than already consumed usage. A new timestamp or readable project ID is not a fresh budget. Changing the state root to avoid exhaustion destroys the intended continuity.

Per-call stall/cleanup timeouts are not a global deadline. Existing AutoBuild environment controls include `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS`, `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` and `ARQUILO_CODEX_KILL_GRACE_SECONDS`. They have different purposes and do not promise that an actively emitting process finishes in bounded total time. Do not set arbitrary very short values merely to make a test pass. The comprehensive supervisor/output-quota work remains open.

Use `--stop ID` for a planned selected boundary, a prearranged `***STOP***` immediately before a task for a list barrier, and `process_stop` for a cooperative run stop. An observed sentinel is latched for the current run even if removed later. Empty, unsafe or unreadable sentinel contents do not cancel the stop signal. `controller-only` is an instruction/control convention about who requests stop; it does not make the model physically incapable of writing a file.

A genuine error plus a stop remains an error with stop metadata, not a clean cancellation. Existing partial artifacts are retained for inspection. Read [workflow limits](../../documents/WORKFLOW_LIMITS.md) before integrating exit codes into automation.

<a id="state"></a>
## 11. State, log layout and diagnosis

Keep the authoritative state outside and separate from the workspace. Preserve paths, ownership and private permissions. `--state-dir` selects a trusted local root; it is not a cache you may delete after each run. The 0.9.1 identity checks reject alternate spellings that would split state/budgets and physical overlap through aliases.

A named project groups logs, while plan-specific directories retain authority. `run.json`, `run_log.json`, `overview.log`, task logs and numbered phase captures help locate a failure. Prefer the recorded error/capture path to a guessed directory suffix. `terminal_attempt` identifies the actual terminal call; the historical `execution_attempts` array is grouped by call type, not a chronological event list.

`--logs-in-workdir` moves diagnostic logs into the workspace but not plan journals, budgets, breakdown state or private worker request/results. Public summaries are not control input. A hard kill can leave nonterminal logs; absence of a failure message is not proof of successful completion. Use run identity, exit status, review validity and actual artifacts together.

For diagnosis, preserve the original error, exact versions and invocation without secrets. Distinguish technical failure, invalid review, domain FAIL, deliberate stop, unmet WAIT and integrity refusal. Inspect side effects before replay. Ordinary restart may reexecute an open task; the narrow [review-only recovery](../review-resume.md) path has stronger, specific prerequisites.

Raw archives are not encrypted, append-only evidence stores or sanitized support bundles. Share a reviewed minimal diagnostic extract, not the whole state root. [Project logs](../project-logs.md) · [Controller safety](../controller-safety.md)

<a id="git"></a>
## 12. Automatic Git: current behavior and open boundary

Automatic Git is off by default. `--git` requires repeated literal `--git-path FILE` choices; it does not sweep the worktree with `git add -A`. `--git-push` is a separate publication opt-in. Selected files must initially be clean or absent; unrelated staged/unstaged files are not meant to be included. Use the Git worktree root and an ordinary feature branch.

A syntax illustration is `--git --git-path tasks.md --git-path summary.md --git-path todo_result_1.md`. This is not a recommendation to enable automatic publication for the tutorials. Internal state/log paths and `process_stop` cannot be selected.

The implementation uses a separate index, hashes selected file contents and creates a commit with Git plumbing. It checks branch/index state and records the configured push destination. Automatic pushes disable tag following. However, **0.9.1 does not yet bind the review to an immutable candidate captured before review**, and the remote/history authorization race remains open. Selected filenames do not prove that the bytes subsequently committed were those the reviewer inspected.

For untrusted or concurrently changing workspaces, leave both automatic commit and push disabled. Review a stable diff and publish through a separately controlled human workflow. A failed automatic push may leave a local commit even though the run reports failure; task DONE does not automatically replay the Git phase on restart. Inspect both local and remote history before taking recovery action. Never force a branch or move an existing tag to hide a mismatch.

[Git behavior and caveats](../controller-safety.md#explicit-git-selection-and-publication)

<a id="integration"></a>
## 13. Calling ARQUILO from another process

Prefer the public CLI and `capabilities` output for an external launcher. Use explicit working directories, argument arrays rather than interpolated shell strings, finite limits and captured exit status. Keep stdout and stderr separate because compatibility notices can appear on stderr. The old `run` command is an alias; new integrations should use `tasklist run`.

Check declared feature contract versions rather than searching source filenames for guessed capabilities. The presence of a design document does not create a command. Private worker payloads and `TodoRunner` internals are not a promised stable remote-service API. An external scheduler should record the command, run identity and outcome and avoid blind whole-task retries after possible side effects.

Running ARQUILO as a daemon, serving it over MCP, recursive suborders, team configuration and alternative backend selection require separate implemented contracts. They are not enabled by passing an invented switch. For internal extension boundaries read the [Technical Guide](technical-guide.en.md).

<a id="limitations"></a>
## 14. Known limitations of the documented baseline

| Area | Operator implication |
| --- | --- |
| Windows project registry concurrency | [Issue #32](https://github.com/abernert/arquilo/issues/32) records intermittent access-denied replacement of `projects.json`. A successful rerun is not a fix. Preserve recovery evidence and avoid overlapping registrations until the cause is repaired. |
| Review-to-Git binding | Do not equate path selection or a successful commit with a byte-exact reviewed publication. |
| Process supervision | Detached descendants, full-run deadlines, output quotas and active preflight cancellation are not comprehensively solved. |
| Legacy state | Old budget-only stores without recoverable identity still need original paths and manual inspection. Historical invalid DONE values are not automatically repaired. |
| Configuration and resources | Trusted native configuration, profile definitions and skill helper files are not a fully immutable capability snapshot. Profile names are not themselves a permissions ceiling. |
| Evidence and quality | Archives are not tamper-proof or automatically redacted. A formal model PASS is not an independent truth oracle. |
| Release process | The baseline regular tag workflow has a single-platform release job; the one-time 0.9.1 publisher's full gate is not a permanent general release mechanism. |

These limitations are separate from the foundational control fixes already implemented. See [Security](../../SECURITY.md), [controller safety](../controller-safety.md) and the source-linked boundaries in the Technical Guide. This documentation-only work does not repair these remaining issues.

<a id="checklist"></a>
## 15. A repeatable operating checklist

Before starting, verify paths, host tooling, provider approval, input classification, explicit resource ceilings, finite limits, stable configuration and observable acceptance criteria. Preview the actual plan, not just a template. Record which side effects require human approval outside ARQUILO.

During execution, follow the printed run path and actual terminal attempt. Use a cooperative stop rather than live plan surgery. Do not edit the index, remote configuration, prompt sources or skill helper assets concurrently.

Before continuing or publishing, inspect partial files and external effects, explain the previous failure, preserve authority/budgets, rerun the appropriate acceptance checks and review the resulting diff. Separate “controller accepted the result” from “the organization authorizes its use.”
