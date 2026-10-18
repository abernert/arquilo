# Reconnection diagnostics and review-only recovery

**Generic ARQUILO behavior** (independent of provider, proxy or employer).

## Transient stream retries vs. final failures

In non-interactive `codex exec --json`, Codex may report an interim event:

    {"type":"error","message":"Reconnecting... 1/12 (stream disconnected before completion: stream closed before response.completed)"}

ARQUILO treats a **well-formed, pre-terminal** `Reconnecting... n/m`
notice as a diagnostic, not an immediately fatal `stream_error`. The raw
JSONL, pretty log, capture `stream_diagnostics` and event index preserve it.
Variants include WebSocket disconnect and HTTP/SSE response-body decoding
errors. These notices do **not** count as a successful model answer.

Only a real `turn.completed`, nonempty final assistant answer, and successful
Codex process result can qualify as successful production. Real
`turn.failed`, unrelated `error` events, nonzero exits, decode/I/O failures,
missing completion, stop signals and process-cleanup errors remain fatal.
An interim reconnect **after** terminal completion is not suppressed.

An external proxy or LLM gateway can terminate a quiet CONNECT/SSE tunnel
independently of the Codex client. Diagnose long reasoning requests using the
**inactivity** timeout at each network hop, not just total response duration.

## Explicit review-only continuation of an archived production

This is for the narrow case where Codex actually finished a production turn
(`turn.completed` and exit code 0), but the older ARQUILO classified **only**
a recovered retry notice as `codex_stream_error` before its mandatory review
could start. It is **not** a general force-resume or DONE bypass.

Prerequisites:

- Operator has inspected the completed previous run and current artifacts.
- The same workspace, original task list, original task ID, unchanged task
  prompt, state root/project identity and task policy are retained.
- No competing run or active `process_stop` exists.
- The *original* complete capture, original contract, original AutoBuild
  summary and response are available in
  `<workdir>/.codex_runs/run_todos/<run>/task-<ID>/001-production/`.
- This command is an explicit operator choice. Archived logs inside a
  model-writable workspace are **not independent trusted evidence**.

Example from inside the original workspace:

~~~bash
SOURCE="$PWD/.codex_runs/run_todos/<RUN>/task-2/001-production"

python3 -B /path/to/arquilo/arquilo.py tasklist resume-review \
  --todo 2 --capture-dir "$SOURCE" -- \
  tasklist run \
  --workdir . \
  --todo-file tasks.md \
  --start 2 --stop 2 \
  --max-steps 1 --max-retries 1 \
  --breakdown-policy off \
  --logs-in-workdir
~~~

Restore any **same** custom `--state-dir`, `--project-id` and
`--runtime-profile` flags used for that workspace after `tasklist run`.
If you want to avoid a separate Codex workspace-write preflight model call,
`--skip-codex-preflight` requires your explicit prior confirmation that
workspace-write behavior was already validated. Never add
`--accept-plan-changes` to sidestep a changed plan.

### Verification and no-replay guarantee

Before the tasklist runner is started, the recovery command verifies the
original capture directory belongs to the selected task, checks
`capture.json`, `stdout.bin`, original `prompt.utf8`, task-level
`prompt.md` and `original_contract.json`, `response.txt`, and
`autobuild_summary.json`:

- Exactly one terminal `turn.completed`, no `turn.failed`.
- Exit code 0, all input/output pipes fully captured, no process stop.
- The previous AutoBuild has one production call and zero review calls,
  failed only with `codex_stream_error`.
- Every prior stream error is a valid interim retry notice; other failures
  cause a refusal.
- The captured **actual input bytes**, task prompt/contract and final
  assistant answer agree.
- The first request in the new run must be the *identical* original task
  prompt and the same workspace and task ID; otherwise recovery refuses
  the request **without replaying production**.

For the matching first production invocation the completed result is supplied
from the validated archive; the Codex production subprocess is **not started
again**. Then an **entirely new, independent read-only review** runs using the
normal original-contract, model, tasklist and controller gates. A review PASS
can lead to DONE; a review FAIL leaves the task open. The one-task bounds
and breakdown=off prevent automatic fix or child-task expansion. No next
task runs due to `--stop`.

The regular AutoBuild call-budget bookkeeping may reserve one synthetic
production attempt even though it does not contact the model. Existing
budgets and controller state are not cleared, reset or guessed. The original
archive remains unchanged; new review logs are written to a new run.

**Fail closed**: If the source evidence is incomplete, different, untrusted,
or the task/prompt does not match, this mode refuses continuation.
It must never be used to mark partially completed production as approved.

Run offline regressions without credentials or model calls:

~~~bash
python3 -B -m unittest discover -s tests -v
~~~
