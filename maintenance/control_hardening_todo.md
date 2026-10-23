***SYNTAX marked-en***

# Foundational control acceptance template

Use a disposable checkout and ordinary private controller state outside it.
This list is for a fresh acceptance run after code changes. Tasks are open
deliberately. Preserve original audit archives, budgets and historical task
states. Do not merge, tag, publish, push or request a real model from a test.
Do not weaken product checks, silently skip a failure or treat synthetic model
responses as evidence of real model reliability. Record exact commit identity,
commands, exit codes and relevant evidence in each result report. Report an
unavailable platform as unverified, never as passed.

***CFG network_access=false web_search=disabled***
1. ***Task***: Establish the reviewed scope against `maintenance/control_hardening.md` and the actual checkout. Verify that the base and changed files match the intended control repair. Inspect the review/plan/stop/state/launcher boundaries and report concrete regressions. Do not alter version metadata or reset state to obtain a pass.
    Acceptance: The report identifies the actual commit and changed files, maps each selected audit finding to a control and test, and explicitly retains the deferred work.

***CFG network_access=false web_search=disabled***
2. ***Task***: Run `python -B -m unittest discover -s tests -v` in an isolated temporary environment and inspect all failures and platform skips. Verify the completion, snapshot, state identity, stop/parallel worker and trusted launcher regression groups. Diagnose any failure before changing implementation; preserve the original failing evidence.
    Acceptance: A complete unedited test log and command/exit status exist. Every relevant assertion passes; platform-specific skips are named. No production credentials, real model calls or customer workspaces were used by the tests.

***CFG network_access=false web_search=disabled***
3. ***Task***: Run `python -B scripts/check_release.py` and build a runtime ZIP with `python -B scripts/build_runtime_zip.py` at a fresh output path. Inspect the runtime manifest and archive; verify that the new host launcher is included and development/audit data are excluded. Keep the version unreleased.
    Acceptance: Both commands succeed, archive contents match the allowlist, and the emitted SHA-256 matches the archive bytes. No release or tag was created.

***CFG network_access=false web_search=disabled***
4. ***Task***: Evaluate the supplied native CI evidence for the exact reviewed commit: Linux/Windows/macOS with Python 3.11/3.12/3.13, plus both configured Codex metadata compatibility versions. Inspect failures and skips, especially Windows npm launch, native path aliases and allocation locking. If logs are missing, record the gap and keep this acceptance blocked.
    Acceptance: Every required native job has completed successfully on the exact reviewed commit. Each job is identified by commit and outcome, relevant native behavior is verified, and platform skips are explained. A local simulated Windows test or an older green commit is insufficient.

***CFG network_access=false web_search=disabled***
5. ***Task***: Produce a final acceptance report using the preceding evidence. Distinguish implemented controls, tested behavior, migration requirements and remaining audit scope. Check that historical invalid DONE entries, budget-only legacy identity, Git publication binding and full process supervision have not been claimed repaired without evidence.
    Acceptance: The report makes a specific merge recommendation with evidence and any blockers. It performs no merge, push, release or task-state cleanup.
