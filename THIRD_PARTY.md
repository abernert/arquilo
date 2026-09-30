# Third-party components and external services

The runtime distribution does not vendor Codex, Node.js or third-party Python
packages. It uses the Python standard library. Separately installed tools retain
their own licenses, service terms and access requirements; this repository's
Apache-2.0 license does not replace them or grant model-service access.

CI references GitHub-maintained actions at pinned commit IDs. They are fetched
by GitHub Actions, not bundled into the runtime ZIP. Review their own repositories
for their licensing. Badges link to external services and are not runtime code.

Original source code, documentation and examples in this repository are released
under Apache-2.0 unless an individual file states otherwise. No third-party
attribution notice has been intentionally removed. Anyone contributing copied
or adapted third-party material must identify it and retain required notices.
Dependency and pattern scans are not a complete provenance or legal-rights audit.
