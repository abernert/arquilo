# State I/O concurrency repairs (#32, #34)

Baseline: 0.9.1 (`0c4de8a76d40821578a9aa6f544dcf5fb45d26d5`). No version/tag change.

## #32: advisory identity metadata versus atomic registry publication

The legacy-identity lookup reads `projects.json`, `project.json`, `latest-run.txt`
and `run.json` without holding the project writer's lock. Windows read handles
previously denied delete sharing, preventing an overlapping `os.replace` even
though the writer publishes an entirely new file. The new synchronized test holds
that actual reader open while registering a second plan.

Only these advisory snapshot readers now request `FILE_SHARE_READ | FILE_SHARE_DELETE`.
They do NOT grant `FILE_SHARE_WRITE`. An opened reader continues reading its old
file object while the writer atomically publishes the next object. Traversal,
parent leases, regular/single-link checks and bounded reads remain unchanged.
Ordinary controller readers retain the original strict sharing mode. This does
not alter the registry writer's lock or introduce a new lock ordering. Lookup
remains read-only and creates no new state or budgets.

## #34: simultaneous first-open of permanent shared lock files

POSIX shared append opens now first open an existing file without `O_CREAT`.
On absence they attempt `O_CREAT | O_EXCL`. Only a competing creator's `EEXIST`
authorizes reopening the existing file. All operations use the SAME anchored
parent descriptor and keep `O_NOFOLLOW | O_NONBLOCK` and post-open regular-file
validation. No sleep, generic retry or ignore-error path is added. Disappearance
following a competing creation fails closed instead of creating a second lock.
Lock files remain permanent; this code never deletes a live coordination lock.

This replaces the combined nonexclusive create/open used by the reported macOS
failure. The traceback alone does not establish a kernel-level root cause.
Native macOS validation (including the unchanged original test) is required;
a Linux or injected syscall test is not a substitute.

## Evidence

`tests/test_state_concurrency_repairs.py` checks the reader/writer overlap,
retention of both project registrations and spent budget, read-only sharing,
unchanged default Windows sharing, hardlink/symlink/size boundaries, exclusive
first creation, competing creation, failure after disappearance, and eight
synchronized two-process alias races per platform. No models or external pushes.

Native CI must also run the existing repository suite. Do not rerun a failing
native race repeatedly until green; investigate any repeatable failure. No
historical DONE entries, budget keys, counters or published release assets are
modified by this change.

## Native Windows correction

The first CI pass confirmed that delete-sharing alone is insufficient for
`os.replace`/MoveFileEx when its destination is open. The implementation now
uses the Windows `FileRenameInfoEx` atomic rename primitive with
`REPLACE_IF_EXISTS | POSIX_SEMANTICS` when ordinary replacement reports Windows
error 5 or 32. The source is opened without following reparse points and checked
as a single-link regular file; the existing parent-directory leases remain
held. It never enables write sharing, ignores read-only attributes, copies over
the target, or retries until success. Unsupported filesystems and incompatible
readers fail closed and retain the complete pending recovery file. The native
tests retain both the positive open-snapshot case and the strict-reader/in-place
write negative controls. This uses a modern Windows filesystem capability;
legacy filesystems without it cannot perform this overlapping replacement.

Platform references: Microsoft `FILE_RENAME_INFORMATION` flags and
`FILE_INFO_BY_HANDLE_CLASS`/`SetFileInformationByHandle` documentation.
