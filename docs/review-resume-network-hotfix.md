# 0.10.0 maintenance: network retry and native review entry

This maintenance change is based on PR #43, head
`5c4c15397359484aef51c188e880be4becb10c98`. The `v0.10.0` tag is not moved.
Update the executing runtime, not just the product repository under construction.

## Start with a fresh review, not a repeated producer

```sh
python3 -B arquilo.py tasklist resume-review \
  --todo 147 --capture-dir /original/state/HASH/runs/RUN/task-147/001-production
```

The command derives the original workspace, working task file, state root and
call-budget limit from the registered run. It enters the native AutoBuild review
phase directly. It does **not** execute or impersonate a successful production
call, and it does not reconstruct the original producer command for comparison.
The original task/preamble, task directives and archived workspace policy must
still match. A changed CLI start/stop boundary or prompt-catalog wrapper is not a
changed task contract. Dispatch is bounded to the selected task regardless of
whether the original run started at an earlier task.

This supports a completed producer with a missing review, an interrupted
producer, or an interrupted review. A crash may have left `run.json` in
`running`/`preparing` state or left no final capture/summary metadata. The original
registered run, task contract, archived task-list input and policy must still be
available and consistent. The normal exclusive controller-plan lock prevents
starting alongside a live controller. No historical error is converted into a
success: a new reviewer judges the **current** candidate against the original
contract. A completed old review is not reused as a shortcut; the ordinary plan
journal handles already recorded acceptance, and this entry refuses to reopen
DONE/OBSOLETE tasks.

Use the original capture directory, including its numbered `production`, `fix`
or `review` suffix. Never copy an archive into another task/state directory or
edit evidence until validation passes.

## Read-only check first

```sh
python3 -B arquilo.py tasklist resume-review \
  --check-only --todo 147 --capture-dir /original/state/HASH/runs/RUN/task-147/001-production
```

This validates the task/policy/archive binding without model calls, Git probes,
new run records or state writes. Exit 0 does **not** certify the candidate, obtain
the controller lock or reserve budget. Those gates are applied on the real run.

## Optional bounded corrections

The default performs a fresh review and stops. A valid PASS goes through the
normal controller acceptance gates; a valid FAIL leaves the task open and does
not manufacture a generic `process_stop` merely because the user requested a
review. Existing STOPs and STOPs observed in the source attempt remain blocking.

Explicitly authorize review-directed correction with:

```sh
python3 -B arquilo.py tasklist resume-review \
  --continue-on-fail --todo 147 --capture-dir /original/state/HASH/runs/RUN/task-147/001-production \
  -- tasklist run --max-steps 2 --max-retries 1
```

The sequence is review -> (only for a valid, locally repairable FAIL) fix ->
fresh review. `max_steps * max_retries` bounds **correction attempts after the
initial review**. Technical review failures do not authorize a fix. Missing
inputs and other nonlocal blockers still require operator handling. No original
production replay, automatic breakdown, other task or child task is scheduled.
Configured trusted runtime-profile preflight runs before the first authorized
fix, not before a review-only invocation. The actual backend transport retains
its normal executable, sandbox, protocol and STOP checks.

## Resources and accounting

Additional current reviewer/model/resource choices may follow
`-- tasklist run ...`. Full original CLI reproduction is unnecessary. The
short form disables MCP/skill selection and does not grant shell-network access;
the provider connection remains necessary. A task requiring incompatible MCP
settings is refused rather than silently changing its permissions. Explicit
long-form resource choices are processed by the normal runner.

Keep the original workspace, working task file and state root. The wrapper fills
omitted paths/budget from the archive, normalizes start/stop to the selected ID and
disables breakdown. Git publication, plan adoption, task-template copying,
mutable plans, workspace logs and dry-run execution are refused. Native recovery
currently supports Codex, serial primary-workspace tasks only; it does not claim
parallel-worker or subworkspace recovery.

For a review-only PASS the summary now reports `Auftraege: 0, Pruefungen: 1`
(localized console spelling may use umlauts). The shared budget consumes the
actual review, not a phantom producer slot. Legacy prose review may require its
normal separate decision call. Corrections consume their normal budgets. Spent
counts are never reset or refunded; an explicit new operator budget choice is
still a separate operator action, not inferred recovery authority.

## Candidate identity and drift checks

Every review round writes `review-candidate-NNN/manifest.json` in its new private
run log. It contains SHA-256 file hashes, lengths, executable bits, repository
HEADs and hashes of per-repository diffs. Nested repositories and uncommitted
files are included. Diffs are built from raw Git objects and current regular
files, without running worktree clean filters, textconv, external diff tools,
hooks, commits or pushes. Binary changes have object/hash identities rather than
a textual representation of their content.

The candidate is checked after the review and again immediately before controller
acceptance. A changed/added/deleted bound file, HEAD or diff blocks DONE and needs
a fresh review. Each authorized correction gets a new candidate identity.

**Scope limits:** this is a live before/after drift guard, not OS isolation
against a hostile same-user writer or a guarantee against transient ABA edits.
The manifest explicitly lists excluded Git internals, backend logs and common
dependency/cache directories (`.venv`, `venv`, `.test-env`, `node_modules`,
`__pycache__`, `.pytest_cache`, `.mypy_cache`). External references and excluded
contents are not byte-bound; the reviewer must report dependence on them and
missing required evidence. Symlink/reparse/hardlink candidate files are refused.
Limits are 100,000 entries, 8 GiB hashed content and 64 MiB per Git diff/object
operation. Exceeding a limit is a refusal, never silent truncation or acceptance.

The new `review_entry.json` preserves the source-capture path, source hashes and
historical execution diagnostics. Original archives and historical test results
are unchanged. PASS, FAIL, NOT_RUN and BLOCKED remain evidence, not permission
for the producer to write DONE. Only the ordinary controller can accept a newly
passed review after its plan, candidate, budget and STOP gates.

## Network classification retained

The original hotfix still classifies known nonterminal `request timed out` and
`waiting for network (Connection failed: error sending request)` reconnects as
diagnostics. Unknown errors, `turn.failed`, incomplete actual executions and
nonzero exits are not silently converted into successful production.

The old strict archived-success loader remains an internal compatibility API;
the public `resume-review` entry now uses the native review-first path above.

## Offline qualification

```sh
python3 -B -m unittest discover -s tests -p 'test_review_entry.py' -v
python3 -B -m unittest discover -s tests -p 'test_review_resume*.py' -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
```

Tests use synthetic transports and archives, not a real provider or the user's
private task-147 files. Local qualification is not a claim that the user's
workspace has already passed its independent review or that all native-platform
CI jobs have run for this patch.
