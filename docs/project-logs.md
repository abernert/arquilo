# Project IDs and readable run logs

Add `--project-id migration-pilot` to your **existing** task-runner command:

```powershell
python3.11 .\arquilo.py run `
  --project-id migration-pilot `
  --workdir 'D:\Migration' `
  --todo-file 'D:\Migration\tasks.md'
```

This is the same runner and the same Codex configuration. No new model,
provider, proxy, permissions or retry settings are supplied. Model calls may
incur usage as before. The Doctor is a separate diagnostic command and does not
accept `--project-id`.

## Find the logs

With the default Windows state root, new logs appear here:

```text
%LOCALAPPDATA%\ARQUILO\controller\
  migration-pilot\
    project.json
    latest-run.txt
    runs\
      2026-10-02T11-12-57.000Z\
        run.json
        run_log.json
        run_config.json
        overview.log
        task-2\
          task_log.json
          autobuild_pretty.log
          autobuild_raw.jsonl
          autobuild_summary.json
          001-production\
            capture.json
            prompt.utf8
            stdout.bin
            stderr.bin
            response.txt
          002-review\
            capture.json
            stdout.bin
            stderr.bin
```

The base directory is configurable with the existing `--state-dir`. For a
**new** project you may choose, for example,
`--state-dir "$env:USERPROFILE\ARQUILO-State"`. It must be a private local
directory outside the model workspace and not an ancestor of that workspace.
Do not change an existing plan's state root merely to move logs: that selects a
different persistent state store, not a migration. Keep the current root and
only add `--project-id` when continuing existing work.

IDs are 1-48 ASCII letters, digits, hyphens or underscores, beginning with a
letter or digit. They are normalized to lowercase on every OS. Paths, dots,
reserved Windows device names and the reserved ID `dry-run` are rejected.

One project ID is bound to one canonical workspace in the selected state root.
Several task files in that workspace can share the project ID and log view;
their plan journals, locks and call budgets stay separate. Reusing the ID for
another workspace fails explicitly. Once a task file is assigned to a project,
omitting the flag on a later run remembers that assignment. Changing its ID
silently is refused. No project ID is read from a task's model-editable text.

## Runs and attempts

A run folder uses its start time in UTC, with milliseconds. The `Z` marks UTC,
not the workstation's local time. Names sort chronologically. A collision gets
`-0002`, `-0003`, etc., allocated exclusively; no prior run is overwritten.
`--run-id`, when provided, remains a diagnostic label in the metadata rather
than determining a directory name. It does not select or resume an old run.

Inside a run, task calls use `task-2`, `task-2-0002`, etc. The task manifest
records the actual identifier/role (including parent review or breakdown).
Codex processes use sequential role folders, e.g. `001-production`,
`002-review`, `003-fix`, `004-review`. A legacy-text review requiring Decide
uses a numbered `decide` archive with its separate attempt manifest and I/O
capture below it. No repeated run/task UUID chains are added to that archive;
identities remain in JSON. External file snapshots retain their own necessary
relative paths; this does not flatten or rename user artifacts.

`latest-run.txt` is an ordinary text file containing a relative path such as
`runs/2026-10-02T11-12-57.000Z`. It identifies the **latest started** run, not the
last successful or last finished run. An older concurrent run finishing later
does not move this pointer backwards. It is informational, never plan authority.

`run.json` contains `status`, `started_at`, `finished_at`, `exit_code`, task log
paths and the controller state location. Status starts as `preparing`, becomes
`running`, and is finalized as `completed`, `failed`, `cancelled`, `stopped`,
`incomplete` or `aborted`, as applicable. A hard-killed process can leave
`preparing`/`running` with no end time: that is **not** a successful completion.
A caught preflight failure is recorded as failed. `overview.log` is a short
start/task/outcome index, not a duplicate transcript of every model message.

Technical failures print the exact captured `stderr.bin` path when a Codex
process capture exists; failures before process capture print the available
Pretty/Raw logs instead. Do not infer the cause from the most recently modified
file: check the recorded phase and the error's own path.

## Open the latest run on Windows

Use your selected state root, and a project ID that has already been assigned:

```powershell
$ProjectDir = Join-Path $env:LOCALAPPDATA 'ARQUILO\controller\migration-pilot'
$RelativeRun = (Get-Content -LiteralPath (Join-Path $ProjectDir 'latest-run.txt') -Raw -Encoding UTF8).Trim()
# This guard prevents treating an edited pointer as an arbitrary path.
if ($RelativeRun -notmatch '^runs/\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z(-\d{4})?$') {
    throw 'Invalid latest-run.txt. Inspect it without following the path.'
}
$RunDir = Join-Path $ProjectDir $RelativeRun
Get-Content -LiteralPath (Join-Path $RunDir 'overview.log') -Encoding UTF8
Get-Content -LiteralPath (Join-Path $RunDir 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json | Format-List
```

The run and capture metadata contain paths; raw stdout/stderr may contain
confidential project data. Keep the state root private. No symlink/junction to
controller records is created inside the agent workspace.

## Existing state is not moved or reset

The readable project folder is a log namespace, **not a fresh plan or budget**.
Authoritative records deliberately remain in the existing workspace+task keyed
state directory (`<state-root>/<hash>/...`). No files or absolute budget paths
are moved, copied, reset or reinterpreted. `project.json` lists each task file and
its exact controller state path; `projects.json` in the base directory records
the binding. This retains old runs as well, at their original locations.

This separation avoids an unsafe automatic state migration. Even if a readable
log folder is changed or removed, it does not refund calls or validate a changed
plan. A malformed registry, conflicting binding or redirected filesystem path
causes an error rather than silently inventing a replacement. The existing
owner-adoption rules in [controller safety](controller-safety.md) still apply.
Changing the base root or removing authoritative state is not a way to resume
safely and must not be used to bypass a failure.

Without `--project-id` and without a stored binding, the root stays compatible
with the existing `<hash>/runs` location, but new runs and captures still have
shorter names. Old archives are never rewritten. The original `run_log.json`
filename/schema remains as a compatibility snapshot; `run.json` uses
`arquilo.run_log.v2`. Code consuming capture paths should use `capture_directory`
/ `stderr_file` in errors or `CAPTURE:` in Pretty logs, not assume a `.calls`
subdirectory. Dry-runs do not create a project registry or run archive.
