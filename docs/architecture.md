# Architecture

ARQUILO is a Python controller around external Codex Exec processes, not a model
server or an OS sandbox. The runtime uses the Python standard library. This page
is the short overview; the [Technical / Architecture Guide](guides/technical-guide.en.md)
explains state, contracts, worker communication, failure handling and extension
boundaries for the unreleased integration based on 0.9.1.
See [the exact baseline](integration-status.md); the published release is unchanged.

## Execution flow

1. `arquilo.py` delegates to `run_todos.py`, which validates the task list,
   directives, operator choices and selected workspace.
2. The controller captures the original task and effective request from accepted
   plan evidence before a producer can edit shared project files.
3. `autobuild.py` starts production through the Codex transport.
4. A separate read-only review checks artifacts against the captured request.
   With `--git`, it examines the private pre-review snapshot.
   A technically successful review may legitimately FAIL its subject.
5. Corrections and decomposition are bounded; completed children still require
   separate parent acceptance. Technical failure does not authorize an automatic
   whole-task replay.
6. Only a valid result passing final stop/plan/review gates can authorize an
   ordinary controller transition to DONE. Mutable-plan mode is an explicit,
   weaker operator opt-in, not independently verified completion of every edit.

Default runner logs and authoritative controller state are **outside** the model
workspace. `--logs-in-workdir` moves diagnostic logs only; journals, budgets and
private worker IPC stay external. Task-authored result reports remain in the
project. [Log layout](project-logs.md) · [State and recovery](controller-safety.md)

## Components

| Area | Files |
| --- | --- |
| Public CLI and diagnostics | `arquilo.py`, `arquilo_doctor.py` |
| Task orchestration and grammar | `run_todos.py`, `todo_syntax.py`, `todo_lint.py`, `todo_context.py`, `todo_ids.py`, `todo_template.py` |
| Production, review and correction | `autobuild.py`, `autobuild_contract.py`, `review_contract.py`, `review_confidence.py`, `review_resume.py` |
| Plan authority and invocation budgets | `controller_state.py`, `execution_budget.py` |
| Filesystem and path boundaries | `safe_io.py`, `runtime_files.py` |
| Host launch and Codex policy | `host_launcher.py`, `codex_launcher.py`, `codex_policy.py` |
| Transport and process cleanup | `codex_transport.py`, `process_tree.py` |
| Restricted decisions | `decide.py`, `decision_request.py`, `decision_exec.py`, `decision_response.py`, `decision_archive.py` |
| Profiles, prompts and resources | `runtime_config.py`, `runtime_profile.py`, `prompt_config.py`, `task_resources.py`, `mcp_selection.py` |
| Results and diagnostics | `runtime_contracts.py`, `runtime_failure.py`, `runtime_logging.py`, `project_logs.py` |
| Optional selected Git outputs | `reviewed_git.py`, `git_snapshot.py` |

## Review contracts and authority

The original contract is captured, archived and passed inline to review, fixes
and parent acceptance. Review does not depend on a model opening a deep archive
path through a shell. This preserves the request without widening permissions;
reviewers still need to inspect the actual outputs.

The parser owns raw review-format provenance. FAIL and blocking issues veto
completion, including at the private worker-result boundary. Legacy prose still
requires its explicit semantic decision, which cannot overrule a blocker.
Confidence is advisory rather than a new acceptance threshold.

Plan completion changes only the approved task command in the accepted revision.
Child adoption persists the exact validated bytes. Physical identity checks
prevent the reproduced state/budget alias splits without changing existing keys.
These are defined controller guarantees, not a claim that every remaining audit
finding is closed.

## Stream and stop semantics

Item-level diagnostics differ from fatal top-level errors and failed turns.
Recognized well-formed pre-terminal reconnect notices, including supported
WebSocket and HTTP/SSE variants, are retained as diagnostics. They do not establish
success without normal response, terminal, process and archive validation.
Unknown or post-terminal errors remain significant.

Stop is recorded independently of genuine failure. Root/peer stop paths reach
Python workers, and final acceptance rechecks stop state. `terminal_attempt`
identifies the actual terminal call; historical attempt arrays are grouped by
call type, not chronologically. Cooperative cancellation is not complete
containment of arbitrary detached processes or active trusted preflights.

## Boundaries and open work

Separate producer/reviewer executions do not guarantee independent judgment.
Native sandbox enforcement belongs to Codex and the OS; configured integrations
and writable roots remain part of host trust. External logs are neither encrypted
nor immutable audit storage.

Automatic Git here binds reviews to pre-review copies and publishes verified
selected bytes through pinned local/remote operations. It requires serial
execution and bounded regular-file contexts; full-context checks can occur
after production. PR #35 supplies the state-I/O repairs for #32/#34. Broader
process supervision, resource-definition integrity and general release gating
remain open. The [Operator Guide limitations](guides/operator-guide.en.md#limitations)
and [Technical Guide](guides/technical-guide.en.md) distinguish current behavior
from proposed repairs.

See [Security](../SECURITY.md), [testing](testing.md) and
[compatibility](compatibility.md). The [pipeline concept](pipeline-mvp-concept.md)
is a proposal, not an implemented command or runnable configuration format.
