# Migration to ARQUILO

The public project is now ARQUILO. The initial public preview is version 0.1.0.
Keep existing `run_todos.py`, `dora_doctor.py`, `DORA_*` variables, `dora.*` schemas
and Markdown task syntax unchanged. `arquilo.py` provides a new public front door
without renaming these interfaces.

Use a new installation folder and a disposable workspace for the first run.
Preserve old logs and do not merge an extracted ZIP into a live installation.
Verify capabilities, perform a dry run, then explicitly opt into the doctor
functional test and a real task. See [quick start](../docs/quickstart.md).

Removed predecessor options remain rejected rather than silently ignored; use
the supported core configuration described in [CONFIGURATION.md](CONFIGURATION.md).
There are no optional add-on groups in the public runtime package.

[Compatibility policy](../docs/compatibility.md)
