# ARQUILO

**Turn Markdown tasks into reviewed results.**

[![CI](https://github.com/abernert/arquilo/actions/workflows/ci.yml/badge.svg)](https://github.com/abernert/arquilo/actions/workflows/ci.yml) · [Deutsch](README.de.md) · [Documentation](docs/README.md)

ARQUILO executes a Markdown task list in a project workspace. Each production or correction step receives a separate review against the original assignment. The controller decides whether to accept the task, correct it, break remaining work into smaller tasks or stop. Files, reviews and execution logs remain available for inspection. A model PASS is not a guarantee of factual correctness.

**Runtime version: 0.10.0 — public preview.** This release adds Claude Code as an alternative execution backend, separates task acceptance from Git publication, and includes four consolidated handbooks. Codex remains the default. See the [release basis and remaining limits](docs/integration-status.md).

## Choose a handbook

| Need | Read |
| --- | --- |
| Install, run a first task and learn everyday options | [User Guide — English](docs/guides/user-guide.en.md) or [Benutzerhandbuch — Deutsch](docs/guides/user-guide.de.md) |
| Configure models, reasoning effort, resources, parallel tasks and recovery; look up every CLI parameter | [Advanced / Operator Guide](docs/guides/operator-guide.en.md) |
| Understand architecture, safety invariants, tests and packaging | [Technical / Architecture Guide](docs/guides/technical-guide.en.md) |

The handbooks are the primary instructions. The [documentation index](docs/README.md) points to examples and the separate review JSON protocol; older tutorials and configuration pages have been consolidated rather than added as competing reading paths.

## Requirements and first check

The core uses Python 3.11+ and its standard library, plus a separately installed and authenticated agent CLI. `--backend codex` is the default; `--backend claude-code` selects Claude Code for the entire run, including review and Decide, without a Codex installation or fallback. Keep the ARQUILO installation, host tools, project workspace and private state separate. Agent/Git executables and their resolved targets must lie outside model-writable workspaces. Provider/authentication settings remain with the selected runtime; do not paste credentials into a task list. Git is optional unless using Git installation/update or explicitly enabling publication.

From a complete checkout or extracted runtime ZIP, print the version and command help without a model call:

```sh
python3 -B arquilo.py --version
python3 -B arquilo.py tasklist run --help
```

On native Windows, use an installed interpreter such as `py -3.11 -B .\arquilo.py`. WSL uses Linux Python and paths. Follow the [first safe preview](docs/guides/user-guide.en.md#preview) before a real run; the handbook uses disposable synthetic inputs and a finite call budget. Real model execution uses your provider arrangement and may incur usage charges.

## Operating boundaries

Review is mandatory. Status changes, shared budgets and stop signals are controller rules, not promises enforced only by prompt wording. Workspaces and raw logs may contain confidential input; read-only and disabled shell networking do not mean local-only inference or remote read-only tools.

Automatic Git is off by default. With `--git`, selected outputs are frozen for review and publication; task acceptance and publication have separate outcomes. `--git-required` makes incomplete delivery stop the run while preserving accepted work. Read the [Git chapter](docs/guides/operator-guide.en.md#git) before enabling it.

The Claude adapter supports no named MCP servers, no reviewer Bash and no mixed-backend run. Production on Windows uses WSL2/Linux. See [backend selection](docs/guides/operator-guide.en.md#backends) and [Claude qualification](docs/claude-code-backend.md). Teams, GUI, a general pipeline runner and an ARQUILO MCP service are not implemented in version 0.10.0.

For testing and contributing, see [CONTRIBUTING.md](CONTRIBUTING.md). For vulnerability reporting and trust boundaries, see [SECURITY.md](SECURITY.md). Source is licensed under [Apache-2.0](LICENSE), with [NOTICE](NOTICE), [authors](AUTHORS.md), [third-party notes](THIRD_PARTY.md) and [version history](CHANGELOG.md).
