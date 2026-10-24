# Documentation consolidation for PR #37

Owner review: 24 October 2026. Baseline: `774adaabd73ed41690bbdfd48fac52f838ca1c0e`.
Runtime code, prompt catalogs, VERSION, CITATION and product workflows are unchanged. The existing changelog receives only a documentation-link update; no release entry is added. No merge, tag or release is requested.

## Reading structure

Four handbooks (DE/EN user, English operator and technical), one documentation index, runnable examples and the narrow review protocol. Installation constraints explain why tools must be outside a writable workspace; no FAQ assumes a previous conversation. The User Guides include model/reasoning and other everyday options. The Operator Guide is the complete public command and configuration reference, with generated CLI defaults/choices checked against the actual parsers.

## Retirement map

| Previous document | Canonical location | Decision |
| --- | --- | --- |
| `docs/guides/README.md` | `docs/README.md` | Compatibility pointer only; ship only QUICKSTART because existing CLI help names it. |
| `docs/installation.md` | `docs/guides/user-guide.en.md`#installation | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/quickstart.md` | `docs/guides/user-guide.en.md`#preview | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/QUICKSTART.md` | `docs/guides/user-guide.en.md`#preview | Compatibility pointer only; ship only QUICKSTART because existing CLI help names it. |
| `docs/cookbook.md` | `docs/guides/operator-guide.en.md`#recipes | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/architecture.md` | `docs/guides/technical-guide.en.md`#overview | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/controller-safety.md` | `docs/guides/technical-guide.en.md`#controller-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/decide-configuration.md` | `docs/guides/operator-guide.en.md`#decide-reference | Compatibility pointer only; ship only QUICKSTART because existing CLI help names it. |
| `docs/documentation-maintenance.md` | `docs/guides/technical-guide.en.md`#documentation-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/git-publication.md` | `docs/guides/operator-guide.en.md`#git | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/operator-controls.md` | `docs/guides/operator-guide.en.md`#operator-controls-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/project-logs.md` | `docs/guides/operator-guide.en.md`#logs-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/prompt-configuration.md` | `docs/guides/operator-guide.en.md`#prompts | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/review-resume.md` | `docs/guides/operator-guide.en.md`#recovery-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/testing.md` | `docs/guides/technical-guide.en.md`#test-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/troubleshooting.md` | `docs/guides/operator-guide.en.md`#troubleshooting-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/CONFIGURATION.md` | `docs/guides/operator-guide.en.md`#cli-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/DISTRIBUTION.md` | `docs/guides/technical-guide.en.md`#distribution-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/PACKAGE_SCOPE.md` | `docs/guides/technical-guide.en.md`#distribution-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/MIGRATION.md` | `docs/guides/operator-guide.en.md`#migration-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/TODO_PREAMBLE.md` | `docs/guides/operator-guide.en.md`#task-format-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/todo_directives.md` | `docs/guides/operator-guide.en.md`#task-directive-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `documents/WORKFLOW_LIMITS.md` | `docs/guides/operator-guide.en.md`#limits-reference | Integrate into the indicated handbook and remove the competing standalone page. |
| `RUNTIME_PROFILE_API.md` | `docs/guides/operator-guide.en.md`#profiles | Integrate into the indicated handbook and remove the competing standalone page. |
| `docs/pipeline-mvp-concept.md` | `design/pipeline-mvp-concept.md` | Move to repository-only design; do not ship an unimplemented proposal as operating instructions. |

Keep SECURITY, licenses/notices, contributor/community metadata, CHANGELOG, the integration-status notice and the review protocol for their distinct purposes. Keep historical compatibility pages in the repository only, not in the runtime ZIP. Old standalone pages remain available in Git history. The normal navigation no longer offers several alternative instruction trees.

## Correctness and remaining blocker

The manuals describe the existing Git snapshot coupling, not an unimplemented fallback. Capacity failures can still prevent ordinary review with --git enabled. The requested separation of optional publication from production/review remains a code follow-up and a reason not to approve the integrated Git behavior solely from a green documentation run.

Documentation-specific tests that depended on removed page paths must point to the new authoritative chapter while retaining their semantic assertions. No behavioral test or controller acceptance condition is relaxed. New full-source CI is required for this documentation commit; prior 769-test acceptance belongs to the previous commit.

## Distribution

Baseline package: 105 entries. Revised package: 80 entries. Runtime Python/scripts remain packaged as before; the reduction is documentation-only apart from one machine-readable CLI reference. Repository-only generation/check scripts are not runtime dependencies.
