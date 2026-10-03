# Installation

ARQUILO deliberately has a small core installation surface: Python 3.11+ and the repository files. Model execution requires a **separately installed and authenticated Codex CLI**. ARQUILO does not install Codex, bundle credentials, or provide a model subscription.

For a first evaluation, use an ordinary user account and a disposable workspace.

## Prerequisites

You need Git, Python 3.11/3.12/3.13, and the Codex CLI installed using its current official instructions.

macOS/Linux:

```sh
git --version
python3 --version
codex --version
```

Windows PowerShell:

```powershell
git --version
py -3.11 --version
codex --version
```

Use the appropriate Python 3.11+ command if `py -3.11` is not your installed Windows interpreter.

## Clone ARQUILO

macOS/Linux:

```sh
git clone https://github.com/abernert/arquilo.git
cd arquilo
python3 -B arquilo.py --version
```

Windows:

```powershell
git clone https://github.com/abernert/arquilo.git
Set-Location arquilo
py -3.11 -B .\arquilo.py --version
```

The core currently requires no `pip install`. There is no official ARQUILO package on PyPI in this preview; use this repository or an official release ZIP.

## Authenticate Codex separately

```text
codex login status
```

If authentication is missing, follow the current Codex CLI login flow. Do not put credentials in the ARQUILO repository, task Markdown, runtime profiles, or example workspaces. ARQUILO uses the trusted Codex host configuration and does not silently select an OpenAI fallback provider.

## Dry-run the supplied smoke task

The dry run validates the plan without intentionally invoking a model.

macOS/Linux:

```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
python3 -B arquilo.py run \
  --workdir .local-work/smoke \
  --todo-file .local-work/smoke/tasks.md \
  --dry-run --dry-run-file .local-work/smoke/preview.md \
  --process-stop-policy controller-only
```

Windows PowerShell:

```powershell
py -3.11 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
py -3.11 -B .\arquilo.py run `
  --workdir .\.local-work\smoke `
  --todo-file .\.local-work\smoke\tasks.md `
  --dry-run --dry-run-file .\.local-work\smoke\preview.md `
  --process-stop-policy controller-only
```

Existing dry-run reports are not overwritten. Use a new smoke directory for a fresh experiment.

## Test the live model boundary

These commands can consume model usage.

macOS/Linux:

```sh
codex login status
python3 -B arquilo.py doctor --workdir .local-work/smoke --check-decide
python3 -B arquilo.py run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8
```

Windows:

```powershell
codex login status
py -3.11 -B .\arquilo.py doctor --workdir .\.local-work\smoke --check-decide
py -3.11 -B .\arquilo.py run --workdir .\.local-work\smoke --todo-file .\.local-work\smoke\tasks.md --process-stop-policy controller-only --max-calls 8
```

The explicit limit of 8 is useful for the smoke test. The normal default is `--max-calls 0`, meaning no call-count ceiling; this is not a monetary or token spending cap.

## Platform notes

### macOS

Run as an ordinary user and keep state/workspaces in locations owned by that user. If host security or filesystem permissions block Codex, grant only the minimum required permission rather than broadly weakening permissions.

### Linux

Run as an ordinary user, not root. Keep the state directory private to that user. Shell network access is not needed for the basic example and remains separate from model-provider communication.

### Windows

Use native PowerShell as a normal user. Do not routinely launch ARQUILO or Codex as Administrator and do not disable UAC as an installation workaround. Configure the native Codex sandbox using Codex's current Windows guidance.

Create task files as UTF-8. PowerShell 5.1 has older default encoding behavior, so prefer modern PowerShell or specify UTF-8 explicitly. Quote paths containing spaces. Task-directive quoting is ARQUILO text grammar, not PowerShell syntax; see the [directive reference](../documents/todo_directives.md).

## Verify the smoke result

For the supplied minimal example:

- `hello.txt` exists and is empty;
- `todo_result_1.md` describes the checks;
- task 1 becomes `DONE` only after a separate passing review;
- the runner prints the external run location containing evidence and diagnostics.

Do not manually mark the task DONE merely to make the smoke test look successful.

## Before a real project

Read [Security](../SECURITY.md), [Controller safety](controller-safety.md), and the [Cookbook](cookbook.md). Then consult the [configuration reference](../documents/CONFIGURATION.md) only for options you actually need.

Useful discovery commands:

```sh
python3 -B arquilo.py doctor --help
python3 -B arquilo.py run --help
python3 -B arquilo.py capabilities
```

On Windows, substitute your `py -3.11 -B .\arquilo.py` invocation.

## Updating an existing plan

ARQUILO stores authoritative controller state outside the production workspace. Before changing versions in the middle of an existing plan, read the release notes and [compatibility guidance](compatibility.md). Keep the same state directory when continuing a plan unless migration documentation explicitly says otherwise. A Git update alone is not evidence that an old plan is safe to resume unchanged.
