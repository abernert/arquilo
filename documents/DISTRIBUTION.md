# Runtime ZIP and releases

From the repository root, with Python 3.11+:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

The default output is `dist/arquilo-0.2.0.zip` for version 0.2.0, plus
`dist/arquilo-0.2.0.zip.sha256`. A custom not-yet-existing ZIP path may be passed.
Existing ZIPs and checksum sidecars are not overwritten. The explicit manifest
in `lean_package.json` determines the content; adding a file to the repository
alone does not include it in the runtime ZIP.

Both LICENSE and NOTICE are mandatory for this project's package check.
The ZIP excludes tests, workflows, Git history, credentials and run workspaces.
The development repository retains its tests and CI. The extracted runtime can
show help and rebuild the same selected file set without a Git checkout.
Reproducibility is tested with the same Python/zlib toolchain; compressed bytes
are not promised to match across every toolchain version.

The checksum detects changed bytes when compared to a trusted expected digest.
It is not a signature, identity proof or safety certification.

## Maintainer release procedure

Review the current diff and attribution, run tests and package validation, update
VERSION, `ARQUILO_RUNTIME_VERSION`, CITATION.cff and CHANGELOG.md together, and ensure
the exact commit's CI passed. Create a `v<version>` tag only after these checks.
The release workflow verifies version/tag agreement, tests and package contents
before publishing a ZIP and sidecar. Version 0.x releases are marked prereleases.
Never attach workspace logs or authentication files as release assets.

[Testing and live acceptance](../docs/testing.md) · [Security](../SECURITY.md)
