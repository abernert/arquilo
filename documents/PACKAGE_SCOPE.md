# Runtime package scope

ARQUILO distributes one standard-library runtime, selected by the explicit
`runtime_files` list in `lean_package.json`. The file count is checked at build
time. The ZIP includes LICENSE, NOTICE, CLI/runtime modules, documentation,
synthetic examples and the distribution tools. It excludes private workspaces,
run archives, Git history, tests and CI.

Tests and CI belong to the public development repository, not the lightweight
runtime ZIP. There are no optional runtime add-on groups to install.

Retained capabilities include task directives, bounded production/review/fix,
parent acceptance, shared budgets, runtime profiles, parallel task workers and
explicit Git opt-in. Capability/schema names from the predecessor runtime are
preserved; see [compatibility](../docs/compatibility.md).

[Build and release instructions](DISTRIBUTION.md)
