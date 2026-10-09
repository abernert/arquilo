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

The `Codex metadata compatibility` workflow checks actual upstream 0.154.0 and
0.159.1 on Linux, Windows and macOS with Python 3.12 and temporary homes. CI
verifies the release digest before extracting the executable. It verifies the
minimal Exec contract and parses synthetic custom-provider/named-profile
configuration with `features list` and `mcp list` (no MCP servers), without
overrides, real credentials or a model prompt. A malformed selected profile must
fail. This metadata-only fixture is not the runtime Decide path.

See `scripts/install_test_codex.py` and `scripts/check_codex_configuration.py`.
The standard offline test command downloads/executes no upstream binaries.
`tests/test_decide_configuration.py` replaces tests of the retired bulk feature
negotiation with configuration inheritance, exact argv, explicit-only selectors,
proxy/CA/token forwarding without archival, cancellation/no-fallback behavior,
format retry and full archive tests. Neither proves a real Databricks tenant
connection or complete native sandbox enforcement.

## Real CLI against a loopback fake provider (no billed model)

The same compatibility jobs also execute `scripts/check_codex_provider.py`.
This is a real Codex process and full Decide result/archive flow, but the
Responses endpoint is a local HTTP test server with synthetic credentials.
Six cases cover config defaults, model-only override, provider-only override,
a named profile, explicit selectors overriding that profile, and provider
rejection without selecting another model/provider. The fixture checks the
actual URL, deployment name, bearer/header values, query parameters, inherited
reasoning effort, unchanged configuration and structured response acceptance.

No personal config, Databricks account or external model service is used. No
MCP servers or hooks are configured in this fixture: their startup remains
trusted Codex behavior, not an ARQUILO prevention guarantee. This test does not
validate corporate TLS/proxies, VM installation or native sandbox enforcement.
Run it locally only with an explicitly approved Codex binary:

```sh
python3 -B scripts/check_codex_provider.py --codex /absolute/path/to/codex
```

## Controller hardening regressions

`tests/test_controller_hardening.py` reproduces six audited failure classes and
tests normal completion, restart and parent review. Windows junction and POSIX
parent-swap cases are platform-specific; symlink tests explicitly skip when the
host cannot create symlinks. Git push tests use disposable local bare repos only.
These are controller regressions, not live model or comprehensive sandbox tests.

## Project log layout

`tests/test_project_logs.py` checks portable ID validation and workspace binding,
multiple independent task plans in one project, unchanged legacy journals and
budgets, remembered IDs, timestamp collisions, concurrent numbered captures,
latest-started pointers, terminal run state, exact error-file pointers, dry-run
non-mutation and symlink/hardlink/native Windows junction rejection. These are
synthetic filesystem/controller checks, not live model or MDE tests.

## Operator controls and planning pause

`tests/test_operator_controls.py` covers unlimited default and explicit finite
budgets, preserving older counters/claims on owner limit changes, stale worker
rejection, process/thread reservation races, mutable primary plans, syntax and
status evidence, original review snapshots across corrections, and human edits
on strict restart. Real controller/AutoBuild functions are used with fake Codex
outputs. The key scenario appends tasks in task 2, performs its separate review,
stops before generated tasks, and executes them only on a later invocation.

Additional tests exercise live workspace logs without moving control records,
private worker IPC despite untrusted public summaries, opt-in precedence,
retained process_stop, unchanged Codex policy, parallel batch stop boundaries,
and independent log runs. No real model, Databricks tenant or native MDE
acceptance is inferred from these regressions.

## Adversarial integration regressions

`tests/adversarial/` extends the offline suite with synthetic controller, parser,
review, state, Git, configuration and diagnostic cases. The normal full-suite
command discovers these tests; a focused run from the repository root is:

```sh
PYTHONPATH=tests python3 -B -m unittest discover -s tests/adversarial -v
```

The full-suite command remains the portable default, including on Windows.
`test_peer_review.py` adds independent boundary variants and an actual local-Git
regression for unwanted annotated tags when `push.followTags` is enabled. It uses
no external remote. The core orchestration tests supply an explicit disposable
budget directory outside their workspaces instead of requiring access to the
user's default state directory. Dedicated default-state path tests remain. The subprocess-stream fixture invokes
a local Python script through an explicitly mocked launcher resolution, so it
does not rely on POSIX shebang execution. Literal Git path tests distinguish
POSIX colon filenames from Windows invalid/stream components. These fixture
changes still require a real Windows CI run; Linux success does not certify it.

Run release/integration checks in a clean source checkout. Audit task lists,
private reports and logs should remain outside that checkout (or in an already
excluded scratch directory). A local Git ignore alone does not narrow the naming
check's filesystem walk. Do not disable that guard to hide an audit input.

A passing offline suite does not prove native Codex sandbox enforcement,
Daybreak entitlement, live model correctness, or an immutable audit archive.


## Reconnect/stop propagation regressions

Run the focused synthetic sequence suite, then the complete suite:

```sh
python3 -B -m unittest discover -s tests -p 'test_reconnect_stop*.py' -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
```

`test_reconnect_stop.py` drives actual transport subprocesses, byte capture,
EOF, terminal events and process-tree cleanup with a temporary Python CLI stub.
It covers the narrow notice grammar, successful completion, real failure,
missing completion/answer, stall/total timeout, expected post-turn cleanup,
pre-start cancellation and natural nonzero exit before stop.

`test_reconnect_stop_faults.py` injects read/log/decode/cleanup/archive faults,
orders early/late stdin errors in both queue paths, and verifies stops observed
after another shutdown cause. Barrier/queue/process-state checks establish the
ordering; short waits are watchdogs, not evidence of completion. Decide and
AutoBuild error returns retain their independent stop facts and error precedence.

`test_reconnect_stop_controller.py` tests sequential and parallel controllers,
real private Python-worker subprocesses, malformed/exit-mismatched returns,
additive/legacy JSON validation, and thread-safe per-attempt path deduplication.
Production -> FAIL review -> stopped correction explicitly tests the terminal
capture pointer; no public summary is re-read as authority. Real errors plus
stop remain failed, and no later task/phase is scheduled or marked DONE.

All fixtures and events are synthetic. They use temporary workspaces and private
state, no original user prompts/logs, credentials or model requests. Positive
cases check complete capture and cleanup; intentional archive faults must remain
visible. Keep the existing Windows/macOS/Linux and Python matrices, metadata and
loopback-provider compatibility checks. These tests validate the controller,
not a particular corporate network or live model/sandbox deployment.
