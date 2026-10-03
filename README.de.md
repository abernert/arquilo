# ARQUILO

**Markdown-Aufträge ausführen, Ergebnisse unabhängig prüfen, kontrolliert fortsetzen.**

ARQUILO steht für **Agentic Runtime for Quality, Unified Iteration, Logging and
Orchestration**. Zur Herkunft des Projekts siehe die ausdrücklich
[historischen Namens- und Migrationshinweise](docs/compatibility.md).

Die Version **0.6.1 ist eine öffentliche Vorschau**. Python 3.11 oder neuer genügt
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

Die direkten Einstiegspunkte heißen `run_todos.py` und `arquilo_doctor.py`.
Neue Konfigurationen verwenden `ARQUILO_*`, neue JSON-Ausgaben `arquilo.*`.
Unterstützte historische Eingabealiase werden mit Migrationshinweis gelesen;
Details stehen in der [Kompatibilitätsdokumentation](docs/compatibility.md).
Seit 0.3.0 liegen die maßgebliche Planhistorie, Aufrufbudgets und Runner-Protokolle
außerhalb des Agenten-Workspaces. Der Doctor verwendet weiterhin `.codex_runs`.
`--git` benötigt eine explizite Dateiauswahl (`--git-path`); ein Push zusätzlich
`--git-push`. Vorhandene Dry-run-Berichte werden nicht überschrieben.
Siehe [Controller-Sicherheit und Migration](docs/controller-safety.md).

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

## Decide ab 0.4.0

Decide übernimmt eure Codex-Hostkonfiguration einschließlich Provider,
Authentifizierung, `CODEX_HOME`, Proxy und Zertifikatsumgebung. Ohne expliziten
Override wird weder Modell noch Provider noch Profil ausgewählt. Die vielen
Feature-Overrides entfallen. `read-only`, nichtinteraktiver Betrieb und
Ergebnisprüfung bleiben; konfigurierte Tools/Hooks sind vertrauenswürdige
Hostkonfiguration, nicht präventiv durch ARQUILO deaktiviert.
[Details und Grenzen](docs/decide-configuration.md).

## Auffindbare Projektlogs

Ergänze den bestehenden Runner-Aufruf um `--project-id migration-pilot`.
Die neuen Logs liegen unter `<state-root>/migration-pilot/runs/<UTC-Zeitstempel>/`.
`latest-run.txt` zeigt auf den zuletzt gestarteten Lauf; `run.json` und
`overview.log` zeigen Status und Übersicht. Fehler nennen die konkrete
`stderr.bin`, soweit ein Prozessarchiv vorliegt. Behalte für bestehende Pläne
denselben `--state-dir`: Aufgabenstände und Budgets bleiben unverändert.
[Details und PowerShell-Beispiel](docs/project-logs.md).

## Operatoroptionen

`--max-calls 0` bedeutet **unbegrenzt und ist der Standard**. Auch vorhandene
endliche Budgets übernehmen ihn beim Weiterführen, ohne Verbrauch zu löschen.
`--logs-in-workdir` legt neue Live-Protokolle unter `.codex_runs/run_todos` ab;
maßgebliche Plan- und Budgetdateien bleiben extern.

Für „Aufgabe 2 erstellt weitere Aufgaben in derselben Datei, danach menschliche
Prüfung“: `--allow-todo-modifications --stop 2`. Ohne den ersten Schalter bleibt
der laufende Plan geschützt. Nach der menschlichen Prüfung ohne den Schalter
fortsetzen, bei eigenen Änderungen einmal `--accept-plan-changes` verwenden.
Ein vorhandenes `process_stop` wird nicht automatisch entfernt.
[Anleitung und Beispiele](docs/operator-controls.md).
