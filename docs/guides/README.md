# ARQUILO handbooks / Handbücher

**Documented runtime: 0.9.1.** These manuals describe the implemented public preview,
not functionality that exists only in feature branches or design proposals.
Documentation revisions do not by themselves change the runtime version or
replace an already published release ZIP.

| Reader / Zielgruppe | Start here / Einstieg | Scope / Inhalt |
| --- | --- | --- |
| Anwender | [Benutzerhandbuch Deutsch](user-guide.de.md) | Einrichtung, erste Läufe, Aufgaben, Ergebnisse, Stopp, Wiederaufnahme und Updates. |
| User | [User Guide English](user-guide.en.md) | Installation, first runs, task authoring, results, stopping, recovery and upgrades. |
| Power user / operator | [Advanced / Operator Guide](operator-guide.en.md) | Configuration layers, MCP, skills, profiles, prompts, parallel work, budgets, state and publication. |
| Developer / technical integrator | [Technical / Architecture Guide](technical-guide.en.md) | Module responsibilities, lifecycle, contracts, persistence, workers, transport, trust boundaries and tests. |

The two User Guides have the same chapter IDs and operational command examples.
Their prose is written for the corresponding language; machine-readable keys,
commands and supplied example filenames remain unchanged. Structural parity tests
help detect drift, but do not prove semantic translation equivalence.

## Choose a reading path

For first use, read the User Guide in your preferred language and perform the
synthetic smoke example. For a complex workflow, continue to the Operator Guide
and consult the relevant reference rather than enabling every option at once.
For code changes, read the Technical Guide and work from a full source checkout.

The [documentation map](../README.md) links the shorter recipes and canonical
references. The manuals explain workflows; they do not duplicate every option,
JSON field or historical migration note. The [configuration reference](../../documents/CONFIGURATION.md),
[task directives](../../documents/todo_directives.md), [review contract](../../documents/REVIEW_CORE.md)
and [controller safety](../controller-safety.md) remain topic references.

## Current boundaries

A model PASS is not a truth guarantee. Review-to-Git snapshot binding and broader
process supervision remain open work. The intermittent native Windows project
registry issue is tracked as [#32](https://github.com/abernert/arquilo/issues/32).
See the [Operator Guide limitations](operator-guide.en.md#limitations) before
unattended or consequential use. This documentation does not claim those defects
were repaired.

## Keep these manuals with the product

The [guide manifest](manifest.json) records audiences, languages, runtime baseline
and shared user chapters. The runtime package allowlist includes all manuals,
this index, the manifest and the maintenance instructions. Existing published
0.9.1 assets remain unchanged; a checkout or later package build includes these
new files after their documentation commit is adopted.

See [documentation maintenance](../documentation-maintenance.md) for change review,
translation parity, executable examples and release packaging checks.
