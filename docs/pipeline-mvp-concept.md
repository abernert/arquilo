# Pipeline MVP: accepted results, revision control and integration

**Status: design proposal, not an implemented interface.** The accompanying CLI
change implements `arquilo tasklist run` and a compatibility notice for `arquilo
run` only. `arquilo pipeline ...`, the YAML below and the lifecycle rules in this
paper are proposed. They are not capabilities of the current task runner.

**Concept revision: 0.2, 2026-10-06.** Revised against the ARQUILO positioning
discussion. This is a document revision, not an ARQUILO software release.

## 1. Positioning and boundary

**ARQUILO should deliver accepted work products with inspectable evidence, not
compete to be another general-purpose workflow platform.** The positioning is
an execution-and-acceptance layer for AI-assisted knowledge work. A small local
pipeline runner makes it usable on its own; the same governed production order
must be callable from an existing business workflow without moving that whole
workflow into ARQUILO.

The value hypothesis is lower recurring effort to specify, verify, revise and
hand over work products. YAML, parallel agents, approvals and restart support
are useful mechanisms, not an exclusive market advantage. Lobster documents
deterministic workflows and resumable approval/input checkpoints; n8n documents
human approval before selected tool calls; CrewAI Flows documents structured
control flow and persistence. Those systems can also run validators or custom
acceptance logic. Their absence is not assumed. The distinction to test is how
much bespoke integration and human checking is needed for the same acceptance
and revision guarantees. See the primary references at the end.

### 1.1 Keep three responsibilities separate

| Responsibility | Owner in the proposed first increment |
| --- | --- |
| Business intake, chat, notifications and cross-system workflow | Existing host or a human using the CLI. Teams/Copilot/OpenClaw/n8n are possible integration contexts, not shipped integrations. |
| Production-order contract, accepted revisions, decisions and case record | ARQUILO acceptance kernel, with a small local dependency runner. |
| Work inside a stage | Existing task-list runtime or an explicitly selected script. |

There must be **one authoritative state owner per scope**, not necessarily one
product for an entire enterprise process. A host owns the business case around
the delegated order; ARQUILO owns that order's internal plan, retries, revisions
and acceptance. The host submits or resumes that same order and reads its status.
It must not independently restart internal stages or turn its own green workflow
indicator into an ARQUILO acceptance decision. Inside a task-list stage, the
existing runner remains authoritative for its captured tasks and mandatory
reviews; the pipeline interprets its completion evidence, not editable markers.

Do not put ARQUILO above a second complete scheduler for the same stages. For
simple glue workflows with no need for this result/revision contract, recommend
using the existing host alone. A future host-scheduled stage API could reuse the
acceptance kernel, but that is not an additional execution mode in this MVP.

### 1.2 Standalone first; embeddable from the start

Execute a local production order from a readable, versioned recipe. A stage uses
one of exactly two executors: an existing ARQUILO task-list run or an explicitly
selected script. The production-order controller owns dependencies, accepted artifact
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

Prioritize the acceptance kernel and handoff contract before adding general
workflow conveniences. A two-stage order with a complete acceptance record is
more useful for this positioning than a large graph with a generic DONE flag.

| Area | First increment |
| --- | --- |
| Recipe | Validated YAML; explicit stage IDs, purposes, executors and artifact bindings |
| Execution | Task-list runner and argv-based scripts; no shell expression language |
| Flow | Fixed dependency graph, independent parallel branches, explicit fan-in |
| Contracts | Versioned result criteria, required artifacts, scoped checks and explicit evidence requirements at stage and order level |
| Workspaces | Isolated stage attempts with explicit input snapshots and candidate outputs |
| Quality | Existing task review plus controller-owned artifact acceptance checks |
| Revisions | Later stages may amend declared artifacts; history and current validity are separate |
| Human decisions | Distinguish permission to act, acceptance of a result and permission to release; persistent revision-bound decisions |
| Recovery | Per-attempt receipts, preserved evidence, restart/resume and stale-input detection |
| Context | Task-list preamble; optional stage-specific AGENTS.md; recorded effective context |
| Tools | Operator-owned execution profiles, including explicit MCP tool availability |
| Handoff | Stable order ID, structured status/outcome and read-only case export; callable through the local CLI |
| Observation | Criterion-to-evidence record, open defects, change-impact report and editable process narrative |

Do not include dynamic swarms, a connector catalog, a general expression engine,
a new provider harness, a web editor or distributed high availability. A shared
writable workspace is not needed for the first pilot. Read access to a project
and write access to a stage area are separate choices.

### 2.1 Required handoff, not a connector project

For the first increment use ordinary local commands and versioned JSON results,
not an HTTP server, MCP server, SDK, queue or connector catalog. The same CLI
behavior serves manual use and a script launched by a host. A call runs until
completion, failure or a durable decision/input checkpoint and then returns;
no model process must wait for a human answer.

A submission binds an order ID to recipe, input, parameter and contract snapshots.
Reusing the ID with the same submission returns or resumes the existing order;
reusing it with different contents is an explicit conflict or amendment, not a
new hidden run. Correlation IDs from hosts are metadata, never authorization.
Concurrent callers cannot both own an order. Lost responses must not cause
unrequested repeats of model work or external effects.

Return the order ID and state revision, execution status, acceptance status,
current accepted artifact references, blockers, required next decision and case
export location. Exact field names and exit codes are to be specified before
implementation. Do not make callers infer acceptance from process exit code,
log prose, task-list DONE markers or a successful send/upload.

The interface must support read-only status/export, explicit resume and a
revision-bound decision using the existing pending gate ID. Stale or duplicate
decisions cannot approve new content. A local owner action is the first supported
authorization mechanism. A label such as `owner` or a username typed into JSON
is not verified identity or enterprise segregation of duties. Remote approval
channels require an authenticated adapter later; merely receiving a chat message
or webhook is not proof of authority.

## 3. Keep the recipe legible

Separate three authoring surfaces without hiding control flow:

- **Recipe:** the stages, their purpose, input/output bindings, checks, amendment
  rights, result contracts, decision boundaries and visible resource limits.
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
A human decision is a typed controller gate on a stage or result, not a third
kind of worker. A
notification or publication with relevant external effects is a visible script
stage, not an invisible hook inside a prompt.

A plan view must expand defaults and show why each stage runs or waits, its input
revisions, writable artifacts, acceptance criteria/evidence, effective tool
profile and decision scopes.
Do not require readers to inspect Python controller branches to discover the
normal process. Keep domain algorithms inside referenced scripts.

## 4. Illustrative recipe — NOT runnable yet

This is a shape to discuss, not a frozen schema. The referenced templates and
scripts are application-owned examples and are not shipped by this change.
Only simple path/parameter substitutions are proposed; no arbitrary evaluation.
`max_attempts` is a stage-attempt limit, not permission to retry automatically
or a replacement for task call budgets. Referenced acceptance documents have
criteria with stable IDs and their required evidence; no programming language
is embedded in them. The plan view expands their contents. Mandatory task-list
reviews are reused, not repeated by default at every outer boundary.

```yaml
schema: arquilo.pipeline.draft-2
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
case_record: {export: evidence/}
deliverables: [report, publication]
acceptance:
  contract: contracts/order.md
  require: [current_revisions, required_checks, required_decisions]
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
    acceptance: {contract: contracts/plan.md}
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
    acceptance: {contract: contracts/evidence.md}

  - id: effects
    purpose: Examine effects independently of the evidence branch.
    kind: tasklist
    template: templates/effects/tasks.md
    inputs: {source: source, plan: plan}
    outputs: {effects: effects.md}
    acceptance: {contract: contracts/effects.md}

  - id: merge
    purpose: Assemble the two accepted review fragments.
    kind: script
    inputs: {evidence: evidence, effects: effects}
    outputs: {merged: merged.md}
    acceptance: {contract: contracts/merge.md}
    argv: ['${python}', '${recipe}/scripts/merge.py',
           '${inputs.evidence}', '${inputs.effects}', '${outputs.merged}']

  - id: synthesis
    purpose: Synthesize results; propose a plan revision when a gap is found.
    kind: tasklist
    template: templates/synthesis/tasks.md
    inputs: {source: source, plan: plan, merged: merged}
    outputs: {report: report.md}
    amends: {plan: revised_plan.md}
    acceptance:
      contract: contracts/report.md
      human: {role: owner, subject: report}
    checks:
      - argv: ['${python}', '${recipe}/checks/report.py', '${outputs.report}']
        expose_to_agent: true

  - id: publish
    purpose: Export the accepted report after a separate release decision.
    kind: script
    before:
      decision: {kind: release, role: owner, subject: report}
    inputs: {report: report}
    outputs: {publication: publication.md}
    acceptance: {contract: contracts/export.md}
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
results. Report acceptance and permission to release are different decisions.
Publication requires both the accepted report and the release decision for its
exact revision and destination. The local export script illustrates the boundary;
it is not a supplied Confluence/Jira connector.
When synthesis amends the plan, its report is not automatically accepted: the
revision-round rules below first reconsider the affected review branches.

`research-read` is an operator-defined profile reference, not a magic built-in
permission and not the name of a particular MCP server. The plan view must
resolve it into actual available servers/tools and executable restrictions.

## 5. Artifact contracts and acceptance

### 5.1 Permission, acceptance and release are different

| Question | Evidence or decision needed |
| --- | --- |
| May this stage use a tool or perform an action? | Executable operator policy and, where requested, a pre-action decision. This proves no output quality. |
| Does this candidate satisfy the result contract? | Criteria, scoped checks, the existing mandatory task review and any explicitly required domain/human review. |
| May this accepted result be handed to this external destination now? | Revision- and destination-bound release permission, followed by delivery evidence. Neither alone proves substantive correctness. |

These are separate meanings, not a requirement for three manual clicks on every
stage. Most stages can use automated checks and the existing mandatory review.
A single human action may expressly cover acceptance and release together if
its recorded scope names both, the exact revisions and the destination. A
recipe chooses where human judgment is necessary; the meanings stay distinct.

A generic `approval: true` must not collapse all three. Rejecting a proposed
release does not retroactively make an accepted report technically invalid; it
leaves delivery blocked. A successful upload does not accept the report. A
human exception cannot silently turn a failed technical check into PASS. In the
MVP, required checks remain required; change the contract explicitly or retain
the blocked outcome. Policy-defined waivers are not a hidden bypass feature.

### 5.2 Result contracts, not only file lists

A stage contract names required deliverables, understandable criteria, the
checks/reviews intended to establish them, and the required decision roles.
Criterion IDs are stable labels for evidence, not a formal-logic language. The
order contract names the externally promised deliverables and any cross-result
checks: completing every stage is insufficient if the final set is incoherent,
stale, missing its required case record or awaiting a required decision.

Separate structural checks (files, schema, references) from substantive review
(coverage of questions, supported conclusions, unresolved contradictions).
Both can be recorded, but one must not impersonate the other. Criteria without
sufficient evidence remain unresolved. Do not require a schema for prose or
invent a universal test of political, actuarial or software correctness.

Reuse the task runner's captured review and fix evidence if it actually covers
the same criterion, scope and candidate revision. Importing a producer's own
claim is not separate review. Do not add a redundant LLM review solely because a
task-list stage has an outer pipeline wrapper. A distinct domain-QA tasklist is
appropriate when it examines a different scope, such as cross-report consistency.
Pure transforms use deterministic acceptance checks; they need not run an LLM.

The contract and preamble must not become two drifting sources of requirements.
Compose or explicitly bind the versioned contract into the task assignment, and
freeze that relevant context for its review. Amendments must satisfy the target
artifact's applicable contract even when a different stage proposes the change.
Missing acceptance definitions or unresolved contract references are recipe
validation errors; they are not an invitation to default to file-exists checks.

### 5.3 Candidate acceptance and publication inside the order

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

## 8. Case record and evolving process documentation

### 8.1 A case record is a first-class deliverable

Export a structured case record plus a short readable acceptance summary from
controller state. This is not another database or a demand to inspect every raw
log. Every externally delivered order should answer: what was requested, what
was produced, against which criteria was it accepted, and what remains uncertain?

The minimum record contains the frozen request/contract and their identifiers;
input and output revision references; actual executor/model configuration when
known; relevant instruction/validator versions; criterion-to-check/review
results; defects, corrections and amendment impacts; human decisions and their
recorded authorization context; and the final outcome with limitations. It also
points to delivery receipts when delivery belongs to the order. Unknown facts
remain unknown; do not infer a model identity from its prose.

Each acceptance entry binds the candidate revision, input dependency set,
contract version, evidence references and decision. Record concise review
findings and rationale, not hidden model chain-of-thought. Keep any available
confidence score as supplementary, uncalibrated evidence unless independently
validated. A separate model call is not guaranteed independent judgment or
human four-eyes approval.

Default export contains the necessary summaries, hashes and artifact references,
not credentials or full private tool transcripts. Evidence pointers must resolve
within the permitted delivery context; unresolved or deliberately withheld
support is identified explicitly, not called a complete evidence bundle. A
required evidence source that was lost blocks the corresponding acceptance.
Redacted views must be labelled and must not rewrite the authoritative record.
The process journal remains useful, but is not itself the acceptance proof.

Call this an inspectable case record, not certified compliance or a tamper-proof
archive. Hashes detect changes relative to trusted records; they do not stop a
host owner from rewriting both content and records. Access control, retention,
privacy, authenticated multi-user decisions and enterprise audit storage are
separate deployment work. None is delivered by this concept or by the CLI rename.

### 8.2 Process documentation without a self-invalidating loop

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

## 12. Acceptance pilot: prove the positioning, not only the scheduler

First adapt one application-owned recipe with real representative templates:
planning, two parallel reviews, deterministic merge, synthesis/QA and gated
export. Adapt input/output paths and the preamble where necessary. Existing
PEM wrappers may initially supply domain scripts; do not move their algorithms
into ARQUILO. Do not run a second full PEM scheduler inside a stage and describe
that as a successful generic migration.

The pilot must produce an accepted delivery set and case record. It should not
succeed merely because every command completed. First run it with controlled
fixtures and deterministic fake workers, then with real domain templates and
supervised model execution. No real legislative assessment is claimed by the
synthetic tests below.

The pilot is accepted only when these cases are demonstrated:

| Scenario | Required result |
| --- | --- |
| Normal order | Both branches run independently; fan-in receives accepted revisions and the final order satisfies its delivery contract. |
| All files exist, but a result is substantively deficient | Its required review identifies the gap; file/schema success alone cannot accept it. |
| Permission confused with acceptance | A pre-action or release decision cannot satisfy a result-acceptance requirement. |
| All stages pass, final bundle is inconsistent | A declared cross-result check blocks order acceptance without relabelling individual histories. |
| Case handoff to a new reader | They can locate the contract, revision, evidence and unresolved issues without reading raw model transcripts. |
| Duplicate external request or lost response | The same order is retrieved/resumed; no duplicate work, budgets or publication. |
| Stale/forged decision or producer-written receipt | It cannot change controller acceptance or approve newer content. |
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

### 12.1 Second domain and fair comparison

Use a small software feature-to-design-to-implementation-to-test order as a
second acceptance fixture, not a second enterprise product. A late feature
clarification must preserve historical acceptance and revalidate affected work.
This checks that the kernel is not PEM hard-coding under generic names.

Compare the same representative order with an existing orchestrator plus
application scripts (Lobster or n8n, and optionally CrewAI Flows). Use the same
inputs, worker capability, validators, budgets and fault scenarios. Allow a fair
baseline to implement equivalent acceptance checks; do not compare a careful
ARQUILO process with a deliberately unvalidated shell loop. Make repeated runs
where model variability matters and report uncertainty.

Measure configuration/custom-code effort, human inspection/recovery effort,
false acceptance and unnecessary rejection in seeded fault cases, duplicated
execution, revalidation scope and evidence completeness; include latency and
usage/cost only when actually observable. These are proposed measurements, not
claimed benchmark results or invented quantitative targets. Set numerical
acceptance targets before the pilot, not after seeing favorable results.

If an existing runner plus a thin acceptance adapter meets the same guarantees
with less overall maintenance, reuse that runner rather than expanding ARQUILO's
scheduler. Keeping a small local runner is justified by a low-friction standalone
path, not a claim that workflow execution must be proprietary to ARQUILO.

### 12.2 Deferred fuller PEM mapping

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
`pipeline run`, `pipeline status`, `pipeline resume`, `pipeline approve` and
`pipeline export` for the case record.
Owner adoption of an artifact change must be explicit in the resume/change
review flow. Exact flags are intentionally not fixed yet. Do not dispatch by
filename suffix or silently treat a broken recipe as a task list.

Build the next feature in vertical increments:

1. Define contracts, decision scopes, acceptance evidence and the order handoff;
   exercise them with fake workers and failing/stale/duplicate inputs.
2. Run a real tasklist/script pair through that kernel and export its case record.
   Reuse existing task review evidence; do not build a second review loop. A
   script's declared postcondition must be checked even when its exit code is 0.
3. Add the minimal dependency runner, bounded parallel fan-in, revision rounds
   and persistent decision/recovery behavior needed for the PEM pilot.
4. Validate a script-based host invocation and the second-domain fixture; compare
   the acceptance/recovery effort against the existing-orchestrator baseline.

All these requirements describe the complete first useful increment; step 2
alone is not a claim that revision handling or restart safety is finished.
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

Workflow comparison, checked 2026-10-06:
[Lobster](https://docs.openclaw.ai/tools/lobster),
[n8n human tool approvals](https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/),
and [CrewAI Flows](https://docs.crewai.com/en/concepts/flows).
These establish overlapping workflow/approval/state capabilities, not a proof
that competitors cannot implement result acceptance or artifact revisions.
Microsoft distribution or Windows bundling assumptions are not a prerequisite
for this architecture and are not asserted here.

### Revision 0.2 change summary

Compared with the original proposal, this revision elevates result contracts,
distinct decision scopes, exported case records and an idempotent host handoff;
it narrows the scheduler's role and adds positioning-oriented acceptance tests.
The two executors, mandatory task reviews, controlled amendments, evolving
process documentation, preamble/AGENTS.md split and operator-owned MCP policy
remain. No pipeline code, new harness, connector catalog, hosted service, swarm
system, software version bump or merge is part of this documentation revision.
