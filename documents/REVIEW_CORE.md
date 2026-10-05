# Mandatory task-bound review

Every successful production or correction attempt receives its own Codex Exec review in the same workspace with `read-only`. The reviewer checks the original task, the effective preamble, previous result reports, and the actual current artifacts. The normal production prompt remains the reference task from the ToDo file. Narratives, analyses, and other domain tasks do not acquire an additional evidence-ledger requirement.

The pure rules, JSON validation, and prompt fragments live in [`review_contract.py`](../review_contract.py). AutoBuild and parent acceptance use the same rules; runtime profiles add to them. An empty list of additional profile rules does not remove the general rules.

## Result and correction

A current review returns this contract:

```json
{
  "verdict": "PASS",
  "short_summary": "The requested results are present.",
  "blocking_issues": [],
  "non_blocking_observations": [],
  "breakdown_recommended": false,
  "breakdown_reason": null
}
```

A blocker contains a non-empty `summary`, the violated `requirement`, and a verifiable `acceptance_criterion`. `type` distinguishes a local fix, need for decomposition, missing input, a genuine scope conflict, technical failure, and external blocking. Supplied IDs are unique; references are text lists. PASS with blockers, FAIL without blockers, mixed old/new issue fields, duplicate keys, unknown fields, wrong types, NaN/Infinity, damaged Unicode, and contradictory breakdown fields are invalid.

### Breakdown field dependencies

A non-empty `breakdown_reason` is allowed only when `verdict` is `FAIL` and
`breakdown_recommended` is `true`. The review prompt states these dependencies
explicitly for both task reviews and parent acceptance; no provider-specific
instructions or local Codex configuration are needed.

| Review outcome | `blocking_issues` | `breakdown_recommended` | `breakdown_reason` to emit |
| --- | --- | --- | --- |
| PASS | Empty | `false` | JSON `null` |
| FAIL, no breakdown needed | Non-empty | `false` | JSON `null` |
| FAIL, breakdown justified | Non-empty | `true` | Non-empty explanation of the remaining workstreams |

Use JSON `null`, not `""`, whitespace, or the string `"null"`. An explanation
of **why no breakdown is needed** belongs in `short_summary` or
`non_blocking_observations`, not in `breakdown_reason`. Do not change a verdict,
discard blockers, or request unnecessary decomposition to satisfy the format.

For compatibility the parser still accepts an omitted reason, or `null` on an
otherwise valid breakdown recommendation, and supplies its existing generic
reason when needed. Newly generated reviews should follow the table above.
The prompt clarification does not relax validation or repair conflicting reviews.

An invalid mandatory review exits with code 8 and does not trigger a blind repeat of production. A failed model call remains a technical failure while preserving prior work and logs.

Compatibility remains for unambiguous older JSON reviews containing `verdict` and `issues`. Missing historical display/metadata fields are normalized as before. Free-form legacy review text still requires a successful explicit Codex decision; structured PASS/FAIL does not require that extra call. The result contract enforces this boundary between the runner and Python worker as well. Parent acceptance itself requires a structured JSON finding.

A correction run first checks every alleged blocker against the task and artifacts. Confirmed defects are fixed with the smallest coherent change. Incorrect criticism or a demand outside scope is rebutted in the result report with task/file references, while correct domain artifacts remain unchanged. A fresh independent review always follows. Merely claiming that criticism was rebutted does not complete the task. Optional style preferences and work requested only later do not become requirements.

For a correctly performed document analysis, source defects, qualified findings, and multiple defensible interpretations are acceptable when the task permits them. For narrative work, the requested substantive and narrative constraints apply. Defects in the subject being analyzed must be distinguished from defects in the analysis or audit task itself.

## Review confidence (advisory)

New task and parent reviewers are asked to report confidence, evidence and
remaining uncertainty. The existing review classification is extended with
optional metadata; the `autobuild.review.v2` verdict/blocker contract is unchanged.
Old structured/legacy reviews remain readable. An omitted score is normalized
to `confidence: null` and `confidence_level: "unknown"`, never zero or a fabricated
high score. Older ARQUILO versions that reject unknown fields cannot consume
these extended reviews; upgrade readers and workers together.

The following is a synthetic example, not a claim about this repository's tests:

```json
{
  "verdict": "PASS",
  "short_summary": "The requested result and focused checks were inspected.",
  "blocking_issues": [],
  "non_blocking_observations": [],
  "breakdown_recommended": false,
  "breakdown_reason": null,
  "confidence": 0.86,
  "confidence_reason": "The requested behavior was observed; native Windows behavior remains unverified.",
  "confidence_breakdown": {
    "requirements_coverage": 0.95,
    "implementation_correctness": 0.9,
    "test_evidence": 0.85,
    "regression_safety": null
  },
  "evidence": [
    "Inspected example.py:10-30 against the requested behavior.",
    "Observed all 3 focused tests passing in the review environment."
  ],
  "uncertainties": ["Native Windows execution was not exercised."],
  "suggested_checks": ["Run the focused tests on Windows."]
}
```

`confidence` is the reviewer's **uncalibrated confidence that its verdict is
correct**. For PASS this is its confidence that the task meets the original
contract. A reviewer certain that a required output is missing can return
FAIL with high confidence: the score never converts that failure into success.
A score of 0.9 is not an empirically demonstrated 90% success rate.

The controller derives display bands: `low` below 0.7, `medium` from 0.7 to below
0.9, and `high` from 0.9 to 1.0. These are presentation conventions, **not
acceptance thresholds**. If a normalized input supplies a contradictory
`confidence_level`, validation fails rather than silently trusting the label.

The breakdown dimensions are separate subjective assessments, not an average:

| Dimension | Meaning; higher means stronger support |
| --- | --- |
| `requirements_coverage` | Coverage of the original explicit acceptance criteria |
| `implementation_correctness` | Support that the implementation satisfies those criteria |
| `test_evidence` | Strength of relevant observed checks |
| `regression_safety` | Support that previously working behavior is preserved |

A certain FAIL can have low `implementation_correctness` but high overall
confidence in the FAIL verdict. Use JSON `null` for unknown or inapplicable
dimensions. Writing and analysis tasks do not acquire a software-test or
additional evidence-ledger requirement: inspecting their requested artifacts
is evidence. `regression_safety` is deliberately not named `regression_risk`;
a larger number must not mean more risk.

A numeric overall score requires a non-empty `confidence_reason` and at least
one `evidence` entry. References and test statements are **reviewer-reported**,
not independently verified by the parser. The reviewer must distinguish
observed results from producer claims and must not invent tests or references.
The controller validates structure, not the truth of the assessment.
`uncertainties` records what remains unverified; `suggested_checks` records
optional follow-up checks, not shell commands to run automatically. Each list
allows at most 64 non-empty strings of at most 2,000 characters each; the same
text limit applies to `confidence_reason`. Scores must be finite numbers in
[0, 1] or null; booleans, strings, out-of-range values and unknown dimensions
are rejected. An invalid review does not retain a seemingly reassuring score.

### Visibility and workflow

The fields travel with `review_classification` in the existing AutoBuild summary,
Python-worker boundary, task outcome and parent-review records. Existing raw
review output also retains them. Parent confidence describes the parent's
integrated result, not an average/product of child scores and not the mandatory
reviewer's confidence that an audit task was performed correctly.

For a compact, read-only view of a saved AutoBuild summary or a standalone
structured review JSON file, run from the ARQUILO checkout:

```sh
python3 -B review_confidence.py /path/to/autobuild_summary.json
```

This offline reader prints the verdict, derived band, component scores,
reviewer-reported evidence, uncertainties and suggested checks. It does not
modify the file, follow artifact references, execute suggestions, contact a
provider, or infer confidence from legacy prose. Input is limited to 8 MiB;
malformed JSON and duplicate keys are rejected. Untrusted terminal controls
are escaped in the display.

**This first implementation is informational.** Low confidence alone does not
create a blocker, rerun, breakdown, extra model call or incomplete task. High
confidence never clears a blocker or bypasses existing review, safety, budget,
parent-acceptance or completion checks. A genuinely unmet acceptance criterion
must still be a blocker, not merely an uncertainty. Criticality-dependent
thresholds, autonomous evidence gathering and empirical calibration are not
implemented; they require a separate policy and outcome data. Repeated reviews
of the same task must not be treated as independent correctness observations.

## Original task and parent acceptance

AutoBuild keeps the task captured before the first execution fixed throughout the local correction loop. Before every review it writes a normal UTF-8 `review_contract_<id>.json` beside its logs from that in-memory snapshot. Review and correction receive the same snapshot inline in the prompt; shell access to the archive file is not required. Intermediate ToDo edits therefore do not replace the original criteria.

The file contains `original_request`, `task_text`, and `source`; the effective preamble is part of the original prompt, preserving `auto|off|required`. An archive-write failure prevents review and completion.

The runner additionally stores `original_contract.json` in the first task log. After child tasks finish, parent acceptance uses these original criteria and checks the integrated current results. Successful children alone do not make the parent DONE. A correctly executed parent audit may report FAIL about its subject; a passing mandatory review of the audit itself does not turn that domain FAIL into PASS.

This binding applies within the running runner. A newly started runner captures the then-current authoritative task version; old tasks are not automatically imported from unrelated runs. The files are ordinary run records without hashes, signatures, or immutability claims. The standalone Decide context remains fresh for each attempt.

## Local acceptance

```text
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
```

Tests in the public development repository use the standard library and simulated Codex results. They cover, among other things, propagation of the original contract, bounded corrections, and archive failures. The runtime ZIP does not contain the tests; package validation and CLI help remain available there.

The CI matrix in `.github/workflows/ci.yml` checks Python 3.11, 3.12, and 3.13 on Linux, Windows, and macOS. The actual result of the specific run is authoritative. Fakes do not demonstrate the judgement quality of a real model or native Codex sandbox enforcement. See [Testing](../docs/testing.md) and [Architecture](../docs/architecture.md).
