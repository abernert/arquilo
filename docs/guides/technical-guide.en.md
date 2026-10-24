# ARQUILO Technical / Architecture Guide

**English · runtime 0.9.1 · code baseline `48331c7210d63787c578bf925ade41da9eb806a8`**
[Guide index](README.md) · [Operator Guide](operator-guide.en.md) · [Architecture summary](../architecture.md)

> **Unreleased integration checkout, not the published v0.9.1 ZIP.** The runtime version string remains 0.9.1. This edition combines the state-I/O repairs from PR #35, Git-integrity repairs from PR #36 and handbooks from PR #33. See [scope, source commits and remaining limits](../integration-status.md). No merge to `main`, new tag or release is implied.

This guide explains the implementation and its trust boundaries for developers and technically advanced integrators. It is a map for reading and changing the code, not a claim that every desired hardening mechanism has been implemented. The code baseline is the unreleased PR #36 commit, which includes PR #35; the handbooks originate in PR #33. The runtime version remains 0.9.1 for this integration only; this does not replace its published asset.

## Contents

[System boundary](#system) · [Module map](#modules) · [Task lifecycle](#lifecycle) · [Review authority](#review) · [Plan persistence](#persistence) · [Filesystem and identity](#filesystem) · [Budgets](#budgets) · [Worker protocol](#workers) · [Transport and cancellation](#transport) · [Resources and prompts](#resources) · [Git](#git) · [Evidence](#evidence) · [Interfaces](#interfaces) · [Testing](#testing) · [Extension rules](#extensions)

<a id="system"></a>
## 1. System boundary and architectural intent

ARQUILO is a synchronous Python controller around external Codex Exec processes. Its runtime uses the Python standard library. It is neither a model server nor an OS sandbox, and it does not directly replace Codex authentication, provider routing or native tool implementations.

```text
Operator
  |
  v
arquilo.py -> task-list controller -> AutoBuild -> Codex transport -> Codex CLI
                  |                     |                              |
                  |                     +-> separate review/fix        +-> provider/tools
                  |
                  +-> private plan, identities, budgets, worker IPC
                  +-> diagnostic logs and visible task reports
                  +-> optional explicit Git integration
```

The producer's workspace is mutable. The controller must not accept model-edited status or public summaries as new authority merely because their format looks plausible. Captured original requirements, mandatory review and deterministic acceptance checks exist to separate proposed work from authorized completion.

An external state directory is a logical trust boundary only when actual host permissions and execution confinement keep workers from writing it. “Outside the workspace” does not defeat another hostile process with the same operating-system credentials. Native Codex integrations and configured writable roots remain relevant. The [security model](../../SECURITY.md) must be read alongside this guide.

<a id="modules"></a>
## 2. Module ownership

| Responsibility | Principal implementation | What to inspect there |
| --- | --- | --- |
| Public command routing | [arquilo.py](../../arquilo.py) | Dispatch of tasklist, doctor, capabilities, package and compatibility aliases. |
| Task-list orchestration | [run_todos.py](../../run_todos.py) | Selection, scope, WAIT/STOP, child scheduling, parent acceptance, worker collection and final state changes. |
| Task grammar/context | `todo_syntax.py`, `todo_lint.py`, `todo_context.py`, `todo_ids.py`, `todo_template.py` | Visible task headers, directives, original preamble, IDs and no-overwrite initialization. |
| Task execution loop | [autobuild.py](../../autobuild.py) | Production, review, corrections, decisions and summary generation. |
| Call/result boundary | [autobuild_contract.py](../../autobuild_contract.py), `runtime_contracts.py`, `runtime_failure.py` | Validated options/context, serialized worker calls, consistent results and failure precedence. |
| Review semantics | [review_contract.py](../../review_contract.py), `review_confidence.py`, `review_resume.py` | Parser-owned provenance, blockers, advisory confidence and narrow archived-production recovery. |
| Plan authority/identity | [controller_state.py](../../controller_state.py) | Persistent accepted text, lock ownership, approved status transitions, identity and alias refusal. |
| Invocation accounting | [execution_budget.py](../../execution_budget.py) | Monotonic reservations, shared root counters and owner limit changes. |
| Safe local I/O | [safe_io.py](../../safe_io.py), `runtime_files.py` | Anchored/leased traversal, link/type checks, atomic creation/replacement and path validation. |
| Host process selection | [host_launcher.py](../../host_launcher.py), `codex_launcher.py`, `codex_policy.py` | Trusted external executables, sanitized PATH, native/npm launch forms and policy construction. |
| Process transport | [codex_transport.py](../../codex_transport.py), `process_tree.py` | Byte streams, event collection, terminal conditions, cancellation and cleanup. |
| Restricted decisions | `decide.py`, `decision_request.py`, `decision_exec.py`, `decision_response.py`, `decision_archive.py` | Input/context capture, constrained options, execution policy, response validation and archives. |
| Resources/configuration | [task_resources.py](../../task_resources.py), `mcp_selection.py`, `runtime_config.py`, `runtime_profile.py`, `prompt_config.py` | Operator ceilings, skill snapshots, native MCP overrides, profiles and immutable prompt catalogs. |
| Logs and publication | [project_logs.py](../../project_logs.py), `runtime_logging.py`, [reviewed_git.py](../../reviewed_git.py), [git_snapshot.py](../../git_snapshot.py) | Readable log namespace, run/attempt records and explicitly selected Git outputs. |
| Packaging | `scripts/stage_lean.py`, `scripts/check_release.py`, `scripts/build_runtime_zip.py` | Allowlisted runtime distribution, license/version/link checks and reproducible ZIP generation. |

Several modules retain dictionaries and compatibility structures alongside immutable dataclasses. Do not assume every internal object is an immutable, complete authority record. Consult the validator at each boundary.

<a id="lifecycle"></a>
## 3. Trace a task through the runtime

### Setup and selection

The CLI delegates to the existing runner rather than reinterpreting run options. The runner resolves paths, parses and validates the current plan, applies operator choices and prepares controller state. Template initialization is an explicit earlier preparation step; dry-run can create a working list and preview while avoiding model execution and controller-state creation.

The runner checks physical stop state before executable preflights. Profile preflight is trusted host code; the Codex workspace-write probe is separate and can be a model operation. An existing stop prevents a new probe. Whole-plan validation prevents later malformed directives from being silently ignored until a task is reached.

Selection honors the owner's `--start`/`--stop` range. A Markdown STOP barrier is considered before status/depth filtering within that range, so a DONE or too-deep task cannot hide a barrier from later work. WAIT evaluates defined dependency state; it is not an independent background scheduler.

### Capture, execute and review

The controller captures the original task and effective context before granting the producer access to mutable files. The task/preamble evidence used for copied worker requests must match that accepted source. AutoBuild executes production under the selected workspace-write policy, then performs a separate read-only review against the captured original request.

```text
Accepted original task
    -> production transport
       -> technical failure/stop: retain evidence; no completion
       -> successful production
          -> separate review
             -> invalid/missing review: failure; no completion
             -> valid FAIL: targeted correction, breakdown handling or stop
             -> valid PASS: final controller checks
                -> accepted plan transition to DONE
```

This is a conceptual flow, not a list of literal persisted status names. A successfully executed reviewer can legitimately reject its subject. Separate this from a reviewer process failure. A fixed artifact must receive another review; a previous pass is not reusable authorization for arbitrary new content.

### Decomposition and final acceptance

When the supported policy calls for decomposition, the controller validates insertion of open direct children and preserves the parent contract. Children share their numeric root's budget. Once required children are DONE, parent acceptance remains a separate review against the original request. OBSOLETE is not interchangeable with completed work.

Before recording completion, the runner checks stop state, the validated execution/review result and the current accepted plan revision. Git-enabled results must also carry an accepted review candidate. A late stop cannot turn into success through delayed collection of a completed worker. Only the authorized task command token may change for an ordinary DONE transition. Artifacts and diagnostics may exist even when final acceptance fails.

<a id="review"></a>
## 4. Review authority and result validation

`review_contract.py` owns detection of the actual incoming review format. A JSON object cannot declare itself legacy prose to select a weaker completion path. Normalized stored classifications have separate compatibility handling; callers should not confuse them with raw reviewer output.

The deterministic veto is simple: an explicit FAIL or blocking issue cannot be converted into COMPLETE by a later semantic decision. Legacy prose still requires its supported explicit Decide step, but that step is not allowed to override a blocker. Present raw findings cannot contradict a supposedly successful normalized result.

`autobuild_contract.validate_result()` checks boolean/integer types, exit/status/completed consistency, review requirements, matching error payloads, stop metadata, budget snapshots and successful completion evidence. At the Python-worker boundary it also compares the process exit with the reported result. Malformed results become technical failures; they are not repaired into success from their final prose.

`runtime_contracts.py` provides typed execution, review and decision results. A valid review FAIL means the review operation succeeded technically but its subject is unacceptable. Confidence fields are advisory: they do not change the verdict rule and are not calibrated probabilities.

These controls prevent contradictory acceptance, not all false model judgments. A plausible but mistaken PASS can still be wrong. Where artifacts permit deterministic checks, add those checks and independently validate the test's meaning. The [review reference](../../documents/REVIEW_CORE.md) is the detailed response contract.

<a id="persistence"></a>
## 5. Plan persistence, restart and owner overrides

`PlanAuthority` holds accepted plan text in a private `plan.json` with a plan-specific lock. At first use, existing owner-supplied statuses establish a baseline; initial DONE is not proof of a past ARQUILO review. Subsequent strict runs compare the live list with persistent accepted text and refuse unauthorized requirement/status/deletion/reordering changes.

An approved transition records its pending target, writes the authorized plan bytes and finalizes the journal. On restart, recovery is limited to the recorded before/after states. A third unrelated value is rejected rather than silently adopted. Completion is based on the accepted snapshot, not on an unchecked reread that can import another writer's DONE status.

Child adoption likewise persists the exact bytes that passed validation. Original contracts are captured from accepted task evidence. These mechanisms do not create a general transaction across the entire filesystem or make all recovery corruption cases solved.

`--accept-plan-changes` is an explicit owner baseline-adoption action. It archives the previous plan and retains budgets; it is not automatic error recovery. `--allow-todo-modifications` is a separate per-invocation opt-in to observe and adopt valid mutable plan changes. Original current-task review requirements remain captured, but future scheduling can intentionally change. Mutation records identify this as observation rather than independent verification.

Keep state and path identities during upgrades. Do not change key calculation to an inode or content hash: atomic file replacement changes an inode, and an ordinary status transition changes the content. Either could accidentally create fresh budgets. [Controller-state guidance](../controller-safety.md)

<a id="filesystem"></a>
## 6. Filesystem protection and physical identity

`safe_io` validates ordinary single-link files and rejects linked/reparse/hardlinked/special control inputs at its protected boundaries. POSIX directory descriptors anchor parent traversal; Windows directory handles prevent parent deletion/renaming during protected operations. Atomic writes stage a complete snapshot and replace the destination rather than falling back to truncation through an unsafe path. Failed replacement retains a complete pending recovery file.

Exclusive creation is different from replacement. Template initialization publishes only if the target is still absent; an existing or racing destination wins. Keep that distinction when adding writers. A prior `exists()` check followed by a normal write is not equivalent.

State allocation retains existing key/counter identities while registering physical plan identity under an allocation lock. It rejects alternate case/Unicode spellings that would create a second state, and physical workspace/state overlap. Legacy journals or private identity metadata can establish that an alias is already allocated. A metadata hint is not a substitute for a missing authoritative journal or permission to restore/reset a counter.

Old standalone budget-only stores without recoverable identity still require original paths and owner inspection. Identity checks should not be described as universal recovery for all historical layouts.

### State metadata and permanent shared locks (#32 and #34)

This integration includes PR #35. Advisory legacy identity reads of `projects.json`, `project.json`, `latest-run.txt` and `run.json` permit Windows read/delete sharing, **never write sharing**. A reader keeps its old opened file object while a new complete object is published. Ordinary readers remain strict, as do no-follow/single-link checks and parent-directory leases. On Windows errors 5/32 from ordinary replacement, the implementation uses `FileRenameInfoEx` with `REPLACE_IF_EXISTS | POSIX_SEMANTICS`; unsupported operations fail closed with the pending recovery file retained. It does not use in-place overwrite or retry-until-success.

POSIX shared-lock opening first opens an existing file, otherwise creates exclusively, and reopens a competing creator's file only on `EEXIST`. These operations use the same anchored parent. Disappearance after competing creation, unsafe links and permission errors remain failures. Permanent coordination locks are not deleted. This changes neither state keys nor consumed budget. Native regressions cover both races; the original macOS kernel-level cause is not claimed proven. The published v0.9.1 ZIP does not include these repairs.

<a id="budgets"></a>
## 7. Persistent invocation budgets

The controller maps `12`, `12.1` and deeper descendants to root `12`. `CallBudget` maintains a monotonic used count and reservations under external state. It reserves before dispatch; failed launch/archive work is not refunded. Deleting a diagnostic claim cannot return a reserved call. Cross-process locking coordinates workers sharing a root.

A numeric root receives its own counter. The count is an execution-attempt bound, not token usage, money or the number of internal provider requests. Separate sandbox preflight and pure CLI metadata operations are outside this budget.

Schema v2 supports unlimited mode with `limit=0`, `remaining=null`, `unlimited=true` and a numeric `used`. Existing valid finite v1 data remains readable. Owner-selected limit changes retain usage and write their history; workers cannot change limits. A positive limit cannot be below consumed usage. The default on a resumed runner is still unlimited unless a positive value is passed again.

Do not conflate call limits with depth, correction count, timeouts or stop state. For example, raising a call limit does not erase an existing process-stop instruction. [Budget reference](../../documents/WORKFLOW_LIMITS.md)

<a id="workers"></a>
## 8. Parallel Python worker boundary

A parallel group uses real Python worker processes in separately selected subworkspaces. The parent serializes the call with `AutoBuildOptions` and `AutoBuildContext` through `call_payload()`. The worker starts through `autobuild.py --request-json ...`, decodes the allowed request shape and executes the same AutoBuild logic.

The parent chooses private request and authoritative result paths outside the model workspace. It captures worker stdout/stderr, reads the private returned bytes, validates them and checks exit consistency. A diagnostic summary may be published into visible logs, but that public file is not reread as completion authority.

Important context includes root budget location/identity, original task context, peer process-stop paths and the original launcher workspace. Retain these when extending or adapting the worker boundary; an active subworkspace alone is not the full launcher trust boundary. Parent and workers must therefore be updated together.

A valid return-only stop is propagated to peers before slow later result copying/acceptance. Malformed payloads do not get to supply trusted stop details or pointers. Equal/nested/root-equal parallel workspaces are rejected before dispatch.

This is not yet a distributed job protocol. The parent currently uses subprocess collection without a comprehensive cross-run worker supervision/deadline system. Separate directories are not security isolation against hostile code with the same credentials. Stronger root/run/task/attempt binding, resource inheritance and exactly-once dispatch need explicit design before recursive or remote orchestration.

<a id="transport"></a>
## 9. Host launchers, transport and cancellation

Host selection treats executable identity as controller authority. Codex/Git lookup uses absolute trusted directories outside the primary and active workspaces, checks physical targets and removes workspace/relative entries from child PATH. External symlinks back into model-writable workspaces are refused. Normal external user installations remain supported.

For Windows, native executables and the specifically supported standard npm `codex.cmd` layout are handled. The recognized npm shim is inspected and translated to an explicit Node executable plus Codex script instead of running arbitrary batch syntax. POSIX executable scripts can use external interpreters; a sanitized PATH prevents ordinary `env node` lookup from selecting a project-local interpreter. Trusted host installations are not made immutable against another host process.

`codex_transport` collects raw byte streams, structured events, answer text, process exit and capture completeness. A successful-looking message without terminal completion and acceptable process/capture state is not successful execution. Item-level diagnostic errors are distinct from fatal top-level events. Only recognized, well-formed pre-terminal reconnect notices are retained as nonfatal diagnostics; unknown or post-terminal errors, `turn.failed`, missing completion and genuine I/O/cleanup failures remain significant.

Stop is an independent observation. Error-plus-stop retains both facts and does not become a clean cancellation. `terminal_attempt` points to the actual relevant call even though historical attempt arrays are grouped by type.

Process groups and cleanup logic are platform-specific. Detached descendants, a continuously productive but never-ending process, worker collection and very large output streams remain reasons for broader supervision hardening. Do not document existing stall timers as a universal total deadline or process-group cleanup as proof that all descendants terminated. [Testing and stop evidence](../testing.md)

<a id="resources"></a>
## 10. Resource and prompt capture boundaries

`task_resources` resolves omitted, explicit-empty and nonempty selections distinctly. Run-level selections provide defaults/ceilings; task/child selections may narrow. `mcp_selection` inspects native configuration, applies temporary server-selection overrides and verifies the effective allowed set. Definitions, credentials and remote per-tool permissions remain native/operator responsibilities, not a complete immutable capabilities service.

`SkillCatalog` binds selected `SKILL.md` instruction snapshots and hashes. Helper scripts and references remain external files. Prompt instructions do not create authority to widen a sandbox, set controller state or skip review. Native implicit discovery is a separate mechanism.

`PromptConfig` loads complete catalogs, validates metadata/elements/placeholders and captures an immutable snapshot passed across Python workers. Both source and effective-content digests assist reproducibility. Rendering is a literal single pass, not expression evaluation. User content is not recursively rendered or translated.

Runtime profiles are JSON-based domain extensions and trusted preflights. Some prompt slots are replacements; others are additive lists/guards. Do not treat the current loader as a complete universal unknown-field-rejecting schema or treat a profile name as a permission ceiling. Keep executable invariants in code regardless of wording. [Prompt reference](../prompt-configuration.md) · [Profile API](../../RUNTIME_PROFILE_API.md)

<a id="git"></a>
## 11. Review snapshot, local commit and remote publication

`git_snapshot.py` creates the private request, captures ordinary workspace files and emits a manifest/token. `AutoBuildContext.git_review` carries the parent-created request across the private Python-worker boundary. AutoBuild captures immediately before each existing mandatory review, switches only the reviewer to the read-only copy, and returns the candidate alongside the validated result. The source workspace remains the producer/correction location.

`ReviewedGit.begin_review()` owns request identity; `accept_review()` verifies request/token, task/attempt, review round, snapshot and selected live outputs. Only the accepted candidate authorizes `commit()`. A fresh task/attempt cannot reuse it. The token is not a model-truth proof or a signed audit ledger. A private state path is not same-UID containment.

```text
Live production/correction
    -> private pre-review snapshot + run/task/attempt/round/parent binding
    -> existing read-only reviewer examines the copy
    -> validated PASS + snapshot/live-selection checks
    -> accepted candidate + final plan/stop checks
    -> task acceptance (DONE)
    -> private Git objects from verified snapshot bytes
    -> index lock + prepared HEAD/branch transaction
    -> optional pinned remote update with exact old-OID lease
```

The diagram is conceptual, not a set of persisted status enums. Local task acceptance and remote publication are distinct. Publication failure can leave a DONE task and local commit while the overall run is failed. Inspect recovery evidence before replay. There is no transaction spanning plan journal, local index/branch and remote server.

Object construction uses a private bare repository, raw blob hashing and a separate index. Mutable source filters, hooks, fsmonitor and transport configuration cannot choose different output bytes or run as publication helpers. Approved global/system host authentication/transport settings are captured before tasks and kept in memory; repository settings and subsequent URL rewrites are excluded. The real index lock and Git's prepared reference transaction protect cooperating writers. Symbolic HEAD identity matters even when two branches have equal object IDs.

Push authorization queries the actual endpoint/branch, not a local tracking ref. The new commit must be one direct child of the exact expected old OID. Transport addresses the pinned endpoint with one explicit refspec and `--force-with-lease=REF:EXPECTED_OLD_OID`; history rewriting, tag following and mirror expansion are not authorized. A remote race rejects the update. Trusted remote/server policy still applies.

The private Git path remains anchored to its private parent; native Windows uses a short relative GIT_DIR and command-scoped long-path support without modifying host configuration. History-pack transfer is bounded separately from the still-open broader supervisor work.

Serial operation, ordinary file contexts and snapshot/pack limits are deliberate restrictions. Full context inspection occurs at capture, after production; it is not a whole-workspace preflight or coherent filesystem snapshot against arbitrary external writers. The reviewer must use captured relative paths, not reach back to live files; model compliance and semantic correctness are not guaranteed. See [Git publication](../git-publication.md) and [Operator guidance](operator-guide.en.md#git).

<a id="evidence"></a>
## 12. Authority, diagnostics and recovery evidence

| Record | Role | Must not be mistaken for |
| --- | --- | --- |
| Private plan journal and pending transition | Accepted plan authority and narrowly defined recovery | A fresh baseline whenever unreadable or missing. |
| Identity and budget records | Continuity of plan identity and consumed reservations | Disposable cache or a refundable model invoice. |
| Private worker return | Input to boundary validation | A success solely because it is parseable JSON. |
| Original contract/prompt snapshot | Reproducible request evidence | A snapshot of every workspace or native configuration file. |
| Private Git review manifest/token | Exact candidate and request binding for selected output publication | Proof of model correctness, same-user isolation or remote push success. |
| Capture bytes, raw/pretty logs and public summaries | Diagnostics and execution evidence | Encrypted, immutable audit storage or trusted instructions. |
| Readable result report | Model-authored explanation and observed checks | Independent proof of correctness or authorization to publish. |

`project_logs` adds readable project/run/phase organization without relocating the authoritative plan key. Default runner logs are external. Workspace log mode is opt-in and makes those diagnostic files model-writable; private worker IPC and control records remain external.

The specialized review-only recovery validates complete archived production evidence, matching prompt/task/workspace identity and the narrow recovered-reconnect failure condition. It substitutes that matching completed production result once, then starts a fresh review. It is not a universal replay API, does not repair arbitrary archives and does not waive operator review of current artifacts. [Exact recovery requirements](../review-resume.md)

<a id="interfaces"></a>
## 13. Supported entry points versus internal APIs

For external programs prefer the CLI plus `capabilities`, which reports versioned feature contracts. The compatibility `run` alias preserves behavior but emits a migration notice. `tasklist resume-review` has its own strict scope. No invented backend, team or service selector should be inferred from an unmerged branch or design proposal.

For Python integrations, `autobuild.start()` accepts exactly one of `task`/`task_file` and one of `workdir`/`file`, with validated `AutoBuildOptions` and `AutoBuildContext`. A configuration-only example is:

```python
from autobuild_contract import AutoBuildContext, AutoBuildOptions

options = AutoBuildOptions(
    max_steps=3,
    max_calls=8,
    network_access=False,
    mcp=(),
    review_mcp=(),
    skills=(),
    prompt_config="en",
)
context = AutoBuildContext(task_source="inline")
# Passing these to autobuild.start(task=..., workdir=..., options=options,
# context=context) performs real work and may consume model usage.
```

An empty tuple is an explicit empty selection; `None` preserves omission/inheritance. Standalone AutoBuild does not provide all task-list journal/selection semantics. Internal helper functions and the current worker JSON format are not promised as a stable remote API. Pin the tested runtime and add integration tests when embedding them.

`decide.run_decision()` uses a `DecisionRequest` and `DecisionExecSettings`; options and output are validated, and unusable results have no usable choice. Legacy API credential/client configuration is not a supported way to provision Decide. A format retry is not an unrestricted semantic fallback. [Decide configuration](../decide-configuration.md)

<a id="testing"></a>
## 14. Testing, packaging and documentation maintenance

Use a full source checkout for development tests; the runtime ZIP intentionally excludes tests, CI and Git history. The basic offline commands from the repository root are:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

The ZIP builder refuses to overwrite existing outputs; choose a clean output location according to its help for repeated builds. Keep private audit inputs outside the checked source tree. Never weaken naming or packaging checks to include confidential project artifacts.

Testing has distinct layers: pure contracts/parsers, synthetic real subprocess and filesystem integration, native OS races, actual Codex against loopback fake providers, and explicitly approved live model/sandbox acceptance. Passing one layer does not establish all the others. Platform skips must remain visible. A useful security regression fails on the vulnerable baseline and passes after the fix, with a positive allowed case as well.

The normal CI covers three operating systems and three Python versions; separate CLI compatibility jobs cover their configured Codex versions. Check the run for the exact content/commit rather than an older green reference. A successful rerun is evidence of that run, not proof that an earlier intermittent failure was harmless.

The runtime package is selected by `documents/lean_package.json`. New guide files and examples must enter the allowlist and file count; repository presence alone does not ship them. `VERSION`, runtime version and citation metadata remain unchanged for this documentation-only work. Do not overwrite existing versioned release assets merely to add manuals.

The regular 0.9.1 tag workflow does not yet enforce all fifteen native gates as a general permanent policy. Future release hardening should bind the actual source commit, checks and generated artifacts. Documentation tests added with these guides check structural parity, referenced files/anchors and offline example behavior; they do not certify translation semantics or model responses. See [documentation maintenance](../documentation-maintenance.md).

<a id="extensions"></a>
## 15. Rules for future extensions

Keep backend adapters responsible for normalizing execution events, not for deciding that a task is DONE. Shared controller validators must retain authority over verdicts, budgets, accepted plans, stop state and result identity. Propagate original workspace boundaries and peer-stop context through every new execution route.

Before a remote or recursive service, define root/parent/run/task/attempt identity, idempotent request handling, inherited resource ceilings, root budgets, depth/width/concurrency limits, global stop propagation and immutable request/artifact bindings. A depth limit alone does not bound total work. A retry must not duplicate an external side effect silently.

A future team mode needs explicit member roles, shared/conflicting workspace semantics and review authority. Several agents in sibling directories are not automatically isolated, independent judges. A future GUI should present recorded state and controlled operations rather than mutating journals behind the controller.

Keep proposals separate from implemented guarantees. The [pipeline concept](../pipeline-mvp-concept.md) is a design document, not an executable schema. The existing runtime, known open findings and regression evidence are the baseline from which an extension must demonstrate compatibility.
