# DORA Lean: Abhängigkeiten und ZIP

Start, Codex-Anmeldung, Doctor, Logs und Retry: [Kurzanleitung](QUICKSTART.md).
Bestehende Projekte: [Migration](MIGRATION.md).

Voraussetzung ist **Python >=3.11** mit Standardbibliothek. Der Kern hat keine
Python-Drittbibliothek und benötigt weder pip noch einen Buildserver. Die
kommentarbasierte `requirements.txt` enthält deshalb keine Installationszeile.
JSON, Dataclasses, Prozesskommunikation, Dateien und einfache Konfiguration
verwenden die Standardbibliothek.

Für echte Aufträge ist eine separat installierte und angemeldete Codex-CLI
erforderlich. Es gibt keine Bindung an eine bestimmte Codex-Version. Der
Doctor prüft mit `--check-decide` den tatsächlichen Decide-Vertrag der
Installation: ein Modellaufruf mit bekannter Antwort, strikter Validierung
und Archivierung; dieser Aufruf kann Kosten verursachen. Ohne die Option
bleibt die Diagnose kostenfrei und kennzeichnet Decide als `NOT_RUN`.
CLI-Schalter, Ausführungsgrenzen und Antwortvertrag müssen weiterhin passen;
eine beliebige künftige CLI wird nicht pauschal als kompatibel zugesagt.
Die Funktionsprobe belegt keine allgemeine Modellurteilsgüte oder native
Sandboxwirkung. Der npm-Launcher benötigt
zusätzlich Node; bei einem nativen Codex-Binary entfällt dieser Launcherbedarf.
Git benötigt DORA nur bei ausdrücklich aktiviertem `--git`.

## ZIP bauen und verwenden

Aus dem Checkout oder einem bereits entpackten Kernpaket:

```text
python3 -B scripts/build_runtime_zip.py
python3 -B scripts/build_runtime_zip.py /pfad/zum/neuen/dora-lean.zip
```

Der erste Befehl erzeugt `dist/dora-lean.zip` im Quellordner des Skripts,
unabhängig vom aktuellen Arbeitsverzeichnis. Der zweite zeigt ein alternatives
Ziel; relative Zielargumente gelten ab dem aktuellen Arbeitsverzeichnis.
Vorhandene ZIPs werden abgewiesen (Exit 2); für einen weiteren Export ein neues
Ziel angeben. Der Export meldet Quelle, Ziel und vollständige Dateiliste als
JSON auf stdout, Fehler auf stderr. Er startet weder Codex noch Git und benötigt
keinen Netzwerkzugriff.

`build_runtime_zip.py` verwendet denselben geprüften Export wie
`python3 scripts/stage_lean.py /pfad/zum/neuen/dora-lean.zip --zip`.

Unter Windows beispielsweise:

```text
py -3.11 -B scripts/build_runtime_zip.py C:\Dora\dora-lean.zip
py -3.11 -m zipfile -e C:\Dora\dora-lean.zip C:\Dora\lean-neu
py -3.11 C:\Dora\lean-neu\run_todos.py --help
```

Zum Entpacken auf macOS/Linux:

```text
python3 -m zipfile -e /pfad/zum/neuen/dora-lean.zip /pfad/zu/lean-neu
python3 /pfad/zu/lean-neu/run_todos.py --help
```

Ein **neues leeres Zielverzeichnis** verwenden. Python-Dateien werden über den
Interpreter gestartet; Bash, make und chmod sind keine Laufzeitvoraussetzungen.
Das ZIP enthält direkt die Dateien der Positivliste, keinen zusätzlichen
übergeordneten Ordner. Der Export verweigert bestehende Ziele und erzeugt
keinen Installer. Auch `stage_lean.py <neuer-ordner>` bleibt verfügbar.

Die Datei `documents/lean_package.json` ist die vollständige Positivliste mit
**45 Dateien** (`runtime_file_count: 45`), keine der 22 früheren Zusatzdateien
und keine `runtime_features.py`. Es gibt keine optionalen Paketgruppen.
Seit 1035 scheitert jede Angabe von `--with-optional` oder Python-`optional`
mit Entfallmeldung vor Quellzugriff und Anlage des Exportziels, auch `()`,
`None`, leere Werte und unbekannte Gruppen. Auswahlargument vollständig entfernen.
Source-Dateien müssen tatsächlich vorhanden sein;
das ZIP lädt keine Dateien nach.
Sortierte Einträge, konstante ZIP-Zeitstempel und Dateirechte machen denselben
Quellstand bei demselben Python/zlib reproduzierbar. Historische Daten,
Git-Verzeichnis, Logs, Tests, Testtreiber und Secrets werden nicht
mitgeliefert. Es gibt keine Hashketten oder Signierung.
Doctor, ToDo-Linter und beide Exportskripte gehören zum Kernpaket.
Paketpfade müssen relativ, eindeutig (auch ohne Groß-/Kleinschreibung), ohne
Symlinks und mit Windows-kompatiblen Dateinamen auflösbar sein. Bestehende
Zieldateien, Zielverzeichnisse und Zielsymlinks werden nicht überschrieben.

## Als Basis für ein neues Repository

Das ZIP enthält alle Runtime-Module einschließlich `dora_doctor.py`, deren
Policy, `VERSION`, die kommentarbasierte `requirements.txt`, die nötigen
Bedienungsdokumente, eine Beispielliste sowie `README.md`, `.gitignore`,
Positivliste und Exportskripte. Alle lokalen Dokumentlinks sind innerhalb des
Pakets auflösbar. Das Paket ist auch ohne den ursprünglichen Checkout lauffähig
und kann sich mit `scripts/build_runtime_zip.py` erneut als ZIP exportieren.

Nach dem Entpacken in einen neuen leeren Ordner kann der Nutzer dort ein
Repository initialisieren, beispielsweise mit
`git -C "/pfad/zu/lean-neu" init` (PowerShell: `git -C "C:\Dora\lean-neu" init`).
Git-Initialisierung, Remoteauswahl, Commit und Push sind keine Exportaktionen.
Es wird weder ein bestehendes Repo kopiert noch eine Installation umgestellt.

Die Repo-Basis enthält bewusst keine `tests/`, `.github/`, Entwicklungs-ToDos,
Ergebnisberichte, `documents/lean_build/`, Historie, virtuellen Umgebungen oder
Lauf-/Projektdaten. Sie liefert damit keine Entwicklungs-CI mit fehlenden
Testquellen aus. Die vorhandene `.gitignore` hält unter anderem Python-Caches,
venvs, `dist/` und Laufprotokolle aus späteren Commits heraus; sie bestimmt
nicht den Paketinhalt. Dafür gilt ausschließlich die Positivliste.

## Trennung von Runtime und Entwicklung

| Bereich | Bedarf |
| --- | --- |
| Kern und ZIP-Export | Python >=3.11; keine pip-Pakete, keine Buildabhängigkeiten |
| Reale Modellarbeit | geprüfte Codex-CLI plus eigene Codex-Anmeldung; kann einen externen Modelldienst nutzen |
| Lean-Tests | `unittest`, `venv` und Python-Fakes aus dem Entwicklungscheckout; keine pip-Pakete; `requirements-dev.txt` dokumentiert diese Grenze |

`openai`, `python-dotenv`, `PyYAML`, `antlr4-python3-runtime`, `cryptography` und `prometheus-client`
sind keine Abhängigkeiten des neuen Kerns. Alte ANTLR-Hilfen fehlen bereits im
Ausgangscheckout. Historische Daten bleiben erhalten. ACE (1030), OpenClaw/Computer-Use/Bridge
(1031), IACT (1032), Queue-/HTTP-/Prometheus-Dienste (1033) und historische Hilfen
(1034) samt Paketauswahl `ace`, `openclaw`, `iact`, `services` bzw. `legacy-tools`
sind entfernt. Alte Auswahlen scheitern vor Anlage des Exportziels.
Die frühere Quality-Suite und ihre Werkzeuganforderungen entfallen; die
Lean-Testtreiber bleiben erhalten. Es wird **kein Wheel** ausgeliefert; das ZIP benötigt keinen
Buildbackend. Eine spätere Wheel-Variante müsste ihre Buildwerkzeuge getrennt
deklarieren und separat geprüft werden.

## Kostenfreier Pakettest

In einer frischen venv ohne pip (keine Aktivierung nötig):

```text
python3 -m venv --without-pip /pfad/zur/test-venv
/pfad/zur/test-venv/bin/python /pfad/zu/lean-neu/run_todos.py --todo-file /projekt/aufgaben.md --workdir /projekt --dry-run --dry-run-file /projekt/vorschau.md
```

Windows verwendet entsprechend
`py -3.11 -m venv --without-pip C:\Dora\test-venv` und
`C:\Dora\test-venv\Scripts\python.exe` für den zweiten Befehl. Der Trockenlauf
prüft keine native Codex-Sandbox; der normale Codex-Preflight eines echten
Runnerstarts kann einen Modellaufruf ausführen.

Im Entwicklungscheckout ist die reproduzierbare Abnahme:

```text
python3 -I -S -B tests/run_lean_distribution.py --output-dir documents/lean_build/meine-neue-paketpruefung
```

Der frei gewählte Ausgabeordner muss neu sein; vorhandene Belege erhalten.
Der Befehl ist ein externer Entwicklungsprüfer, kein Bestandteil des ZIPs.
Er vergleicht Verzeichnisexport und ZIP, entpackt es, erzeugt eine neue venv ohne System-Site-Pakete
und pip und startet deren Python **ohne `-S`**. Leerer PATH und Auditguards
sperren Git, Codex, Shell- und Netzwerkstarts im Import-/Trockenlauftest.
Doctor prüft dort sowohl die Diagnose einer fehlenden CLI als auch drei lokale
Metadatenproben mit einer Python-Prozessfixture; keine echte CLI, kein Modell.
Das Receipt nennt die tatsächlich geprüfte Python-/Hostversion. Es ersetzt
keinen nativen Windows-/Linux-/Python-3.11- oder Live-Codex-Nachweis.
Die Plattformmatrix steht als externer Entwicklungsbeleg im Checkout in
`documents/TEST_MATRIX.md`. Ihre bisherigen Prüflücken bleiben ausgewiesen.
Die Matrixkonsolidierung 1036 und Releaseabnahme 1037 sind frühere
Entwicklungsbelege. Die gezielten Paketprüfungen zu 1039 stehen im Checkout
unter `documents/lean_build/1039/`; sie sind nicht Teil der Distribution.

Konfigurationswerte und ihre Prioritäten stehen in [CONFIGURATION.md](CONFIGURATION.md).
