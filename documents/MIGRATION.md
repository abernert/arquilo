# Migration to the current ARQUILO names

Use `arquilo_doctor.py` or `arquilo.py doctor` for diagnostics. `run_todos.py`,
`autobuild.py`, `decide.py`, Markdown task syntax and `.codex_runs` are unchanged.
New configuration uses `ARQUILO_*` environment variables; newly emitted JSON
schema identifiers use `arquilo.*`. The naming change does not grant additional
sandbox, tool or network permissions and does not bypass review.

Supported predecessor inputs remain readable with a deprecation warning. The
[naming history and compatibility matrix](../docs/compatibility.md) lists the old
spellings and the migration requirements for consumers of JSON output. Old
release archives and previous run logs are historical records and are not rewritten.

Use a new installation folder and a disposable workspace for the first run.
Preserve old logs and do not merge an extracted ZIP into a live installation.
Verify capabilities, perform a dry run, then explicitly opt into the doctor
functional test and a real task. See [quick start](../docs/quickstart.md).

Removed predecessor options remain rejected rather than silently ignored; see
[historical migration notes](HISTORICAL_MIGRATION.md). There are no optional
add-on groups in the public runtime package.
