# Release 0.10.0: source basis and limits

**ARQUILO 0.10.0 — public preview, 2026-10-25.**
This version includes Claude Code support, state-I/O repairs, reviewed Git
publication and the four consolidated handbooks. Install the complete 0.10.0
runtime package or check out `v0.10.0`; do not mix individual modules from older
installations. The published v0.9.1 tag and ZIP retain their original contents.

| Source input | Pinned commit | Role |
| --- | --- | --- |
| Earlier v0.9.1 release | `0c4de8a76d40821578a9aa6f544dcf5fb45d26d5` | Foundational review/plan/STOP/state/launcher repair. |
| State-I/O merge, PR #35 | `f716aadcbb5bade403680c0cbb43d598ea26dcf1` | Immutable metadata sharing, atomic replacement and shared-lock creation repairs. |
| Claude Code merge, PR #30 | `cded22f337a0033a3b0934709a82e1ce3db7cdb3` | Alternative execution backend on the shared controller basis. |
| Reviewed integration, PR #37 | `0d5dc9a1d580ddb4b5dd571daaa46455c4e78076` | Acceptance/publication separation, durable recovery, selected-absence correction and consolidated handbooks. |
| Original Git repair source | `48331c7210d63787c578bf925ade41da9eb806a8` | Reviewed-byte/local/remote publication controls retained in the integration. |
| Original handbook source | `0e57df59ea067596b0ab0db987347aa31e7870de` | Initial four-handbook edition, subsequently consolidated and updated. |

These pinned commits identify source provenance. The `v0.10.0` tag identifies the
complete versioned release revision, including the release metadata and manuals.
In the guide manifest, `source_commit` identifies the reviewed PR #37 input and
`release_baseline` identifies the older v0.9.1 package; neither is the final
release commit. Check validation evidence and package checksums for the exact
release revision rather than inheriting a green result from a parent commit.

## What changed for users

Codex remains the default. `--backend claude-code` uses Claude for production,
fixes, review, parent review and Decide without a Codex executable/configuration
lookup or fallback. Claude deliberately has no named MCP servers or reviewer
Bash; Windows production requires WSL2/Linux. The same controller acceptance,
plan, STOP and budget rules apply. See [backend selection](guides/operator-guide.en.md#backends).

Git is optional. With `--git`, selected outputs are captured before review;
the reviewer stays in the normal workspace and receives frozen output references.
Unselected links and large context files do not require a full-workspace snapshot.
Snapshot/token/selected-output integrity remains mandatory when a candidate was
captured. Capture unavailable before review can leave publication blocked while
a valid ordinary review still accepts the task.

The Git review contract also distinguishes run-wide publication selection from
the current task's deliverables. A selected path absent both in the bound baseline
and in the snapshot is unchanged absence, not a deletion. Explicit baseline and
snapshot presence prevent a later task's not-yet-created output from becoming
a false deletion issue in an earlier task. Genuine deletions and required missing
outputs still require the ordinary review decision.

Task acceptance and delivery are separate. Optional commit/push failures retain
accepted DONE work and a publication record. `--git-required` requires the
requested delivery before continuation and stops with incomplete delivery while
retaining task acceptance. A private blocked obligation preserves incomplete
delivery across restarts even when setup, capture or receipt persistence failed
without an accepted candidate. That obligation must be durable before DONE;
failure to persist it is a controller acceptance failure.

`git status` shows receipts and blocked obligations. `git retry` reconciles an
accepted receipt without production or model review; it cannot authorize an
unbound obligation. Resolve such a block by inspecting and preserving outputs,
preparing a valid clean Git baseline for selected files, deliberately reopening
the task, adopting the inspected plan change and requesting a fresh ordinary
optional `--git` attempt. A matching successful new receipt supersedes the old block
while retaining history. Required delivery remains a barrier otherwise.
Automatic parallel Git remains unsupported. See
[publication and retry](guides/operator-guide.en.md#git).

State-I/O fixes retain keys, journals and used budgets. Keep the same workspace,
task-list path and state root when continuing. Update controller and workers
together. No historical DONE record is automatically recertified.

## Remaining limits and evidence

General parent-side worker supervision, global deadlines/output quotas,
detached-process containment, active trusted-preflight cancellation, stricter
control streams, broader recovery/resource hardening and permanent release
gates remain separate work. Model PASS is not truth; snapshots are not same-user
isolation or a signed ledger. Local state/index/branch and remote delivery are
not one distributed transaction. Synthetic fixtures and local remotes do not
establish real-provider quality, production credentials or complete native
sandbox enforcement.

## Documentation and package

The four handbooks under `docs/guides/` remain the canonical instructions. The
Operator Guide's CLI inventory is generated from the actual parsers; the
Technical Guide contains the integrated Codex/Claude architecture. The former
standalone `docs/architecture.md` is not revived. The focused Claude qualification
page records native adapter limits and compatibility evidence. The runtime
manifest includes both backend modules and the consolidated documentation;
repository-only tests, maintenance sources and future designs stay outside it.

[Benutzerhandbuch Deutsch](guides/user-guide.de.md) ·
[User Guide English](guides/user-guide.en.md) ·
[Operator Guide](guides/operator-guide.en.md) ·
[Technical Guide](guides/technical-guide.en.md)
