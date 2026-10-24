# Reviewed Git publication

This page describes the **unreleased Git-integrity repair checkout based on
0.9.1**. It does not change the already published 0.9.1 ZIP or tag. Use the commit
identity, not just the unchanged preview version string, to distinguish this
checkout from that release.

[Exact integration baseline](integration-status.md) · [Operator Guide](guides/operator-guide.en.md#git)

## Scope and normal use

Git remains optional. Without `--git`, task execution neither needs Git nor uses
the publication machinery described here. With `--git`, select ordinary output
files explicitly; push additionally requires `--git-push`.

```sh
python3 -B arquilo.py tasklist run \
  --workdir /absolute/path/to/worktree \
  --todo-file /absolute/path/to/worktree/tasks.md \
  --git --git-path src/example.py --git-path tests/test_example.py
```

Use the actual Git working-tree root. Selected paths are literal relative file
names, not patterns. Files must be clean or absent at startup. Commit the owner's
initial task plan manually before starting, but **do not select the task plan,
controller logs or automatically rewritten result reports as Git outputs**.
The controller changes their statuses/report sections after review. Unrelated
staged, unstaged and untracked files remain untouched.

## What is reviewed and committed

For a Git-enabled task, production and correction still run in the original
workspace. Immediately before each existing mandatory review, the controller
captures a private copy of the regular workspace files. The review runs with its
normal read-only policy in that copy, preserving relative paths. It receives the
original task contract inline and instructions identifying the selected outputs,
manifest digest and expected parent commit. There is no additional model call
solely to approve Git publication.

The copy excludes `.git`, `.codex_runs`, `.arquilo`, `process_stop` and temporary
controller-write names. The reviewer must inspect the copied files, not the
producer's claims or absolute paths into the live workspace. Tasks that depend
on executing Git inside the reviewer workspace must be redesigned or performed
without automatic Git. A manifest does not prove that a model actually examined
every file or reached a correct judgment.

A private request binds run, task, attempt, review round, parent commit and a
fresh nonce. The snapshot records exact bytes, executable modes and selected
file absences (deletions). The parent accepts this token only through its
validated successful in-process/private-worker result. Workspace summary files
cannot authorize a commit. Tokens cannot be reused for another attempt or
retargeted to a different selection.

The controller verifies the snapshot after review and at acceptance/publication.
A detected change to selected live files requires a fresh review. Even a later
race, after that comparison, cannot change commit content: objects are built
from the already verified snapshot bytes, not another live read. Such late
workspace edits are not overwritten; they can remain as uncommitted changes.

## Git execution and local transaction

The controller resolves an external host Git executable once. Repository
inspection uses plumbing and raw file/index comparisons, not `git status` or a
filter-driven clean check. Git clean/smudge filters, commit/reference hooks,
fsmonitor and automatic maintenance are not used to authorize this publication.
Built-in CRLF checkout normalization is recognized at startup when configured;
commits still contain the exact reviewed bytes rather than silently running a
filter or newline conversion.

A private bare repository outside the model-writable workspace holds verified
base objects and constructs the candidate with a private index. Only one direct
child of the expected parent can be published. A separate copy of the user's
actual index changes only selected entries; other staging remains in place.

During local publication the controller owns `index.lock`. Git's own prepared
reference transaction locks both `HEAD` and the branch it resolves to. The
controller checks the symbolic branch identity again after preparation, before
publishing the index and committing that transaction. A branch with the same
object ID is not an interchangeable destination. Existing locks are never
removed as an automatic repair.

The index, local branch and remote are **not one atomic distributed transaction**.
A failed prepared transaction restores the prior index only if its own exact
new bytes are still present and Git proves the reference did not change.
Otherwise complete recovery candidates are retained for inspection. Ordinary
Git writers honor the locks; arbitrary hostile processes with the same user
credentials can violate filesystem/lock assumptions and are not contained by
this Python controller.

## Push destination and history

An automatic push requires exactly one configured push endpoint and a normal
remote branch. The controller queries that actual endpoint at startup: its
branch must equal local HEAD. A local `origin/branch` tracking ref is diagnostic,
not authority for the remote's state.

Transport runs from the private repository to the pinned resolved URL and exact
branch, never by looking up the mutable source remote name at the last instant.
Resolved system/global host settings are captured before task execution and
passed in memory to child Git processes; local/worktree configuration, include
directives, URL rewrites and named-remote rules are not imported into the
publisher. Authentication helpers and SSH settings from those host scopes
remain trusted operator configuration. Their values are not written to review
snapshots or public reports. Configure required credentials at the host level,
not as executable helpers in a model-writable repository.

Only `http`, `https`, `ssh`, `git`, local `file` and ordinary local/scp-like
endpoints are supported. Custom external Git transport helpers are refused.
Local endpoints must be absolute and outside the task workspace. The remote
server and its own policy/hooks remain external trusted services.

The push uses an explicit lease of the form
`--force-with-lease=refs/heads/BRANCH:EXPECTED_OLD_OID`, plus one exact refspec.
This is **not permission to rewrite history**: the new commit must be the direct
child of that expected old commit. A remote change between checking and pushing
makes the lease fail, including a concurrent fast-forward. An implicit lease
based on a mutable tracking ref is never used. Tag following, mirror rules,
additional source refspecs and source pre-push hooks cannot expand the push.
Remote branch protection remains effective and may refuse it.

## Current deliberate limits

Automatic publication supports **serial task execution**. Combining it with
`CFG parallel` is refused before that parallel batch starts: a global output
selection is not yet a per-worker publication-ownership contract. Parallel work
without `--git` remains supported. A serial task can use a subworkspace; its
snapshot preserves the relative location within the root copy.

Snapshots accept ordinary single-link files and real directories only. Symlinks,
hardlinks, junctions and special files in the captured context are refused, not
followed. The limits are 32 MiB per file, 128 MiB total copied contents, 20,000
entries, depth 64 and an 8 MiB manifest. A workspace containing linked virtual
environments or very large dependency trees should use a smaller dedicated
worktree or manual Git publication; no silent context omission is promised.
Full-context checks happen at snapshot capture after production, not in a
complete startup preflight. A linked or oversized unselected file can therefore
consume a production call before refusal; a dry run does not establish snapshot
suitability. Preserve partial artifacts and resolve the context before retrying.

Git history transfer is limited to 128 MiB of pack output, 64 KiB of diagnostic
output and 60 seconds per pack operation. This can reject a large repository
before model execution. These targeted bounds do not complete the separate
project-wide process-supervision/output-quota work. Split indexes are refused
for automatic publication; convert them explicitly outside a run or publish
manually. Unsupported Git/filesystem operations fail closed.

## Failure and recovery

A valid task review and successful Git publication are different results. A Git
failure after task acceptance can leave that task marked DONE while the **run is
reported failed**; it is not reported as a successful push. A transport error can
also mean an uncertain remote result. Inspect the recorded candidate, local
commit/index and actual remote branch before any retry. Do not blindly replay
the task, delete controller state, move a tag or force-push to make the error
vanish. Completed tasks do not automatically repeat their Git step on restart.

Private artifacts are kept below `git-reviews/` and `git-publication/` in the
plan state directory. They can contain confidential workspace contents and
history; normal private-state access and retention rules apply. The successful
`git_TASK.json` diagnostic binds commit, parent, selected paths and review
manifest digest. It is evidence, not an immutable or cryptographically signed
ledger. No historical DONE entries or existing Git history are rewritten by
installing this repair.

## Validation and references

The offline tests use temporary repositories and local bare remotes. They cover
snapshot/token corruption, post-review edits, actual Python workers, forged
tracking refs, last-moment URL and remote-ref changes, host-helper canaries,
cooperating writer conflicts, retained staging and failure recovery. Model
answers are synthetic; no production provider, external push or comprehensive
native sandbox certification is claimed.

Git's [reference transactions](https://git-scm.com/docs/git-update-ref) and
[explicit push leases](https://git-scm.com/docs/git-push) describe the underlying
primitives. See [controller safety](controller-safety.md) and
[testing](testing.md) for the wider contract and its limits.
