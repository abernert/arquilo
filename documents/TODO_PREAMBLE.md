# Project preamble and dynamic Markdown work plans

A normal ARQUILO run continues to operate in a shared, evolving workspace. The ToDo file remains editable. The production agent and reviewer can read project files, earlier `todo_result` reports, and new artifacts. The production request continues to reference the ToDo file, task number, and result file; the runner does not replace it with an extracted standalone task.

## Preamble

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

Immediately before every central AutoBuild call, the active ToDo file is read again. The same embedded original request reaches production, review, correction, and subsequent review. Breakdown, children, parent review, and the optional Python worker also receive the preamble. For a subworkspace, its active ToDo copy is used.

Within one central invocation, including its bounded attempts, this preamble remains fixed. The next central invocation reads changes again; the review of an already-started attempt does not receive a retroactively changed prompt. Standalone AutoBuild receives exactly the task passed to it and does not load a preamble automatically.

UTF-8, a single BOM at the start of the file, and LF/CRLF are supported. The embedded prefix is preserved including whitespace and line endings; the BOM is not part of the context text. More than **65,536 UTF-8 bytes**, read errors, or invalid encoding cause an error; there is no silent truncation. Referenced files are not automatically expanded into the prefix. Text and byte count are logged without hash labels, signatures, or additional access rights. Full prompts also appear in the normal run archive and dry-run preview.

## Existing task semantics

- `<id>. Auftrag: ...`, `<id>. Task: ...`, and `<id>. ***Task***: ...` remain readable. New marked entries use `<id>. ***Task***: ...`. `***SYNTAX marked-en***` and `--todo-syntax` control emitted spelling; examples or comments do not change it.
- Unique, ascending IDs and the existing numbering remain in force. Only the controller marks a successful task DONE. OBSOLETE is not successful completion and does not satisfy a WAIT dependency.
- The runner rereads the file during a run. An authorized planning task can add follow-up tasks; they are discovered and processed in the same workspace. A deliberate `--stop` boundary limits the run. Completion of a planning task does not prove completion of later work.
- CFG/WAIT apply to the immediately following entry. STOP must appear directly before the affected open task. Grammar is validated before selection, including WAIT/STOP, and before AutoBuild. Removed features or invalid directives are reported explicitly even when the remaining task list would otherwise be closed.
- Stored DONE entries satisfy `WAIT on=todo:<id>` or `WAIT on=<id>` after restart. Mere attempts and OBSOLETE do not. `group:`/`agent:` retain their existing runtime states; those states are not invented from DONE entries. Bridge WAIT conditions have been removed since 1031 and are rejected with a migration message.

The complete directive reference is [todo_directives.md](todo_directives.md). There is no new board, mandatory `mission.md`, or new status database. Preamble embedding does not replace mandatory reviews or inspection of the actual artifacts.
