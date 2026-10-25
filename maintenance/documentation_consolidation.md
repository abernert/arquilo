# Documentation consolidation for PR #37

Owner review: 24 October 2026. Baseline: `774adaabd73ed41690bbdfd48fac52f838ca1c0e`.
Runtime code, prompt catalogs, VERSION, CITATION and product workflows are unchanged. The existing changelog receives only a documentation-link update; no release entry is added. No merge, tag or release is requested.

## Reading structure

Four handbooks (DE/EN user, English operator and technical), one documentation index, runnable examples and the narrow review protocol. Installation constraints explain why tools must be outside a writable workspace; no FAQ assumes a previous conversation. The User Guides include model/reasoning and other everyday options. The Operator Guide is the complete public command and configuration reference, with generated CLI defaults/choices checked against the actual parsers.

## Retirement map

| Previous document | Canonical location | Decision |
| --- | --- | --- |
| `docs/guides/README.md` | [Documentation index](../docs/README.md) | Repository-only compatibility pointer; not shipped or maintained as a second index. |
| `docs/installation.md` | [User Guide: installation](../docs/guides/user-guide.en.md#installation) | Integrate into the handbook and remove the competing standalone page. |
| `docs/quickstart.md` | [User Guide: first preview](../docs/guides/user-guide.en.md#preview) | Integrate into the handbook and remove the competing standalone page. |
| `documents/QUICKSTART.md` | [User Guide: first preview](../docs/guides/user-guide.en.md#preview) | Short compatibility pointer remains shipped because existing CLI help names this path. |
| `docs/cookbook.md` | [Operator Guide: recipes](../docs/guides/operator-guide.en.md#recipes) | Integrate into the handbook and remove the competing standalone page. |
| `docs/architecture.md` | [Technical Guide: system architecture](../docs/guides/technical-guide.en.md#system) | Integrate into the handbook and remove the competing standalone page. |
| `docs/controller-safety.md` | [Technical Guide: controller reference](../docs/guides/technical-guide.en.md#controller-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/decide-configuration.md` | [Operator Guide: Decide configuration](../docs/guides/operator-guide.en.md#decide-reference) | Repository-only compatibility pointer for the existing source reference; no duplicate guidance. |
| `docs/documentation-maintenance.md` | [Technical Guide: documentation maintenance](../docs/guides/technical-guide.en.md#documentation-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/git-publication.md` | [Operator Guide: Git](../docs/guides/operator-guide.en.md#git) | Integrate into the handbook and remove the competing standalone page. |
| `docs/operator-controls.md` | [Operator Guide: operational controls](../docs/guides/operator-guide.en.md#operator-controls-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/project-logs.md` | [Operator Guide: logs](../docs/guides/operator-guide.en.md#logs-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/prompt-configuration.md` | [Operator Guide: prompts](../docs/guides/operator-guide.en.md#prompts) | Integrate into the handbook and remove the competing standalone page. |
| `docs/review-resume.md` | [Operator Guide: recovery](../docs/guides/operator-guide.en.md#recovery-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/testing.md` | [Technical Guide: testing](../docs/guides/technical-guide.en.md#test-reference) | Integrate into the handbook and remove the competing standalone page. |
| `docs/troubleshooting.md` | [Operator Guide: troubleshooting](../docs/guides/operator-guide.en.md#troubleshooting-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/CONFIGURATION.md` | [Operator Guide: CLI reference](../docs/guides/operator-guide.en.md#cli-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/DISTRIBUTION.md` | [Technical Guide: distribution](../docs/guides/technical-guide.en.md#distribution-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/PACKAGE_SCOPE.md` | [Technical Guide: distribution](../docs/guides/technical-guide.en.md#distribution-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/MIGRATION.md` | [Operator Guide: migration](../docs/guides/operator-guide.en.md#migration-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/TODO_PREAMBLE.md` | [Operator Guide: task format](../docs/guides/operator-guide.en.md#task-format-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/todo_directives.md` | [Operator Guide: directives](../docs/guides/operator-guide.en.md#task-directive-reference) | Integrate into the handbook and remove the competing standalone page. |
| `documents/WORKFLOW_LIMITS.md` | [Operator Guide: workflow limits](../docs/guides/operator-guide.en.md#limits-reference) | Integrate into the handbook and remove the competing standalone page. |
| `RUNTIME_PROFILE_API.md` | [Operator Guide: runtime profiles](../docs/guides/operator-guide.en.md#profiles) | Integrate into the handbook and remove the competing standalone page. |
| `docs/pipeline-mvp-concept.md` | [Pipeline design proposal](../design/pipeline-mvp-concept.md) | Move to repository-only design; do not ship an unimplemented proposal as operating instructions. |

Keep SECURITY, licenses/notices, contributor/community metadata, CHANGELOG, the integration-status notice and the review protocol for their distinct purposes. Keep historical compatibility pages in the repository only, not in the runtime ZIP. Old standalone pages remain available in Git history. The normal navigation no longer offers several alternative instruction trees.

## Correctness and remaining blocker

The manuals describe the existing Git snapshot coupling, not an unimplemented fallback. Capacity failures can still prevent ordinary review with --git enabled. The requested separation of optional publication from production/review remains a code follow-up and a reason not to approve the integrated Git behavior solely from a green documentation run.

Documentation-specific tests that depended on removed page paths must point to the new authoritative chapter while retaining their semantic assertions. No behavioral test or controller acceptance condition is relaxed. New full-source CI is required for this documentation commit; prior 769-test acceptance belongs to the previous commit.

## Distribution

Baseline package: 105 entries. Revised package: 80 entries. Runtime Python/scripts remain packaged as before; the reduction is documentation-only apart from one machine-readable CLI reference. Repository-only generation/check scripts are not runtime dependencies.


## Combined backend/publication integration, 25 October 2026

The earlier 105-to-80 reduction describes the handbook-only #37 edition. The
new combined manifest also includes the Claude/agent runtime modules,
`docs/claude-code-backend.md`, `git_publication_cli.py` and
`git_publication_state.py`. Counts are derived from `documents/lean_package.json`;
the previous number is not the current distribution contract. The four manuals
remain canonical, and `docs/architecture.md` remains retired. The Claude page
is focused qualification evidence, with normal usage/architecture in the manuals.
