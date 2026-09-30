# Testing and evidence

## Offline automated tests

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
```

The suite uses only the Python standard library. It does not authenticate, call
Codex, send project data to a provider or incur model usage. Where a controller
expects Codex, tests inject deterministic fake results.

Covered areas include inline review contracts, mandatory read-only review,
correction rounds, archive preservation, Decide event restrictions, CLI
forwarding, dry-run behavior, version consistency, release-license inclusion,
allowlist isolation and ZIP overwrite protection.

CI is configured for Linux, native Windows and macOS with Python 3.11, 3.12 and 3.13.
The exact commit's Actions run is the source of truth for its outcome; merely
including a workflow file does not mean that a job passed.

## Live acceptance — explicit and separate

In a new disposable workspace, record OS, Python version, Codex version and
model. Run the doctor without and then with `--check-decide`. Run the minimal
task and independently verify its output and controller status. Next test a
bounded correction and a controlled stop. Never use client secrets or important
files for these first tests.

A complete native-platform acceptance also needs positive and negative sandbox
checks: permitted reads/writes work; prohibited writes and unintended tool paths
do not. Do not infer those negative checks from a successful “create empty file”
test. Human domain review remains necessary for consequential outputs.

No live provider call or comprehensive native-sandbox certification is claimed
by the offline publication tests. User-reported doctor success during prior
Windows troubleshooting is useful evidence, but not a blanket release approval.

## Distribution check

The runtime ZIP deliberately excludes tests, CI, Git history and workspaces.
It includes licenses, documentation, examples and its own build tools. Tests
verify that an extracted ZIP can display help and be repackaged without access
to the original checkout. SHA-256 sidecars are integrity checks, not proof of
origin, chronology or code quality.

## Naming regression guard

Release checks also reject the former project name in active source, examples
and documentation. Explicitly historical attribution, migration notes and
input-compatibility tests are allowlisted; rejected predecessor options remain
rejection-only. Tests cover the doctor entry point and output, canonical
configuration precedence, same-version schema aliases, budget preservation and
package contents. These are offline checks, not live model or sandbox claims.

## Real Codex metadata compatibility (opt-in locally; no model calls)

The `Codex metadata compatibility` workflow checks upstream 0.154.0 (without
`daemon_auto_start`) and 0.159.1 (with it) on Linux, Windows and macOS using
Python 3.12 and isolated temporary homes. CI downloads an exact upstream release
asset and verifies its SHA-256 digest before extracting only the CLI executable.
It does not update a user's installation, load personal credentials, or send
model prompts. The workflow runs on pushes and pull requests to main and can
also be triggered manually. Outcomes must be read from the exact CI run.

See `scripts/install_test_codex.py` and `scripts/check_codex_features.py`; run
these locally only when intentionally testing external executables. The
standard offline unit-test command does not download or execute these binaries.

Offline tests separately simulate wrong values, ignored overrides, malformed and
duplicate catalogs, missing mandatory controls, interruptions, no-model failures,
independent per-call negotiation and the full decision archive path. These tests
cannot prove live model access or native sandbox behavior.
