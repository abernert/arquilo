# Cookbook

Common ARQUILO operating patterns. This complements the [quick start](quickstart.md); it does not replace [Security](../SECURITY.md) or the runtime references.

Commands use `python3` on macOS/Linux. On Windows, use the corresponding `py -3.11 -B .\arquilo.py ...` form and native paths.

## Run one task

```md
1. ***Task***: Create `hello.txt` as an empty file and document verification in `todo_result_1.md`.
```

Preview before making a model call:

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --dry-run --dry-run-file /path/to/project/preview.md --process-stop-policy controller-only
```

Then run explicitly:

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --process-stop-policy controller-only
```

The producer saying it is finished is not sufficient; the separate review and controller determine completion.

## Initialize a working task list from a template

`--todo-file` remains the working task list. Add `--todo-template` to initialize
it from a local UTF-8 file **only when the destination does not exist**:

```sh
python3 -B arquilo.py tasklist run \
  --workdir /path/to/project \
  --todo-file /path/to/project/tasks.md \
  --todo-template /path/to/templates/migration.md
```

PowerShell uses the same flags with native paths:

```powershell
py -3.11 -B .\arquilo.py tasklist run `
  --workdir 'C:\Projects\Migration' `
  --todo-file 'C:\Projects\Migration\tasks.md' `
  --todo-template 'C:\Task templates\migration.md'
```

The workdir must already exist. With this option, the destination must be inside
that workdir; missing subdirectories are created safely. All relative CLI paths
remain relative to the **invocation directory**, not to `--workdir`. Quote paths
containing spaces; absolute paths are the least ambiguous choice.

The controller validates the template before any model call and publishes an
exact byte copy without overwriting a file that appears concurrently. The
original template is never written, synchronized, or passed as the working
plan. Existing destinations are used unchanged, with an informational message;
an unused template is not opened and may have moved or been deleted. Reuse the
same command to continue with the working file's existing progress.

**Initialization is an explicit preparation step and also happens with
`--dry-run`.** Such a run can create the working file and the chosen preview
report, but calls no model, changes no task status, and creates no controller
state. Without `--todo-template`, the existing dry-run behavior is unchanged.
To preview without creating a task list, provide an already-existing working
file and omit `--todo-template`. An invalid template is rejected before any
working copy is created; a later runner/profile/preflight failure can leave the
successfully initialized file for inspection and reuse.

Only the task-list file is copied. Referenced inputs, neighboring result files,
credentials, and other assets are not copied; paths in the template must make
sense in the destination workspace. No variable substitution or status reset is
performed: use a genuinely fresh template for a fresh job. Normal Git selection
and plan-authority rules are not relaxed.

A missing working file with an existing plan-specific controller directory is a
**recovery error**, not a new initialization, even if the directory is empty or
`--accept-plan-changes` was passed. Restore the working file against the existing
controller evidence. Keep the same workdir, task-file path and `--state-dir` on
continuation; selecting another state root cannot reveal state kept elsewhere.
Unsafe linked/reparse/hardlinked paths below the workspace root are rejected.
Publication fails closed on filesystems lacking the required no-replace operation;
there is no unsafe overwrite/copy fallback. This is not a security boundary
against another process with the same operating-system identity.

## Put a finite call-count guard on an experiment

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --max-calls 12 --process-stop-policy controller-only
```

The default is unlimited (`--max-calls 0`). A positive value counts ARQUILO-managed Codex execution attempts; it is not a token, currency, or provider spending limit.

## Select a model explicitly

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --model MODEL_ID --process-stop-policy controller-only
```

Use a model ID available through your Codex configuration/account. Without an override, ARQUILO preserves the trusted Codex configuration rather than inventing a fallback.

## Give one task shell network access

Task file:

```md
***CFG network_access=true web_search=disabled***
1. ***Task***: Perform the requested operation that requires shell network access and document the result.
```

Runner:

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --network-access --process-stop-policy controller-only
```

Shell network, provider communication, web search, and configured integrations are distinct paths. Disabling one does not prove that the process is offline.

## Run independent tasks in parallel workspaces

```md
***CFG parallel=analysis workspace=workspaces/analysis***
1. ***Task***: Analyze the input and write the requested artifact.

***CFG parallel=analysis workspace=workspaces/tests***
2. ***Task***: Build the requested independent test artifact.

***WAIT on=group:analysis mode=all timeout=120m on_timeout=stop***
3. ***Task***: Integrate the reviewed outputs from tasks 1 and 2.
```

Every task in a parallel group needs its own subworkspace inside the main workspace.

## Wait for another task

```md
1. ***Task***: Produce the reviewed source artifact.

***WAIT on=todo:1 mode=all timeout=60m on_timeout=stop***
2. ***Task***: Use the reviewed result of task 1.
```

A stored DONE satisfies the dependency after restart. An attempted run or OBSOLETE does not.

## Generate follow-up tasks, then stop for human review

If task 2 is deliberately a planning task:

```sh
python3 -B arquilo.py tasklist run \
  --workdir /path/to/project \
  --todo-file /path/to/project/tasks.md \
  --allow-todo-modifications --stop 2 \
  --process-stop-policy controller-only
```

After the planning task is reviewed, ARQUILO stops before later tasks are dispatched. Inspect the generated plan yourself and continue separately. Do not use `--accept-plan-changes` merely to silence an unexpected integrity error. See [Operator controls](operator-controls.md).

## Put readable diagnostics in the workspace

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --logs-in-workdir --process-stop-policy controller-only
```

This makes diagnostics agent-readable/writable. Authoritative plan, budget, and worker state remain external; workspace logs are not tamper-proof evidence.

## Group logs under a readable project ID

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --project-id migration-pilot --process-stop-policy controller-only
```

See [Project logs](project-logs.md) for the external hierarchy and continuation rules.

## Create reviewed Git commits for selected files

Git is opt-in and allowlisted:

```sh
python3 -B arquilo.py tasklist run \
  --workdir /path/to/project \
  --todo-file /path/to/project/tasks.md \
  --git --git-path src/example.py --git-path tests/test_example.py \
  --process-stop-policy controller-only
```

Selected files must be clean or absent at startup. This creates local commits only. Publishing additionally requires the explicit push option and its safeguards. Read [Controller safety](controller-safety.md) before using Git integration.

## Use per-task configuration

A task can select a subworkspace, model/profile, web-search mode, result file, or breakdown policy through `CFG`. Example:

```md
***CFG workspace=analysis model=MODEL_ID web_search=disabled result_file=todo_result_7.md breakdown=minimal***
7. ***Task***: Analyze the supplied material and write the requested result.
```

Global runner model configuration takes precedence over a per-task model override. Consult the [directive reference](../documents/todo_directives.md) rather than guessing keys; removed or unknown directives are errors.

## Continue after a stop

Before continuing:

1. inspect the stop reason and partial artifacts;
2. inspect the task file and authoritative state;
3. fix the underlying problem;
4. preserve the same workspace, task path, and state directory;
5. remove or move a stop marker only when you deliberately intend to resume.

Do not create a new state directory merely to bypass an exhausted/blocked old run. See [Workflow limits](../documents/WORKFLOW_LIMITS.md) and [Controller safety](controller-safety.md).

## Diagnose a setup problem

Start with:

```sh
python3 -B arquilo.py doctor --workdir /path/to/project
python3 -B arquilo.py doctor --help
python3 -B arquilo.py capabilities
```

Only add `--check-decide` when you intentionally want the live restricted-model check; it can consume model usage. Continue with [Troubleshooting](troubleshooting.md).

## Where to go next

- Syntax and directives: [Task directives](../documents/todo_directives.md)
- Configuration: [Configuration reference](../documents/CONFIGURATION.md)
- Mutable planning and continuation: [Operator controls](operator-controls.md)
- Safety and recovery: [Controller safety](controller-safety.md)
- Testing: [Testing](testing.md)
- More task files: [Examples](../examples/README.md)
