# Foundational control repair acceptance

Base: `35e5f17457bfd1c42b439f522f83c4d435421e1c` (0.9.0).
Development branch: `fix/control-invariants-090`. This is an unreleased repair
set; existing version metadata is deliberately unchanged.

## Implemented scope

| Audit finding | Control repaired | Principal regression evidence |
| --- | --- | --- |
| AQ-8-01 | Raw review format is parser-owned; FAIL/blockers veto COMPLETE/DONE, including worker returns and resume | `tests/test_review_completion_integrity.py`, `tests/test_review_resume.py` |
| AQ-6-01 | One accepted snapshot controls the exact task-to-DONE mutation; child adoption saves the validated bytes | `tests/adversarial/test_snapshot_authority.py` |
| AQ-7-01 | Reject physical state/workspace overlap and alternate plan identities without changing the budget key | `tests/adversarial/test_state_identity.py` |
| AQ-7-02 | Accepted original contract and bounded no-follow decision inputs; copied task/preamble evidence must match | `tests/adversarial/test_snapshot_authority.py` |
| AQ-5-01 | STOP is applied before depth/status/processed-task filters, within the explicit start/stop range | `tests/adversarial/test_control_stop_invariants.py` |
| AQ-13-04 | WAIT cannot turn an observed file stop into continuation, including `on_timeout=continue` | `tests/adversarial/test_control_stop_invariants.py` |
| AQ-17-02 | A startup stop prevents profile/Codex preflight; stop after profile preflight prevents the next probe | `tests/adversarial/test_control_stop_invariants.py` |
| AQ-12-02 | Peers receive physical stop paths; validated return-only stops are published before output copying; final acceptance rechecks stop | `tests/adversarial/test_control_stop_invariants.py` |
| AQ-12-01, path-overlap subset | Reject equal, nested or root-equal parallel workspaces before dispatch | `tests/adversarial/test_control_stop_invariants.py` |
| AQ-10-01 and confirmed Git PATH variant | External absolute launchers, physical path checks, sanitized child PATH and pinned host Git selection | `tests/test_trusted_launchers.py` |

This table is the implemented scope, not a blanket closure of the audit register.
The parallel path check does not provide a hostile-worker filesystem sandbox.

## Evidence and acceptance method

The regression tests use disposable workspaces and private controller state.
Model transport responses are synthetic. Important assertions read the actual
artifact, task Markdown and external plan journal; a reported success alone is
not the assertion. Restart tests use a new runner against preserved state.
Parallel cancellation tests launch two actual Python AutoBuild workers through
their private serialized request/summary boundary. State allocation includes a
real two-process alias race. Launcher tests execute synthetic local programs,
without credentials or external pushes.

The new review, snapshot/state, launcher and STOP regression groups were also
run against the unchanged base to demonstrate the reported failures. Expected
native filesystem skips are reported explicitly; simulated Windows path tests
do not stand in for native Windows execution.

Run the complete offline gate from the repository root:

```sh
python -B -m unittest discover -s tests -v
python -B scripts/check_release.py
python -B scripts/build_runtime_zip.py
```

The ZIP builder refuses to overwrite an existing output; choose a fresh output
path when repeating the build. Decide fixtures require a temporary root without
inherited project configuration. If the host's default temporary root is not
isolated, select an appropriate `TMPDIR` (or the native platform equivalent)
for the test process; do not disable the product guard.

The existing CI matrix is the native gate: Linux, Windows and macOS on Python
3.11, 3.12 and 3.13. The separate Codex compatibility workflow checks both
configured CLI versions with local synthetic providers. These workflows do not
make external model calls. Review the run tied to the actual PR head, not an
older green base commit.

## Compatibility and migration

- Keep the original workspace, task path and state root. No budget-key change,
  refund, state deletion or automatic counter migration is part of this repair.
- New `identity.json` records and an allocation lock protect subsequent state
  allocation. Legacy plan journals/private identity metadata can reject aliases.
  Historical standalone budget-only records without recoverable identity still
  require the original invocation paths and owner inspection.
- Controller Codex/Git/Node installations must be outside the workspace and
  selected by absolute host paths. Relative/project-local installations are
  refused. Provider, proxy, certificate and credential settings remain host
  configuration; external host installations themselves remain trusted.
- Decision input/control files must be ordinary files, not symlinks, hardlinks
  or special files. The supported Windows npm wrapper is retained.
- Update parent controller and Python workers together. The additive internal
  `process_stop_paths` context is required for cross-process cancellation.
- A stopped batch leaves its produced artifacts available and its pending
  tasks open. Resuming still requires owner inspection and fresh acceptance.
- Previously persisted invalid DONE statuses are not automatically undone.
  Review such runs separately against original evidence; do not clear the
  complete controller state to force a rerun.

## Explicit remaining work

Review-snapshot binding through Git commit/push and remote-ref authorization
need a separate repair. Broader process deadlines, output quotas, detached-child
containment and active trusted preflight cancellation also remain separate.
Other audit findings, model truthfulness, backend additions and release policy
are not certified by this change. A formal PASS remains a model assessment; the
controller now enforces its own deterministic completion rules.

Use [the repeatable task list](control_hardening_todo.md) for a fresh acceptance
run after future modifications. Its tasks remain open deliberately; it is a
template, not a retrospective claim that an ARQUILO model ran this development.
