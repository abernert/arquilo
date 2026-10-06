# Pipeline MVP: contracts, revisions and controlled production

**Status: design proposal, not an implemented interface.** The accompanying CLI
change implements `arquilo tasklist run` and a compatibility notice for `arquilo
run` only. `arquilo pipeline ...`, the YAML below and the lifecycle rules in this
paper are proposed. They are not capabilities of the current task runner.

## 1. Goal and boundary

Execute a local production order from a readable, versioned recipe. A stage uses
one of exactly two executors: an existing ARQUILO task-list run or an explicitly
selected script. The outer controller owns dependencies, accepted artifact
revisions, checks, approvals and recovery. The existing task runner continues to
own production, mandatory review, bounded correction and task completion inside
a task-list stage. Do not implement another coding harness or duplicate that loop.

A production order binds a recipe version, parameters, imported inputs and an
external controller-state directory to an order ID. A process invocation may
stop and later resume the same order. An order is not an issue-tracker service,
a queue, a daemon or a distributed scheduler.

The first deliverable should execute a meaningful PEM-style pilot, not claim to
replace the complete PEM application. Domain templates, validators and algorithms
remain in the application repository. No private source material, real prompts,
credentials or PEM implementation files need to enter the public ARQUILO repo.

## 2. Minimum useful increment

| Area | First increment |
| --- | --- |
| Recipe | Validated YAML; explicit stage IDs, purposes, executors and artifact bindings |
| Execution | Task-list runner and argv-based scripts; no shell expression language |
| Flow | Fixed dependency graph, independent parallel branches, explicit fan-in |
| Contracts | Required files/directories, scoped checks, optional schema validators supplied as scripts |
| Workspaces | Isolated stage attempts with explicit input snapshots and candidate outputs |
| Quality | Existing task review plus controller-owned artifact acceptance checks |
| Revisions | Later stages may amend declared artifacts; history and current validity are separate |
| Human decisions | Persistent approval at a declared boundary; no waiting LLM process |
| Recovery | Per-attempt receipts, preserved evidence, restart/resume and stale-input detection |
| Context | Task-list preamble; optional stage-specific AGENTS.md; recorded effective context |
| Tools | Operator-owned execution profiles, including explicit MCP tool availability |
| Observation | Order status, reasons for blocked work, change-impact report, process journal |

Do not include dynamic swarms, a connector catalog, a general expression engine,
a new provider harness, a web editor or distributed high availability. A shared
writable workspace is not needed for the first pilot. Read access to a project
and write access to a stage area are separate choices.

## 3. Keep the recipe legible

Separate three authoring surfaces without hiding control flow:

- **Recipe:** the stages, their purpose, input/output bindings, checks, amendment
  rights, approval boundaries and visible resource limits.
- **Template package:** task list, optional reusable instructions, schemas and
  domain-specific utilities. It contains no hidden pipeline scheduler.
- **Order parameters / operator profiles:** concrete input paths, project values,
  model settings and permitted tools. Secrets remain outside recipe files.

A normal template can be a directory containing `tasks.md` and optionally
`AGENTS.md`. Explicit file paths must also work for existing projects. Paths are
relative to the recipe, not to whichever directory a terminal happens to use.
The controller materializes a version-pinned copy for each attempt; changing a
source template does not silently change an already running attempt.

Use explicit `kind: tasklist` or `kind: script`. Data bindings determine ordinary
readiness; `after` is reserved for a control dependency that has no data input.
An approval is a controller gate on a stage, not a third kind of worker. A
notification or publication with relevant external effects is a visible script
stage, not an invisible hook inside a prompt.

A plan view must expand defaults and show why each stage runs or waits, its input
revisions, writable artifacts, checks, effective tool profile and approvals.
Do not require readers to inspect Python controller branches to discover the
normal process. Keep domain algorithms inside referenced scripts.

## 4. Illustrative recipe — NOT runnable yet

This is a shape to discuss, not a frozen schema. The referenced templates and
scripts are application-owned examples and are not shipped by this change.
Only simple path/parameter substitutions are proposed; no arbitrary evaluation.
`max_attempts` is a stage-attempt limit, not a replacement for task call budgets.

```yaml
schema: arquilo.pipeline.draft-1
id: pem-pilot
parameters:
  basis_document: {type: path, required: true}
defaults:
  workspace: isolated
  execution_profile: local
  max_attempts: 3
limits:
  max_parallel: 2
  max_revision_rounds: 2
journal: {path: process.md}
artifacts:
  source: {source_parameter: basis_document, lifecycle: fixed}
  plan: {lifecycle: versioned}
  evidence: {lifecycle: versioned}
  effects: {lifecycle: versioned}
  merged: {lifecycle: versioned}
  report: {lifecycle: versioned}
  publication: {lifecycle: versioned}
stages:
  - id: plan
    purpose: Define the material review questions.
    kind: tasklist
    template: templates/plan/tasks.md
    instructions: templates/plan/AGENTS.md
    inputs: {source: source}
    outputs: {plan: analysis_plan.md}
    checks:
      - argv: ['${python}', '${recipe}/checks/plan.py', '${outputs.plan}']
        expose_to_agent: true

  - id: evidence
    purpose: Examine the evidence for the planned questions.
    kind: tasklist
    template: templates/evidence/tasks.md
    execution_profile: research-read
    inputs: {source: source, plan: plan}
    outputs: {evidence: evidence.md}

  - id: effects
    purpose: Examine effects independently of the evidence branch.
    kind: tasklist
    template: templates/effects/tasks.md
    inputs: {source: source, plan: plan}
    outputs: {effects: effects.md}

  - id: merge
    purpose: Assemble the two accepted review fragments.
    kind: script
    inputs: {evidence: evidence, effects: effects}
    outputs: {merged: merged.md}
    argv: ['${python}', '${recipe}/scripts/merge.py',
           '${inputs.evidence}', '${inputs.effects}', '${outputs.merged}']

  - id: synthesis
    purpose: Synthesize results; propose a plan revision when a gap is found.
    kind: tasklist
    template: templates/synthesis/tasks.md
    inputs: {source: source, plan: plan, merged: merged}
    outputs: {report: report.md}
    amends: {plan: revised_plan.md}
    checks:
      - argv: ['${python}', '${recipe}/checks/report.py', '${outputs.report}']
        expose_to_agent: true

  - id: publish
    purpose: Export the accepted report after owner approval.
    kind: script
    approval: owner
    inputs: {report: report}
    outputs: {publication: publication.md}
    argv: ['${python}', '${recipe}/scripts/export.py',
           '${inputs.report}', '${outputs.publication}']
```

`inputs` map stage-local names to logical artifact IDs. `outputs` map logical
artifact IDs to candidate paths in the attempt workspace. A normal producer
creates the first revision; `amends` names an additional, explicitly permitted
writer of an existing artifact. An amendment target must also be a declared
input, so the exact base revision is known. An absent optional amendment means
no change, not deletion. Required normal outputs must not silently become
optional; an amendment-only completion is a distinct controller outcome.

Here the two review branches can run in parallel. Merge needs both accepted
results, and publication needs both a current report and an owner decision.
When synthesis amends the plan, its report is not automatically accepted: the
revision-round rules below first reconsider the affected review branches.

`research-read` is an operator-defined profile reference, not a magic built-in
permission and not the name of a particular MCP server. The plan view must
resolve it into actual available servers/tools and executable restrictions.

## 5. Artifact contracts and acceptance

An artifact is a logical deliverable, not just a filename. A revision records
its bytes or directory manifest, producer/amender, attempt, input revisions,
effective instruction and validator versions, checks and acceptance decision.
Inputs bind to a concrete accepted revision at attempt start. A later revision
must not change files beneath an already running worker.

The proposed flow is: materialize inputs, execute, collect candidates, check,
review where required, and publish an accepted revision through the controller.
File existence, a zero process exit code, a generated DONE marker or an agent's
self-assurance alone is not acceptance. A task-list stage must also be complete
under the existing runner's completion-scope and stop semantics. Stopping a list
intentionally before remaining work is not whole-stage success.

Checks name their targets explicitly. They may examine a single output, a
specified directory manifest or several inputs/outputs together. An empty match
is an error unless emptiness is deliberately allowed by the contract. Do not
run every linter over every file. Validator failure to start is an infrastructure
failure, not a negative domain finding or permission to waive the check.

Expose ordinary validators to the producer for self-checking. Keep the
controller's authoritative validator and acceptance records outside the worker's
writable area, and rerun those checks against the collected candidate snapshot.
A worker cannot make itself pass by editing the test, the receipt or the recipe.
A model review is additional evidence, not proof of factual truth. Confidence
scores cannot replace a required check or approval.

Multi-artifact acceptance must be recoverable as one publication transaction:
downstream workers see either the previous accepted set or the complete new set.
A crash halfway through file copies must not expose a half-published bundle.
Use a controller-owned publication record and staged snapshots; implementation
storage can be chosen later. No separate database server is required.

## 6. Mutable artifacts are normal

**A logical artifact may evolve; a historical revision does not change in place.**
Immutability applies to evidence of what was accepted, not to the user's ability
to improve a feature description, analysis plan or design.

Three cases need different treatment:

| Case | Treatment |
| --- | --- |
| Fixed imported source | Preserve that source revision. A replacement is an explicit new source revision/order input, never a hidden edit. |
| Versioned working artifact | Normal default. Declared later stages or the owner can submit a new revision. |
| Process journal | Controller-owned event history with a regenerable/versioned readable document; not an automatic semantic input to every stage. |

A continuously edited narrative document can also be an ordinary versioned
artifact with several declared amend-capable stages. It does not have to be
append-only. For parallel writers, use fragments plus a merge or serialized
amendments; do not allow uncoordinated last-write-wins updates.

### Example: a missing feature decision

A defines feature@1. B designs against feature@1. C discovers an unresolved
choice during implementation and is allowed to amend the feature. C submits
feature@2, a reason and a change description under the target artifact's contract.
The controller accepts that revision through the configured amendment policy.
This can be automatic after prescribed checks/review for a pre-authorized scope;
it need not require a human for every spelling or consistency correction.
Business-significant choices can explicitly require an owner decision.

A's historical run remains completed for feature@1. Its original receipt is not
rewritten and A is not rerun just because somebody improved its output. The
current accepted feature is now feature@2, attributed to C's amendment.

B's design and dependent code/tests are now **needs revalidation**, not
retroactively failed. Their bytes and history stay available. Work that did not
consume the feature or a changed derivative stays valid. Any approval bound to
the old feature revision must be reconsidered too.

The impact plan chooses a fresh run, a targeted repair plus review, or an
explicitly evidenced no-impact revalidation. First-increment automation should
be conservative: default to rerunning affected work; no-impact reuse requires
a declared check/review or owner decision recorded as such. A formatting-only
linter cannot certify that a requirement change is semantically harmless.

### Amendment protocol

1. Preserve the attempt's input revisions and identify each amendment base.
2. Check the writer's declared scope, artifact contract and reason for change.
3. Validate/review the candidate against the applicable acceptance requirements.
4. Accept through controller policy; reject a stale base if another writer has
   already advanced that artifact. Preserve both candidates on a conflict.
5. Advance the logical head and create an impact/revision round. Rebind future
   attempts to the new accepted revision; reconsider affected consumers and gates.

This is not permission to rewrite the task runner's captured original request,
its mandatory review rules or its trusted state. An artifact can contain evolving
requirements; changing the executable acceptance contract itself is a separate,
explicit owner-adopted recipe/contract revision.

If an owner edits an exported working copy directly, detect a candidate revision
and show its diff and impact. Do not report every legitimate edit as corruption,
and do not silently trust every file edit as an accepted contract change. The
first increment can offer explicit import/adoption at resume; no file watcher
or background daemon is required.

## 7. Revision rounds, not broken DAGs

A recipe describes the normal forward dependency graph. A permitted amendment
starts a new revision round; it is not a permanent backwards scheduling edge
from C to A. Otherwise a useful correction would appear to be a graph cycle.

Walk actual artifact dependencies, not stage numbers or filename prefixes.
Track transitive impact, including checker inputs and approval subjects. Normal
ordering-only edges do not on their own imply semantic invalidation. Contract,
template and effective-context changes need explicit adoption and the same
impact discipline. They must not silently leak into active attempts.

If C both revises an input and produces a downstream result, conservatively
accept only its approved amendments/change record first. Keep its ordinary
results as candidates. Reconsider the intervening work and run/review C again
with a coherent, current input set. Do not relabel a result produced from stale
inputs as if it had consumed the new revision. A narrowly optimized joint
acceptance protocol can be added later, not assumed in the MVP.

Workers already running with old inputs may finish for diagnostic value, but
cannot publish as current without a fresh acceptance decision. Recheck input
heads under the publication lock; checks performed earlier are not sufficient
if another writer advanced a relevant input meanwhile. Use explicit conflict
handling rather than silently overwriting either output.

Bound amendment rounds and task/stage correction budgets. Repeated mutually
contradictory changes should produce an actionable decision pause, not oscillate
forever. Pure script retries, model corrections and upstream specification
changes are distinct actions with distinct evidence and budget accounting.

## 8. Process documentation without a self-invalidating loop

The controller emits events for starts, accepted outputs, reviews, amendments,
approvals, failures and resumptions. Each event has an identity and belongs to an
order/attempt. Retrying a renderer does not append the same event twice.

A readable process.md can be rewritten after each event or checkpoint. Its
historical versions remain available; the controller event history is the
factual execution record. Agent or human annotations can be added as attributed
entries without rewriting past controller events. A free-form narrative remains
editable through ordinary versioned updates.

Do not put that live journal into every stage's semantic input set or a global
workspace fingerprint. That would make each new log line invalidate completed
work. For a final audit or report, explicitly freeze and bind a journal revision.
If a stage actually relies on journal content for substantive reasoning, it is
a normal input dependency; the filename 'log' is not a license to hide material
changes. Keep task-local histories out of the same running task's input set
unless a new attempt explicitly adopts them.

## 9. Context: preamble and AGENTS.md

The current task-list preamble already supplies shared project intent and
quality criteria. `todo_context.augment_with_preamble` captures it for one
handoff, and AutoBuild reuses that captured context for review and repair. The
next handoff rereads the live task list. A standalone AutoBuild invocation does
not implicitly receive a task-list preamble. See [Task preambles](../documents/TODO_PREAMBLE.md).

Therefore an AGENTS.md is **optional**, not a second mandatory place to maintain
the same instructions. Prefer:

- task-list preamble for the task-list/stage objective, deliverables and criteria;
- reusable stage/repository instructions for conventions and tool-use guidance;
- YAML/operator profile for executable dependencies, checks and permissions.

A stage-specific AGENTS.md is useful when reusing a role or running Codex
manually outside ARQUILO. Alternatively, reusable instruction text can be
composed into the generated task-list preamble from one source. Do not maintain
duplicate normative copies. A filename reference in today's preamble is not an
automatic include; any future composition must explicitly read and snapshot it.

The pipeline should freeze the selected template/preamble/instruction set for
an attempt, record its origin and ensure producer/reviewer get the same relevant
contract context. Distinct review instructions remain necessary. A producer
must not weaken a later review by changing AGENTS.md during the attempt.

Codex also discovers global and nested instruction files; a stage directory does
not automatically exclude those. Account for that effective instruction chain,
its size limits and managed/user configuration. Do not silently overwrite a
repository's AGENTS.md, change the user's global files, or claim that a recorded
prompt proves perfect model instruction-following. The outer contract must
remain independent of the order in which natural-language guidance is read.

## 10. MCP and privileges

Writing 'use MCP service X' in AGENTS.md or a preamble is useful guidance. It
neither installs/connects that service nor enforces what it may do.

An operator profile should resolve required servers, allowed tools, credential
references and the relevant execution policy. The recipe selects that profile;
it cannot grant more than the operator allows. Distinguish web research, shell
networking, MCP discovery and MCP actions. A filesystem read-only sandbox does
not by itself demonstrate that a remote MCP write is impossible.

For the first increment, keep the interface at named profiles rather than a
large inline connector schema. Validate the actual Codex/host configuration and
record the effective exposure. Optional services must be marked optional; an
unavailable required service stops before production. Requesting a tool
restriction that the adapter cannot enforce must fail or require an explicitly
different trusted profile, never silently weaken the guarantee.

Codex documents server enable/disable, required servers and tool allow/deny
lists. Their behavior in the installed version must be capability-tested; a
configuration string alone is not evidence of enforcement. Plugin-provided
servers and inherited hooks/configuration also need accounting. Server-side
authorization and appropriately scoped credentials remain important. Do not
modify a shared CODEX_HOME in place during parallel stages or copy secrets into
logs, templates or recipes.

Prefer read-only service access inside analytic stages. An external mutation
such as publishing to Confluence/Jira should normally be a separately named
script stage with an approval where appropriate and a delivery receipt. This
keeps the recipe honest about what is published and when. A notification is not
an approval, and a business approval is not a blanket grant of shell/tool rights.

YOLO is out of scope and remains rejected by current ARQUILO. No permission
expansion accompanies the CLI rename or this concept.

## 11. Recovery, effects and budgets

Keep order authority outside agent-writable workspaces, building on the existing
controller-state boundary. Store recipe/parameter snapshots, current artifact
heads, historical accepted revisions, attempts, checks, approvals and changes.
A stored 'running' record after a crash is not success. Recover according to
receipts and the actual artifact set before scheduling new work.

A human gate persists its exact artifact revisions and decision scope. Resume
requires no lingering LLM process. Content changes invalidate the relevant old
approval, not every unrelated approval in the order.

Scripts are supplied executable programs, not automatically pure functions.
Classify externally mutating scripts separately from local transforms. A crash
after an upload but before its local receipt is an ambiguous result: reconcile
with the external system or request a decision; do not blindly publish again.
Use idempotency keys where supported. No universal exactly-once promise.

Honor one outer concurrency/resource budget. Inner task-list parallelism must
not multiply an outer limit unnoticed. Preserve consumed task budgets on resume
and distinguish task-call counts from token or currency caps. Define bounded
attempt/revision-round limits for the pilot. Independent branches may finish
after a sibling failure, but a fan-in cannot use missing required results.

## 12. PEM acceptance pilot and migration path

First adapt one application-owned recipe with real representative templates:
planning, two parallel reviews, deterministic merge, synthesis/QA and gated
export. Adapt input/output paths and the preamble where necessary. Existing
PEM wrappers may initially supply domain scripts; do not move their algorithms
into ARQUILO. Do not run a second full PEM scheduler inside a stage and describe
that as a successful generic migration.

The pilot is accepted only when these cases are demonstrated:

| Scenario | Required result |
| --- | --- |
| Normal order | Both branches run independently and fan-in receives their accepted revisions. |
| Missing/malformed output | Stage is not accepted; downstream work remains blocked. |
| Targeted linter | Only named files are checked; an empty target selection is not a free pass. |
| Branch failure | Successful independent work survives; recovery reruns only required work. |
| Crash around publication | No half-published artifact bundle becomes an input. |
| Late plan correction | A new plan revision is accepted; the original planning receipt survives; affected consumers are reconsidered. |
| Concurrent amendments | A stale-base writer cannot overwrite a newer accepted revision. |
| Amendment plus report | A report based on the old plan is not accepted as current without revalidation. |
| Process document update | Progress documentation evolves without invalidating unrelated analysis. |
| Human gate and restart | The decision remains pending after restart and binds to exact revisions. |
| Context/MCP profile | Stage-specific context is visible; required unavailable tools fail; a denied remote write is not treated as sandbox-safe. |
| Repeated specification changes | The round limit yields a reasoned pause instead of endless repair. |
| Ambiguous external delivery | Resume reconciles or pauses instead of duplicating publication. |

After the pilot, add bounded `foreach` over a validated planning artifact,
stable instance IDs and deterministic collection/fan-in. That is needed for a
fuller PEM mapping with dynamically sized review branches. Explicit conditions,
application-specific source/evidence transactions and specialized repair paths
also need separate mapping. The first fixed-graph pilot does not claim drop-in
compatibility with all PEM stages or existing PEM resume state. Start new pilot
orders; historical PEM workspaces require an explicit import/migration design.

## 13. Proposed CLI and implementation sequence

The implemented command is `python arquilo.py tasklist run ...`; old `run`
continues with a short stderr notice. No release number is assigned by this
proposal. `run_todos.py` remains available as a direct/internal entry point.

The future group should start with `pipeline validate`, `pipeline plan`,
`pipeline run`, `pipeline status`, `pipeline resume` and `pipeline approve`.
Owner adoption of an artifact change must be explicit in the resume/change
review flow. Exact flags are intentionally not fixed yet. Do not dispatch by
filename suffix or silently treat a broken recipe as a task list.

Build the next feature in vertical increments: contract validation and a fake
executor first; a real two-stage tasklist/script handoff next; then parallel
fan-in, revision rounds, approval/recovery and the PEM pilot acceptance suite.
The revision model must exist before calling the pilot stable, not be a later
patch that simply disables integrity checks. Consider one optional YAML parser
dependency for the pipeline layer, while keeping the existing task-list core
stdlib-only; do not write a new YAML parser.

### Reference boundaries

Current runtime behavior: [Architecture](architecture.md),
[Controller safety](controller-safety.md), [Task preambles](../documents/TODO_PREAMBLE.md),
[Decide configuration](decide-configuration.md), and `removed_features.py`.

External driver references, checked 2026-10-06:
[Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md) and
[Codex MCP configuration](https://developers.openai.com/codex/mcp).
These document driver features, not implemented ARQUILO stage-profile guarantees.
