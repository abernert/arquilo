# Examples

Copy examples into a **new disposable workspace**, never run them in this source
folder. Use `--process-stop-policy controller-only` for these task lists.

`minimal_todo.md` asks for one empty file and a factual result report. It is the
smallest end-to-end smoke test; see the quick start.

`document_review_todo.md` together with `brief.md` demonstrates a non-coding task:
a source-bound summary with an explicitly permitted open question. Copy both,
rename the task list to `tasks.md`, then dry-run and inspect before opting into
model usage. The brief is synthetic.

`lean_todo.md` is the retained German two-task example. Its syntax remains
compatible; use a separate workspace for it as well.

Examples do not prove model accuracy or sandbox security. Their real outputs,
reports and controller status must be checked after execution.

`planning_todo.md` generates the remaining work in the **same file**. Copy it to
`tasks.md` in a fresh workspace, run with `--allow-todo-modifications --stop 2`,
and inspect the generated open tasks before a separate strict continuation.
Do not use this example without the opt-in: strict mode rejects plan mutations.
[Full commands and trust boundaries](../docs/operator-controls.md).
