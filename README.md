# ARQUILO

**Turn Markdown tasks into reviewed results.**

[![CI](https://github.com/abernert/arquilo/actions/workflows/ci.yml/badge.svg)](https://github.com/abernert/arquilo/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**A**gentic **R**untime for **Q**uality, **U**nified **I**teration, **L**ogging and **O**rchestration.

ARQUILO executes tasks from a Markdown file in a shared workspace. A separate
review pass checks the results against the captured original request. Local
corrections are bounded; unresolved blockers stop the workflow rather than
silently becoming `DONE`. Requests, reviews and captured process output remain
available for inspection.

**Public preview: 0.6.0.** Suitable for supervised evaluation in disposable
workspaces, not a claim of production readiness or infallible verification.

[Documentation](docs/README.md) · [Installation](docs/installation.md) ·
[Quick start](docs/quickstart.md) · [Cookbook](docs/cookbook.md) ·
[Security](SECURITY.md) · [Architecture](docs/architecture.md) · [Deutsch](README.de.md)

## Find your way around

If you are new to ARQUILO, use this path:

1. **[Installation](docs/installation.md)** — prerequisites and setup on macOS, Linux and Windows.
2. **[Quick start](docs/quickstart.md)** — validate a disposable task, then make an explicit first model-backed run.
3. **[Cookbook](docs/cookbook.md)** — copyable patterns for common runs, dependencies, parallel work, planning pauses, logs and Git.
4. **[Security](SECURITY.md)** — trust boundaries to understand before using a real workspace.

The **[documentation guide](docs/README.md)** is the full map. In particular:

| Need | Document |
| --- | --- |
| Understand production → review → correction → completion | [Architecture](docs/architecture.md) |
| Diagnose a problem | [Troubleshooting](docs/troubleshooting.md) |
| Understand authoritative state, recovery and Git safeguards | [Controller safety](docs/controller-safety.md) |
| Let a planning task extend the task list, then pause for review | [Operator controls](docs/operator-controls.md) |
| Find and interpret run logs | [Project logs](docs/project-logs.md) |
| Configure restricted Decide calls | [Decide configuration](docs/decide-configuration.md) |
| Test ARQUILO or understand what CI proves | [Testing](docs/testing.md) |
| Upgrade older inputs | [Compatibility](docs/compatibility.md) |
| Browse runnable task-list examples | [Examples](examples/README.md) |

Detailed English runtime references live under `documents/`: [configuration](documents/CONFIGURATION.md), [task directives](documents/todo_directives.md), [task preambles](documents/TODO_PREAMBLE.md), [review rules](documents/REVIEW_CORE.md), and [workflow limits](documents/WORKFLOW_LIMITS.md).

For the checked-out version, CLI help and `python3 -B arquilo.py capabilities` remain the best machine-readable view of the runtime's actual interface.

## Why another agent tool?

ARQUILO focuses on the controller around task execution, not on another chat UI:

- **Explicit completion criteria:** a producer's “done” is not enough; the
  controller requires a separate review before changing task status.
- **Bounded correction and decomposition:** local fixes, child tasks and parent
  acceptance are distinct steps with shared call budgets and explicit stops.
- **Inspectable evidence:** captured original requirements, structured reviews,
  result reports and run logs stay with the project.
- **Small deployment surface:** Python 3.11+ and its standard library; no Python
  package installation, database, server or framework dependency for the core.

The runtime currently uses a **separately installed and authenticated Codex CLI**.
It is not a provider-independent backend and does not include Codex. Model access
may require a paid plan or incur usage charges under your provider arrangement.
Disabling shell networking does not make model inference local or offline.

## Start with one small task

Clone this repository, then run these commands from its root. On Windows use
`py -3.11` (or your installed newer interpreter) instead of `python3`.

```sh
git clone https://github.com/abernert/arquilo.git
cd arquilo
python3 -B arquilo.py --version
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
python3 -B arquilo.py run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only
```

The dry run does not call a model. It checks the task plan and writes the chosen
preview file. A real run is an explicit next step:

```sh
codex --version
codex login status
python3 -B arquilo.py doctor --workdir .local-work/smoke --check-decide
python3 -B arquilo.py run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8
```

The last two commands can consume model usage. The sample asks for one empty
`hello.txt` plus an evidence report. Inspect the files, `tasks.md` and the logs;
do not treat terminal prose alone as proof. The smoke workspace is intentionally
excluded from Git. Reusing its creation command refuses to overwrite an old run.

See the [PowerShell walkthrough](docs/quickstart.md#windows-powershell),
[examples](examples/README.md) and [test guide](docs/testing.md).

## What it does — and does not promise

```text
Markdown task → production → separate review → local correction, if needed
                                  ↓
                       controller accepts DONE
                       or stops / decomposes
                                  ↓
                    parent review for child tasks
```

“Separate review” means a separate execution, not necessarily a different model
or statistically independent judgement. Both passes can make the same mistake.
Tests and domain-specific acceptance checks still matter.

Production uses `workspace-write`; reviews use `read-only`. ARQUILO does not
provide its own OS security boundary: enforcement depends on Codex and the host.
Shell network access and Git actions are explicit opt-ins. The call budget is
not a currency or token cap, and the runner's preliminary Codex probe is outside
that per-task budget. Read [SECURITY.md](SECURITY.md) before real project use.

## Use your existing Codex provider

Decide inherits the trusted Codex configuration and host environment, including
custom provider authentication, `CODEX_HOME`, proxies and certificates. With no
explicit model/provider/profile override, ARQUILO sends none. It never chooses
an OpenAI fallback. See [Decide configuration](docs/decide-configuration.md) for
minimal argv, explicit overrides and the changed trust boundary in 0.4.0.
Configured integrations are trusted; rejecting a tool event is not prevention
of a tool/hook having run. Decide now requests `read-only` with no escalation.

## Controller safety and plan authority

The task runner keeps authoritative plan snapshots, persistent call reservations,
and breakdown plans **outside the agent workspace**. Run logs are external by
default; `--logs-in-workdir` selects workspace diagnostics without moving
controller authority. The initial owner-supplied plan is the baseline. In the
default strict mode, later changes to task statuses, requirements, or membership
need controller approval or explicit owner adoption; an agent-written `DONE`
cannot silently skip another task. `--allow-todo-modifications` deliberately
selects a mutable plan, but observed status changes are not independent completion
evidence.

Routine continuation uses the same private controller state and preserves call
reservations. Use `--accept-plan-changes` only after personally reviewing an
intentional owner edit; do not use it merely to suppress an integrity failure.
Keep the same trusted state root when continuing an existing plan.

Git integration is explicit: `--git` requires one or more literal
`--git-path FILE` selections. Selected files must be clean or absent at startup;
unrelated staged/unstaged files and internal archives are not swept into commits.
Pushing additionally requires `--git-push`; the default is a local commit only.
Existing dry-run reports are never overwritten.

The external controller-state and explicit Git-selection model was introduced in
ARQUILO 0.3.0. If you are migrating a plan or workspace last used with 0.2.x,
inspect it before establishing the current controller baseline; old workspace
logs are historical evidence, not controller authority. Current users do not
need a special 0.3.0 upgrade step. See [controller safety](docs/controller-safety.md)
for state locations, recovery, Git examples, and the dedicated legacy-migration
notes.

## Readable project logs

Add `--project-id migration-pilot` to your existing runner command. New logs live
under `<state-root>/migration-pilot/runs/<UTC-timestamp>/`, with a
`latest-run.txt` pointer, `run.json` status and `overview.log` index. Individual
Codex calls use short numbered phase folders and errors print their stderr path.
Keep your existing `--state-dir` when continuing a plan: authoritative state and
budgets stay in their current location. [Layout and migration](docs/project-logs.md).

## Commands and compatibility

| Command | Purpose |
| --- | --- |
| `python3 arquilo.py run --help` | Task runner and all existing runner options |
| `python3 arquilo.py doctor --help` | Local checks and optional Decide smoke test |
| `python3 arquilo.py capabilities` | Machine-readable capability contracts |
| `python3 arquilo.py package` | Allowlisted runtime ZIP and SHA-256 sidecar |

Use `run_todos.py` or `arquilo.py run` for tasks and `arquilo_doctor.py` or
`arquilo.py doctor` for diagnostics. New configuration uses `ARQUILO_*`
environment variables; JSON output uses `arquilo.*` schema identifiers.
Historical input aliases remain migration-only compatibility support; see
[naming history and migration](docs/compatibility.md).
There is no official PyPI package in this release; use this repository or its
release ZIP, not an unrelated similarly named package.

## Development and validation

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

CI runs offline controller tests on Linux, Windows and macOS with Python 3.11, 3.12
and 3.13. These tests use simulated Codex executions where relevant; a green CI
run is not proof of real model access, native sandbox enforcement or unattended
production suitability. The [testing guide](docs/testing.md) separates these checks.

Detailed ARQUILO runtime reference material is available in English:
[configuration](documents/CONFIGURATION.md), [task directives](documents/todo_directives.md),
[preambles](documents/TODO_PREAMBLE.md), [review rules](documents/REVIEW_CORE.md)
and [workflow limits](documents/WORKFLOW_LIMITS.md).

## Contributing and license

Created and maintained by **[Alexander Bernert](https://github.com/abernert)**.
Bug reports with small, sanitized reproductions and regression tests are welcome.
See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and
[the conduct guidelines](CODE_OF_CONDUCT.md). Voluntary citation metadata is in
[CITATION.cff](CITATION.cff); citation is not an additional license condition.

Copyright 2026 Alexander Bernert. Original code, documentation and examples in
this repository are licensed under **Apache-2.0**, unless marked otherwise.
See [LICENSE](LICENSE), [NOTICE](NOTICE) and [third-party information](THIRD_PARTY.md).
ARQUILO is an independent project, not an official OpenAI or Apache Software
Foundation product. External products and their marks remain their owners'.

### Commercial and proprietary use

**Commercial and proprietary use is welcome.** You may use, modify and integrate
ARQUILO into commercial products, closed-source applications and internal company
workflows under Apache-2.0. You do not have to publish your source code or
modifications, or contribute changes back.

When redistributing ARQUILO or derivative works, include a copy of the license,
retain the applicable copyright, patent, trademark and attribution notices
(including relevant [NOTICE](NOTICE) content), and prominently mark modified
files as changed, in accordance with Apache-2.0.

This is a plain-language summary, not an additional license condition or a change
to the license. See [LICENSE](LICENSE) for the full terms. Third-party components
and external services remain subject to their own terms.

## Operator controls and planning in one file

Call counting is **unlimited by default** (`--max-calls 0`). An explicit positive
limit is optional; existing finite budgets adopt the default on continuation,
retaining consumed reservations. An existing `process_stop` remains effective.

A sequential task may append the remaining tasks to its own file with
`--allow-todo-modifications --stop 2`. The generator is reviewed and the runner
stops before dispatching generated work. Inspect the file, then continue without
that opt-in; use `--accept-plan-changes` only for edits you intentionally made.
`--logs-in-workdir` optionally restores live metarunner logs under
`.codex_runs/run_todos/`. These flags do not relax Codex sandbox or review policy.
See [operator controls](docs/operator-controls.md) and the
[synthetic planning example](examples/planning_todo.md).
