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
