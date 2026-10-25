# Integration baseline and release distinction

**Unreleased combined checkout, 2026-10-25. Runtime version string: 0.9.1.**
The version string alone does not identify the installed behavior. The published
v0.9.1 tag/ZIP predates the later main and integration changes listed here. This
checkout does not replace a published asset or imply a new release.

| Source input | Pinned commit | Role |
| --- | --- | --- |
| Published v0.9.1 baseline | `0c4de8a76d40821578a9aa6f544dcf5fb45d26d5` | Foundational review/plan/STOP/state/launcher repair. |
| Current main input | `cded22f337a0033a3b0934709a82e1ce3db7cdb3` | Includes merged state-I/O PR #35 and Claude-backend PR #30. |
| Consolidated integration input, PR #37 | `209d5a709da9d53bad987720b3f5dcc6cbc3a837` | Git work from #36 and the consolidated four-handbook edition. |
| Git repair source inside #37 | `48331c7210d63787c578bf925ade41da9eb806a8` | Original reviewed-byte/local/remote publication controls. |
| Original handbook source inside #37 | `0e57df59ea067596b0ab0db987347aa31e7870de` | Initial user/operator/technical guides, subsequently consolidated. |

This integration reconciles those inputs and changes publication behavior.
Runtime code is **not** claimed byte-identical to the earlier #36 or #37 tree.
The source inputs above are provenance, not a final-commit validation statement.
Use the exact combined commit, its tests and package checksum for acceptance;
a green result on one parent does not validate the combined checkout. No
version, tag or release-asset change is part of the integration.

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

Task acceptance and delivery are separate. Optional commit/push failures retain
accepted DONE work and a publication record. `--git-required` requires the
requested delivery before continuation and stops with incomplete delivery while
retaining task acceptance. `git status` and `git retry` inspect/reconcile retained
publication evidence without production or model review. They do not create a
fresh reviewed candidate from current live files. Automatic parallel Git remains
unsupported. See [publication and retry](guides/operator-guide.en.md#git).

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
