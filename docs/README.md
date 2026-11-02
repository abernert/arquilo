# ARQUILO documentation

**ARQUILO 0.10.0 — public preview.**

Start with the handbook for your role. Each contains its own contents and links to relevant chapters. If you are setting up a Mac from scratch, use the focused macOS prerequisite checklist below before entering the handbook; it does not replace the user, operator or architecture guidance.

| Audience | Handbook | What you will find |
| --- | --- | --- |
| Anwender | [Benutzerhandbuch Deutsch](guides/user-guide.de.md) | Einrichtung, erster Lauf, Aufgaben, wichtige Parameter, Ergebnisse und Fortsetzung. |
| Users | [User Guide English](guides/user-guide.en.md) | Setup, first run, task authoring, everyday options, results and continuation. |
| Workflow authors and operators | [Operator Guide](guides/operator-guide.en.md) | Operating procedures and the complete CLI, environment, CFG/WAIT, runtime-profile and prompt reference. |
| Developers | [Technical / Architecture Guide](guides/technical-guide.en.md) | Internal lifecycle, authority, files/processes, Git transactions, tests and distribution. |

## macOS setup: from a new Mac to optional format readers

| Task | English | Deutsch |
| --- | --- | --- |
| Bootstrap a Mac (Homebrew, Git, optional gh, compatible Python, Codex or Claude, first no-model test) | [Fresh-Mac setup](setup/macos-from-scratch.en.md) | [Mac-Ersteinrichtung](setup/macos-from-scratch.de.md) |
| Install tools for VS Code, PDF/OCR, Office, JSON/YAML/CSV, images and media as needed | [Optional helper tools](setup/optional-tools.en.md) | [Optionale Werkzeuge](setup/optional-tools.de.md) |

These are optional platform/tool setup checklists, not replacements for the four primary handbooks. There is no requirement to install every listed helper.

## Focused companion material

[Backend selection](guides/operator-guide.en.md#backends) · [Claude qualification](claude-code-backend.md) · [Runnable synthetic examples](../examples/README.md) · [Review JSON protocol](../documents/REVIEW_CORE.md) · [Security and reporting](../SECURITY.md) · [Version history](../CHANGELOG.md) · [Release basis and limits](integration-status.md)

The [CLI inventory](guides/cli-reference.json) and [documentation manifest](guides/manifest.json) are machine-readable maintenance aids, not user configuration. Detailed historical migration and future-design files are kept in the repository and are not included as competing instructions in the runtime ZIP.
