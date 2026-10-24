# Maintaining ARQUILO documentation

The manuals are maintained product documentation, not snapshots of a conversation.
Their canonical sources are Markdown files in `docs/guides/`. The product version
remains in `VERSION`; a documentation-only edit does not require a tag, version
bump, runtime dependency or replacement of an existing release asset.

## Integration identity

For an unreleased integration, keep `runtime_version` unchanged and record
`status`, `release_baseline`, `source_commit` (the exact code baseline),
`documentation_base_commit` and pinned `integrated_pull_requests` in the guide
manifest. The documentation revision is identified by the checkout commit, not
by embedding its own hash into itself. Keep a clear release-versus-checkout
notice in every guide. The source branches remain separate review units.

## Documentation responsibilities

| Content | Canonical home | Maintenance rule |
| --- | --- | --- |
| First use and everyday operation | `docs/guides/user-guide.en.md` and `user-guide.de.md` | Maintain the same chapters, safety warnings and tutorial commands in both languages. |
| Advanced operating procedures | `docs/guides/operator-guide.en.md` | Explain configuration interactions and link detailed field references. |
| Implementation and extension model | `docs/guides/technical-guide.en.md` | Describe actual code paths and distinguish invariants, limitations and future design. |
| Exact options and task grammar | `documents/CONFIGURATION.md`, `documents/todo_directives.md` | Verify against CLI help, parsers and tests; do not create competing exhaustive tables. |
| Review/state/security contracts | `documents/REVIEW_CORE.md`, `docs/controller-safety.md`, `SECURITY.md` | Treat a guarantee change as a code-and-documentation review item. |
| Worked examples | `examples/` | Keep synthetic, portable and separately testable; no private configuration or customer inputs. |
| Documentation map | `docs/README.md`, `docs/guides/README.md` | Keep the short path from each audience to its next action. |
| Guide inventory/baseline | `docs/guides/manifest.json` | Record document IDs, language, audience and supported runtime baseline. |

Existing reference paths remain valid. Do not rename or remove a page solely to
make the folder tree prettier; keep a redirect page or update all incoming links
when a move is genuinely needed. A guide is a reading path, not another source
of defaults competing with the implementation.

## When code changes

Review the affected manual sections in the same pull request as a user-visible
change. CLI options, defaults, status semantics, permissions, file locations,
recovery, costs and package contents all count as user-visible behavior. Update
the source baseline and version metadata in the guide manifest after checking
the new runtime. Do not merely change the version number to satisfy a test.

For purely editorial changes, retain the runtime baseline and record the change
in the documentation pull request. Do not imply that the previously published
ZIP now contains files absent from that already published release artifact.

Use explicit HTML anchors for guide chapters so translations and cross-links
remain stable. Both User Guides must retain the same ordered chapter anchors.
Named tutorial blocks use `<!-- example: ID -->`; their command bodies should be
identical across languages. Localize explanatory prose, not executable keys,
filenames or command tokens. A reviewer still needs to compare meaning and
safety advice: structural equality cannot certify translation quality.

## Test commands and examples

From a full repository checkout:

```sh
python3 -B -m unittest discover -s tests -p test_documentation_guides.py -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py
```

On native Windows substitute the selected Python interpreter, such as `py -3.11`.
The documentation tests are discovered by the normal offline suite. They check
the guide inventory, version baseline, bilingual chapter/command parity, local
file/guide-anchor links, referenced CLI flags, sample profile loading and
synthetic task-list dry runs. They do not call a live model, start MCP servers,
validate provider permissions or certify real output quality. Keep external
web-link availability separate from deterministic offline CI.

`check_release.py` also checks package allowlisting, licensing, version alignment
and relative document targets. A new document needs an entry in
`documents/lean_package.json` and the matching `runtime_file_count`; being tracked
in Git is not enough to ship it. Tests themselves remain repository-only. Check
the final ZIP, not just the source folder. The ZIP builder refuses overwrites;
use its documented output options or a fresh build directory for repeat builds.

Live examples must be visibly labeled as potentially billable. Never make a
routine documentation check depend on credentials, remote side effects or a
paid model call. Do not run generated software before reviewing it. Keep a dry
run clearly separate from live acceptance and mark placeholder server/model
names as placeholders rather than pretending they are installed.

## Rendered editions

Markdown is the maintained source. HTML or PDF can be generated as reading
editions; they should identify the documented runtime and documentation revision,
include a table of contents, preserve warning text and resolve links to references.
Do not edit a rendered edition independently. Build-time rendering dependencies,
if introduced, must not become mandatory ARQUILO runtime dependencies.

A documentation-only preview bundle can be shared without creating a product
release. The regular runtime allowlist ships the Markdown sources. Automated
PDF/HTML publication is not added by these guides and is a separate build-policy
decision, not an already implemented runtime feature.

## Review checklist

Check that each instruction identifies its shell and working directory; separates
preparation, dry run, model execution and verification; states what is overwritten
or retained; and includes a safe recovery route. Distinguish model judgment from
controller acceptance and organizational authorization. Keep known limitations
visible until an actual fix and regression evidence exist. Use ARQUILO as the
product spelling in every language.

Before merging, compare new claims with code and tests, inspect both User Guide
languages, run offline documentation checks and confirm that version/tag/release
metadata has not changed unintentionally.
