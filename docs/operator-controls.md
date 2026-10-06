# Operator controls: budget, workspace logs and editable plans

These settings are independent. They do not change the Codex model/provider,
credentials, sandbox, network permissions, mandatory review or retry policy.
They are operator CLI/API choices, not model-editable task directives.

| Option | Default | Effect |
| --- | --- | --- |
| `--max-calls N` | `0` (unlimited) | Bounds counted Codex execution attempts per top-level task tree only when N is positive. |
| `--logs-in-workdir` | Off | Writes live runner logs under `<workdir>/.codex_runs/run_todos/<UTC timestamp>/`. |
| `--allow-todo-modifications` | Off | Adopts and records valid edits to the primary task file, including new tasks. |

## Generate tasks in the same file, then stop for human review

A normal sequential task may generate the rest of its own task list. Use one
Markdown file and explicitly ask the generating task to append open tasks,
keep existing IDs and avoid executing the plan. A ready-to-copy synthetic
example is [planning_todo.md](../examples/planning_todo.md).

For an existing project, keep its workdir, task-file path and **same state root**.
The following paths and project ID are examples, not deployment requirements:

```powershell
python .\arquilo.py tasklist run `
  --workdir 'D:\Migration' `
  --todo-file 'D:\Migration\tasks.md' `
  --project-id migration-pilot `
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
  --workdir 'D:\Migration' `
  --todo-file 'D:\Migration\tasks.md' `
  --project-id migration-pilot `
  --start 3 `
  --accept-plan-changes
```

Omit `--accept-plan-changes` if the generated file was not changed afterwards.
Omit `--stop 2` for the continuation. Omitting `--allow-todo-modifications`
restores the strict mode: this permission is **not sticky**. Omit `--start 3`
if you want the normal selection of all remaining open tasks instead.
Neither command clears an existing `process_stop`; inspect any such stop first.

## Budget semantics and existing runs

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

## Logs for metarunners

```powershell
python .\arquilo.py tasklist run --workdir 'D:\Migration' --todo-file 'D:\Migration\tasks.md' --logs-in-workdir
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

## Editable-plan trust boundary

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
that fits the workflow. See [controller boundaries](controller-safety.md).
