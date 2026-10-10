# Troubleshooting

Keep the original run evidence. Do not bypass a failing review, enable full
access, weaken ACLs globally, or blindly mark tasks DONE to get past an error.
The conditional owner recovery below applies only to an already passed review.

## Decide fails before a process starts

`decision_setup_failed` with zero started Exec processes indicates a preparation
failure. Inspect the reported attempt's `call.json`, specifically
`result.execution.failure.message`. This is not by itself proof of an invalid
Codex login. The start counter counts processes, not billable model requests.

An accidentally initialized Git repository at the OS user home can make the
normal temporary directory inherit a Git context. The Decide path intentionally
rejects that situation. Inspect the home `.git` before removing or renaming it;
never delete legitimate repository history blindly. Use a private, user-owned
temporary root outside such a repository when intentional isolation requires it.
Do not use a world-writable shared directory for sensitive workloads.

## A diagnostic `error` item aborts Decide

The runtime distinguishes a nonfatal item notification from a top-level fatal
error (apart from the narrow provisional reconnect notice described below). The public code includes the fix allowing diagnostic items without enabling the historical unstable host-skill-discovery setting.
Unknown items and tool execution events remain rejected for Decide.

## The file was created, but the review stopped

The review may have found a real blocker even when production exited normally.
Read the structured review before retrying. The inline-contract fix means that
the reviewer no longer has to open an archived `review_contract_*.json` through
PowerShell. Actual output files still need to be readable and verifiable.
A missing artifact or access failure is not automatically a semantic task defect.

## Review passed, but an edited task plan blocks DONE

In guarded-plan mode, editing the task file during a run (even inserting only
`***STOP***` before the next task) can fail the post-review integrity check.
A successful AutoBuild review is not yet controller acceptance: the task stays
open and the runner stops with `unapproved_plan_mutation`.

For a successfully completed ordinary task with a validated PASS review, the
runner now explicitly reports `Review für ToDo <id>: PASS` followed by conditional
manual-DONE guidance. The same text is retained in the terminal execution error
in `run.json` / `run_log.json`. It does not turn the run into a success, remove a
STOP, change a task status, or repeat production/review. No such hint is inferred
from a prose PASS, missing/invalid/failed reviews, technical execution failures,
unsafe/unreadable paths, breakdowns, parent-review subtasks or worker copies.

After the runner exits, compare the task file with the captured plan and inspect
the review and outputs. Only if your intended STOP/control edit is the sole plan
change and the reviewed assignment, requirements, context and outputs are
unchanged may you deliberately mark that task `***DONE***`. ARQUILO has not
verified those recovery conditions. Preserve the review's stated scope and any
non-blocking observations; this is owner adoption, not new independent evidence.

On the next run, retain the same workspace, task-file path and state root and
use `--accept-plan-changes` once to adopt the deliberately checked status/plan.
A STOP before the next task still pauses scheduling: remove it deliberately only
when ready to continue. Any separate `process_stop` must be inspected separately.
Do not delete controller state, edit its journal or use broad mutable-plan mode
merely to silence this error. Existing run logs are not rewritten retroactively.

## Native Windows encoding and access failures

Use explicit UTF-8 when creating text files. Mojibake in a terminal can originate
in file encoding, the shell's encoding, or its display; inspect the actual file
bytes before attributing it to the model. Do not globally change encodings or
permissions merely on the basis of a rendered console excerpt.

The native Codex sandbox must be set up for the current user. A Python unit test
on Linux, a successful login, and a WSL run do not prove native Windows sandbox
correctness. Follow the current vendor setup guidance linked in the quick start.

### Windows: sandbox setup helper is reported as `program not found`

If a shell/file tool fails with `orchestrator_helper_launch_failed` and names
`codex-windows-sandbox-setup.exe` (or a versioned/helper-prefixed equivalent),
the model is not the cause: Codex could not start the Windows sandbox helper.

This is a known failure mode of some standalone Windows launcher layouts. In
particular, `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` can exist
and pass `codex --version` while the matching `codex-resources` live only in a
versioned standalone release. Do not copy a helper from another Codex version
and do not bypass the sandbox.

Inspect the launcher and installed releases first:

```powershell
(Get-Command codex).Source
Get-ChildItem "$HOME\.codex\packages\standalone\releases" -Directory
Get-ChildItem "$HOME\.codex\packages\standalone\releases" -Recurse `
  -Filter codex-windows-sandbox-setup.exe -ErrorAction SilentlyContinue
```

For diagnosis, invoke the `bin\codex.exe` from the matching complete versioned
release directly and repeat a tiny `exec --sandbox workspace-write` test. If
that works, repair/reinstall the public launcher or put that matching release's
`bin` directory first in the current process PATH. Do not silently select a
different release. Upstream examples include openai/codex issues #30829, #32359
and #38039.

## Find a run or failed Codex process

With `--project-id`, start with `<state-root>/<project-id>/latest-run.txt`,
then inspect that run's `run.json` and `overview.log`. The failure output names
its exact `stderr_file` / `capture_directory` when available. Each capture has
`capture.json`, `stdout.bin` and `stderr.bin` under a short numbered phase folder,
not an additional `.jsonl.calls/call-<uuid>` chain. `CAPTURE:` in the Pretty log
also gives the actual path. [PowerShell walkthrough](project-logs.md).

A run marked `preparing`/`running` without `finished_at` may have been killed;
do not count it as completed. The latest pointer means latest **started**, not
latest successful. Old archive locations and contents stay unchanged.

## Extract a small diagnostic locally

In PowerShell, from the failing workspace:

```powershell
$runDir = Read-Host "Paste the controller run directory printed by ARQUILO"
$raw = Get-ChildItem -LiteralPath $runDir -Recurse -Filter autobuild_raw.jsonl |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $raw) { throw 'No AutoBuild log found.' }
Get-Content -LiteralPath $raw.FullName -Encoding UTF8 | ForEach-Object {
    try { $e = $_ | ConvertFrom-Json } catch { return }
    if ($e.item.type -eq 'command_execution' -and $e.item.status -eq 'failed') {
        [PSCustomObject]@{ Command=$e.item.command; ExitCode=$e.item.exit_code; Output=$e.item.aggregated_output }
    }
} | Format-List
```

Review and redact this output before sharing. Pretty/JSONL views may redact
prompt fragments; the captured `stdout.bin`, `stderr.bin` and `prompt.utf8` are
sensitive raw evidence, not safe public attachments. Never upload a complete
`.codex_runs` directory or any Codex `auth.json`.

## Reconnect notices, stops and genuine failures

A pre-terminal top-level event with **exactly** `type="error"` and a string
`message` matching the following text is a provisional diagnostic, not a fatal
result on its own:

```text
Reconnecting... <k>/<n> (stream disconnected before completion: websocket closed by server before response.completed)
```

Only positive ASCII integers with `1 <= k <= n` are recognized; outer whitespace
is ignored for classification but retained in raw evidence. Even `5/5` describes
an attempt, not successful reconnection or definitive failure. Additional error
fields, another message (including `error decoding response body`), and any such
notice after `turn.completed` or `turn.failed` remain fatal.

| End of this invocation | Result |
| --- | --- |
| Recognized notice, final answer, `turn.completed`, natural process exit 0 | Technical success; the normal independent review/acceptance still follows |
| Recognized notice, observed stop, evidenced controller termination | Cancelled/6; no DONE and no automatic retry |
| Terminal failure, I/O/archive/cleanup failure, timeout, or natural nonzero process exit | Failed/7, even when a stop was also observed |

An invalid review keeps its existing exit 8. A raw subprocess exit, such as
POSIX SIGTERM/-15, stays separate from the ARQUILO exit. Stop does not forgive
an archive failure or a process that naturally failed before the sentinel.
Only an actual stdin pipe break during already initiated controller shutdown
is treated as an expected abort; its diagnostic remains in the capture.

Inspect `stream_diagnostics` in the capture and returned `execution_attempts`.
These retain original notices with `event_index`, not a claim of recovery. A
capture uses `cancellation_reason`; summaries, task logs and both run-log filenames
use `process_stop_details` plus `process_stop_triggered`. A missing legacy reason
is explicitly labeled unavailable, never replaced with a technical error message.
For a pure stop, historical task/run statuses remain `incomplete`/`stopped` and
additive `termination_status` is `cancelled`. A failure with stop retains failed
status and both the real error and stop reason.

The returned `terminal_attempt` identifies the actual terminal captured invocation
by phase, index and capture directory. Do **not** take the last array element of
`execution_attempts`: a stopped correction can precede an older review in that
historically grouped array. The console prints the exact capture/stderr and
other diagnostic paths once per attempt; a different attempt is shown again.
Original archives are not rewritten. No task is retrospectively accepted.

Write a required handoff/report before creating `process_stop`: once the marker
is observed, the remaining commands in that process may be terminated.

## Resuming after `process_stop`

Correct the documented cause first. Preserve the marker as a timestamped file
outside the active marker path, then rerun consciously. A fresh test is often
best done in a new disposable workspace rather than by deleting evidence.

## Direct Codex works, but Decide fails (provider/model/proxy)

If you are still running ARQUILO 0.3.x or older, update to a current release. The pre-0.4 Decide path forced a provider, ignored user configuration and filtered provider/proxy/CA environment variables. Merely removing the model name in 0.3.1 did not fix these differences. Current Decide
inherits trusted host configuration without bulk feature overrides. Start it
from the same approved shell environment as the working CLI. Set `--profile`
only when a saved named profile is actually needed. No endpoint or model is
selected automatically. [Configuration details](decide-configuration.md).

`codex_decision_cli_failed` means required Exec flags could not be confirmed
before the model started. The Doctor no longer requires `features list` or
new experimental flags. `--model`/`--profile` support is needed only when those
selectors are used. Review the bounded diagnostics, not a complete config dump.

## Decide rejected a tool event under the configured provider

The prompt asks for a decision from supplied evidence only, and ARQUILO rejects
tool/unknown events. In the current configuration-inheritance model (introduced in 0.4.0), the host's configured integrations remain trusted;
the event gate cannot prevent or undo their execution. Inspect local Codex
configuration and use an IT-approved restricted profile where appropriate.
Do not bypass the sandbox or change a failed review to PASS.

## Controller integrity failures

Do not delete state or automatically accept modified plans. See
[controller safety and recovery](controller-safety.md) for the controller state roots,
explicit owner adoption, Git selection and no-overwrite dry-run reports.

## Old call budget blocks continuation

Use the same workspace, task path and state root. The current default
`--max-calls 0` adopts unlimited even for older exhausted budgets, preserving
their counters. Do not delete controller state. If a separate `process_stop`
file already exists, inspect its cause and partial work before deliberately
removing it. It is never automatically ignored. Human task edits may need
`--accept-plan-changes` for the next strict run.

For a generator task that writes the rest of the same task file, use
`--allow-todo-modifications --stop 2` for the planning phase. See
[operator controls](operator-controls.md).
