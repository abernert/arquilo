# Compatibility and naming

ARQUILO 0.1.0 is the initial public preview of the renamed DORA Lean runtime.
The public project version is `0.1.0`; the previous internal `1.0-rc5` designation
is not a promise of public 1.0 stability.

## Intentionally retained

`run_todos.py`, `autobuild.py`, `decide.py`, `dora_doctor.py`, `DORA_*` environment
variables, `dora.*` schema identifiers, `.codex_runs` and the existing task syntax
remain intact. These are compatibility contracts, not separate public products.
The new `arquilo.py` entry point delegates to the existing CLIs.

Do not perform a global DORA-to-ARQUILO search-and-replace in integrations or
runtime profiles. Use `python arquilo.py capabilities` and the documented
feature versions. Per-contract schema versions do not follow the public package
version and are not increased for a cosmetic rename.

## Codex

The runtime checks required CLI capabilities rather than accepting a version
string alone. CLI changes can still break execution or native sandbox behavior.
Record `codex --version`, the OS, Python version and model when reporting a bug.
No Codex executable or authentication state is distributed here. Production,
review and Decide have different policies; a successful Decide smoke test does
not attest to the other paths.

## Preview policy

Expect documented changes during 0.x. New integrations should use public
entry points, explicit workspace paths and capability checks, not private Python
implementation details. Changes to a safety boundary require dedicated tests
and an explicit migration note.
