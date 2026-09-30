# Troubleshooting

Keep the original run evidence. Do not bypass a failing review, enable full
access, weaken ACLs globally, or mark tasks DONE to get past an error.

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
error. The public code includes the fix allowing diagnostic items and suppresses
the unstable-feature warning caused by its own host-skill-discovery setting.
Unknown items and tool execution events remain rejected for Decide.

## The file was created, but the review stopped

The review may have found a real blocker even when production exited normally.
Read the structured review before retrying. The inline-contract fix means that
the reviewer no longer has to open an archived `review_contract_*.json` through
PowerShell. Actual output files still need to be readable and verifiable.
A missing artifact or access failure is not automatically a semantic task defect.

## Native Windows encoding and access failures

Use explicit UTF-8 when creating text files. Mojibake in a terminal can originate
in file encoding, the shell's encoding, or its display; inspect the actual file
bytes before attributing it to the model. Do not globally change encodings or
permissions merely on the basis of a rendered console excerpt.

The native Codex sandbox must be set up for the current user. A Python unit test
on Linux, a successful login, and a WSL run do not prove native Windows sandbox
correctness. Follow the current vendor setup guidance linked in the quick start.

## Extract a small diagnostic locally

In PowerShell, from the failing workspace:

```powershell
$raw = Get-ChildItem .\.codex_runs\run_todos -Recurse -Filter autobuild_raw.jsonl |
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

## Resuming after `process_stop`

Correct the documented cause first. Preserve the marker as a timestamped file
outside the active marker path, then rerun consciously. A fresh test is often
best done in a new disposable workspace rather than by deleting evidence.
