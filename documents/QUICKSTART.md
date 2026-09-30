# DORA Lean: Installation und Bedienung

Dieser Stand benötigt **Python >=3.11**, keine Python-Pakete und für echte
Aufträge eine separat installierte **Codex-CLI**. Eine bestimmte CLI-Version
ist nicht vorgeschrieben. Nach Installation oder CLI-Update den tatsächlichen
Decide-Vertrag mit `dora_doctor.py --check-decide` prüfen (kann Modellkosten
verursachen; Details unten).
`VERSION` lautet noch `1.0-rc5`; dies ist der Lean-Entwicklungsstand, keine
Freigabe für unbeaufsichtigten Betrieb. Native Windows-11-/Linux-/WSL2-Läufe
und Live-Modell-/Sandboxabnahmen sind hier weiterhin nicht verifiziert.

## Einmalig einrichten

1. Python 3.11 oder neuer installieren. macOS/Linux: `python3 --version`;
   natives Windows/PowerShell: `py -3.11 --version` (bei neuerem Interpreter
   die Versionsauswahl entsprechend ändern). Download: [Python](https://www.python.org/downloads/).
2. Codex separat nach der
   [offiziellen CLI-Anleitung](https://learn.chatgpt.com/docs/codex/cli)
   bereitstellen und mit `codex --version` anzeigen. Die Versionsnummer dient
   der Diagnose; maßgeblich ist die Funktionsprobe. `codex` muss im PATH des
   startenden Terminals liegen.
   Unter Windows bevorzugt DORA `codex.exe`; der unveränderte Standard-npm-
   `codex.cmd` wird über `node.exe` und `bin/codex.js` gestartet. Andere Batch-/
   PowerShell-Wrapper werden abgewiesen. Kein Aufweichen der Execution Policy nötig.
3. Im eigenen Terminal `codex login` ausführen und die Browseranmeldung abschließen;
   `codex login status` zeigt den Anmeldestatus. DORA richtet keine Anmeldung ein,
   lädt keine `.env` und benötigt keinen eigenen API-Key. Zugangsdaten gehören
   nicht in ToDos, Profile oder Ergebnisdateien.
   [Codex-Anmeldung](https://learn.chatgpt.com/docs/auth)
4. Das DORA-ZIP in einen **neuen, leeren Ordner** entpacken. Laufende Installation
   und deren venv behalten; erst nach Abnahme bewusst auf den neuen Pfad umstellen.
   [Verzeichnisexport und ZIP](DISTRIBUTION.md) verwenden dieselbe Positivliste
   mit 45 Dateien einschließlich README, `.gitignore` und Exportskripten für
   eine neue Repo-Basis. Es gibt keine Zusatzpakete oder Nachinstallation.

macOS/Linux (absolute Beispielpfade anpassen):

```text
python3 -m zipfile -e "/pakete/dora-lean.zip" "/programme/dora-lean-neu"
python3 -B "/programme/dora-lean-neu/run_todos.py" --help
```

Natives Windows, PowerShell; weder Bash noch make/chmod nötig:

```powershell
py -3.11 -m zipfile -e "C:\Pakete\dora-lean.zip" "C:\Dora\lean-neu"
py -3.11 -B "C:\Dora\lean-neu\run_todos.py" --help
```

Eine eigene venv ist optional: `python3 -m venv --without-pip /pfad/venv`
bzw. `py -3.11 -m venv --without-pip C:\Dora\venv-neu`. Danach deren
`bin/python` bzw. `Scripts\python.exe` statt `python3`/`py -3.11` verwenden;
in PowerShell einen quotierten Interpreterpfad mit `&` aufrufen. Keine
Aktivierung und kein `pip install` für den Kern erforderlich.

**Windows-Sandbox:** Die native Codex-Sandbox muss vor dem echten DORA-Lauf
im eigenen Codex eingerichtet sein. Die offizielle Dokumentation bevorzugt
`[windows] sandbox = "elevated"`; die Ersteinrichtung kann eine bewusste
Admin-/UAC-Zustimmung für Sandboxbenutzer und Firewallregeln verlangen.
Das bezeichnet die Sandbox-Implementierung, keine allgemeine Freigabe des
Agenten. DORA führt diese Einrichtung nicht aus, startet keinen Adminprozess
und eskaliert bei Fehlern nicht automatisch. Einrichtung mit Codex bzw. der IT
abschließen; DORA anschließend als normaler Nutzer starten. Ein `unelevated`-
Fallback hat andere Grenzen und ist hier nicht als gleichwertig abgenommen.
WSL2 verwendet den Linuxpfad und zählt nicht als nativer Windowsnachweis.
[Windows-Sandbox und Fehlerdiagnose](https://learn.chatgpt.com/docs/windows/windows-sandbox)

## Projekt vorbereiten und kostenfrei prüfen

Einen vorhandenen Projektordner als gemeinsamen Workspace wählen. Die
[Beispielliste](../examples/lean_todo.md) als `aufgaben.md` dorthin kopieren und
anpassen. Bestehende Listen bleiben verwendbar; vor dem Start die
[Migration](MIGRATION.md) anwenden. ToDo-Datei und Workspace explizit und absolut
angeben: **Ohne `--workdir` gilt der Ordner der ToDo-Datei**, nicht automatisch
die Projektwurzel. Dadurch funktionieren die Aufrufe aus jedem Arbeitsverzeichnis.

macOS/Linux:

```text
python3 -B "/programme/dora-lean-neu/dora_doctor.py" --todo-file "/projekte/Projekt/aufgaben.md" --workdir "/projekte/Projekt"
python3 -B "/programme/dora-lean-neu/run_todos.py" --todo-file "/projekte/Projekt/aufgaben.md" --workdir "/projekte/Projekt" --dry-run --dry-run-file "/projekte/Projekt/vorschau.md" --process-stop-policy controller-only
```

PowerShell:

```powershell
py -3.11 -B "C:\Dora\lean-neu\dora_doctor.py" --todo-file "C:\Projekte\Projekt\aufgaben.md" --workdir "C:\Projekte\Projekt"
py -3.11 -B "C:\Dora\lean-neu\run_todos.py" --todo-file "C:\Projekte\Projekt\aufgaben.md" --workdir "C:\Projekte\Projekt" --dry-run --dry-run-file "C:\Projekte\Projekt\vorschau.md" --process-stop-policy controller-only
```

Der Doctor zeigt Interpreter, Installations-/Workspace-/Logpfade, Versionen,
benötigte Exec-Schalter und die Prüfung der Decide-Featurewerte. Er startet
ohne `--check-decide` nur `--version`, `exec --help` und `features list`, jeweils mit zehn Sekunden
Antwortzeitlimit zuzüglich Prozessbereinigung, keinen Modellprompt. `--json` liefert auch bei Fehlern einen strukturierten
Bericht auf stdout. Exit **0 / QUALIFIED** bedeutet: lokale Voraussetzungen
bestanden, Anmeldung, Modellzugang und Sandboxwirkung **nicht verifiziert**.
Die Funktionsprobe steht dabei ausdrücklich auf `decision_probe.status=NOT_RUN`;
Exit 0 allein belegt keine funktionierende Entscheidung.
Exit **1 / FAIL** benennt fehlende Voraussetzungen; CLI-Syntaxfehler liefern 2.
DORA liest dabei selbst keine Auth-Dateien und gibt keine Umgebungs-/Konfigurationsdumps aus.
CLI-Diagnosetext wird nur als `stderr_present` vermerkt. Für Details denselben
Leseaufruf lokal im Terminal prüfen; keine Secrets in Supportberichte kopieren.

Der Trockenlauf prüft die Aufgabenplanung und schreibt nur die gewählte Vorschau;
er überspringt Codex und Profil-Preflight. Einen eigenen Vorschaupfad verwenden,
denn die Vorschau wird überschrieben. `--print-capabilities` zeigt kostenfrei
die DORA-Kernverträge und die erhaltenen Optionen für Parallel-CFG,
Runtime-Profile und Git-Opt-in; keine Zusatzgruppen.
Diese Diagnosewege ohne Funktionsprobe sind keine Live-Abnahme.
Ein WAIT auf ein noch nicht gespeichertes DONE kann auch im Trockenlauf
Exit 9 liefern: Die Vorschau schreibt keine künftigen DONEs in die Liste.
In diesem Fall die vorhandene Teilvorschau prüfen bzw. den Bereich mit
`--start`/`--stop` wählen; die Bedingung nicht als erfolgreich getestet ausgeben.

## Decide mit der installierten CLI prüfen

Nach den lokalen Prüfungen die Funktionsprobe ausdrücklich einschalten:

```text
python3 -B "/programme/dora-lean-neu/dora_doctor.py" --workdir "/projekte/Projekt" --check-decide --json
```

```powershell
py -3.11 -B "C:\Dora\lean-neu\dora_doctor.py" --workdir "C:\Projekte\Projekt" --check-decide --json
```

**Das kann Modellkosten verursachen.** Der Doctor ruft den öffentlichen
`decide.py`-Pfad genau einmal auf, sofern die lokalen Voraussetzungen bestehen.
Die kurze Rechenfrage benötigt keine Projektinhalte oder Werkzeuge. Nur die
erwartete Auswahl mit gültiger Begründung, erfolgreichem Exec-Abschluss und
vollständigem Entscheidungsarchiv ergibt `decision_probe.status=PASS`.
Ungültiges JSON, falsche Antwort, Auth-/Providerfehler, fehlende Antwortdatei,
Zeitüberschreitung, Abbruch oder Archivfehler ergeben Exit 1. Keine automatische
Wiederholung und keine Aufweichung der Sandbox-/Werkzeugregeln.

Optional `--model MODELL_ID --reasoning-effort low --decide-timeout 120`
ergänzen. Ohne Modellangabe gilt derselbe Standard wie bei `decide.py`.
Das Zeitlimit betrifft den Exec-Aufruf, zuzüglich Metadatenproben und
Prozessbereinigung. Diese Optionen erfordern `--check-decide`.
Die Codex-Anmeldung wird wie bei Decide aus dem eigenen `~/.codex` verwendet;
eine geerbte `CODEX_HOME`-Variable wählt hier keine andere Anmeldung.
Logs einschließlich Fehlversuchen bleiben unter
`<workdir>/.codex_runs/dora_doctor/decide/`; das konkrete Archiv steht im Bericht.
Ein vorhandenes `process_stop` verhindert den Modellstart. Projektaufträge
und deren Status werden nicht bearbeitet.

Auch nach PASS bleibt der Gesamtstatus `QUALIFIED`: Geprüft ist die konkrete
Decide-Funktion mit diesem Modell und dieser Installation, keine allgemeine
Modellurteilsgüte oder native Sandboxwirkung. `model_calls` zählt gestartete
Exec-Prozesse; es ist kein Abrechnungsnachweis.

## Bewusst einen echten Auftrag starten

Nach Einrichtung und Prüfung: Im jeweiligen Runnerbefehl oben `--dry-run` und
`--dry-run-file …` entfernen. Optional `--start 1 --stop 1` ergänzen, um die
erste Aufgabe auszuwählen. **Der echte Start kann bereits beim Codex-Preflight
Modellkosten verursachen**, anschließend für Produktion, Review, Korrektur und
gegebenenfalls Decide. Installer, Help, Doctor ohne `--check-decide` und
Trockenlauf starten das nicht.
Der Preflight liegt außerhalb des Aufgabenbudgets `--max-calls`.
`--skip-codex-preflight` ist nur für extern geprüfte Umgebungen vorgesehen und
macht die anschließende Aufgabenarbeit nicht kostenfrei.

| Auswahl | Wirkung |
| --- | --- |
| `--model MODELL_ID --reasoning-effort medium` | `MODELL_ID` durch ein im eigenen Codex-Zugang verfügbares Modell ersetzen. Keine feste Modellvorgabe; Verfügbarkeit/Effort werden im echten Codex-Lauf geprüft. Für reproduzierbare Decide-Auswahl Modell explizit setzen. |
| `--network-access` | Shellnetzwerk ausdrücklich erlauben. Ohne diese Option aus; `CFG network_access=true` benötigt diese Starterfreigabe. |
| `--max-calls 20` | Gemeinsames Aufrufbudget pro Aufgabenbaum im Lauf, einschließlich Reviews/Korrekturen/Decide; kein Geld-/Tokenlimit. |
| `--todo-preamble required` | Inhaltliche Vorbemerkung erzwingen; `auto` ist Standard, `off` schaltet nur die Einbettung aus. |

Die maximale Schreibgrenze bleibt `workspace-write`, der Review läuft lesend.
`approval_policy=never` betrifft Nachfragen und hebt die Sandbox nicht auf.
Shellnetzwerk, integrierte Websuche, MCP/Apps und Providerkommunikation sind
getrennte Wege: `--network-access` verändert keine Dateirechte und Netzwerk aus
bedeutet keine Offline-Inferenz. Modellprioritäten und Details:
[Konfiguration](CONFIGURATION.md), [CFG/WAIT/STOP](todo_directives.md).

## Ergebnisse, Abbruch und Retry

Ergebnisse stehen neben der aktiven ToDo-Datei als `todo_result_<id>.md`,
Fragen mit Datum/Zeit in `todo_fragen.md`. Der Agent dokumentiert und repariert;
der Controller entscheidet nach Pflichtreview über DONE. OBSOLETE bedeutet
entfallen, nicht erfolgreich erledigt. Neue Aufgaben verwenden
`<id>. ***Task***: Text`. Ein gültiger Breakdown verlangt weiter die Parent-Abnahme.

Die Laufablage liegt unter `<workdir>/.codex_runs/run_todos/<lauf>/`:
`run_config.json`, Tasklogs unter `todo/<id>/<versuch>/`, darunter
`autobuild/attempt_1/autobuild_summary.json`, lesbare Logs und JSONL.
Die `*.calls/`-Unterordner behalten `prompt.utf8`, `stdout.bin`, `stderr.bin`,
`response.txt` und `capture.json`. Decide-Archive liegen unter einem
`decide/`-Unterbaum der verwendeten Codex-Logwurzel, mit Input, Prompt, Schema,
Antwort und `call.json`; fehlgeschlagene Versuche bleiben sichtbar.

Dies sind vollständige **erfasste** Ein-/Ausgaben und ausgewählte I/O-Kopien,
keine vollständige Sicherung des Workspaces. Fehler oder unvollständige Erfassung
stehen im Status. Rohbytes können sensible Projekt-/Werkzeugausgaben enthalten;
vor Weitergabe prüfen. Keine Hashketten, Signaturen oder Unveränderbarkeitsgarantie:
Logs dienen Diagnose und Review, nicht als kryptographischer Nachweis.

Mit **Ctrl+C** abbrechen und die Rückkehr des Controllers abwarten. Ein
vorhandenes `process_stop` stoppt weitere Arbeit; `***STOP***` unmittelbar vor
einem ToDo stoppt die Auswahl ohne diese Datei. Die Beispiele verwenden
`--process-stop-policy controller-only`: Der Agent soll keine Stopdatei schreiben;
die technische Stopentscheidung verbleibt beim Controller.

Vor einem Retry Ursache und Teiländerungen anhand von Summary/Logs prüfen,
etwa Anmeldung/Quota, Rechte oder einen Dateilock beheben. Einen vorhandenen
Stop erst nach Klärung durch den verantwortlichen Nutzer/Controller aufheben;
DORA entfernt ihn nicht automatisch. Dann denselben Runner bewusst erneut
starten, optional mit `--start <id>`. Frühere DONEs bleiben erhalten. Ein neuer
Lauf erhält ein neues Budget; ohne validierten Breakdown-Plan ist dies ein neuer
Versuch im fortgeschriebenen Workspace, keine Codex-Session-Wiederaufnahme.
`--max-retries` ist ein Fortsetzungsfaktor innerhalb der Grenzen und wiederholt
keinen technisch gescheiterten Gesamtauftrag blind. Details:
[Fortsetzung und Budgets](WORKFLOW_LIMITS.md).
