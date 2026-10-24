# Prompt configuration

Introduced in 0.9.0; applicable to the documented 0.9.1 runtime.

**Public preview.** This feature moves ARQUILO's
built-in model-facing instruction texts into complete, editable TOML catalogs.
The Python core, parser contracts and authorization checks remain separate.
Python 3.11's standard `tomllib` is sufficient; no new package is required.

## Three supplied files

| Selection | File | Texts |
| --- | --- | --- |
| `default` (also the omitted option) | [default.toml](../prompts/default.toml) | The original 0.8.0 wording, including its German/English mixture. |
| `de` | [de.toml](../prompts/de.toml) | German built-in instructions. |
| `en` | [en.toml](../prompts/en.toml) | English built-in instructions. |

Each file contains all 53 elements. The files have the same keys and placeholder
contracts, so an editor or translation program can work element by element.
There is no silent fallback from a missing German element to an English default.
The default's extracted element texts and representative assembled prompts are
checked against SHA-256 fixtures from commit
`027206436b9c6ba4474af19476bd12e86c0f7840` (0.8.0).

## Select a catalog

Select once for the invocation. The same catalog serves all tasks, parallel
workers and their review/correction calls during that run.

```bash
python3 -B /path/to/arquilo/arquilo.py tasklist run \
  --workdir /path/to/project \
  --todo-file /path/to/project/tasks.md \
  --prompt-config de
```

Use `--prompt-config en` for English, `--prompt-config default` for the original
wording, or a file path for a complete custom catalog. Relative file paths refer
to the invocation directory, not the work directory. On Windows, use your
Python 3.11+ command (for example `py -3.11`), native paths and your shell's
line-continuation convention. In WSL, the example above uses Linux paths.

The direct AutoBuild entrypoint supports the same option:

```bash
python3 -B autobuild.py \
  --workdir /path/to/project \
  --task "Analyze input.md and write an evidence-based summary to analysis.md." \
  --prompt-config en
```

A task-list `--dry-run --dry-run-file /path/to/new-preview.md` shows the actual
expanded assignment without executing the task. It does not validate model
behavior or authorize external effects. `arquilo.py doctor --prompt-config de`
validates the catalog selection as part of diagnostics; an actual diagnostic
model call still requires the existing explicit `--check-decide` option.

Prompt selection is an operator-level option, not a `CFG` or `DEFAULTS` field
that a task or an agent-generated child can change. There is no implicit
workspace file search or automatic environment-variable selection.

## Edit a complete copy

Copy one supplied file outside the application checkout, for example:

```bash
cp prompts/de.toml /path/to/my-prompts.toml
```

Then edit the copy and select `--prompt-config /path/to/my-prompts.toml`.
A typical element looks like this (the actual file contains the full catalog):

```toml
schema_version = "arquilo.prompts.v1"
id = "my-team-de"
version = "1"
language = "de"

[prompts.task_assignment]
# Keep these placeholder names unchanged.
text = """
Bearbeite die Aufgabe {{task_id}} aus `{{todo_path}}`.
Dokumentiere das Ergebnis in `{{result_path}}`.
"""
```

The example is a fragment for explanation, not a runnable partial configuration.
Use a complete file. Change `id` and increase `version` when maintaining your
own variants. `language` is descriptive metadata (`mixed`, `de` or `en`); it does
not translate text at runtime and is not an automatic language detector.

The supplied files use TOML multiline strings. A backslash at the end of a
source line joins the next line without adding whitespace; this lets the
default preserve the old rendered bytes while remaining readable. Ordinary
newlines can be used when intentionally changing a prompt. Escape literal
backslashes and double quotes according to TOML basic-string syntax.

Only `{{name}}` tokens listed in each element's comment are substitutions.
Retain their names, but move them as grammar requires. Every required token must
remain present and no new token may be introduced. There are no expressions,
attribute access, shell expansion, template includes or executable code. Values
are inserted once: braces inside a task, source text or model answer are not
interpreted again as template syntax.

Validation rejects unknown/missing elements, malformed TOML, unsupported schema,
invalid placeholder sets, empty texts, NUL bytes and oversized catalogs. Limits
are 512 KiB per file/combined text and 128 KiB per element. Nothing is silently
truncated. UTF-8 with an optional leading BOM and LF/CRLF is accepted.

## Coverage and language boundaries

The catalogs cover task assignment, subworkspace/agent hints, status/stop rules,
policy wrappers, the preamble wrapper and work-plan semantics, reviewer role and
response instructions, confidence guidance, correction requests, minimal and
legacy decomposition, parent review, decision questions/instructions and system
text, skill-binding wrappers, question-file headings and the diagnostic probe.

A language choice changes **ARQUILO-authored instructions**, not all bytes in a
model conversation. The following deliberately retain their original form:

- User tasks and task-list preambles, `AGENTS.md`, selected skills, runtime-profile
  additions, source documents, prior model answers, filenames and tool output.
- Machine-readable JSON keys, enum values and sentinel markers such as `verdict`,
  `PASS`, `FAIL`, `COMPLETE` and the review-contract delimiters. These are protocol,
  not translatable prose. Likewise, executable task syntax remains unchanged.
- CLI help, console messages, technical exception/validation diagnostics and
  existing log field names. This change is not a full user-interface localization.

The `ARQUILO_DECISION_SYSTEM_PROMPT` override and an explicitly supplied Python
`system_prompt` retain their existing precedence; they are owner-authored text,
not automatically translated. To use only the supplied built-in system wording,
do not set that override. A model's output language is not guaranteed merely by
translating its instructions; put any required output language into the task or
preamble and verify it at review.

## Configuration layers

| Layer | Responsibility |
| --- | --- |
| Prompt catalog (`--prompt-config`) | Built-in wording, reusable elements and language. |
| Runtime profile (`--runtime-profile`, JSON) | Existing domain-specific additions and supported single-slot overrides. Those contributions remain unchanged and can be in another language. |
| Codex profile (`--agent`) | Native model/provider/tool configuration. It is not a prompt-catalog selector. |
| Task-list preamble and tasks | Concrete project goal, inputs, work and acceptance criteria. |
| Skills | Explicitly selected procedure text; its user-authored content is not translated. |
| MCP selection | Available configured tools, independent of prompt wording. |

The feature does not weaken sandbox selection, tool permissions, review-required
rules, parser validation, call budgets, stop handling or controller ownership of
`DONE`. A template cannot change those executable checks. However, changing the
substantive reviewer wording can change review quality. Inspect custom prompts
as trusted operator configuration, test them, and do not treat successful TOML
validation as proof of a good or safe review policy.

## Snapshots and reproducibility

A catalog is loaded and validated once by the run owner. Its immutable text
snapshot is passed through Python and serialized into each worker request.
Workers validate the snapshot instead of reopening the source file. Editing or
deleting the source file after the run starts does not alter that run's catalog;
a later invocation loads the new file. Two concurrent runs can use different
catalogs without process-global language switches.

Task-list run archives contain catalog metadata in `run_config.json` and the
complete `prompt_config_snapshot.json`. Direct AutoBuild archives use a unique
`prompt_config_<id>.json`; standalone decision archives also retain a snapshot.
Source-byte and canonical-content SHA-256 digests distinguish the loaded file
from its effective text contents. These are reproducibility records, not signed
or tamper-proof evidence. Prompt files and archives must not contain secrets.

Task/prelude capture and exact-original-request recovery checks continue to
apply. Selecting a different catalog in a later recovery invocation does not
retroactively translate an archived assignment or bypass a mismatch. This
feature does not freeze all workspace, reference, skill-script or Codex files.

## Python use

```python
from pathlib import Path
from prompt_config import load_prompt_config
from autobuild_contract import AutoBuildOptions

catalog = load_prompt_config(Path("/path/to/my-prompts.toml"))
options = AutoBuildOptions(prompt_config=catalog)
```

`TodoRunner(prompt_config=...)`, `AutoBuildOptions(prompt_config=...)`,
`DecisionRequest(prompt_config=...)` and the public `decide`/`evaluate` helpers
accept the selector or loaded catalog. Existing calls that omit it use `default`.
A snapshot includes its original source metadata but is validated without
requiring that source path to exist on a worker.

## Validation

Offline tests cover exact default text, all catalog keys, translation selection,
custom edits, placeholder failures, literal user inputs, parallel language
isolation, worker serialization, archived snapshots, and real production/review/
correction controller flows with a fake model transport. Native response parsers
are unchanged. No live model API or customer service is used by these tests.

See [task directives](../documents/todo_directives.md),
[task preambles](../documents/TODO_PREAMBLE.md) and the
[Runtime Profile API](../RUNTIME_PROFILE_API.md) for the neighboring interfaces.
