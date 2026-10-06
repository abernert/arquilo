# Controller safety and state management

This document describes the current controller authority, state storage, restart, filesystem and Git safeguards. These controls were introduced and strengthened across earlier releases; the legacy 0.2.x → 0.3.0 migration is documented separately below. They do not certify the host sandbox or make an LLM review infallible.

## Plan authority and restart (strict default)

On first use, inspect the task file: its existing statuses are an owner-supplied
baseline, not proof of a previous ARQUILO review. The runner then persists its
exact text outside the model workspace. New `DONE`, `OBSOLETE`, deleted/hidden
or reordered tasks and altered requirements/directives cannot silently remove
work in the default strict mode. A normal completed task requires its separate review and a controller
status transition. A breakdown may insert only open direct children in the
correct block while preserving existing tasks and requirements. Parent
acceptance still requires a separate review after the children complete.

The same plan journal is checked on restart. A pending approved status write can
recover from its journal; an unrelated third value is rejected. Two controllers
cannot concurrently own the same plan. Parallel worker copies are also checked.

For deliberate owner edits, stop the runner, inspect the changes, and run once
with `--accept-plan-changes`. The preceding baseline is archived. This flag is
an explicit owner override, not an automatic repair for an integrity alert.
Do not leave it permanently enabled. It does not reset budgets. Alternatively,
restore the plan from the controller evidence and rerun normally.

## Where state and logs live

For readable project IDs, timestamped run folders and direct failure-log paths,
see [project logs](project-logs.md). `--project-id` changes the log namespace,
not the persistent plan/budget directory. Keep the same state root on restart.


The task runner prints its actual log paths. It keys a controller directory by
the canonical workspace and task-file path under:

| Platform | Default root |
| --- | --- |
| macOS | `~/Library/Application Support/ARQUILO/controller` |
| Linux | `~/.local/state/arquilo/controller` |
| Windows | `%LOCALAPPDATA%\ARQUILO\controller` |

Use `--state-dir PATH` to choose a trusted user-owned local root outside the
workspace (and not an ancestor of it). POSIX roots must have mode 0700 and be
owned by the current user. Windows roots must have private user ACLs; the default
LocalAppData is preferable to shared/public folders. Network/UNC/device paths
are not supported for these controller records.

Each plan directory contains `plan.json`, `controller.lock`, `runs/`,
`breakdowns/`, `call_budgets/` and, after owner adoption, `owner-adoptions/`.
The model does not need write access to any of them. Review contracts still go
inline in the review prompt. Diagnostic copies may contain confidential input;
external storage does not encrypt or anonymize them.

The Doctor retains its own `.codex_runs/arquilo_doctor` diagnostics. Standalone
AutoBuild logging options also remain separate from runner log placement.

Do not delete controller state to bypass an error. A root task's monotonic call
counter is shared by children/reviews and retained across restart. Deleting a
diagnostic claim does not refund a reservation. Failed writes after reservation
also retain the charge. Changing a root identity is refused. The owner may change its limit while
retaining consumption; default 0 removes an older finite limit on continuation.
Never switch state stores to reset a counter. An existing stop instruction is
separate and remains effective. This counts attempts, not tokens or currency.

## Legacy migration from 0.2.x

Old 0.2.x workspace archives are retained and never rewritten or automatically trusted as authority. If a plan or workspace was last used with 0.2.x, manually inspect it before establishing its current controller baseline and use a fresh disposable smoke workspace first. This is a historical migration path; current installations do not need a special 0.3.0 upgrade step. Migrating a legacy numeric-claim budget explicitly in trusted state uses the highest claim number, not the number of remaining files.

## Filesystem boundaries

Controller-generated writes and archived reads reject symbolic links, Windows
reparse points/junctions, hardlinked files and non-regular files. Parent traversal
is anchored with POSIX directory descriptors or Windows no-delete-sharing parent
handles; a replaced path cannot redirect a write to an outside target. Explicit
owner-selected workspace roots are canonicalized once. Normal macOS OS-owned
`/var`, `/tmp` and `/etc` aliases are normalized to `/private/...`.

Use real files/directories for internal control paths. If an old `.codex_runs`
is a link, the runner refuses it instead of following it. Keep UAC enabled; do
not solve permission errors with administrator mode or broad ACL grants.
This is not protection against arbitrary hostile processes with the same user
credentials or against trusted preflight programs; native Codex confinement and
its integrations remain separate security boundaries.

## Explicit Git selection and publication

Run from the Git worktree root. Commit or stash pending edits of selected files
first; initially absent selected output files are fine. Unrelated staged,
unstaged and untracked files are left alone.

```sh
python3 -B arquilo.py tasklist run --workdir /path/to/worktree \
  --todo-file /path/to/worktree/tasks.md \
  --git --git-path tasks.md --git-path hello.txt --git-path todo_result_1.md
```

Paths are literal, relative filenames, not glob patterns or whole directories.
Internal `.codex_runs`, `.git` and `process_stop` paths cannot be selected, even
if tracked. ARQUILO constructs the commit with a separate index and frozen file
bytes. It does not run Git clean filters or commit hooks; exact bytes are retained.
Changes to the branch or staging index outside the runner cause a refusal.
Do not change the worktree/index concurrently. The selected paths are authorized
for this run, not a blanket secret scan or per-file correctness guarantee.

Add `--git-push` **only** when publication to the configured upstream is intended.
HEAD must initially match that upstream; unrelated unpushed commits are not
published automatically. No force push is used. Branch protection can refuse
the push; use an ordinary feature branch and pull request instead of weakening
protection. With no `--git`, no automatic Git mutation occurs.

## Smaller error cases

A dry-run report is created exclusively; existing files, including the task file
or aliases of it, are never truncated. Use a new filename for each preview.
An existing policy must be a readable regular UTF-8 file; deletion or read failure
stops execution. An intentionally empty default policy remains valid.
Preflight argv retains repeated options, empty argument values and whitespace
exactly. Its executable must be nonempty; NULs and invalid/nonfinite timeouts
are rejected. Preflight is explicit trusted host-code execution.

## Validation scope

The regression suite includes adversarial status edits, ordinary completion,
breakdown/restart/parent review, symlink and hardlink targets, a POSIX directory
swap, a native Windows junction, dry-run aliases, unreadable policies, concurrent
budget reservations, literal Git selection and disposable local-remote push tests.
They do not require model credentials or transmit project contents to a provider.

## Explicit operator choices

The plan rules above are the strict default. `--allow-todo-modifications` permits
valid primary-file changes, archives their before/after state externally, and
keeps original current-task review requirements. A mutable plan may remove or
mark tasks DONE without executing them; this is not independent verification.
For task generation followed by human review, use `--stop 2` with the opt-in.

`--logs-in-workdir` writes live diagnostics in the workspace while keeping plan,
budget and private parallel-worker return paths external. Those visible logs
can be model-edited and must not be consumed as trusted execution instructions.
The default call limit is 0 (unlimited); counting and explicit finite limits
remain. These settings never enable YOLO, extra sandbox roots or retries.
See [operator controls and migration](operator-controls.md).
