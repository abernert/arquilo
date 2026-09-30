# Contributing to ARQUILO

Small, focused issues and pull requests are welcome. Prefer a minimal synthetic
reproduction, an explanation of the expected behavior and a regression test.
Do not upload customer data, credentials, private prompts or complete run logs.
Read SECURITY.md before reporting a sensitive issue.

## Local checks

Python 3.11+ is sufficient. No development dependency installation is required.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

Use a new ZIP output path if a previous build exists. Keep test workspaces under
`.local-work/` or OS temporary directories. Tests must not require Codex credentials,
network access or billable model calls. Live verification must be explicitly
opted into and clearly described separately from simulated tests.

## Change discipline

Use the current `ARQUILO_*` and `arquilo.*` integration contracts unless an
intentional migration is part of the change. Keep review criteria pinned to the
original request, preserve failed-attempt evidence, and never fix a test by
weakening an execution boundary or bypassing review. Add new distributed files
to `documents/lean_package.json` and update its count; source-only tests and CI
must remain outside the runtime package.

Use UTF-8 and LF. New original Python files should include:

```python
# Copyright 2026 Your Name
# SPDX-License-Identifier: Apache-2.0
```

Retain existing attributions. Clearly identify any third-party code and its
license before proposing it; do not assume AI-generated content is necessarily
free of third-party obligations.

## License and review

By intentionally submitting a contribution for inclusion, you provide it under
the project's Apache-2.0 license unless you clearly state otherwise and a separate
arrangement is agreed. Submit only material you have the right to contribute.
No copyright assignment or separate CLA is required by this project at present.
Contributors retain their copyright. The maintainer decides whether to merge;
a contribution does not imply future maintenance obligations.
