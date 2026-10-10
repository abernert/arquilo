# Architecture

ARQUILO is a Python controller around Codex Exec, not a replacement model or a
web service. The code uses only the Python standard library.

## Execution flow

1. `run_todos.py` parses the task list, directives and selected workspace.
2. The controller captures the task and effective original request before an
   agent can edit the shared task list.
3. `autobuild.py` starts production in the shared workspace.
4. A separate read-only review checks actual artifacts against the captured
   request. Structured reviews distinguish blocking issues from observations.
5. Local corrections are bounded. Missing input, scope conflicts and technical
   failures cannot silently become successful completion. Decomposed tasks
   require parent acceptance after their children.
6. Only the controller changes task completion status. Logs and result reports
   remain in the project; explicit stop conditions end the run.

## Components

| Area | Files |
| --- | --- |
| Public CLI | `arquilo.py` (delegates without changing existing runtime APIs) |
| Task orchestration | `run_todos.py`, `todo_syntax.py`, `todo_lint.py`, `todo_context.py` |
| Production / review / correction | `autobuild.py`, `autobuild_contract.py`, `review_contract.py` |
| Restricted decisions | `decide.py`, `decision_request.py`, `decision_exec.py`, `decision_response.py` |
| Codex process boundary | `codex_transport.py`, `codex_launcher.py`, `codex_policy.py`, `process_tree.py` |
| Runtime contracts and logging | `runtime_contracts.py`, `runtime_files.py`, `runtime_logging.py`, `decision_archive.py` |
| Budgets and extension rules | `execution_budget.py`, `runtime_profile.py` |

## Review evidence must not depend on a shell read

The original review contract is captured by the controller, retained in memory,
archived as JSON and passed inline to the reviewer. Fix rounds and parent reviews
receive the captured contract as well. The archive is an audit/diagnostic copy,
not a file the reviewer must successfully open from within the sandbox.

This avoids a class of native Windows read failures against deep run-log paths.
It does not bypass file permissions or relax the review sandbox. Reviewers still
have to inspect the real task outputs, rather than accept the producer's claims.
The compatibility helper's path-only form remains available for older callers;
current runtime call sites pass `contract_text` explicitly.

## Nonfatal messages and tool policy

A Codex `item.type=error` notification is distinct from a fatal top-level
`error` or `turn.failed` event. One narrowly recognized pre-terminal WebSocket
reconnect notice is retained separately as `stream_diagnostics`, with its original
event and 1-based parsed stdout event index. Other top-level errors remain fatal.
The Decide event policy retains its closed list against tool execution and unknown
items. Diagnostics alone never establish successful completion: normal response,
completion, process and archive validation still apply.

A stop is an independent observation, not a substitute for a genuine failure.
The first observed reason survives through failed as well as cancelled outcomes.
AutoBuild returns an explicit `terminal_attempt` reference because its historical
`execution_attempts` array groups production/fix attempts before reviews and is
not chronological. The controller uses only the validated in-process/private
worker return for this identity, not the public workspace summary.

## Boundaries

Separate producer/reviewer executions do not guarantee independent judgements.
The logs are captured evidence, not a cryptographically immutable ledger or a
complete backup of the workspace. Native sandbox enforcement belongs to Codex
and the OS. A runtime profile may add domain-specific context and checks; it
must not disable controller security or forge a successful run state.

See [SECURITY.md](../SECURITY.md) and the [compatibility policy](compatibility.md).
