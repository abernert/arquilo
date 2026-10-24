# Git integrity repair acceptance

Base: `557f4f1b9b1959002a0677315f809426de1aab9b`, the tested state-I/O
repair PR #35. This is a separate, stacked repair: no merge, version bump,
new tag or published-asset replacement is part of this work.

## Control map

| Finding | Repair | Principal regression |
| --- | --- | --- |
| AQ-15-01 | Capture before mandatory review; bind private result to run/task/attempt/round/parent; commit exact verified snapshot bytes | Post-review/late edits, modified manifests/files, reused/foreign tokens, real controller and private Python worker |
| AQ-15-02 | Query the actual remote instead of trusting local tracking refs; publish only one direct child of its expected commit | Forged upstream tracking ref with unselected unpublished parent |
| AQ-15-03 | Raw/plumbing inspection with fsmonitor/hooks disabled; private object building and transport do not inherit source filters/helpers | Source filter, fsmonitor, reference/pre-push hook and receive-pack canaries |
| AQ-15-04 | Exclusive real-index reservation plus Git-prepared HEAD/branch transaction and post-prepare symbolic-identity check | Concurrent index writer, same-OID branch switch, existing lock ownership, preserved unrelated staging |
| AQ-15-05 | Pin the effective endpoint, isolate source config, and use an exact old-OID lease | Target swap immediately before push; remote advance after last query |
| AQ-15-06 | Private publisher has one explicit refspec, no tag following or source remote mirror/refspec settings | Mirror config, extra tag refspecs and existing tag-following regressions |

The map describes the implemented mechanisms and tests, not an independent
certification of all possible Git configurations. Host authentication helpers,
Git/OS binaries, remote server behavior and the effective sandbox remain trusted
boundaries. Broader controller process/resource hardening remains separate.

## Compatibility

See `docs/git-publication.md`. The low-level `ReviewedGit.commit` Python API now
requires an explicit accepted `ReviewedCandidate`; it never creates a review
candidate after the supposed review. Controller CLI options do not change.
Update controller and Python workers together. Serial subworkspace operation
retains its relative path in the copy. `CFG parallel` with Git, split indexes,
task-plan selection, linked context, large snapshots/history packs, custom
transport helpers and local remotes inside the workspace fail closed.

The user index, local branch and remote are not a single atomic transaction.
Private old/new index candidates survive failures. A failed/uncertain push may
leave a valid local commit and a reviewed DONE task in a failed run; inspect
before retrying. Never reset state or rewrite old commits as automatic recovery.

## Verification

Run the complete repository suite, the targeted Git tests and package checks:

```sh
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s tests -p test_git_integrity.py -v
python -B scripts/check_release.py
python -B scripts/build_runtime_zip.py --help
```

Existing Git assertions remain. Their explicit synthetic-review fixture is
repository-only; it is not shipped. The remote-divergence fixture now advances
a local bare remote directly rather than rewriting/resetting the owner's index.
Post-local-commit races intercept the ref transaction instead of the removed
unsafe direct real-index update. These changes preserve the tested invariants.
Use exact CI commit identities and report platform-specific skips separately.
No live model or external remote is used in these regressions.

Docs PR #33 is an independent open branch based on released 0.9.1. Before combining
it with this repair, retain its guides and update their Git sections to reference
this contract; reconcile the runtime allowlist/count rather than replacing either
branch's additions. Do not describe the old release ZIP as containing this repair.
