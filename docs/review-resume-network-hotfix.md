# 0.10.0 hotfix: network recovery and review-only continuation

This is a maintenance patch on the 0.10.0 code base. The `v0.10.0` tag and
existing downloaded ZIPs are not rewritten. Update the **executing runtime**,
not just the repository that an agent is currently building.

## What changes

The Codex transport now recognizes these exact nonterminal retry notices:

```text
Reconnecting... 2/5 (request timed out)
Reconnecting... waiting for network (Connection failed: error sending request)
```

The previously supported `stream disconnected before completion: ...` form
remains supported. All notices remain in the original capture and diagnostics.
They do not cause a false `codex_stream_error` after an otherwise healthy
completion. This is not a generic “ignore errors after completion” rule:
unknown errors, `turn.failed`, missing completion/answer, nonzero exit codes,
truncated captures and STOPs remain failures or cancellations.

`tasklist resume-review` now accepts both historical workspace captures and
closed captures in the existing private controller state. External captures
must match the workspace, working task file, existing state identity,
`run.json` and (when used) the registered named-project binding. Captures are
not moved into `.codex_runs` and state or call budgets are not reset.

A mixed capture containing previously recognized reconnect diagnostics and
misclassified errors is checked against the complete original stream. Every
notice must be accounted for exactly once and in the recorded order. The
original files remain unchanged.

## Before running

Stop other controllers for this workspace. Keep the same workspace, **working**
task file and `--state-dir`; do not copy the task list or create a new state root.
Keep the original prompt catalog, process-stop policy, runtime profile, agent,
MCP/skill selections and other task-context settings. A different regenerated
production prompt is refused before any review model call.

The archive must describe exactly one completed production call, zero reviews,
`turn.completed`, exit code 0, no STOP and only the known misclassified retry
notices. A textual “PASS” in an agent answer alone is insufficient. The task
must still satisfy the normal controller plan and budget gates.

The original run's `run.json` and `run_config.json`, two directories above the
production capture, identify its paths and several effective settings. They do
not record every original CLI option: preserve your original invocation rather
than treating these JSON files as a complete replay script.

## Check without model calls or state changes

From the updated runtime directory, use the following shape. Substitute the
original paths and retain any original context/resource options after the
required bounded options. All file paths are relative to the shell's working
directory unless absolute. Use separated `--option value` spelling for the
required recovery options and `--state-dir`.

```sh
python3 -B arquilo.py tasklist resume-review \
  --check-only --todo 147 --capture-dir /original/state/HASH/runs/RUN/task-147/001-production \
  -- tasklist run \
  --workdir /original/workspace \
  --todo-file /original/workspace/TASKS.md \
  --state-dir /original/state \
  --start 147 --stop 147 \
  --max-steps 1 --max-retries 1 --breakdown-policy off
```

`--check-only` reads and validates the archive/binding only. It creates no new
run, changes no task state and makes no model calls. Exit 0 means the archived
production is eligible for this recovery mechanism, **not** that the current
plan/prompt/budget has passed the normal runner gates or that the task is DONE.

## Run the independent review

Run the identical command **without `--check-only`**. Remove any original
`--accept-plan-changes`, `--allow-todo-modifications`, `--todo-template`, `--git`,
`--git-push` and `--dry-run` flags; recovery refuses these rather than adopting
plan changes or publishing files. Do not remove a STOP to force recovery.

The wrapper verifies the existing archive, substitutes its completed production
result once, and invokes one normal read-only reviewer. It skips the optional
workspace-write backend preflight probe, while retaining the review transport's
normal executable/protocol checks. Parallel-worker recovery, production/fix
calls, other tasks and additional model phases are refused; there is no fallback
to a new production run.

Expected recovery messages include:

```text
[recovery] Verified ... recovered reconnect notices; no production replay.
[recovery] Reused verified completed production of ToDo 147; reviewer runs normally.
```

The new run's logs and mandatory review determine acceptance. A successful
recovery typically reports `Aufträge: 1, Prüfungen: 1`: the first count includes
the **reused archived result**, not another production process. The legacy
AutoBuild accounting still reserves that production slot plus the new review;
no past calls are refunded and no budget counter is reset. Preserve the original
`--max-calls` setting; a deliberately exhausted budget is not bypassed.

A failed review leaves the task unaccepted and does not automatically repair,
repeat production or proceed to the next task. Archive validation refusals use
exit 125. Normal runner errors, review failures and STOPs retain their ordinary
exit codes. Unknown or incomplete evidence requires inspection, not editing the
original JSON until it passes.

## Offline verification

```sh
python3 -B -m unittest discover -s tests -p 'test_review_resume*.py' -v
python3 -B -m unittest discover -s tests -p 'test_reconnect*.py' -v
python3 -B -m unittest discover -s tests -v
```

The new fixtures cover a 220-notice outage, mixed diagnostic/error partitions,
external and named project state, immutable archive reads, malformed evidence,
STOPs, review FAIL and a native task-runner recovery with exactly one synthetic
reviewer process and no production replay. No real provider call is needed.
