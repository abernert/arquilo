# Task-runner resume validation

Date: 2026-11-08. Branch: `feature/0.10.0-task-resume`.

## Scope and sources

The implementation is based directly on release `v0.10.0`, commit
`d8a75dea4b9ce8327bc7d2748772a4f1c6996247`. It implements the owner's requested `tasklist run --resume-task`
and `tasklist run --resume-review` contract. Source review used the release's
runner, AutoBuild loop, immutable task/prompt contracts, budget/STOP controls,
worker payload protocol, selected-output Git publication, and existing native
synthetic Codex/Claude fixtures. No changes were copied from the superseded
network/review recovery branch.

Both flags bind only the explicit open start task. Review entry makes no
initial production call; valid findings enter ordinary bounded correction.
Following tasks start after acceptance. Optional history is informational,
limited to registered run metadata and exact report paths; there is no new
recursive workspace scan. Current resources and control gates remain active.
Newer subworkspace reports/questions survive preparation; both report copies
are archived. Changed mutable task revisions cannot unlock following tasks.

## Candidate identity

Tested implementation tree, before this validation report was added:
`83711b478a60410d18625c475ec2a6c527daf9c8`. Staged implementation diff SHA-256:
`dcc7f82bd5bd3e9e18ac2d6d4224fe01d70f3b66ada8d24280e279327f9b70da`.

The final branch commit adds this report to that same implementation tree.
Hashes below identify the uncommitted files used for local verification.

| File | SHA-256 |
| --- | --- |
| `CHANGELOG.md` | `0b12c8542c22713b0440f13898271e8f74ffd607c66be16312aff83ba601b8ea` |
| `README.de.md` | `cec474df177a3fd57a9a6b0fa0fa35dfe0c1e1aa1c88cb554a8b2972a29d6f20` |
| `README.md` | `f20a3a38d29520e0d6528e4419e123a185161b265bf8ec433e0ff834c6d615ca` |
| `autobuild.py` | `e2b2407b9b96c738d44e0ce8f7d25a3c8662ccc0e8bf3555b097c1fc3daa45bd` |
| `autobuild_contract.py` | `720932ce13e9079dad7e510562f1d082418bf24a50bac784d19d9990767db538` |
| `docs/guides/cli-reference.json` | `02abe635b5a59d29351f385541cd722545b7a5a5319d938f04b6ed78964a1344` |
| `docs/guides/operator-guide.en.md` | `79aee45d9eeea72e92d548bd1b07cdf50e598e249424bdad58e60f9d5aa66e30` |
| `docs/guides/technical-guide.en.md` | `894b628b2d96f604b7a30e61ff4e8af134253178d4897fa79bdeb65ecd27b04e` |
| `docs/guides/user-guide.de.md` | `fd29651aa57d0e3886d8949c93e769311488441c82a28f38acb7505c50b00d38` |
| `docs/guides/user-guide.en.md` | `dd37d6410bfef6f1678ee3e4ef1f4023665c132a515312da8c9bcd2e4ce4d5a1` |
| `documents/lean_package.json` | `789f323a42822ddf149f8509d20204a7a9588fb969a3f4e129666cc3741b514a` |
| `prompt_config.py` | `f81947c4f8e3a8c7d0a3c3cd73bb4e9e910a26dbe6133645c23f2740ca3e28ab` |
| `prompts/de.toml` | `2cbc6f83a5ce5f49d00107407e2247f2448c2d634d2ef10a7e1307d16bafdf2c` |
| `prompts/default.toml` | `dc779c0b7c09164657842084899d45e72eca22f644adc2e28eb59a990271b45e` |
| `prompts/en.toml` | `8bdd85260e700e20256c88b06ad56448731d4ee57b125bff2bbf165f88e37f79` |
| `run_todos.py` | `018b28a6df8840fb4510a73f0d3caa82200047c4211a2c1d455a5197f965e878` |
| `scripts/documentation_reference.py` | `3be29f668175b780045a7ed012dddd28d5008573383c59e3835ee1aa5f2d76af` |
| `task_resume.py` | `6ad5c295bd72d4439b02f3180c8f7f6325c944296d131606fa4d55f61be11eff` |
| `tests/test_autobuild_resume.py` | `13b266934768249d267c24b39141538c0223f813362ac0aa557ecfd5ac0afef3` |
| `tests/test_documentation_manuals.py` | `8795bd43bac981e5208bd70e28c1e6928dc585f7d7ed4b0cf3587d1e7f469b7b` |
| `tests/test_prompt_configuration.py` | `a6ad0defb15a28550a207562571a5939fd84a1a4de17a00a84263fa4fb0dd8cb` |
| `tests/test_task_resume_sources.py` | `4b3d7c9d70d8848c8768f66b55bf9606455516f3a64292204ae05b1c19b0967e` |
| `tests/test_tasklist_resume.py` | `b0825549baeb7bab6c28630be50734196ca52a1dbd944d6cd5e09789f02def59` |

## Verification

| Check | Status | Evidence |
| --- | --- | --- |
| Full offline regression suite | PASS | Python 3.12.14 / Linux; `python3 -B -m unittest discover -s tests -v`: 1,022 tests in 61.870 seconds; 1,012 passed, 10 platform-dependent skips, no failures/errors. |
| New core resume tests | PASS | 23 tests, real synthetic protocol subprocesses; budget, STOP, review/fix, prompt snapshots and selected-output Git drift. |
| New runner/source tests | PASS | 51 tests: 39 CLI/native integration and 12 bounded-source tests. Includes Codex, Claude and private-worker serialization. |
| Documentation reference | PASS | 122 CLI entries checked without agent calls. |
| Distribution checks | PASS | `scripts/check_release.py`: 91 runtime files / 54 Python files; licensing, names, links, versions and syntax valid. |
| Packaged runtime smoke check | PASS | Built ZIP, compared all 91 extracted files with source bytes; both flags and `run_todos.resume=1` capability present. |
| Whitespace check | PASS | `git diff --cached --check`. |
| Native macOS/Windows execution | NOT_RUN locally | Separate CI/host qualification needed; Linux results do not certify other hosts. |
| Real Codex/Claude providers | NOT_RUN | Tests use controlled synthetic CLIs, no provider calls. |
| Owner's private workspace/tasks | NOT_RUN | No private task status changed or current run resumed by this development work. |

Package SHA-256 from the tested 91-file runtime:
`b616a97209d874f6a5f50b0f36d5af40fee0e58798888f21e92a5797424da50f`.
The validation report is maintenance evidence and is not part of the runtime ZIP.

## Remaining boundaries

Resume starts a fresh invocation on current work; it does not restore an old
model session or promise exactly-once external side effects. Existing task
requirements still determine necessary candidate identity and test evidence.
No new full-workspace snapshot is required by these flags. Explicit parent
resume requires accepted descendants and valid saved child-continuation data.
The normal preflight/resource rules still apply. Model PASS remains evidence;
only normal controller acceptance advances task status. This is an unreleased
branch extension; the existing `v0.10.0` tag and release assets are unchanged.
