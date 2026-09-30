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

## Resuming after `process_stop`

Correct the documented cause first. Preserve the marker as a timestamped file
outside the active marker path, then rerun consciously. A fresh test is often
best done in a new disposable workspace rather than by deleting evidence.

## Doctor reports `decision_features` with an older Codex CLI

Update ARQUILO to 0.2.1 or later; updating Codex is not required merely because
`daemon_auto_start` is absent. The Doctor reports this as an optional unavailable
control and omits that override. On newer CLIs the same control must be disabled.

Run `python3 arquilo_doctor.py --json` for `decision_feature_details` (expected,
observed, availability and per-control status). `unavailable_optional` is an
accepted absence, not proof of a disabled feature. `missing_required`,
`not_confirmed`, `wrong_value` and `catalog_changed` prevent Decide execution.
Do not remove mandatory tool controls to make a test pass. From 0.3.2 Decide
does not itself force strict-config or suppress user config.

The actual Decide transport independently repeats this verification. A
`codex_decision_features_failed` result means no model process was started;
its archive retains bounded capability diagnostics, not a user config dump.

## Controller integrity failures (0.3.0)

Do not delete state or automatically accept modified plans. See
[controller safety and recovery](controller-safety.md) for the new state roots,
explicit owner adoption, Git selection and no-overwrite dry-run reports.

## Direct Codex works but corporate Decide fails

Use 0.3.2 or newer: older Decide calls could override the provider and omit
proxy/credential environment even after the fixed model default was removed.
Verify that the same approved CLI and user/managed `CODEX_HOME` configuration
are used. Do not dump credential files or redirect a corporate task to another
provider to obtain a PASS. Configured gateway/authentication errors remain
errors, without fallback. See [Decide configuration](decide-configuration.md).
