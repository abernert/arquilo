# ARQUILO

**Markdown-Aufträge ausführen, Ergebnisse unabhängig prüfen, kontrolliert fortsetzen.**

ARQUILO steht für **Agentic Runtime for Quality, Unified Iteration, Logging and
Orchestration**. Das Projekt führt den bisherigen DORA-Lean-Kern unter einem
neuen öffentlichen Namen fort.

Die Version **0.1.0 ist eine öffentliche Vorschau**. Python 3.11 oder neuer genügt
für den Kern; Python-Drittpakete sind nicht erforderlich. Echte Modellaufrufe
benötigen eine separat installierte und angemeldete Codex-CLI und können
Modellnutzung verbrauchen. Das ist keine rein lokale KI und keine
Produktionsfreigabe.

## Einstieg

Das [englische README](README.md) enthält das vollständige Beispiel. Unter
Windows funktioniert der dortige Ablauf mit `py -3.11` statt `python3`;
bei deiner Installation ist auch `python3.11` möglich.

```powershell
py -3.11 -B arquilo.py --version
py -3.11 -B arquilo.py run --help
py -3.11 -B arquilo.py doctor --help
```

[Schritt-für-Schritt-Anleitung einschließlich PowerShell](docs/quickstart.md)

Der Controller hält ursprüngliche Anforderungen fest, startet Produktion und
separaten Review, steuert begrenzte Korrekturen und setzt erst nach Abnahme auf
DONE. Ein separater Review kann trotzdem denselben Modellfehler wiederholen.
Die tatsächlichen Dateien und fachlichen Prüfkriterien bleiben entscheidend.

Die bisherigen Einstiegspunkte `run_todos.py` und `dora_doctor.py`,
`DORA_*`-Umgebungsvariablen, `.codex_runs` und `dora.*`-Schemas bleiben aus
Kompatibilitätsgründen erhalten. Bestehende Integrationen benötigen keine
pauschale Umbenennung.

## Referenz

[Konfiguration](documents/CONFIGURATION.md) · [Direktiven](documents/todo_directives.md) ·
[Vorbemerkung](documents/TODO_PREAMBLE.md) · [Review](documents/REVIEW_CORE.md) ·
[Workflowgrenzen](documents/WORKFLOW_LIMITS.md) · [Fehlerdiagnose](docs/troubleshooting.md)

Die [Sicherheitshinweise](SECURITY.md) gelten auch für Testläufe. Rohprotokolle
können vollständige Prompts, Dateiinhalte und Werkzeugausgaben enthalten.
Keine Zugangsdaten oder Kundendaten in öffentliche Issues hochladen.

## Entwicklung

```powershell
py -3.11 -B -m unittest discover -s tests -v
py -3.11 -B scripts/check_release.py
py -3.11 -B scripts/build_runtime_zip.py
```

Diese automatischen Tests sind ohne Modellzugang ausführbar; sie ersetzen keine
Live-Abnahme der konkreten Codex-/Windows-Sandbox-Installation.

Autor und Maintainer: **Alexander Bernert**. Apache-2.0; siehe [LICENSE](LICENSE)
und [NOTICE](NOTICE). Hinweise für Beiträge: [CONTRIBUTING.md](CONTRIBUTING.md).
