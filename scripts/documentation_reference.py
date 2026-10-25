# Copyright 2026 ARQUILO contributors
# SPDX-License-Identifier: Apache-2.0
"""Maintain the handbook CLI inventory without launching any agent or subprocess.

Run with --check in CI or --write after an intentional CLI change. This is a
repository maintenance utility, not a runtime dependency or user command.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
START = '<!-- BEGIN GENERATED CLI REFERENCE -->'
END = '<!-- END GENERATED CLI REFERENCE -->'

DESCRIPTIONS = {
 '--help': 'Show the help for this command and exit; no model call.',
 '--version': 'Print the runtime version and exit. For development checkouts also record the commit.',
 'command': 'Select a subcommand. Options belong after their owning subcommand.',
 '--backend': 'Select codex (default) or claude-code for production, fixes, review, parent review and Decide. No implicit fallback or mixed-backend run.',
 '--skip-backend-preflight': 'Skip only the selected-backend runner preflight. Per-call executable/protocol checks, sandbox requirements and mandatory reviews remain.',
 '--git-required': 'Require successful requested Git delivery before the run continues; requires --git. Accepted tasks remain DONE, but pending delivery yields incomplete exit 9.',
 '--publication': 'Exact existing publication ID returned by git status. Required for git retry and rejected for status; no model or review call.',
 '--todo-syntax': 'Choose the spelling used when writing new task headers; existing supported spellings remain readable. CLI overrides ARQUILO_TODO_SYNTAX.',
 '--todo-preamble': 'Include the visible project preamble when present (auto), omit it (off), or require it (required). CLI overrides ARQUILO_TODO_PREAMBLE.',
 '--todo-file': 'Working UTF-8 Markdown task list. Required for execution; not needed for help/capabilities. An existing list is resumed, not replaced.',
 '--todo-template': 'Initialize a missing task list from this local template. Never overwrite an existing list. The destination must be inside the workspace. Explicit initialization also writes in dry-run mode.',
 '--workdir': 'Workspace. In the task runner, defaults to the task-list directory; Doctor uses the task-list directory or current directory. Use a narrow project directory, not your entire home.',
 '--start': 'Start selection at this task ID, for example 3 or 3.1. Already terminal tasks are not rerun. Earlier tasks lie outside the explicitly selected scope.',
 '--stop': 'Stop scheduling after this task and its required acceptance. It is not cancellation of the current model call.',
 '--max-depth': 'Maximum numeric task depth; 3 includes IDs such as 2.1.1. This does not disable a STOP barrier.',
 '--max-retries': 'Continuation multiplier for production/correction steps: max-steps times max-retries. It is not whole-task replay after a technical failure.',
 '--max-calls': 'Persistent invocation budget per top-level task tree, shared with descendants/reviews/Decide; 0 means unlimited. Counts attempts, not tokens, money or all internal provider requests.',
 '--breakdown-policy': 'Decompose unfinished work using a minimal residual contract, the legacy free decomposition, or no automatic decomposition.',
 '--breakdown-max-children': 'Maximum direct children in minimal decomposition. Valid range: 1 to 12.',
 '--breakdown-max-rounds': 'Maximum focused decomposition/repair rounds including the first child wave. Valid range: 1 to 8.',
 '--process-stop-policy': 'model allows the task to request a stop; controller-only instructs it to return structured feedback and leave stop decisions to the controller. Existing stop signals still apply.',
 '--max-steps': 'Production/correction-step limit for AutoBuild. The task runner combines this with max-retries; mandatory reviews also use call budget.',
 '--sandbox': 'Explicit execution policy. The task runner only accepts workspace-write; standalone AutoBuild also accepts read-only. Mandatory review/Decide remain read-only.',
 '--network-access': 'Grant shell-network access within workspace-write. A task may restrict this grant, not create it. Does not control provider, MCP or web-search traffic.',
 '--model': 'Explicit model/deployment identifier. Task runs: CLI, selected-backend environment (ARQUILO_CODEX_MODEL or ARQUILO_CLAUDE_CODE_MODEL), CFG model, native configuration. Doctor overrides require --check-decide.',
 '--reasoning-effort': 'Request supported effort; provider/model support is required. CLI precedes the selected-backend environment. Claude accepts low/medium/high/xhigh/max; Codex also none/minimal. Doctor requires --check-decide.',
 '--skip-codex-preflight': 'Skip the runner workspace-write functional probe only after that environment has been checked separately. Does not skip mandatory task reviews.',
 '--dry-run': 'Lint and render planned work without model calls. Explicit --todo-template can still create the missing list. Does not certify provider permissions or Git snapshot suitability.',
 '--dry-run-file': 'New output file for the dry-run report, relative to the invocation directory. Existing output is refused rather than overwritten.',
 '--simulate-incomplete': 'In dry run only, mark the supplied task ID as incomplete for simulation; repeat for multiple IDs.',
 '--run-id': 'Optional run identifier; a new identifier is generated when omitted. Changing the identifier does not reset task state or consumed budgets.',
 '--git': 'Request commits of explicit selected outputs bound to their review; no implicit push. Capture only selected files; task acceptance and optional publication have separate outcomes.',
 '--git-path': 'One literal relative output filename per occurrence, not a glob or directory. Requires --git. Do not select task plans, rewritten reports or controller logs.',
 '--git-push': 'Additionally publish reviewed commits to the approved existing upstream. Requires --git and the documented remote/serial-execution conditions.',
 '--state-dir': 'Trusted external controller-state root. Defaults: ~/Library/Application Support/ARQUILO/controller on macOS, ~/.local/state/arquilo/controller on Linux/WSL, LOCALAPPDATA/ARQUILO/controller on Windows. Keep the same root when resuming.',
 '--project-id': 'Readable log grouping identifier, 1 to 48 characters, validated as a portable name. Bound to workspace/plan; does not merge independent budgets.',
 '--logs-in-workdir': 'Place new diagnostic run logs in the workspace under the selected backend log directory. Authoritative journals, budgets and worker returns remain external.',
 '--allow-todo-modifications': 'Explicitly permit and record valid primary-plan edits during this run. Model-written statuses are not independent review evidence. Permission is not sticky across runs.',
 '--accept-plan-changes': 'Adopt owner-inspected external plan changes on restart. Preserve consumption/history. Not a generic repair for an unexplained integrity failure.',
 '--runtime-profile': 'Load an operator-trusted JSON runtime profile. CLI precedes ARQUILO_RUNTIME_PROFILE. A real run may execute its host preflight command.',
 '--print-capabilities': 'Print the core capability/contract JSON without model execution; also available through arquilo.py capabilities.',
 '--prompt-config': 'Use the complete built-in default, de or en TOML catalog, or an explicit file. Frozen for the invocation; not a task-controlled selector.',
 '--mcp': 'Comma-separated explicit server selection/ceiling, or none. Codex omission inherits native configuration. Claude accepts only none/omission; no named servers or native MCP inheritance.',
 '--review-mcp': 'Subset of production MCP servers for review, or none. Explicit --mcp defaults review to none. Local read-only policy does not make remote tools read-only.',
 '--skills': 'Comma-separated skill names, or none for no explicit bindings. Instruction snapshots, not permission grants. Does not disable native implicit discovery.',
 '--skill-dir': 'Approved root containing skill directories with SKILL.md; repeatable. Explicit roots replace default discovery roots.',
 '--agent': 'Native Codex profile name and agent hint, not a team definition. Local CFG agent can override it. Rejected for Claude.',
 '--json': 'Emit the Doctor report as JSON on stdout, including failures; not a request for model-generated JSON.',
 '--check-decide': 'Opt in to one live diagnostic model call after metadata checks; may incur provider charges. Default Doctor is metadata-only.',
 '--model-provider': 'Existing native Codex provider for the live Doctor probe; requires --check-decide. Does not define credentials or a URL. Rejected for Claude.',
 '--profile': 'Existing native Codex profile for the live Doctor probe; requires --check-decide. Tasklist run uses --agent. Rejected for Claude.',
 '--decide-timeout': 'Positive finite timeout for the live Doctor probe. Effective default is 120 seconds, plus metadata/cleanup. Requires --check-decide.',
 '--todo': 'Required exact task ID for narrow review-only recovery; must match the single task selected after the -- separator.',
 '--capture-dir': 'Required original archived production-capture directory. Evidence is verified before any model call; an arbitrary folder of outputs is insufficient.',
 'destination': 'Optional NEW ZIP filename. Default: dist/arquilo-VERSION.zip. Both archive and checksum must be absent. Building does not tag or publish a release.',
 'summary': 'Existing AutoBuild summary JSON or structured review JSON. Print advisory confidence; do not modify the file or infer a new PASS.',
 '--task': 'Standalone assignment text. Supply exactly one of --task or --task-file.',
 '--task-file': 'UTF-8 file containing the standalone assignment; mutually exclusive with --task.',
 '--file': 'Standalone single-file mode in an isolated workspace, mutually exclusive with --workdir. Inspect the returned output path; do not assume in-place publication.',
 '--codex-profile': 'Existing native Codex profile for standalone AutoBuild; tasklist run calls this --agent. Rejected for Claude.',
 '--extra-arg': 'Repeatable validated additional Codex argument for standalone use. Policy-changing or conflicting arguments are rejected; not a sandbox bypass.',
 '--logfile': 'Standalone readable log path; omitted paths are allocated for the run.',
 '--rawlog': 'Standalone raw event log path; raw content can contain sensitive data.',
 '--summary-json': 'Optional standalone machine-readable result path. A workspace summary is diagnostic, not a private worker-authority channel.',
 '--process-stop': 'Optional standalone stop-signal path. Inspect an existing stop before explicitly resuming.',
 '--todo-identifier': 'Task identity attached to standalone diagnostics and decision context, when integrating with a controller.',
 '--decision-todo-file': 'Task-list reference for standalone decision context; not permission to replace the original task contract.',
 '--decision-run-id': 'Run identity for standalone decision context; does not create a new shared budget.',
 '--auto-continue': 'Compatibility/progress flag: in this implementation it adds an automatic-continuation log message; it does not change the correction loop or require/skip a confirmation. Mandatory review and limits remain in force.',
 '--print-end-answer': 'Also print the final standalone assistant answer.',
 '--verbose': 'Print detailed standalone progress. Keep potentially sensitive output private.',
 '--source': "Source checkout or extracted runtime to validate offline; defaults to this script's checkout root. No model or network call.",
 '--zip': 'Stage an allowlisted ZIP rather than a new directory; this lower-level utility does not publish a release.',
 '--codex': 'Required path to the trusted Codex binary used by the synthetic compatibility check. Not a task runner option; no production credentials are needed.',
 'version': 'Required exact test-binary version from the listed choices, not a model name. The downloader uses the upstream release service and verifies its digest.',
 '--write': 'Regenerate the documentation CLI catalog and tables after reviewing an intentional parser change; modifies documentation files only.',
 '--check': 'Verify the generated documentation against the parsers without writing; this is also the default.',
}

class _Captured(BaseException):
    pass

def parser_inventory():
    import run_todos, autobuild, arquilo_doctor, arquilo, review_resume, review_confidence, git_publication_cli
    from scripts import build_runtime_zip, check_release, stage_lean, install_test_codex, check_codex_configuration, check_codex_provider, check_resource_configuration
    parsers = {}
    def collect(name, callback):
        def intercept(parser, *args, **kwargs):
            parsers[name] = parser
            raise _Captured()
        with patch.object(argparse.ArgumentParser, 'parse_args', intercept):
            try:
                callback()
            except _Captured:
                pass
    # Prevent accidental environment-specific defaults or any real process.
    with patch.dict(os.environ, {}, clear=True), patch('subprocess.Popen', side_effect=AssertionError('Documentation capture cannot launch a process')), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        collect('arquilo', lambda: arquilo.main(['--help']))
        collect('tasklist', lambda: arquilo.main(['tasklist', '--help']))
        collect('tasklist run', lambda: run_todos.parse_args([]))
        collect('doctor', lambda: arquilo_doctor.main([]))
        collect('tasklist resume-review', lambda: review_resume.main(['resume-review', '--']))
        parsers['git'] = git_publication_cli.build_parser()
        collect('package', lambda: build_runtime_zip.main([]))
        collect('review_confidence.py', lambda: review_confidence.main([]))
        parser = argparse.ArgumentParser(allow_abbrev=False)
        autobuild.add_run_arguments(parser)
        parsers['autobuild.py'] = parser
        collect('scripts/check_release.py', lambda: check_release.main([]))
        collect('scripts/stage_lean.py', lambda: stage_lean.main([]))
        collect('scripts/install_test_codex.py', install_test_codex.main)
        collect('scripts/check_codex_configuration.py', check_codex_configuration.main)
        collect('scripts/check_codex_provider.py', check_codex_provider.main)
        collect('scripts/check_resource_configuration.py', check_resource_configuration.main)
        parsers['scripts/documentation_reference.py'] = build_cli_parser()
    result = {}
    for name, parser in parsers.items():
        records = []
        for action in parser._actions:
            if action.help == argparse.SUPPRESS:
                continue  # retired rejection stubs/private IPC are NOT public controls
            keys = action.option_strings or [action.dest]
            primary = keys[-1]
            if primary not in DESCRIPTIONS:
                raise ValueError(f'Undocumented CLI option: {name} {primary}')
            default = action.default
            if isinstance(default, Path): default = '<checkout-root>' if default == ROOT else str(default)
            if default == argparse.SUPPRESS: default = None
            description = DESCRIPTIONS[primary]
            if name == 'git':
                description = {
                    'command': 'status lists retained publication records; retry reconciles one exact recorded publication. Both print JSON and make no model/review calls.',
                    '--workdir': 'Required original Git working-tree root; use the same path as the task run.',
                    '--todo-file': 'Required original task-list path selecting existing private state. Relative paths are relative to the shell working directory, as in tasklist run.',
                    '--state-dir': 'Original private state base, if the task run used a custom --state-dir. Do not select a new state root to retry publication.',
                }.get(primary, description)
            records.append({'names': keys, 'destination': action.dest,
                'default': default, 'choices': list(action.choices) if action.choices else None,
                'required': action.required, 'nargs': action.nargs,
                'repeatable': isinstance(action, argparse._AppendAction),
                'flag': action.nargs == 0,
                'description': ('Required NEW destination directory.' if name == 'scripts/install_test_codex.py' and primary == 'destination' else 'Required NEW output directory, or ZIP path with --zip.' if name == 'scripts/stage_lean.py' and primary == 'destination' else description)})
        result[name] = records
    return {'schema_version': 'arquilo.cli_reference.v1', 'commands': {k:v for k,v in result.items() if not k.startswith('scripts/')},
            'maintenance_commands': {k:v for k,v in result.items() if k.startswith('scripts/')},
            'aliases': {'run':'tasklist run', 'resume-review':'tasklist resume-review',
                        'capabilities':'tasklist run --print-capabilities',
                        'run_todos.py':'tasklist run', 'arquilo_doctor.py':'doctor',
                        'scripts/build_runtime_zip.py':'package'},
            'scope': 'Public options in this checkout. Private worker IPC and rejection-only historical flags are not supported user configuration.'}

def render(inventory):
    def esc(s): return str(s).replace('|', '&#124;').replace('\n', ' ')
    anchors = {'arquilo':'cli-entry', 'tasklist':'cli-tasklist', 'tasklist run':'cli-run',
               'doctor':'cli-doctor', 'tasklist resume-review':'cli-resume',
               'package':'cli-package', 'git':'cli-git', 'review_confidence.py':'cli-confidence', 'autobuild.py':'cli-autobuild'}
    notes = {
       'tasklist run':'Use `python3 -B arquilo.py tasklist run OPTIONS`. The table lists every public runner option. Defaults below are parser defaults in a clean environment; environment/native fallbacks are explained in each description and the configuration chapter.',
       'doctor':'Use `python3 -B arquilo.py doctor OPTIONS`. Model/provider/profile/effort/timeout overrides require `--check-decide`; metadata-only checks do not call a model.',
       'tasklist resume-review':'Use `python3 -B arquilo.py tasklist resume-review --todo ID --capture-dir DIR -- tasklist run ORIGINAL_OPTIONS`. Recovery requires `--start ID --stop ID` after the separator; the original workspace/task contract must match. All following runner options are listed above.',
       'package':'Use `python3 -B arquilo.py package [NEW_ZIP_PATH]`. This creates an archive and checksum, not a release.',
       'autobuild.py':'Use `python3 -B autobuild.py OPTIONS`. Exactly one task source (`--task` or `--task-file`) AND one target (`--workdir` or `--file`) are required. This is a single-assignment interface, not a second task-list scheduler.',
       'review_confidence.py':'Use `python3 -B review_confidence.py SUMMARY_JSON`. Confidence is advisory, not an acceptance threshold.',
       'arquilo':'Use `python3 -B arquilo.py COMMAND`. `--version` is a top-level option. Place --backend after tasklist run or doctor; it is not a top-level option. The git group performs model-free publication operations.',
       'git':'Use `python3 -B arquilo.py git status --workdir DIR --todo-file FILE` or `git retry` with the same paths and --publication ID. Reuse the original --state-dir when set. Status/retry never run a model or review; retry retains normal STOP and controller-lock checks.',
       'tasklist':'The tasklist group selects `run` or `resume-review`; options belong to the selected subcommand.'}
    notes.update({
      'scripts/check_release.py': 'Offline source/package validation. `--source` can point at an extracted runtime; no publication is performed.',
      'scripts/stage_lean.py': 'Lower-level allowlist staging. Prefer the `package` command for the standard runtime ZIP plus checksum.',
      'scripts/install_test_codex.py': 'Repository-only CI utility: downloads an exact upstream binary into a new directory. This uses the network, but does not install globally, log in or call a model.',
      'scripts/check_codex_configuration.py': 'Repository-only synthetic configuration/metadata compatibility probe; starts the specified local CLI in disposable directories. Not a production task.',
      'scripts/check_codex_provider.py': 'Repository-only synthetic loopback-provider probe. Starts the supplied CLI and a local test server; no live model provider is used.',
      'scripts/check_resource_configuration.py': 'Repository-only synthetic MCP configuration/startup probe. Uses local test processes, not customer MCP servers or live model credentials.',
      'scripts/documentation_reference.py': 'Repository-only handbook maintenance. --check and --write are mutually exclusive; omission checks without writing.'})
    lines = [START]
    combined = {**inventory['commands'], **inventory.get('maintenance_commands', {})}
    for name, actions in combined.items():
        if name == 'scripts/check_release.py':
            lines += ['### Maintainer and synthetic test utilities', '', 'These are separate from task execution. Repository-only test utilities are not normal runtime configuration. Their parameters are included here for a complete command reference.', '']
        anchor = anchors.get(name, 'cli-' + name.replace('/', '-').replace('.', '-'))
        lines += [f'<a id="{anchor}"></a>', f'### `{name}`', '', notes[name], '', '| Parameter / argument | Value / default | Meaning |', '| --- | --- | --- |']
        for a in actions:
            names=' / '.join('`'+x+'`' for x in a['names'])
            d=a['default']
            if a['required']: value='Required'
            elif a['flag']: value='Action' if a['names'][-1] in ('--help','--version') else ('On' if d else 'Off')
            elif d is None: value='Not set'
            elif d==[]: value='Empty list'
            else:value='`'+str(d)+'`'
            if a['choices']: value += '; one of ' + ', '.join('`'+esc(x)+'`' for x in a['choices'])
            if a['repeatable']: value+='; repeatable'
            lines += [f'| {names} | {value} | {esc(a["description"])} |']
        lines += ['']
    lines += ['### Aliases and excluded internal arguments', '',
              'Use the canonical commands in new scripts. `run` is a compatibility alias for `tasklist run`; `resume-review` aliases `tasklist resume-review`. `run_todos.py`, `arquilo_doctor.py` and `scripts/build_runtime_zip.py` expose the corresponding parser directly. `capabilities` forwards to the runner with `--print-capabilities`; model/run selectors do not turn that metadata request into execution.', '',
              '`autobuild.py --request-json`, `--decision-attempt-id` and `--decision-phase` are private worker/controller transport fields, not supported user configuration. Rejection-only removed switches (for example `--full-auto`, `--no-check`, `--yolo` and task-runner `--profile`) do not enable hidden modes. Standalone AutoBuild has no `--max-retries`; use the runner for task-list continuation.', '',
              '`decide.py` provides a Python API, not a standalone argument parser. `scripts/check_naming.py` has no argument parser and checks its own source tree; `scripts/check_release.py --source` is listed above. No CLI setting for teams, an MCP service or a GUI is supplied by this checkout.', END]
    return '\n'.join(lines)+'\n'

def outputs():
    inventory = parser_inventory()
    return json.dumps(inventory, ensure_ascii=False, indent=2)+'\n', render(inventory)

def check_or_write(write=False):
    catalog, block = outputs()
    path = ROOT/'docs/guides/cli-reference.json'
    guide = ROOT/'docs/guides/operator-guide.en.md'
    text = guide.read_text(encoding='utf-8')
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError('Operator guide must contain exactly one generated CLI reference')
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    desired = before + block.rstrip('\n') + after
    if write:
        path.write_text(catalog, encoding='utf-8')
        guide.write_text(desired, encoding='utf-8')
    elif not path.is_file() or path.read_text(encoding='utf-8') != catalog or desired != text:
        raise ValueError('CLI reference is stale; review the CLI changes, then run scripts/documentation_reference.py --write')
    inventory = parser_inventory()
    return sum(len(actions) for group in ('commands', 'maintenance_commands') for actions in inventory[group].values())

def build_cli_parser():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    return parser

if __name__ == '__main__':
    args = build_cli_parser().parse_args()
    print(f'{check_or_write(args.write)} CLI entries checked; no agents launched.')
