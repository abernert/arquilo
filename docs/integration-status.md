# Integration baseline and release distinction

**Unreleased integration checkout, 2026-10-24. Runtime version string: 0.9.1.**
The version number alone does not identify these changes. They are not in the
existing v0.9.1 ZIP/tag. No merge into `main`, tag, release or replacement of
published assets is part of this work.

| Source | Pinned commit | Role |
| --- | --- | --- |
| Published baseline / unchanged main at preparation | `0c4de8a76d40821578a9aa6f544dcf5fb45d26d5` | Existing 0.9.1 release. |
| PR #35 | `557f4f1b9b1959002a0677315f809426de1aab9b` | State metadata/lock repairs for #32 and #34. |
| PR #36 (contains #35) | `48331c7210d63787c578bf925ade41da9eb806a8` | Exact code baseline for reviewed Git publication. |
| PR #33 | `0e57df59ea067596b0ab0db987347aa31e7870de` | Original DE/EN user and EN operator/technical guides. |

This integration preserves the PR #36 runtime code, prompt catalogs and workflows
byte for byte. It reconciles documentation and package lists and adds offline
integration acceptance tests. Runtime version, citation and release entries remain unchanged; one historical
documentation link in CHANGELOG is retargeted to the handbook. The original PR branches remain independent review units. Use the
integration checkout's commit and test results for deployment/review decisions;
a green result on a parent alone is not acceptance of the combined tree.

## What changed for users

Normal commands without `--git` do not use Git review snapshots. Ordinary
external Codex installations remain supported. The state-I/O fixes retain keys,
journals and used budgets; unsupported Windows atomic replacement fails closed.

With `--git`, review and selected commit bytes are bound to a private pre-review
copy. Automatic publication is serial only. Do not select the task plan or
rewritten reports. Snapshot restrictions apply to the full captured context,
not only selected outputs; `.gitignore` is not a snapshot exclusion mechanism.
There is no general early workspace preflight: an unsuitable linked environment
or large context file may stop the run after production, before review. Preserve
partial work and diagnose rather than deleting state. See [Git publication](guides/operator-guide.en.md#git).

A Git failure can leave an accepted task and reviewed local commit in a failed
run. Remote acceptance may be uncertain after a transport error. Inspect local
and remote state before retrying; task restart does not automatically replay
publication. No historical DONE state is repaired automatically.

## Remaining limits

General parent-side worker supervision, global deadlines/output quotas, detached
process containment, active trusted-preflight cancellation, stricter control
streams, broader recovery/resource hardening and permanent release gates remain
separate work. Model PASS is not truth; snapshots are not same-user isolation,
a signed evidence ledger or a distributed transaction across local/remote state.
The tests use synthetic model responses and local remotes, not real provider
quality or production credentials.

## Reading paths

[Benutzerhandbuch Deutsch](guides/user-guide.de.md) ·
[User Guide English](guides/user-guide.en.md) ·
[Operator Guide](guides/operator-guide.en.md) ·
[Technical Guide](guides/technical-guide.en.md) ·
[Testing](guides/technical-guide.en.md#test-reference) · [Documentation maintenance](guides/technical-guide.en.md#documentation-reference)

## Handbook consolidation edition

The PR #37 documentation revision consolidates overlapping instruction pages into four handbooks and a single index. The User Guides include an everyday configuration reference; the Operator Guide includes the complete generated CLI inventory and all current ARQUILO configuration layers. This documentation change does not implement the requested Git/ordinary-review separation. It changes no runtime, prompt catalog, version or product workflow. See the repository-only consolidation map for retired page locations.
