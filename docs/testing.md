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

CI is configured for Linux, native Windows and macOS with Python 3.11 and 3.13.
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
