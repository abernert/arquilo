# Call budgets, continuation, and other limits

`--max-calls 0` is the default: there is no ceiling on counted Codex execution attempts. A positive value limits each numeric root-task tree across restarts. `12`, `12.1`, their children, breakdown, corrections, reviews, and Decide share one counter; root task `13` receives its own.

The counter is reserved before an execution attempt, not for every internal model request made by Codex. Startup/provider/archive failures are not refunded. One `codex exec` may contain multiple model requests. The budget is not a money, token, or time limit. CLI metadata probes, pure Python worker startup, and JSON evaluation do not count. The separate sandbox preflight is outside the task-tree counter. Usage is still counted when the budget is unlimited.

## Already-started runs

At startup the runner applies the selected limit to existing budgets in the current controller state. With no parameter, previous limits such as 100, including exhausted limits, adopt **0 = unlimited** while preserving consumed reservations and claims. Changes are recorded under `limit_changes/`. Only the operator/runner may change limits, not a worker. An explicitly selected finite limit must be at least the amount already consumed. Damaged state is not automatically deleted or reset.

Keep the workspace, task-list path, and `--state-dir` unchanged when continuing. New runtime timestamps or different log locations do not create a new counter. Existing `process_stop` files remain separate stop instructions even when they were originally caused by an exhausted budget. Before deliberately removing one, inspect its cause, partial changes, and the intended continuation.

## Other loop and stop limits

`max_steps × max_retries` bounds the production/correction steps of an AutoBuild task in the runner (default 3 × 2). `max_retries` is a continuation factor, not a complete replay of the task. After a valid domain FAIL, a targeted correction against the original task may run followed by a new review. Standalone AutoBuild uses `max_steps`. Parallel CFG uses Python workers and controller-assigned shared budget directories.

`breakdown_max_rounds`, `breakdown_max_children`, `max_depth`, invocation timeouts, STOP/WAIT/questions, and `--stop` remain independent of the call budget. Unlimited does not mean endless technical retries or unlimited depth. Quota, authentication, transport, and protocol failures remain technical failures and do not automatically replay the entire task.

With an explicit finite budget, the next invocation is checked before it starts. A PASS on the last permitted invocation remains valid. If a mandatory review is still missing, partial results remain but the task stays open. AutoBuild reports `budget_exhausted` with exit 9; the runner reports `shared_call_budget_exhausted` with exit 6 and `process_stop`. Unlimited budgets do not exhaust.

## Data and operator options

Authoritative data remains in external `budget.json`, `reservations.json`, and numbered claims under `<controller-state>/<plan>/call_budgets/task_<root>/`. Reservation and file operations are locked across processes; a missing diagnostic claim does not release an invocation. The last reservation number continues to increase.

Current budget/claim schemas are `arquilo.call_budget.v2` and `arquilo.call_claim.v2`. For unlimited budgets, `limit=0`, `remaining=null`, `unlimited=true`; `used` remains numeric. Finite v1 data is still validated and read. JSON infinity is never written.

`--logs-in-workdir` moves only new diagnostic logs, not these counters. `--allow-todo-modifications` deliberately permits a mutable main plan. For planning in the same file, task 2 can create later open tasks; `--stop 2` pauses after task 2 has passed review and before those later tasks execute. The operator then inspects the plan and continues separately. Options and detailed PowerShell examples are in [Operator controls](../docs/operator-controls.md).
