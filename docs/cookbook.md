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
