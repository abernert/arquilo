# ARQUILO

**Turn Markdown tasks into reviewed results.**

[![CI](https://github.com/abernert/arquilo/actions/workflows/ci.yml/badge.svg)](https://github.com/abernert/arquilo/actions/workflows/ci.yml) · [Deutsch](README.de.md) · [Documentation](docs/README.md)

ARQUILO executes a Markdown task list in a project workspace. Each production or correction step receives a separate review against the original assignment. The controller decides whether to accept the task, correct it, break remaining work into smaller tasks or stop. Files, reviews and execution logs remain available for inspection. A model PASS is not a guarantee of factual correctness.

**Runtime version: 0.9.1 — public preview.** This branch is an **unreleased integration checkout**, including state and Git repairs not present in the already published v0.9.1 ZIP. See the [exact baseline and remaining limits](docs/integration-status.md). No new release is implied by the unchanged version string.

## Choose a handbook

| Need | Read |
| --- | --- |
| Install, run a first task and learn everyday options | [User Guide — English](docs/guides/user-guide.en.md) or [Benutzerhandbuch — Deutsch](docs/guides/user-guide.de.md) |
| Configure models, reasoning effort, resources, parallel tasks and recovery; look up every CLI parameter | [Advanced / Operator Guide](docs/guides/operator-guide.en.md) |
| Understand architecture, safety invariants, tests and packaging | [Technical / Architecture Guide](docs/guides/technical-guide.en.md) |

The handbooks are the primary instructions. The [documentation index](docs/README.md) points to examples and the separate review JSON protocol; older tutorials and configuration pages have been consolidated rather than added as competing reading paths.

## Requirements and first check

The core uses Python 3.11+ and its standard library, plus a separately installed and authenticated Codex CLI. Keep the ARQUILO installation, host tools, project workspace and private state separate. Codex and its actual executable target must lie outside model-writable workspaces. Native provider/authentication settings remain with Codex; do not paste credentials into a task list. Git is optional unless using Git installation/update or explicitly enabling Git publication.

From a complete checkout or extracted runtime ZIP, print the version and command help without a model call:

```sh
python3 -B arquilo.py --version
python3 -B arquilo.py tasklist run --help
```

On native Windows, use an installed interpreter such as `py -3.11 -B .\arquilo.py`. WSL uses Linux Python and paths. Follow the [first safe preview](docs/guides/user-guide.en.md#preview) before a real run; the handbook uses disposable synthetic inputs and a finite call budget. Real model execution uses your provider arrangement and may incur usage charges.

## Operating boundaries

Review is mandatory. Status changes, shared budgets and stop signals are controller rules, not promises enforced only by prompt wording. Workspaces and raw logs may contain confidential input; read-only and disabled shell networking do not mean local-only inference or remote read-only tools.

Automatic Git is off by default. In this branch, enabling it couples review to bounded private snapshots; capacity failures can still block ordinary work. The requested separation of optional publication is not implemented. Read the [Git chapter](docs/guides/operator-guide.en.md#git) before enabling it. Teams, GUI, MCP service and alternative-backend branches are not part of this checkout.

For testing and contributing, see [CONTRIBUTING.md](CONTRIBUTING.md). For vulnerability reporting and trust boundaries, see [SECURITY.md](SECURITY.md). Source is licensed under [Apache-2.0](LICENSE), with [NOTICE](NOTICE), [authors](AUTHORS.md), [third-party notes](THIRD_PARTY.md) and [version history](CHANGELOG.md).
