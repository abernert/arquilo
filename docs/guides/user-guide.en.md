# ARQUILO User Guide

**English · runtime 0.10.0 · release edition 2026-10-25**
[Deutsch](user-guide.de.md) · [All guides](../README.md) · [Advanced operation](operator-guide.en.md)

> **ARQUILO 0.10.0 — public preview.** This edition includes Claude Code support, state-I/O repairs, separate task acceptance and Git publication, and the consolidated handbooks. See the [release basis and remaining limits](../integration-status.md). Older release ZIPs retain their original contents.

This guide is for people who want to use ARQUILO, not modify its Python code. You should be comfortable opening a terminal, copying files and checking a result. You do not need to understand the internal controller. ARQUILO is a public preview: use supervised, disposable examples before important work.

## Contents

[1. What ARQUILO does](#purpose) · [2. The working model](#concepts) · [3. Installation](#installation) · [4. First safe preview](#preview) · [5. First real run](#first-run) · [6. Document example](#documents) · [7. Software example](#software) · [8. Writing tasks](#authoring) · [9. Everyday options](#options) · [10. Reading results](#results) · [11. Stopping](#stopping) · [12. Continuing](#continuing) · [13. Changing a plan](#plan-changes) · [14. Troubleshooting](#troubleshooting) · [15. Updating](#updating) · [16. Checklist and next reading](#checklist)

<a id="purpose"></a>
## 1. What ARQUILO does

ARQUILO turns a Markdown task list into model-assisted work, separate reviews and, where appropriate, corrections. A separately installed agent CLI supplies the model connection and tools: Codex by default, or Claude Code with `--backend claude-code`. ARQUILO manages the workflow and decides whether completion conditions have been met. The chosen backend applies to production, correction, review, parent review and Decide for the whole run; no automatic backend fallback occurs.

Suitable starting points are producing a source-bound summary, preparing a small code change, or working through a well-defined analysis. Give every task an observable result and acceptance criteria. “Improve this project” is too open-ended for a first run.

A review is mandatory, but it is still a model assessment. `DONE` is not a guarantee of factual truth, legal suitability or production readiness. Independently check consequential results. In 0.10.0 the public workflow is task-list execution; a graphical workbench, a general pipeline command, agent-team configuration and an ARQUILO MCP service are not part of this documented runtime.

<a id="concepts"></a>
## 2. The working model

| Term | Meaning for you |
| --- | --- |
| ARQUILO installation | The directory containing `arquilo.py` and the shipped modules. Keep it separate from the project being edited. |
| Workspace / `--workdir` | The project directory containing inputs and outputs for this run. Use a specific project, not your entire home directory. |
| Task list / `--todo-file` | Your Markdown work plan. ARQUILO records approved task transitions here. |
| Producer | A model execution that performs a task and can edit permitted files. |
| Reviewer | A separate read-only model execution checking outputs against the captured request. |
| Controller state | Persistent plan and budget records outside the workspace. Keep them when continuing. |
| Logs and reports | Execution evidence and readable task results. These can contain the input text and confidential information. |

The normal sequence is **task → production → review → correction if necessary → controller acceptance**. A producer's claim that it is finished is not enough. Some tasks can be decomposed into smaller tasks; completing those does not remove the separate parent acceptance requirement.

Do not put passwords, access tokens or unrelated personal files into task lists. A local workspace does not mean local-only processing: provider communication remains possible even without shell-network access.

<a id="installation"></a>
## 3. Installation and prerequisites

Use an ordinary user account. The core needs Python 3.11 or newer and no third-party Python runtime packages. The maintained test matrix covers Python 3.11, 3.12 and 3.13. Git is useful for cloning/updating the repository and is required for explicitly enabled automatic Git functions; a release ZIP is another installation option.

Obtain ARQUILO from the [repository](https://github.com/abernert/arquilo) or its [releases](https://github.com/abernert/arquilo/releases). For a release ZIP, extract the versioned runtime ZIP, not just an individual Python file. For a checkout, clone the repository and change into its root. The commands below assume your terminal is in the directory containing `arquilo.py`.

For the default Codex backend, install and authenticate Codex separately using the [official CLI instructions](https://developers.openai.com/codex/cli). Organization-managed providers, proxies and certificates belong to your approved Codex/host setup, not to a copied secret in an ARQUILO file. For native Windows, also consult the [official Windows guidance](https://developers.openai.com/codex/windows).

**macOS, Linux or an Ubuntu shell in WSL:**

<!-- example: prerequisites-posix -->
```sh
python3 --version
python3 -B arquilo.py --version
codex --version
codex login status
```

**Native Windows PowerShell:** choose an installed Python 3.11+ interpreter; the following examples use `py -3.11`.

<!-- example: prerequisites-windows -->
```powershell
py -3.11 --version
py -3.11 -B .\arquilo.py --version
codex --version
codex login status
```

For a standard Codex login, use `codex login` when required. An organization may provide a different approved authentication method. Verify setup in the same environment in which ARQUILO will run: a Windows installation is not automatically an Ubuntu/WSL installation. Do not mix Windows Python, Linux paths and Linux Codex in one invocation.

### Install tools outside the task workspace

ARQUILO starts trusted host tools to perform the job. Install **Codex or Claude Code, and Git, outside the directories the task can modify**, including task subworkspaces. Otherwise an agent could replace a program in its project and cause the controller to execute that replacement. This is why executable location is a prerequisite, not a new command-line option.

Keep three locations separate: the ARQUILO installation, the project workspace containing inputs/outputs, and the private controller state. For example, a user-level Codex installation in `~/.local/bin` can serve a project under `~/projects/report`; it must not be inside that project. Use an absolute trusted directory in `PATH`. ARQUILO resolves the executable and any symlink target before launch; ordinary command-name invocation remains unchanged. Select a project directory rather than your entire home directory as `--workdir`.

Git is required only for Git-based installation/update or explicitly enabled Git automation. Node is needed only when the chosen Codex or Claude installation uses a supported npm launcher. Keep those host installations outside writable task directories as well.

### Choose Claude Code instead of Codex

Install and authenticate the official Claude Code CLI separately. A Claude-only run needs no Codex installation, login, configuration lookup or fallback. Use native Claude provider/model settings approved for your environment. All generic examples below default to Codex; add `--backend claude-code` to the doctor and task-run commands when using Claude.

On Windows, production requires **WSL2/Linux with Linux Python and Linux Claude**; native Windows read-only metadata support does not make production supported. Linux production also requires `bubblewrap`, `socat` and permission to use the native sandbox. A missing sandbox is an installation failure; it is not bypassed.

Replace the paths before using this metadata-only check:

<!-- example: claude-doctor -->
```sh
claude --version
python3 -B arquilo.py doctor --backend claude-code --workdir /path/to/project
```

The following command starts a real producer and mandatory review and may consume model usage:

<!-- example: claude-run -->
```sh
python3 -B arquilo.py tasklist run --backend claude-code --workdir /path/to/project --todo-file /path/to/project/tasks.md --mcp none --review-mcp none --prompt-config en --max-calls 12 --process-stop-policy controller-only
```

The Claude adapter accepts `--mcp none` and `--review-mcp none`; **named MCP servers are unsupported**, and omission also enables no native MCPs. Explicit ARQUILO skills bind text and hashes; native Claude skills, plugins and subagents are not enabled. Its reviewer can Read/Glob/Grep but has **no Bash or write tools**, so production/fix must create the evidence of any executed tests. `--agent`/`CFG agent` and Codex provider/profile overrides are not supported for Claude. Review-only reconnect recovery remains Codex-specific. For exact permissions and protocol compatibility, see [Claude qualification](../claude-code-backend.md).

<a id="preview"></a>
## 4. First safe preview

Use the shipped synthetic example, not a customer directory. This preparation creates a new workspace and copies the task list without changing its encoding. It refuses an existing destination so an earlier run is not overwritten.

**macOS/Linux/WSL:**

<!-- example: smoke-prepare-posix -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

**Native Windows PowerShell:**

<!-- example: smoke-prepare-windows -->
```powershell
py -3.11 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
py -3.11 -B .\arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

Open `preview.md`. A dry run validates the plan and writes a preview; it does not run the producer, reviewer or profile preflight and does not mark tasks complete. It does not certify authentication, native MCP configuration or model quality. Existing preview reports are not overwritten: use `preview-2.md` for another preview.

The explicit `--mcp none` requests no direct MCP servers for the model calls and disables plugin/app integrations in this explicit mode. `--skills none` adds no explicitly bound skills; it does not disable Codex's own discovery of skills or `AGENTS.md`. The example also disables web search and shell network through its task directives. This is not a claim of complete offline execution.

Relative CLI paths are relative to your terminal's current directory, **not** automatically to `--workdir`. Keep using the installation directory for these commands. Quote paths with spaces. For a new independent experiment choose another workspace name; do not delete controller state to recycle a previous plan.

<a id="first-run"></a>
## 5. First real run and success check

First run the metadata-only doctor. It does not make a model request, although it may write diagnostic files.

<!-- example: doctor-posix -->
```sh
python3 -B arquilo.py doctor --workdir .local-work/smoke
```

<!-- example: doctor-windows -->
```powershell
py -3.11 -B .\arquilo.py doctor --workdir .local-work/smoke
```

Adding `--check-decide` explicitly opts into a real restricted-decision model probe and may incur usage. It is optional before this tutorial, not a substitute for production/review acceptance. It has its own options and should not be assumed to inherit the task runner's resource selections.

The following command **does make model calls**. It can edit files in the permitted workspace. The runner's sandbox preflight can also consume usage and is outside the task-tree call counter.

<!-- example: smoke-run-posix -->
```sh
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

<!-- example: smoke-run-windows -->
```powershell
py -3.11 -B .\arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

Success means that `hello.txt` is a regular empty file, `todo_result_1.md` reports actual checks, the separate review was accepted and task 1 became `DONE`. Inspect the external run directory printed by ARQUILO. An independent file check is:

<!-- example: smoke-check-posix -->
```sh
python3 -c "from pathlib import Path; p=Path('.local-work/smoke/hello.txt'); assert p.is_file() and not p.is_symlink() and p.stat().st_size == 0; print('Empty regular file verified')"
```

In PowerShell, replace `python3` with `py -3.11`. This file check alone does not establish that the review ran: inspect the task status and logs too. A finite budget can stop a legitimate run before its review; that is an incomplete run, not permission to mark it complete manually.

<a id="documents"></a>
## 6. A document task from supplied sources

The supplied `brief.md` is fictional. The task asks for a short `summary.md` preserving three milestone dates and explicitly recording an unknown acceptance owner.

Create a **different** workspace:

<!-- example: document-prepare -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/document'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/document_review_todo.md', p/'tasks.md'); shutil.copyfile('examples/brief.md', p/'brief.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/document --todo-file .local-work/document/tasks.md --dry-run --dry-run-file .local-work/document/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

For native PowerShell use `py -3.11` instead of `python3`. After reading the preview, repeat the second command **without** `--dry-run --dry-run-file .local-work/document/preview.md` to opt into model execution.

Check the source yourself: requirements draft **2030-01-10**, prototype **2030-01-24**, acceptance review **2030-02-07**. The summary must be under 250 words and include an `Open questions` section. It must not invent a person responsible for acceptance. These are dates in a synthetic example, not real project commitments.

This illustrates an important distinction: a faithfully recorded unknown can be an acceptable result. It becomes a blocker only when the task requires that unknown to be resolved before acceptance. Put that distinction in the task rather than leaving the reviewer to guess.

<a id="software"></a>
## 7. A small software task

The [software example](../../examples/python_function_todo.md) asks for an integer addition function and ordinary standard-library tests. It requires no package installation or network access.

<!-- example: software-prepare -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/software'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/python_function_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/software --todo-file .local-work/software/tasks.md --dry-run --dry-run-file .local-work/software/preview.md --process-stop-policy controller-only --max-calls 12 --mcp none --skills none
```

After inspection, repeat the run command without its dry-run options. On Windows use the interpreter substitution above. Inspect the generated `calculator.py` and `test_calculator.py` **before executing model-generated code yourself**. Then, in a separate terminal inside `.local-work/software`, run:

<!-- example: software-check -->
```sh
python3 -B -m unittest discover -s . -p test_calculator.py -v
```

Check that at least the three required cases actually ran: positive numbers, a negative number and zero. “Zero tests ran” is not acceptance. Read `todo_result_1.md` and `todo_result_2.md` and check both task states. Model-authored tests can share the same misunderstanding as the implementation, so compare them with the written requirements.

<a id="authoring"></a>
## 8. Writing your own task list

Create a UTF-8 file. Use a short project preamble and unique numeric task IDs. Do not indent executable headers by four spaces or place them inside a Markdown code fence: those are examples, not executable tasks.

```md
***SYNTAX marked-en***

# Local source review
Use only input.md. Write the final answer in English.
Do not change the task list or mark tasks DONE.
Report blockers; do not create process_stop.

***CFG network_access=false web_search=disabled***
1. ***Task***: Create findings.md from input.md and record checks in todo_result_1.md.
    Acceptance: Separate source facts from assumptions. Cite the relevant
    source section for each finding. List missing evidence explicitly.
```

Provide `input.md` before starting. Specify the output filename, permissible inputs, tests or other acceptance checks, and how to handle missing information. “Create findings.md” is a deliverable; “each finding is grounded in a source section” is an acceptance condition.

Keep tasks small enough to inspect. Put requirements shared by all tasks in the preamble. Task directives apply to the next task only; do not assume the `CFG` above task 1 also configures task 2. Markers such as `Task`, `DONE`, `CFG`, `WAIT` and option names are machine syntax and are not translated with prose.

For repeatable jobs keep a clean template separately. `--todo-template` initializes a missing working list and does not overwrite an existing one. It copies only that list, not referenced inputs, and performs initialization even with `--dry-run`. See the [template recipe](operator-guide.en.md#recipes).

<a id="options"></a>
## 9. Configure a run: the options you will use most

Place runner options **after `tasklist run`**. The following table is a working reference for everyday use; the [Operator Guide contains the complete command and configuration reference](operator-guide.en.md#cli-reference), including less common and standalone commands. File paths passed on the CLI are relative to the terminal's current directory unless absolute; they are not automatically rebased to `--workdir`.

| Parameter | Use | Default / practical rule |
| --- | --- | --- |
| `--backend codex/claude-code` | Select the agent CLI for every phase of the run. | `codex`; no automatic fallback or mixed-backend review. |
| `--todo-file FILE` | Select the working task list. | Required for a real task-list run; preserve this path for continuation. |
| `--workdir DIR` | Select the project workspace. | Task-list directory when omitted. |
| `--todo-template FILE` | Copy a template when the working list does not yet exist. | Off; existing lists are never replaced. Explicit copying also occurs in dry run. |
| `--model MODEL_ID` | Choose the model or deployment used for the run. | Inherit unless set; use an identifier available through your own provider. |
| `--reasoning-effort LEVEL` | Request reasoning effort. | Inherit unless set. Codex: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; Claude: `low`, `medium`, `high`, `xhigh`, `max`. The model must support it. |
| `--agent PROFILE` | Select an existing native Codex profile. | No run-level profile override; a task's `CFG agent` can override it. Not an agent team. |
| `--prompt-config default/de/en/FILE` | Select built-in wording or a complete custom TOML catalog. | `default`; user instructions and output language remain separate. |
| `--max-calls N` | Limit attempts in each top-level task tree. | **0 = unlimited**; use a positive limit for a bounded trial. |
| `--max-steps N` | Bound production/correction steps. | 3; the runner combines this with `--max-retries` (default 2). |
| `--start ID` / `--stop ID` | Select a starting task and a boundary after an accepted task. | All remaining selected tasks; not immediate cancellation. |
| `--dry-run` | Preview instructions without model execution. | Off. Does not verify authentication or remote-tool permissions. |
| `--dry-run-file FILE` | Choose the preview output. | `run_todos_dry_run.md`; choose a new filename, because overwrite is refused. |
| `--project-id NAME` | Give the log group a readable name. | Automatic identity; changing log names does not reset budgets. |
| `--logs-in-workdir` | Keep visible diagnostic logs in the workspace. | Off; authoritative state always remains external. |
| `--state-dir DIR` | Select a private external state root. | Platform default; keep it stable across restarts. |
| `--network-access` | Permit sandboxed shell-network access. | Off; provider communication, MCP and web search are separate. |
| `--mcp NAMES/none` | Restrict explicit MCP server selection. | Codex omission inherits; names must be configured. Claude accepts none/omission only. |
| `--review-mcp NAMES/none` | Select a subset for the reviewer. | Explicit `--mcp` defaults review to none; remote read-only requires server permissions. |
| `--skills NAMES/none` / `--skill-dir DIR` | Bind selected procedure instructions and optionally choose discovery roots. | No explicit binding; roots are repeatable. |
| `--runtime-profile FILE` | Load approved domain rules and optional host preflight. | None; inspect it before use because preflight can execute host code. |
| `--todo-preamble auto/off/required` | Control inclusion of shared project instructions. | `auto`; use `required` when a substantive preamble is mandatory. |
| `--process-stop-policy model/controller-only` | Choose who is instructed to request process stops. | `model`; neither mode ignores an existing stop. |
| `--accept-plan-changes` | Adopt plan edits you have deliberately reviewed. | Off; not a generic workaround for an unexplained failure. |
| `--allow-todo-modifications` | Permit a planning task to modify the primary task list. | Off; use together with a deliberate boundary and later human review. |
| `--git`, `--git-path FILE`, `--git-push` | Opt in to reviewed Git commits and, separately, push. | Off; publication failure is separate from task acceptance. |
| `--git-required` | Require successful selected Git delivery before the run continues. | Off; requires `--git`. Accepted tasks remain DONE if delivery is incomplete. |

### Choose model and reasoning effort

Replace `YOUR_MODEL_ID` and the two paths below with your configured model/deployment and project paths before running. This is a **real run**, not a preview. In PowerShell use your installed Python command and native paths; the single-line argument layout is the same.

<!-- example: model-and-effort -->
```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --model YOUR_MODEL_ID --reasoning-effort high --prompt-config en --max-calls 20
```

Reasoning effort is a request to the chosen provider/model, not a quality guarantee. A higher setting may increase work, response time and usage; only select values supported by that model. An unsupported combination is an error, not permission for ARQUILO to choose a different model. These options do not edit the selected runtime's native configuration.

### Understand where settings come from

| Setting | Effective order |
| --- | --- |
| Model | `--model` → selected-backend environment (`ARQUILO_CODEX_MODEL` or `ARQUILO_CLAUDE_CODE_MODEL`) → task `CFG model` → that runtime's native configuration. |
| Reasoning effort | `--reasoning-effort` → `ARQUILO_CODEX_REASONING_EFFORT` or `ARQUILO_CLAUDE_CODE_REASONING_EFFORT` → native configuration. No task `CFG reasoning_effort`. Codex model/effort settings do not configure Claude. |
| Native profile (Codex only) | Task `CFG agent` → run `--agent` → native default configuration. |
| Prompt wording | Explicit `--prompt-config` or `default`; no automatic project catalog lookup. |
| Domain rules | `--runtime-profile` → `ARQUILO_RUNTIME_PROFILE`; separate from the native profile and prompt catalog. |
| Shared task instructions | Text before the first real task, controlled by `--todo-preamble`; task-specific requirements belong in the task. |

No ARQUILO YAML configuration file or automatically loaded workspace `.env` is required. For reusable model defaults, set the selected backend's model/effort variables in the launching shell; native profile selectors are Codex-only. Do not store access tokens in task text or handbooks. MCP/skill selections use ceilings, not ordinary last-value-wins precedence; consult the Operator Guide before narrowing resources per task.

**Repeat a finite `--max-calls` on continuation.** Omitting it can change an older finite limit to unlimited while preserving used attempts. One agent invocation may contain multiple internal model requests, so this is not a time, token or currency cap. Leave automatic Git off for the introductory examples.

<a id="results"></a>
## 10. Reading results, status and logs

Look at three things together: **the actual artifact**, **the task/result report**, and **the controller's execution/review evidence**. A nice final message is not enough.

Default controller-state roots are `~/Library/Application Support/ARQUILO/controller` on macOS, `~/.local/state/arquilo/controller` on Linux/WSL and `%LOCALAPPDATA%\ARQUILO\controller` on Windows. The printed run path is the best way to find a specific run. A readable project ID changes the log namespace, not the persistent budget identity. [Log layout](operator-guide.en.md#logs-reference)

Common runner exit codes are:

| Code | Interpretation |
| --- | --- |
| `0` | Successful return within the selected scope; tasks outside that scope may remain open. |
| `2` / `3` | Invalid configuration or a runner/controller error. Read the diagnostic rather than retrying blindly. |
| `6` | Observed process stop or a controller stop such as exhausted shared task budget. |
| `7` | Technical execution failure, possibly alongside a separately recorded stop. |
| `8` | Invalid review protocol; this is not a valid PASS. |
| `9` | Incomplete work or unmet workflow conditions. |

Entry points and layers have differences; for example, standalone AutoBuild reports budget exhaustion differently from the task runner. Use the error's phase and message as well as the number. A deliberate selected boundary or no-work run can return 0 without completing the entire file.

Review confidence, where present, is advisory and uncalibrated. It cannot override blockers. Logs are not encrypted or tamper-proof records. Inspect and redact before sharing them; private storage does not make their contents harmless.

<a id="stopping"></a>
## 11. Stopping deliberately

For a planned pause, select `--stop TASK_ID` before starting. To interrupt a current run cooperatively, create the `process_stop` file in its main workspace. From the installation directory, for the smoke example:

<!-- example: stop-posix -->
```sh
python3 -c "from pathlib import Path; f=Path('.local-work/smoke/process_stop').open('x', encoding='utf-8'); f.write('Operator requested stop\n'); f.close()"
```

On Windows use `py -3.11`. An existing file causes this command to fail without replacing its contents; its existence already signals stop. Inspect it rather than overwrite it.

The controller checks the sentinel before new work, during relevant waits and before final acceptance. It propagates stop information to parallel workers. This is **not** a guarantee of instant termination of every detached process or trusted preflight command. Inspect partial outputs and active work before continuing.

`***STOP***` inside the Markdown list is a different mechanism: a scheduling barrier immediately before a task. Arrange it before a run, with any CFG/WAIT lines above the barrier. Editing the live task list can trigger plan-integrity checks. Do not use a live plan edit as the standard emergency-stop method.

<a id="continuing"></a>
## 12. Continuing after interruption or failure

Stop any old controller first. Read the failure and the latest capture; inspect changed files and any external side effects. Correct the underlying cause. Preserve evidence. Only then move aside a `process_stop` marker when you deliberately authorize continuation; do not remove it automatically in a retry loop.

Run with the **same workspace, task-file path and state root**, plus the intended finite call limit and the required resource/profile settings. Previously accepted tasks are normally skipped. An open task may execute production again; ordinary restart is not “continue from the next line” and is not guaranteed exactly-once execution. This matters especially for tasks that send messages or alter external systems.

Do not delete state, rename the plan to obtain a new budget, or manually set `DONE` to resolve an error. Historical DONE values supplied as an initial owner baseline are not retrospective proof of a review. Version 0.10.0 does not automatically repair incorrectly accepted historical runs.

There is a narrow Codex-only [review-only recovery procedure](operator-guide.en.md#recovery-reference) for a completed production turn formerly rejected solely because a recovered reconnect was misclassified. It requires complete matching evidence and a fresh review. It is not a general force-resume switch; use the dedicated procedure only when its conditions hold.

<a id="plan-changes"></a>
## 13. Deliberately changing an established plan

In the default strict mode, requirements and accepted state cannot silently change. To make an intentional owner edit, stop the runner, inspect and edit the plan, and use `--accept-plan-changes` once with the normal run options. This archives the old baseline and retains budgets. Remove the flag on later runs. It is an explicit trust decision, not an error-repair default.

`--allow-todo-modifications` is a different, more powerful option. It permits valid model-authored changes to the working plan, including changes that are not independently verified completion. It is useful for a bounded planning stage followed by human inspection, but it is not the beginner default. See [planning with a pause](operator-guide.en.md#planning).

<a id="troubleshooting"></a>
## 14. Common problems

| Symptom | First action |
| --- | --- |
| `codex` not found or refused | Check the installation and PATH in the current OS environment; ensure the executable and target are outside all selected workspaces. |
| Authentication, proxy or certificate error | Verify the approved host/provider configuration. Do not add credentials to the task or switch to another provider without authorization. |
| Existing preview file | Choose a new preview filename. Do not overwrite useful evidence. |
| Plan integrity error | Compare the live list with accepted state. Restore the intended plan or explicitly adopt a reviewed owner edit; never reset the state directory. |
| Budget exhausted before review | Inspect partial results, then consciously increase the finite limit while preserving usage and resolve the stop marker. |
| Reconnect messages | Distinguish recovered diagnostics from the final outcome. A reconnect notice alone is neither success nor terminal failure. |
| Good artifact but open task | Review or final controller acceptance may have failed. Read the recorded phase; do not set DONE manually. |
| Windows access denied during parallel project registration | Preserve the error and pending recovery file; stop competing runs. Version 0.10.0 includes the PR #35 repair for Issue #32; the older v0.9.1 ZIP does not. A recurring failure still requires investigation, not state deletion. |

See [Troubleshooting](operator-guide.en.md#troubleshooting-reference) and [known limitations](operator-guide.en.md#limitations). Do not solve an installation error by routinely running as Administrator/root or disabling platform protection.

For automatic Git publication, selected outputs are frozen before review and the reviewer stays in the normal workspace with explicit snapshot references. Unselected links or large context files are not copied into a full-workspace snapshot. Optional publication can remain blocked while a successful task becomes DONE. The controller preserves this obligation across restarts, including when no accepted publication candidate exists. `git status` shows it; `git retry` can continue delivery without model work only when accepted private evidence exists. With `--git-required`, incomplete delivery stops the run, including a later restart.

The files selected with `--git-path` may belong to different tasks in the same run. A file for task 2 that is absent both before and after task 1 is not a deletion or an additional requirement for task 1. Review distinguishes this case from an actually removed file. If the current task itself requires the missing file, it remains incomplete.

Without an accepted candidate, first inspect and preserve the existing outputs and prepare a valid clean Git baseline for the selected files. Then deliberately reopen the task, accept the inspected plan change and run ordinary optional `--git` again for a fresh review. Successful matching delivery supersedes the old block while retaining its history. Failure to persist the required controller record prevents DONE; tampering with a captured reviewed output or its binding also remains an acceptance failure. See [Git publication and recovery](operator-guide.en.md#git).

<a id="updating"></a>
## 15. Updating without losing progress

Stop active runs and retain a backup of relevant project inputs and controller evidence. Update the **whole installation**, including Python workers; do not mix old and new individual modules. For a Git checkout, check local changes before a normal fast-forward update. For a ZIP installation, extract to a separate installation directory and verify its version before switching your launcher.

Keep ongoing project paths and their state root unchanged. Read the changelog and compatibility notes and perform a new disposable smoke test. Do not assume that updating files automatically makes an old incomplete plan safe to resume. Obtain the complete matching runtime and documentation for the selected release or revision. Older release assets retain their original contents; copying a new handbook into an old installation does not add its features.

<a id="checklist"></a>
## 16. Before important work

Confirm that the workspace is deliberately scoped, inputs are approved for the configured provider, the task has observable acceptance criteria, the call limit is explicit, and the stop/recovery process is understood. Check outputs independently before publication. Preserve logs appropriately without sending raw confidential archives to support.

Continue with the [Advanced / Operator Guide](operator-guide.en.md) for resources, profiles, parallelism and operations, or the [Technical / Architecture Guide](technical-guide.en.md) for internals. The [configuration reference](operator-guide.en.md#cli-reference) and [directive reference](operator-guide.en.md#task-directive-reference) remain the detailed references for the installed version.
