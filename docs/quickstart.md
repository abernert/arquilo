# Quick start

Run ARQUILO as an ordinary user in a disposable workspace first. Python 3.11+
is required. The core needs no `pip install`. Model calls use a separately
installed Codex CLI; follow the current [official Codex CLI documentation](https://developers.openai.com/codex/cli)
for installation and authentication. ARQUILO never installs Codex or copies
its credentials.

## macOS and Linux

From the cloned repository root:

```sh
python3 --version
python3 -B arquilo.py --version
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only
```

Then, explicitly opting into model usage:

```sh
codex --version
codex login status
python3 -B arquilo.py doctor --workdir .local-work/smoke --check-decide
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8
```

Use `codex login` first if authentication is missing. No credentials belong in
ARQUILO's repository, Markdown task lists or runtime profiles.

## Windows PowerShell

From the cloned repository root, choose an installed Python 3.11+ interpreter.
`python3.11` can be substituted for `py -3.11` when that is your installed command.

```powershell
py -3.11 --version
py -3.11 -B .\arquilo.py --version
py -3.11 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
py -3.11 -B .\arquilo.py tasklist run --workdir .\.local-work\smoke --todo-file .\.local-work\smoke\tasks.md --dry-run --dry-run-file .\.local-work\smoke\preview.md --process-stop-policy controller-only
```

After installing and signing into the native Codex CLI:

```powershell
codex --version
codex login status
py -3.11 -B .\arquilo.py doctor --workdir .\.local-work\smoke --check-decide
py -3.11 -B .\arquilo.py tasklist run --workdir .\.local-work\smoke --todo-file .\.local-work\smoke\tasks.md --process-stop-policy controller-only --max-calls 8
```

Configure the native Windows sandbox through Codex's documented setup, not by
loosening ARQUILO's policy or routinely launching it as Administrator. See the
[official Windows guidance](https://developers.openai.com/codex/windows).
Spaces in paths are supported; quote explicit paths. Create task files as UTF-8.
PowerShell 5.1's default file encodings differ from modern PowerShell: use an
explicit UTF-8 encoding, or Python's `Path.write_text(..., encoding='utf-8')`.
The sample-copy commands above avoid re-encoding Markdown through the shell.

## What success looks like

The `hello.txt` file exists with zero bytes, `todo_result_1.md` describes the actual
checks, and the controller changes task 1 to DONE after a separate passing
review. Inspect the external controller run directory printed by the runner for its evidence.
See [state locations](controller-safety.md#where-state-and-logs-live).
Never manually mark DONE simply to make a test pass.

The creation command deliberately refuses to overwrite an existing smoke
workspace. For a fresh test, choose another name such as `.local-work/smoke-2`.
For continuation, inspect the previous stop reason and correct it before moving
an old `process_stop` marker aside; preserve the logs.

## Optional controls

`--model MODEL_ID` chooses an available model. Use a model ID supported by your
own Codex account; ARQUILO does not promise access to any named model.
`--max-calls` is a shared per-task-tree call count, not a monetary/token cap.
A preliminary runner probe is outside that budget. `--network-access` and
`--git` with explicit `--git-path` selections are opt-ins, not needed for the examples. See the
[detailed configuration reference](../documents/CONFIGURATION.md).

## Three different checks

- `doctor` without `--check-decide` probes local setup and CLI metadata only.
- `doctor --check-decide` tests one restricted decision, if setup permits it.
- A real task tests production, review, artifact handling and controller flow.

None is a comprehensive security certification. [Testing details](testing.md).

## Planning pause and optional workspace logs

The default call budget is unlimited (`--max-calls 0`); the explicit limit of
8 in the smoke examples is intentional. Existing finite runner budgets adopt
unlimited on continuation unless a positive limit is supplied. This does not
clear an existing stop file or remove other limits.

Use `--allow-todo-modifications --stop 2` when task 2 should add future tasks to
the same file and then pause for human review. `--logs-in-workdir` optionally
writes live diagnostics under `.codex_runs/run_todos`. See
[the complete planning/continuation example](operator-controls.md).
