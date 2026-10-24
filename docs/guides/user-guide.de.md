# ARQUILO Benutzerhandbuch

**Deutsch · Laufzeitversion 0.9.1 · Integrationsdokumentation 24.10.2026**
[English](user-guide.en.md) · [Alle Handbücher](../README.md) · [Fortgeschrittener Betrieb](operator-guide.en.md)

> **Unveröffentlichter Integrationsstand, nicht das veröffentlichte v0.9.1-ZIP.** Die Laufzeitversionsnummer bleibt 0.9.1. Diese Ausgabe kombiniert die Zustandsreparaturen aus PR #35, die Git-Integritätsreparaturen aus PR #36 und die Handbücher aus PR #33. Siehe [Umfang, Quellcommits und verbleibende Grenzen](../integration-status.md). Daraus folgt kein Merge nach `main`, neuer Tag oder Release.

Dieses Handbuch richtet sich an Menschen, die ARQUILO verwenden und nicht seinen Python-Code verändern möchten. Du solltest ein Terminal öffnen, Dateien kopieren und Ergebnisse prüfen können. Die interne Controllerarchitektur musst du dafür nicht kennen. ARQUILO ist eine öffentliche Vorschauversion: Beginne mit beaufsichtigten Beispielen in einem entbehrlichen Arbeitsverzeichnis, bevor du wichtige Projekte bearbeitest.

## Inhalt

[1. Zweck](#purpose) · [2. Arbeitsmodell](#concepts) · [3. Installation](#installation) · [4. Erste Vorschau](#preview) · [5. Erster echter Lauf](#first-run) · [6. Dokumentbeispiel](#documents) · [7. Softwarebeispiel](#software) · [8. Aufgaben schreiben](#authoring) · [9. Häufige Optionen](#options) · [10. Ergebnisse lesen](#results) · [11. Anhalten](#stopping) · [12. Fortsetzen](#continuing) · [13. Planänderungen](#plan-changes) · [14. Fehlerbehebung](#troubleshooting) · [15. Aktualisieren](#updating) · [16. Checkliste und Vertiefung](#checklist)

<a id="purpose"></a>
## 1. Was ARQUILO macht

ARQUILO macht aus einer Markdown-Aufgabenliste einen Ablauf aus modellgestützter Bearbeitung, gesonderten Reviews und gegebenenfalls Korrekturen. Es ruft eine separat installierte Codex CLI auf. Codex stellt Modellverbindung und Werkzeuge bereit; ARQUILO steuert den Ablauf und entscheidet, ob die Bedingungen für einen dokumentierten Aufgabenabschluss erfüllt sind.

Gute Einstiegsaufgaben sind eine quellengebundene Zusammenfassung, eine kleine Codeänderung oder eine klar abgegrenzte Analyse. Jede Aufgabe braucht ein sichtbares Ergebnis und prüfbare Abnahmekriterien. „Verbessere dieses Projekt“ ist für den ersten Lauf zu unbestimmt.

Ein Review ist verpflichtend, bleibt aber eine Modellbeurteilung. `DONE` garantiert weder sachliche Richtigkeit noch rechtliche Eignung oder Produktionsreife. Prüfe folgenreiche Ergebnisse unabhängig. Der hier beschriebene öffentliche Ablauf in 0.9.1 ist die Ausführung von Aufgabenlisten. Eine grafische Workbench, ein allgemeiner Pipeline-Befehl, Agententeam-Konfigurationen und ein ARQUILO-MCP-Service gehören nicht zu dieser dokumentierten Laufzeitversion.

<a id="concepts"></a>
## 2. Das Arbeitsmodell

| Begriff | Bedeutung für dich |
| --- | --- |
| ARQUILO-Installation | Verzeichnis mit `arquilo.py` und den mitgelieferten Modulen. Halte es vom bearbeiteten Projekt getrennt. |
| Workspace / `--workdir` | Projektverzeichnis mit Eingaben und Ausgaben dieses Laufs. Wähle ein konkretes Projekt, nicht dein gesamtes Home-Verzeichnis. |
| Aufgabenliste / `--todo-file` | Dein Arbeitsplan als Markdown-Datei. Hier vermerkt ARQUILO freigegebene Statusübergänge. |
| Producer | Modellausführung, die eine Aufgabe bearbeitet und erlaubte Dateien verändern kann. |
| Reviewer | Gesonderte Modellausführung im Read-only-Modus, die Ergebnisse gegen den zuvor gesicherten Auftrag prüft. |
| Controller-State | Dauerhafte Plan- und Budgetdaten außerhalb des Workspaces. Beim Fortsetzen erhalten lassen. |
| Logs und Berichte | Ausführungsnachweise und lesbare Aufgabenergebnisse. Sie können Eingabetexte und vertrauliche Informationen enthalten. |

Der normale Ablauf lautet **Aufgabe → Bearbeitung → Review → gegebenenfalls Korrektur → Freigabe durch den Controller**. Die Aussage des Producers, fertig zu sein, genügt nicht. Manche Aufgaben können zerlegt werden; fertige Unteraufgaben ersetzen die gesonderte Abnahme der übergeordneten Aufgabe nicht.

Schreibe keine Passwörter, Zugangstokens oder unbeteiligten persönlichen Daten in Aufgabenlisten. Ein lokaler Workspace bedeutet keine ausschließlich lokale Verarbeitung: Die Kommunikation mit dem Modellanbieter bleibt auch ohne Shell-Netzwerkfreigabe möglich.

<a id="installation"></a>
## 3. Installation und Voraussetzungen

Verwende ein normales Benutzerkonto. Der Kern benötigt Python ab 3.11 und keine Python-Drittpakete. Die gepflegte Testmatrix umfasst Python 3.11, 3.12 und 3.13. Git ist zum Klonen und Aktualisieren des Repositorys hilfreich und für ausdrücklich aktivierte automatische Git-Funktionen erforderlich; alternativ lässt sich ein Release-ZIP verwenden.

Beziehe ARQUILO aus dem [Repository](https://github.com/abernert/arquilo) oder den [Releases](https://github.com/abernert/arquilo/releases). Entpacke bei einer ZIP-Installation das vollständige versionierte Runtime-ZIP, nicht nur eine einzelne Python-Datei. Bei einem Checkout klonst du das Repository und wechselst in dessen Hauptverzeichnis. Die folgenden Befehle setzen voraus, dass dein Terminal im Verzeichnis mit `arquilo.py` steht.

Installiere und authentifiziere Codex separat nach der [offiziellen CLI-Anleitung](https://developers.openai.com/codex/cli). Unternehmensanbieter, Proxys und Zertifikate gehören in deine freigegebene Codex-/Hostkonfiguration und nicht als kopierte Geheimnisse in ARQUILO-Dateien. Für natives Windows beachte auch die [offiziellen Windows-Hinweise](https://developers.openai.com/codex/windows).

**macOS, Linux oder eine Ubuntu-Shell in WSL:**

<!-- example: prerequisites-posix -->
```sh
python3 --version
python3 -B arquilo.py --version
codex --version
codex login status
```

**Native Windows PowerShell:** Wähle einen installierten Python-Interpreter ab 3.11; die Beispiele verwenden `py -3.11`.

<!-- example: prerequisites-windows -->
```powershell
py -3.11 --version
py -3.11 -B .\arquilo.py --version
codex --version
codex login status
```

Für die normale Codex-Anmeldung dient bei Bedarf `codex login`. Dein Unternehmen kann einen anderen freigegebenen Anmeldeweg vorgeben. Prüfe die Einrichtung in genau der Umgebung, in der ARQUILO laufen soll: Eine Windows-Installation ist nicht automatisch eine Ubuntu-/WSL-Installation. Vermische Windows-Python, Linux-Pfade und Linux-Codex nicht in einem Aufruf.

### Werkzeuge außerhalb des Arbeitsbereichs installieren

ARQUILO startet für seine Arbeit vertrauenswürdige Programme des Rechners. Installiere **Codex und Git außerhalb der Verzeichnisse, die eine Aufgabe verändern kann**, einschließlich ihrer Unterarbeitsbereiche. Andernfalls könnte ein Agent im Projekt ein Programm austauschen und den Controller dazu bringen, diese Ersatzdatei auszuführen. Der Installationsort ist deshalb eine Voraussetzung, kein zusätzlicher Aufrufparameter.

Trenne drei Orte: die ARQUILO-Installation, den Projekt-Workspace mit Eingaben und Ergebnissen sowie den privaten Controller-Zustand. Eine benutzerspezifische Codex-Installation in `~/.local/bin` kann beispielsweise ein Projekt unter `~/projects/bericht` bearbeiten; innerhalb dieses Projekts darf sie nicht liegen. Verwende in `PATH` einen absoluten vertrauenswürdigen Verzeichnispfad. ARQUILO prüft die ausführbare Datei einschließlich möglicher Symlink-Ziele vor dem Start; der normale Aufruf über den Programmnamen bleibt gleich. Wähle mit `--workdir` ein Projektverzeichnis, nicht das gesamte Home-Verzeichnis.

Git ist nur für Installation/Updates über Git oder ausdrücklich aktivierte Git-Automatik erforderlich. Node wird nur benötigt, wenn die gewählte Codex-Installation den unterstützten npm-Launcher verwendet. Auch diese Programme gehören außerhalb der beschreibbaren Aufgabenverzeichnisse.

<a id="preview"></a>
## 4. Die erste sichere Vorschau

Verwende das mitgelieferte synthetische Beispiel, kein Kundenverzeichnis. Diese Vorbereitung erstellt einen neuen Workspace und kopiert die Aufgabenliste unverändert. Ein vorhandenes Ziel wird abgewiesen, damit kein früherer Lauf überschrieben wird.

**macOS/Linux/WSL:**

<!-- example: smoke-prepare-posix -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

**Native Windows PowerShell:**

<!-- example: smoke-prepare-windows -->
```powershell
py -3.11 -c "from pathlib import Path; import shutil; p=Path('.local-work/smoke'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/minimal_todo.md', p/'tasks.md')"
py -3.11 -B .\arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --dry-run --dry-run-file .local-work/smoke/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

Öffne `preview.md`. Ein Dry-run prüft den Plan und schreibt die Vorschau. Er führt weder Producer noch Reviewer oder Profil-Preflight aus und setzt keine Aufgaben auf erledigt. Er bestätigt weder Authentifizierung noch native MCP-Konfiguration oder Modellqualität. Vorhandene Vorschauberichte werden nicht überschrieben: Verwende für eine weitere Vorschau etwa `preview-2.md`.

Das ausdrückliche `--mcp none` wählt keine direkten MCP-Server für die Modellaufrufe und deaktiviert in diesem expliziten Modus Plugin-/App-Integrationen. `--skills none` bindet keine Skills ausdrücklich ein; es deaktiviert aber nicht die eigene Skill- oder `AGENTS.md`-Erkennung von Codex. Das Beispiel schaltet außerdem Websuche und Shell-Netzwerk über Taskdirektiven ab. Das ist keine Zusage vollständig netzfreier Ausführung.

Relative CLI-Pfade beziehen sich auf das aktuelle Terminalverzeichnis, **nicht** automatisch auf `--workdir`. Führe diese Befehle weiterhin aus dem Installationsverzeichnis aus. Setze Pfade mit Leerzeichen in Anführungszeichen. Für ein unabhängiges neues Experiment wählst du einen neuen Workspacenamen; lösche nicht den Controller-State, um einen früheren Plan wiederzuverwenden.

<a id="first-run"></a>
## 5. Der erste echte Lauf und seine Prüfung

Führe zunächst den Doctor für lokale Metadaten aus. Er stellt keine Modellanfrage, kann aber Diagnosedateien schreiben.

<!-- example: doctor-posix -->
```sh
python3 -B arquilo.py doctor --workdir .local-work/smoke
```

<!-- example: doctor-windows -->
```powershell
py -3.11 -B .\arquilo.py doctor --workdir .local-work/smoke
```

Mit `--check-decide` entscheidest du dich ausdrücklich für einen echten Modelltest einer eingeschränkten Entscheidung; dabei kann Nutzung anfallen. Dieser Test ist vor dem Tutorial optional und ersetzt keine Produktions-/Reviewabnahme. Er besitzt eigene Optionen; die Ressourcenauswahl des Taskrunners wird nicht automatisch auf diesen separaten Doctor-Aufruf übertragen.

Der folgende Befehl **führt Modellaufrufe aus** und kann Dateien im erlaubten Workspace bearbeiten. Auch der Sandbox-Preflight des Runners kann Nutzung verursachen und liegt außerhalb des Aufrufzählers für den Aufgabenbaum.

<!-- example: smoke-run-posix -->
```sh
python3 -B arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

<!-- example: smoke-run-windows -->
```powershell
py -3.11 -B .\arquilo.py tasklist run --workdir .local-work/smoke --todo-file .local-work/smoke/tasks.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

Erfolg bedeutet: `hello.txt` ist eine reguläre leere Datei, `todo_result_1.md` beschreibt tatsächlich durchgeführte Prüfungen, der gesonderte Review wurde akzeptiert und Aufgabe 1 ist `DONE`. Prüfe den von ARQUILO ausgegebenen externen Laufpfad. Ein unabhängiger Dateicheck lautet:

<!-- example: smoke-check-posix -->
```sh
python3 -c "from pathlib import Path; p=Path('.local-work/smoke/hello.txt'); assert p.is_file() and not p.is_symlink() and p.stat().st_size == 0; print('Empty regular file verified')"
```

Ersetze unter PowerShell `python3` durch `py -3.11`. Dieser Dateicheck allein beweist keinen erfolgten Review; kontrolliere zusätzlich Aufgabenstatus und Logs. Ein endliches Budget kann einen fachlich zulässigen Lauf vor dem Review anhalten. Das ist ein unvollständiger Lauf und keine Erlaubnis, die Aufgabe manuell auf erledigt zu setzen.

<a id="documents"></a>
## 6. Eine Dokumentaufgabe aus vorgegebenen Quellen

Das mitgelieferte `brief.md` ist fiktiv. Die Aufgabe verlangt eine kurze `summary.md`, die drei Meilensteintermine erhält und einen unbekannten Abnahmeverantwortlichen ausdrücklich offenlässt.

Erstelle dafür einen **anderen** Workspace:

<!-- example: document-prepare -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/document'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/document_review_todo.md', p/'tasks.md'); shutil.copyfile('examples/brief.md', p/'brief.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/document --todo-file .local-work/document/tasks.md --dry-run --dry-run-file .local-work/document/preview.md --process-stop-policy controller-only --max-calls 8 --mcp none --skills none
```

Unter nativer PowerShell verwendest du `py -3.11` statt `python3`. Nach dem Lesen der Vorschau wiederholst du den zweiten Befehl **ohne** `--dry-run --dry-run-file .local-work/document/preview.md`, um die Modellausführung freizugeben.

Kontrolliere die Quelle selbst: Anforderungsentwurf **2030-01-10**, Prototyp **2030-01-24**, Abnahmeprüfung **2030-02-07**. Die Zusammenfassung muss unter 250 Wörtern bleiben und einen Abschnitt `Open questions` enthalten. Sie darf keinen Verantwortlichen erfinden. Die Termine gehören ausschließlich zum synthetischen Beispiel und sind keine echten Projektzusagen.

Daran wird eine wichtige Unterscheidung sichtbar: Eine korrekt dokumentierte Unbekannte kann ein akzeptables Ergebnis sein. Ein Blocker entsteht erst, wenn die Aufgabe verlangt, diese Unbekannte vor der Abnahme zu klären. Schreibe diese Unterscheidung in die Aufgabe, statt sie dem Reviewer zum Raten zu überlassen.

<a id="software"></a>
## 7. Eine kleine Softwareaufgabe

Das [Softwarebeispiel](../../examples/python_function_todo.md) verlangt eine Additionsfunktion für ganze Zahlen und gewöhnliche Tests aus der Python-Standardbibliothek. Paketinstallation und Netzwerkzugriff werden nicht benötigt.

<!-- example: software-prepare -->
```sh
python3 -c "from pathlib import Path; import shutil; p=Path('.local-work/software'); p.mkdir(parents=True, exist_ok=False); shutil.copyfile('examples/python_function_todo.md', p/'tasks.md')"
python3 -B arquilo.py tasklist run --workdir .local-work/software --todo-file .local-work/software/tasks.md --dry-run --dry-run-file .local-work/software/preview.md --process-stop-policy controller-only --max-calls 12 --mcp none --skills none
```

Wiederhole nach der Kontrolle den Run-Befehl ohne seine Dry-run-Optionen. Unter Windows gilt die oben beschriebene Interpreterersetzung. Lies die erzeugten Dateien `calculator.py` und `test_calculator.py`, **bevor du modellgenerierten Code selbst ausführst**. Starte danach in einem gesonderten Terminal innerhalb von `.local-work/software`:

<!-- example: software-check -->
```sh
python3 -B -m unittest discover -s . -p test_calculator.py -v
```

Prüfe, ob mindestens die drei verlangten Fälle tatsächlich gelaufen sind: positive Zahlen, eine negative Zahl und Null. „Zero tests ran“ ist keine erfolgreiche Abnahme. Lies `todo_result_1.md` und `todo_result_2.md` und kontrolliere beide Aufgabenstatus. Modellgenerierte Tests können dasselbe Missverständnis wie die Implementierung enthalten; vergleiche sie deshalb mit den geschriebenen Anforderungen.

<a id="authoring"></a>
## 8. Eigene Aufgabenlisten schreiben

Erstelle eine UTF-8-Datei. Verwende eine kurze Projektpräambel und eindeutige numerische Aufgaben-IDs. Rücke ausführbare Aufgabenüberschriften nicht um vier Leerzeichen ein und setze sie nicht in einen Markdown-Codeblock: Dort gelten sie als Beispiele, nicht als auszuführende Aufgaben.

```md
***SYNTAX marked-en***

# Lokale Quellenprüfung
Verwende ausschließlich input.md. Schreibe das Ergebnis auf Deutsch.
Verändere die Aufgabenliste nicht und setze keine Aufgabe auf DONE.
Dokumentiere Blocker; erstelle keine process_stop-Datei.

***CFG network_access=false web_search=disabled***
1. ***Task***: Erstelle findings.md aus input.md und dokumentiere Prüfungen in todo_result_1.md.
    Abnahme: Trenne Quellenfakten von Annahmen. Nenne zu jedem Befund
    den betreffenden Quellenabschnitt. Kennzeichne fehlende Belege ausdrücklich.
```

Lege `input.md` vor dem Start bereit. Benenne Ausgabedatei, erlaubte Eingaben, Tests beziehungsweise Abnahmekriterien und den Umgang mit fehlenden Informationen. „Erstelle findings.md“ ist ein Liefergegenstand; „jeder Befund ist in einem Quellenabschnitt belegt“ ist eine Abnahmebedingung.

Halte Aufgaben klein genug, um sie prüfen zu können. Gemeinsame Anforderungen gehören in die Präambel. Taskdirektiven gelten nur für die nächste Aufgabe; die `CFG` vor Aufgabe 1 konfiguriert nicht automatisch Aufgabe 2. Marker wie `Task`, `DONE`, `CFG`, `WAIT` und Optionsnamen sind Maschinensyntax und werden nicht mit dem Fließtext übersetzt.

Bewahre für wiederkehrende Arbeiten eine saubere Vorlage separat auf. `--todo-template` initialisiert eine fehlende Arbeitsliste und überschreibt keine bestehende. Es kopiert nur die Liste, keine referenzierten Eingaben, und initialisiert auch mit `--dry-run`. Einzelheiten stehen im [Vorlagenrezept](operator-guide.en.md#recipes).

<a id="options"></a>
## 9. Einen Lauf konfigurieren: die wichtigsten Optionen

Die Optionen des Aufgabenläufers stehen **nach `tasklist run`**. Die folgende Tabelle ist die Arbeitsreferenz für den Alltag. Der [Operator Guide enthält sämtliche Befehle und Konfigurationsoptionen](operator-guide.en.md#cli-reference), einschließlich seltenerer und separater Programme. Relative CLI-Dateipfade beziehen sich auf das aktuelle Terminalverzeichnis, nicht automatisch auf `--workdir`.

| Parameter | Verwendung | Standard / wichtige Regel |
| --- | --- | --- |
| `--todo-file DATEI` | Arbeitskopie der Aufgabenliste auswählen. | Für einen echten Aufgabenlauf erforderlich; beim Fortsetzen denselben Pfad verwenden. |
| `--workdir VERZEICHNIS` | Projekt-Workspace festlegen. | Ohne Angabe: Verzeichnis der Aufgabenliste. |
| `--todo-template DATEI` | Eine Vorlage kopieren, wenn die Arbeitsliste noch fehlt. | Aus; bestehende Listen werden nie ersetzt. Ausdrückliches Kopieren erfolgt auch im Dry-run. |
| `--model MODELL_ID` | Modell oder Deployment für den Lauf wählen. | Ohne Angabe geerbt; die Kennung muss beim eigenen Provider verfügbar sein. |
| `--reasoning-effort STUFE` | Gewünschten Reasoning-Aufwand anfordern. | Ohne Angabe geerbt. Zulässige Zeichenketten: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. |
| `--agent PROFIL` | Ein vorhandenes natives Codex-Profil auswählen. | Kein laufweiter Override; `CFG agent` einer Aufgabe kann ihn überschreiben. Kein Agententeam. |
| `--prompt-config default/de/en/DATEI` | Eingebaute Texte oder einen vollständigen eigenen TOML-Katalog wählen. | `default`; eigene Aufgaben und Ergebnissprache bleiben davon getrennt. |
| `--max-calls N` | Aufrufversuche je oberstem Aufgabenbaum begrenzen. | **0 = unbegrenzt**; für einen begrenzten Versuch einen positiven Wert verwenden. |
| `--max-steps N` | Produktions-/Korrekturschritte begrenzen. | 3; der Aufgabenläufer kombiniert dies mit `--max-retries` (Standard 2). |
| `--start ID` / `--stop ID` | Startaufgabe und Grenze nach einer abgenommenen Aufgabe festlegen. | Alle verbleibenden ausgewählten Aufgaben; kein sofortiger Abbruch. |
| `--dry-run` | Anweisungen ohne Modellaufruf vorab ansehen. | Aus. Prüft keine Anmeldung oder Rechte externer Werkzeuge. |
| `--dry-run-file DATEI` | Vorschauziel festlegen. | `run_todos_dry_run.md`; neue Datei wählen, weil Überschreiben abgewiesen wird. |
| `--project-id NAME` | Lesbaren Namen für die Loggruppe vergeben. | Automatische Identität; ein anderer Logname setzt kein Budget zurück. |
| `--logs-in-workdir` | Sichtbare Diagnoseprotokolle im Workspace ablegen. | Aus; der maßgebliche Steuerzustand bleibt immer extern. |
| `--state-dir VERZEICHNIS` | Privaten externen Zustandsordner auswählen. | Plattformstandard; über Neustarts hinweg beibehalten. |
| `--network-access` | Shell-Netzwerkzugriff in der Sandbox freigeben. | Aus; Providerkommunikation, MCP und Websuche sind getrennte Wege. |
| `--mcp NAMEN/none` | Explizite MCP-Serverauswahl begrenzen. | Ohne Angabe geerbt; die Server müssen bereits konfiguriert sein. |
| `--review-mcp NAMEN/none` | Eine Teilmenge für den Reviewer festlegen. | Bei explizitem `--mcp` standardmäßig none; externe Leserechte brauchen serverseitige Begrenzung. |
| `--skills NAMEN/none` / `--skill-dir VERZEICHNIS` | Verfahrensanweisungen binden und gegebenenfalls Suchwurzeln wählen. | Keine explizite Bindung; Suchwurzeln mehrfach angebbar. |
| `--runtime-profile DATEI` | Freigegebene Domänenregeln und optionalen Host-Preflight laden. | Keines; vorher prüfen, weil Preflight Programme auf dem Rechner ausführen kann. |
| `--todo-preamble auto/off/required` | Einbindung gemeinsamer Projektanweisungen steuern. | `auto`; mit `required` eine inhaltliche Präambel verlangen. |
| `--process-stop-policy model/controller-only` | Festlegen, wer laut Anweisung Prozessstopps anfordert. | `model`; beide Modi beachten vorhandene Stopps. |
| `--accept-plan-changes` | Bewusst geprüfte externe Planänderungen übernehmen. | Aus; kein allgemeines Mittel gegen einen ungeklärten Fehler. |
| `--allow-todo-modifications` | Einer Planungsaufgabe Änderungen an der Hauptliste erlauben. | Aus; mit einer bewussten Grenze und anschließender menschlicher Prüfung verwenden. |
| `--git`, `--git-path DATEI`, `--git-push` | Geprüfte Git-Commits und separat Push einschalten. | Aus. Vorher das Git-Kapitel lesen; aktuelle Snapshotgrenzen können den Review blockieren. |

### Modell und Reasoning-Aufwand auswählen

Ersetze `YOUR_MODEL_ID` sowie die beiden Pfade durch dein konfiguriertes Modell/Deployment und dein Projekt. Dies ist ein **echter Lauf**, keine Vorschau. Unter PowerShell verwendest du deinen installierten Python-Befehl und Windows-Pfade; die einzeilige Argumentanordnung bleibt gleich.

<!-- example: model-and-effort -->
```sh
python3 -B arquilo.py tasklist run --workdir /path/to/project --todo-file /path/to/project/tasks.md --model YOUR_MODEL_ID --reasoning-effort high --prompt-config en --max-calls 20
```

Reasoning-Aufwand ist eine Anforderung an das Modell beziehungsweise den Provider, keine Qualitätsgarantie. Eine höhere Stufe kann Arbeitsaufwand, Antwortdauer und Verbrauch erhöhen; wähle nur Werte, die dein Modell unterstützt. Eine unzulässige Kombination ist ein Fehler und keine Erlaubnis, still ein anderes Modell zu verwenden. Die Optionen ändern nicht deine native Codex-Konfigurationsdatei.

### Herkunft und Vorrang der Einstellungen

| Einstellung | Wirksame Reihenfolge |
| --- | --- |
| Modell | `--model` → `ARQUILO_CODEX_MODEL` → `CFG model` der Aufgabe → native Codex-Konfiguration. Eine globale Modellwahl hat also Vorrang vor Aufgabenmodellen. |
| Reasoning-Aufwand | `--reasoning-effort` → `ARQUILO_CODEX_REASONING_EFFORT` → native Konfiguration. Ein aufgabenbezogenes `CFG reasoning_effort` gibt es in diesem Stand nicht. |
| Natives Profil | `CFG agent` der Aufgabe → laufweites `--agent` → native Standardkonfiguration. |
| Eingebaute Prompttexte | Explizites `--prompt-config` oder `default`; keine automatische Suche nach einem Projektkatalog. |
| Domänenregeln | `--runtime-profile` → `ARQUILO_RUNTIME_PROFILE`; getrennt vom nativen Profil und Promptkatalog. |
| Gemeinsame Aufgabenanweisungen | Text vor der ersten echten Aufgabe, gesteuert durch `--todo-preamble`; konkrete Anforderungen stehen in der Aufgabe. |

ARQUILO benötigt weder eine eigene YAML-Konfiguration noch eine automatisch geladene Workspace-`.env`. Für wiederverwendbare Modellvorgaben kannst du die beiden genannten Umgebungsvariablen in der startenden Shell setzen oder ein freigegebenes natives Profil verwenden. Zugangstoken gehören nicht in Aufgaben oder Handbücher. Für MCP und Skills gelten Rechteobergrenzen statt einer einfachen Überschreibungsreihenfolge; lies dazu den Operator Guide.

**Beim Fortsetzen einen endlichen `--max-calls`-Wert erneut angeben.** Ohne Angabe kann eine frühere endliche Grenze auf unbegrenzt wechseln; verbrauchte Versuche bleiben erhalten. Ein Codex-Aufruf kann mehrere interne Modellanfragen enthalten. Der Zähler ist deshalb kein Zeit-, Token- oder Geldlimit. Lass die automatische Git-Veröffentlichung für die Einstiegsbeispiele ausgeschaltet.

<a id="results"></a>
## 10. Ergebnisse, Status und Logs lesen

Betrachte immer drei Dinge gemeinsam: **das tatsächliche Ergebnis**, **Aufgabenliste und Ergebnisbericht** sowie **die Ausführungs- und Reviewnachweise des Controllers**. Eine überzeugend klingende Abschlussmeldung reicht nicht.

Standardorte des Controller-State sind `~/Library/Application Support/ARQUILO/controller` unter macOS, `~/.local/state/arquilo/controller` unter Linux/WSL und `%LOCALAPPDATA%\ARQUILO\controller` unter Windows. Den konkreten Lauf findest du am zuverlässigsten über den ausgegebenen Laufpfad. Eine lesbare Projekt-ID verändert die Logzuordnung, nicht die dauerhafte Budgetidentität. [Logstruktur](operator-guide.en.md#logs-reference)

Häufige Exitcodes des Runners:

| Code | Einordnung |
| --- | --- |
| `0` | Erfolgreiche Rückkehr im ausgewählten Umfang; außerhalb können Aufgaben offenbleiben. |
| `2` / `3` | Ungültige Konfiguration oder Runner-/Controllerfehler. Diagnose lesen, nicht blind erneut starten. |
| `6` | Beobachtetes Prozess-Stoppsignal oder Controllerstopp, etwa bei erschöpftem gemeinsamem Aufgabenbudget. |
| `7` | Technischer Ausführungsfehler, gegebenenfalls zusätzlich zu einem getrennt dokumentierten Stoppsignal. |
| `8` | Ungültiges Reviewprotokoll; das ist kein gültiger PASS. |
| `9` | Unvollständige Arbeit oder nicht erfüllte Ablaufbedingungen. |

Einstiegspunkte und Schichten unterscheiden sich; beispielsweise meldet eigenständiges AutoBuild eine Budgeterschöpfung anders als der Taskrunner. Beachte zusätzlich zur Zahl die Fehlerphase und Meldung. Ein bewusst gewähltes Ablaufende oder ein Lauf ohne offene Arbeit kann 0 liefern, ohne die gesamte Datei zu erledigen.

Eine gegebenenfalls ausgegebene Review-Confidence ist eine unkalibrierte Zusatzinformation und darf Blocker nicht überstimmen. Logs sind weder verschlüsselte noch manipulationssichere Nachweise. Prüfe und bereinige sie vor dem Teilen; ein privater Ablageort macht den Inhalt nicht unbedenklich.

<a id="stopping"></a>
## 11. Bewusst anhalten

Wähle für eine geplante Pause vor dem Start `--stop AUFGABEN_ID`. Um einen laufenden Prozess kooperativ zu unterbrechen, erstellst du die Datei `process_stop` im Hauptworkspace. Für das Smoke-Beispiel lautet der Befehl aus dem Installationsverzeichnis:

<!-- example: stop-posix -->
```sh
python3 -c "from pathlib import Path; f=Path('.local-work/smoke/process_stop').open('x', encoding='utf-8'); f.write('Operator requested stop\n'); f.close()"
```

Unter Windows verwendest du `py -3.11`. Ist die Datei schon vorhanden, bricht dieser Befehl ab, ohne ihren Inhalt zu ersetzen; ihre Existenz signalisiert bereits einen Stopp. Prüfe sie, statt sie zu überschreiben.

Der Controller prüft das Signal vor neuer Arbeit, während relevanter Wartephasen und vor der endgültigen Annahme. Er gibt Stoppinformationen an parallele Worker weiter. Das garantiert **keine sofortige Beendigung jedes abgekoppelten Prozesses oder vertrauenswürdigen Preflight-Befehls**. Kontrolliere Teilresultate und laufende Arbeit vor einer Fortsetzung.

`***STOP***` in der Markdown-Liste ist ein anderer Mechanismus: eine Ablaufbarriere direkt vor einer Aufgabe. Platziere sie vor einem Lauf; etwaige CFG-/WAIT-Zeilen stehen oberhalb der Barriere. Änderungen der laufenden Aufgabenliste können die Planintegritätsprüfung auslösen. Verwende eine Live-Planänderung nicht als normalen Notstopp.

<a id="continuing"></a>
## 12. Nach Unterbrechung oder Fehler fortsetzen

Beende zunächst einen noch laufenden alten Controller. Lies Fehler und letzte Aufzeichnung; prüfe veränderte Dateien und mögliche externe Nebenwirkungen. Behebe die Ursache und erhalte die Nachweise. Verschiebe einen `process_stop`-Marker erst dann aus dem aktiven Pfad, wenn du die Fortsetzung bewusst freigibst; entferne ihn nicht automatisch in einer Wiederholungsschleife.

Starte mit **demselben Workspace, Aufgabenpfad und State-Verzeichnis**, dem beabsichtigten endlichen Aufruflimit und den benötigten Ressourcen-/Profileinstellungen. Bereits akzeptierte Aufgaben werden normalerweise übersprungen. Eine offene Aufgabe kann ihre Bearbeitung erneut beginnen; der normale Neustart setzt nicht „ab der nächsten Zeile“ fort und garantiert keine einmalige Ausführung. Das ist besonders bei Nachrichtenversand oder Änderungen externer Systeme wichtig.

Lösche keinen State, benenne keinen Plan für ein neues Budget um und setze `DONE` nicht manuell zur Fehlerbehebung. Historische DONE-Werte, die als erste Eigentümervorgabe eingelesen wurden, beweisen keinen früheren Review. Version 0.9.1 repariert historisch falsch akzeptierte Läufe nicht automatisch.

Es gibt ein eng begrenztes [Verfahren zur reinen Review-Wiederaufnahme](operator-guide.en.md#recovery-reference): für einen abgeschlossenen Produktionslauf, der früher ausschließlich wegen einer fälschlich als fatal behandelten, tatsächlich überwundenen Reconnect-Meldung abgewiesen wurde. Es verlangt vollständige passende Nachweise und einen neuen Review. Das ist kein allgemeiner Force-resume-Schalter; verwende das Verfahren nur unter seinen dokumentierten Voraussetzungen.

<a id="plan-changes"></a>
## 13. Einen bestehenden Plan absichtlich ändern

Im strikten Standardmodus dürfen Anforderungen und akzeptierter Zustand nicht stillschweigend wechseln. Für eine beabsichtigte Eigentümeränderung stoppst du den Runner, prüfst und bearbeitest den Plan und verwendest einmal `--accept-plan-changes` zusammen mit den normalen Laufoptionen. Dabei wird der frühere Stand archiviert; Budgets bleiben erhalten. Lasse den Schalter bei späteren Läufen wieder weg. Es ist eine ausdrückliche Vertrauensentscheidung, kein Standardmittel gegen Fehlermeldungen.

`--allow-todo-modifications` ist ein anderer, weitergehender Schalter. Er erlaubt gültige modellseitige Änderungen am Arbeitsplan, einschließlich Änderungen, die keine unabhängig geprüfte Erledigung sind. Das ist für eine begrenzte Planungsphase mit anschließender menschlicher Prüfung nützlich, aber kein Anfängerstandard. Siehe [Planung mit Pause](operator-guide.en.md#planning).

<a id="troubleshooting"></a>
## 14. Häufige Probleme

| Symptom | Erster Schritt |
| --- | --- |
| `codex` nicht gefunden oder abgewiesen | Installation und PATH in der aktuellen Betriebssystemumgebung prüfen; Programm und Ziel müssen außerhalb aller ausgewählten Workspaces liegen. |
| Authentifizierungs-, Proxy- oder Zertifikatsfehler | Freigegebene Host-/Anbieterkonfiguration prüfen. Keine Zugangsdaten in Aufgaben aufnehmen und nicht ohne Freigabe den Anbieter wechseln. |
| Vorschaudatei bereits vorhanden | Neuen Dateinamen wählen. Brauchbare Nachweise nicht überschreiben. |
| Planintegritätsfehler | Aktuelle Liste mit akzeptiertem Stand vergleichen. Beabsichtigten Plan wiederherstellen oder eine geprüfte Eigentümeränderung bewusst übernehmen; nie das State-Verzeichnis zurücksetzen. |
| Budget vor Review erschöpft | Teilresultate prüfen, endliches Limit bewusst unter Erhalt des Verbrauchs erhöhen und den Stoppmarker klären. |
| Reconnect-Meldungen | Überwundene Diagnosemeldungen vom Endergebnis unterscheiden. Die Meldung allein bedeutet weder Erfolg noch endgültigen Fehler. |
| Gutes Artefakt, aber Aufgabe offen | Review oder abschließende Controllerannahme können gescheitert sein. Dokumentierte Phase lesen; DONE nicht manuell setzen. |
| Windows-Zugriffsfehler bei paralleler Projektregistrierung | Fehler und vollständige Pending-Datei erhalten, konkurrierende Läufe stoppen. Dieser Integrationsstand enthält die Reparatur aus PR #35 für Issue #32; das veröffentlichte v0.9.1-ZIP nicht. Ein erneuter Fehler muss untersucht werden; State nicht löschen. |

Weitere Hilfe bieten [Troubleshooting](operator-guide.en.md#troubleshooting-reference) und die [bekannten Grenzen](operator-guide.en.md#limitations). Löse Installationsfehler nicht durch routinemäßigen Administrator-/Rootbetrieb oder das Abschalten des Plattformschutzes.

Bei automatischer Git-Veröffentlichung werden nur ausdrücklich ausgewählte Ausgabedateien aus einem verifizierten Vorab-Prüfstand committed. Verwende serielle Aufgaben; wähle weder `tasks.md` noch nachträglich ergänzte Ergebnisberichte aus. Eine verlinkte virtuelle Umgebung oder eine zu große Kontextdatei kann weiterhin **nach der Produktion, vor dem Review** abgewiesen werden. Prüfe den Workspace vorher oder veröffentliche manuell mit Git. Siehe [Git-Veröffentlichung](operator-guide.en.md#git).

<a id="updating"></a>
## 15. Aktualisieren, ohne Fortschritt zu verlieren

Stoppe aktive Läufe und sichere relevante Projekteingaben sowie Controller-Nachweise. Aktualisiere die **gesamte Installation einschließlich Python-Workern**; vermische nicht einzelne alte und neue Module. Prüfe bei einem Git-Checkout lokale Änderungen vor einem normalen Fast-forward-Update. Entpacke bei einer ZIP-Installation die neue Fassung in ein separates Installationsverzeichnis und kontrolliere ihre Version, bevor du den Aufruf umstellst.

Lasse laufende Projektpfade und ihr State-Verzeichnis unverändert. Lies Changelog und Kompatibilitätshinweise und führe einen neuen entbehrlichen Smoke-Test aus. Ein Dateiaustausch allein macht die Fortsetzung eines älteren unvollständigen Plans nicht automatisch sicher. Ein reiner Dokumentationsbranch verändert veröffentlichte Release-Dateien nicht; neuere Anleitungen beziehst du aus der entsprechenden Repository-Revision oder dem Dokumentationspaket.

<a id="checklist"></a>
## 16. Vor wichtiger Arbeit

Prüfe, ob der Workspace bewusst eingegrenzt ist, die Eingaben für den konfigurierten Anbieter freigegeben sind, die Aufgabe beobachtbare Abnahmekriterien besitzt, das Aufruflimit ausdrücklich gesetzt ist und Stopp sowie Wiederaufnahme verstanden sind. Kontrolliere Ergebnisse vor der Veröffentlichung unabhängig. Bewahre Logs angemessen auf, ohne vertrauliche Roharchive ungeprüft an Supportstellen zu senden.

Der [Advanced / Operator Guide](operator-guide.en.md) vertieft Ressourcen, Profile, Parallelität und Betrieb. Der [Technical / Architecture Guide](technical-guide.en.md) erklärt die Interna. Die [Konfigurationsreferenz](operator-guide.en.md#cli-reference) und [Direktivenreferenz](operator-guide.en.md#task-directive-reference) bleiben die detaillierten Nachschlagewerke für die installierte Version.
