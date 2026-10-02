# Controller safety and migration (0.3.0)

This release changes controller state storage and automatic Git semantics.
It addresses unapproved task completion, redirected controller writes,
Git over-staging, dry-run collisions, unreadable policies and preflight argv.
It does not certify the host sandbox or make an LLM review infallible.

## Plan authority and restart

On first use, inspect the task file: its existing statuses are an owner-supplied
baseline, not proof of a previous ARQUILO review. The runner then persists its
exact text outside the model workspace. New `DONE`, `OBSOLETE`, deleted/hidden
or reordered tasks and altered requirements/directives cannot silently remove
work. A normal completed task requires its separate review and a controller
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
also retain the charge. Changing an existing root/limit is refused. Start a
consciously new workspace/plan for a new execution budget, after reviewing the
previous result. This counts launches, not tokens or currency.

Old 0.2.x workspace archives are retained and never rewritten or automatically
trusted as authority. Existing work should be manually checked before starting
its first 0.3.0 baseline; use a fresh disposable smoke workspace first. Migrating
a legacy numeric-claim budget explicitly in trusted state uses the highest claim
number, not the number of remaining files.

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
python3 -B arquilo.py run --workdir /path/to/worktree \
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
