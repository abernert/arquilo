# Documentation guide

This page is the map of ARQUILO's documentation. Start with the path that matches what you are trying to do.

## First run

1. Read the [installation guide](installation.md) for macOS, Linux, or Windows.
2. Follow the [quick start](quickstart.md) to run the disposable smoke example.
3. Read [Security](../SECURITY.md) before using a real workspace or sensitive data.
4. Use the [cookbook](cookbook.md) for common operating patterns.

ARQUILO's core is a Python 3.11+ controller around a separately installed and authenticated Codex CLI. There is no official PyPI package in the current preview.

## Choose a document by task

| I want to... | Read |
| --- | --- |
| Install ARQUILO and its prerequisites | [Installation](installation.md) |
| Get one small task running | [Quick start](quickstart.md) |
| Copy a working command for a common scenario | [Cookbook](cookbook.md) |
| Understand the controller and review flow | [Architecture](architecture.md) |
| Understand trust boundaries before real use | [Security](../SECURITY.md) |
| Diagnose setup or runtime failures | [Troubleshooting](troubleshooting.md) |
| Understand plan authority, state, recovery, or Git safeguards | [Controller safety](controller-safety.md) |
| Generate a plan and pause before executing it | [Operator controls](operator-controls.md) |
| Find project run logs | [Project logs](project-logs.md) |
| Configure the restricted Decide path | [Decide configuration](decide-configuration.md) |
| Test ARQUILO or interpret CI evidence | [Testing](testing.md) |
| Upgrade older inputs or understand renamed/removed features | [Compatibility](compatibility.md) |
| See runnable task-list examples | [Examples](../examples/README.md) |
| Contribute changes | [Contributing](../CONTRIBUTING.md) |

## Runtime reference

| Reference | Covers |
| --- | --- |
| [Configuration](../documents/CONFIGURATION.md) | CLI/environment configuration and runtime options |
| [Task directives](../documents/todo_directives.md) | CFG, WAIT, workspaces, parallel groups, models, network and result files |
| [Task preambles](../documents/TODO_PREAMBLE.md) | Project instructions, preamble modes and dynamic follow-up tasks |
| [Review rules](../documents/REVIEW_CORE.md) | Mandatory review contract, blockers, correction and parent acceptance |
| [Workflow limits](../documents/WORKFLOW_LIMITS.md) | Call budgets, retries, continuation and stop boundaries |
| [Migration](../documents/MIGRATION.md) | Migration of older task inputs and removed features |
| [Historical migration](../documents/HISTORICAL_MIGRATION.md) | Historical names and retired behavior |

The executable implementation remains authoritative when a guide and the checked-out version differ. Use `arquilo.py run --help`, `doctor --help`, and `capabilities` to inspect the installed runtime.

## Suggested reading paths

**First evaluation:** [Installation](installation.md) → [Quick start](quickstart.md) → [Cookbook](cookbook.md) → [Security](../SECURITY.md).

**Real project:** [Security](../SECURITY.md) → [Controller safety](controller-safety.md) → [Operator controls](operator-controls.md) → [Project logs](project-logs.md) → relevant runtime references.

**Contributing:** [Architecture](architecture.md) → [Testing](testing.md) → [Compatibility](compatibility.md) → [Contributing](../CONTRIBUTING.md).
