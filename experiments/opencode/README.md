# OpenCode: eigenständige Machbarkeitsprüfung (Schritt 1)

Dieser Ordner ist **kein ARQUILO-Backend**. Der Branch
`spike/opencode-feasibility` enthält nur eine technische Erprobung. ARQUILOs
CLI, Codex-Pfad, Laufzustände, Budget, Versionsnummer und Runtime-Paket bleiben
unverändert. `--backend opencode` ist noch nicht implementiert. Nicht nach
`main` mergen, bevor eine separate Integrationsentscheidung getroffen wurde.

## Was wird wirklich geprüft?

Das Programm startet eine **echte native OpenCode-CLI 1.18.34** als lokalen
Server. Statt eines Sprachmodells antwortet ein kleiner, deterministischer
HTTP-Testserver auf derselben Maschine. Er liefert vorgegebene Textantworten,
Werkzeugaufrufe und Fehler. OpenCode verarbeitet diese selbst, liest/schreibt
echte synthetische Dateien und liefert seine nativen Session-/Message-/SSE-Daten.

Damit prüfen wir die Schnittstelle und ihre Steuerbarkeit, **nicht** die Qualität
eines Modells oder den Zugang zu Databricks, LM Studio oder einem Abonnement.
Es werden keine Modellzugangsdaten verlangt oder an den Testprozess weitergegeben.
Auch kein Codex-Aufruf ist erforderlich. Der Binärdownload benötigt Internet;
OpenCode kann beim Start Metadaten oder Hilfspakete beziehen. Dies ist deshalb
kein Nachweis eines vollständig netzwerkfreien Betriebs.

Die separate Testkonfiguration setzt Haupt- und Hilfsmodell auf `spike/fixture`,
begrenzt die Provider darauf und verwendet frische Home-/XDG-/Datenverzeichnisse
unter dem gewählten Diagnoseordner. Persönliche Konfigurationen werden weder
geändert noch in den Test kopiert. Maschinenweit verwaltete Regeln werden nicht
ausgeschaltet. Abweichende effektive Konfiguration beendet den Versuch.
**Diese Isolation ist nur ein Testaufbau, keine Policy für das spätere Backend:**
Ein tatsächlicher OpenCode-Betrieb soll seine freigegebene Host-Konfiguration
verwenden und keine erfundenen Modell-/Providerdefaults bekommen.

## Prüfungen und Erfolgskriterien

| Prüfung | Was PASS bedeutet |
| --- | --- |
| API und Konfiguration | Eigener Loopback-Server startet, richtige Version, geschützter Zugriff ohne Passwort wird abgewiesen; OpenAPI und erwartete Testkonfiguration sind vorhanden. |
| Text und Zuordnung | Antwort ist abgeschlossen, fehlerfrei und derselben Session/Message zugeordnet; sie kann anschließend erneut gelesen werden. |
| Lesewerkzeug | OpenCode liest `input.txt`; das tatsächliche Werkzeugergebnis gelangt zurück zum Testprovider. |
| Schreibwerkzeug | OpenCode erstellt `output.txt` mit dem erwarteten Inhalt und meldet den Werkzeugabschluss. |
| Strukturierte Ausgabe | `info.structured` enthält exakt die lokal validierte Antwort; keine fachlichen Werkzeuge werden verwendet. |
| Verbotener Schreibversuch | Die absichtlich vom Testprovider geforderte, nicht freigegebene Schreiboperation produziert einen Fehler und keine Zieldatei. |
| Providerfehler | Ein absichtlich erzeugtes HTTP-400-Fehlerergebnis wird nicht als erfolgreicher Abschluss interpretiert. |
| Offene Genehmigung | Ein `ask`-Ereignis wird sichtbar; Session-Abbruch funktioniert ohne automatische Genehmigung und ohne die Datei zu schreiben. |
| Laufender Stream | Eine tatsächlich laufende Providerverbindung lässt sich abbrechen; persistierter Fehler und anschließend inaktiver Zustand verhindern eine falsche Erfolgsmeldung. |

Ein normaler `tool-calls`-Zwischenschritt, `idle` allein, ein Fehler, ein
abgeschnittener Abschluss (`length`) oder irgendeine letzte Textnachricht sind
kein Erfolg. Die konkrete strukturierte Antwort wird zusätzlich auf den
angeforderten kleinen Vertrag geprüft; das ist kein allgemeiner JSON-Schema-
Validator. Native strukturierte Ausgabe verwendet intern `StructuredOutput`.
Der Test erlaubt diese Ausgabeoperation ausdrücklich, während Shell, MCP,
Dateiänderungen und Unteragenten in der Entscheidungsrolle nicht freigegeben sind.
Der Name allein wäre in einem späteren produktiven Adapter keine ausreichende
Authentifizierung eines fremden Tools.

Jeder Testfall erhält eine neue Session. Der Testprovider, dessen Session-Titel
und alle Dateien sind synthetisch. Freigabeantworten werden nie automatisch
bestätigt. Es gibt enge technische Laufzeit-/Ausgabelimits für diesen Versuch;
sie ändern **nicht** ARQUILOs unbegrenztes Standardbudget.

## Auf dem Mac starten

Im bestehenden ARQUILO-Checkout zunächst den Erprobungsbranch holen. Bei einer
bereits lokal vorhandenen Branchkopie stattdessen `git switch
spike/opencode-feasibility` und `git pull --ff-only` verwenden. Einen laufenden
ARQUILO-Prozess nicht durch einen Branchwechsel in dessen Checkout verändern;
stattdessen einen separaten Checkout/Worktree für den Test verwenden.

```bash
git fetch origin
git switch --track origin/spike/opencode-feasibility
python3 -B -m unittest discover -s experiments/opencode -p 'test_*.py' -v
```

Der letzte Befehl testet zunächst nur das Prüfprogramm. Er installiert nichts,
startet kein OpenCode und ruft kein Modell auf. Erfolg endet mit `OK`.

Ist eine freigegebene native OpenCode-CLI **1.18.34** bereits vorhanden, ihren
Pfad mit `command -v opencode` ermitteln und direkt unten einsetzen. Andernfalls
lädt der folgende optionale Schritt das offizielle Versionsarchiv in einen
neuen separaten Ordner. SHA-256 wird gegen die veröffentlichte GitHub-Angabe
geprüft; es erfolgt keine globale Installation und keine PATH-Änderung.

```bash
python3 -B experiments/opencode/download_test_binary.py \
  --destination "$HOME/ARQUILO-OpenCode-Test/bin-1.18.34"

python3 -B experiments/opencode/feasibility.py \
  --opencode "$HOME/ARQUILO-OpenCode-Test/bin-1.18.34/opencode" \
  --out "$HOME/ARQUILO-OpenCode-Test/versuch-1"
```

**Beide Zielordner müssen beim ersten Aufruf neu sein.** Beim nächsten Versuch
wird dasselbe Binary wiederverwendet, aber `--out .../versuch-2` angegeben.
Bestehende Diagnosen und Ergebnisse werden nicht überschrieben.

## Auf Windows/MDE starten

Dies sind kopierbare PowerShell-Befehle, **keine auszuführende `.ps1`-Datei**.
Python 3.11 oder neuer muss vorhanden sein. `python` bei Bedarf durch eure
bekannte Python-EXE ersetzen. Die MDE muss die native OpenCode-EXE und Loopback-
Verbindungen freigeben. Keine Execution-Policy-, Dienst-, TLS- oder Sandbox-
Einstellungen zur Umgehung einer Unternehmensrestriktion ändern.

```powershell
git fetch origin
git switch --track origin/spike/opencode-feasibility
python -B -m unittest discover -s experiments/opencode -p 'test_*.py' -v

Get-Command opencode.exe -ErrorAction SilentlyContinue |
    Select-Object Name, Source
```

Ein vorhandener freigegebener **nativer EXE-Pfad** kann direkt als `$OpenCode`
verwendet werden. Eine `.cmd`-, `.bat`- oder `.ps1`-Hülle wird im Spike bewusst
nicht über eine Shell gestartet. Der Test setzt keine bestimmte globale
Installation voraus. Den Download nur ausführen, wenn eure IT ihn gestattet:

```powershell
python -B experiments/opencode/download_test_binary.py `
    --destination "$HOME\ARQUILO-OpenCode-Test\bin-1.18.34"

$OpenCode = "$HOME\ARQUILO-OpenCode-Test\bin-1.18.34\opencode.exe"

python -B experiments/opencode/feasibility.py `
    --opencode $OpenCode `
    --out "$HOME\ARQUILO-OpenCode-Test\versuch-1"
```

Auch hier: Downloadordner und erster Versuchsordner dürfen noch nicht existieren.
Der Test startet seinen Server selbst, schützt ihn mit einem zufälligen Passwort
und beendet nur seinen eigenen Prozess/Prozessbaum. Bereits laufende persönliche
OpenCode-Instanzen werden nicht verwendet oder gestoppt.

## Ausgabe verstehen und finden

Während des Tests erscheinen benannte `PASS`-/`FAIL`-Zeilen und am Ende der
konkrete Pfad zu `report.json`. **Exitcode 0** bedeutet, dass die implementierte
synthetische Prüffolge bestanden ist. **Exitcode 1** bedeutet einen Prüf- oder
Infrastrukturfehler; Argumentfehler können vor dem Anlegen des Reports abbrechen.
Eine noch als `RUNNING` gespeicherte Datei ist keine erfolgreiche Abnahme.

```text
ARQUILO-OpenCode-Test/
  bin-1.18.34/
    opencode(.exe)
    download.json
  versuch-1/
    report.json
    fixture-opencode.json
    workspace with spaces/
      input.txt
      output.txt
    logs/
      server.stdout
      server.stderr
      openapi.json
      events.jsonl
      provider-requests.json
      <Fall>-request.json
      <Fall>-response.json
      <Session>-messages.json
    home/, config/, data/, cache/, state/, ...
```

Zum Lesen unter Windows:

```powershell
Get-Content "$HOME\ARQUILO-OpenCode-Test\versuch-1\report.json" -Raw -Encoding UTF8
Get-Content "$HOME\ARQUILO-OpenCode-Test\versuch-1\logs\server.stderr" -Tail 100 -Encoding UTF8
```

Der Tokenwert des lokalen Serverpassworts wird nicht absichtlich protokolliert.
Die aufgezeichneten Providerdaten sind beim unveränderten Test synthetisch;
interne Hostpfade können trotzdem enthalten sein. Berichte vor dem Weitergeben
prüfen. Keine persönlichen Zugangsdaten, Auth-Dateien oder kopierte MDE-
Konfigurationen in den öffentlichen Branch einchecken.

Ein GitHub-HTTP-403 beim Download kann das anonyme API-Kontingent des Anschlusses
betreffen. CI nutzt deshalb ausschließlich im Downloadschritt ein lesendes
GitHub-Token für die Versionsmetadaten. OpenCode selbst erhält dieses Token
nicht. Lokal besser ein bereits freigegebenes Binary verwenden oder den
Download später wiederholen; keinen Unternehmensschutz abschalten.

## Was noch ausdrücklich NICHT bewiesen ist

Keine Modellqualität, keine echte Databricks-/LM-Studio-Anmeldung, keine
MDE-Proxy-/Zertifikatsverträglichkeit. Kein Test mit Unternehmensdokumenten,
keine Browser-/Desktop-Oberfläche, keine ARQUILO-Aufgabenliste, kein produktiver
Review oder Decide-Aufruf. Die Leseregel ist **keine Betriebssystem-Sandbox**.
Insbesondere sind allgemeine Shell-Ausführung, Unterprozess-Abbruch und externe
MCP-Seiteneffekte nicht durch die vorhandenen nativen Lese-/Schreibtests zertifiziert.
Ein lokaler Prozess unter demselben Benutzer kann ohne zusätzliche Isolation
weitergehenden Zugriff haben; dafür garantiert dieser Test keine Begrenzung.

Ein späterer Realmodell-Test braucht einen **explizit ausgewählten und bereits
freigegebenen OpenCode-Konfigurationskontext** auf dem Zielrechner. Dabei wird
zunächst derselbe kleine synthetische Auftrag geprüft, nicht sofort ARQUILO
umgebaut. Ergebnisse werden getrennt von dieser Transportprüfung dokumentiert.
Die Integration beginnt erst nach einer eigenen Entscheidung über Schritt 2.

## Primärquellen und Prüfstand

- OpenCode 1.18.34: https://github.com/anomalyco/opencode/releases/tag/v1.18.34
- Native Server-API: https://opencode.ai/docs/server/
- Strukturierte Ausgabe: https://opencode.ai/docs/sdk/
- Konfigurationsreihenfolge: https://opencode.ai/docs/config/
- Werkzeugberechtigungen: https://opencode.ai/docs/permissions/
- Sicherheitsgrenzen: https://github.com/anomalyco/opencode/blob/v1.18.34/SECURITY.md
- Versionsgebundener Ergebnis-Handler: https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/session/prompt.ts

Maßgeblich für die gemessene Schnittstelle ist die beim Versuch archivierte
OpenAPI-Datei der tatsächlich gestarteten Version, nicht allein die laufend
aktualisierte Website. Konkrete Ergebnisse stehen in `RESULTS.md`, sobald der
Teststand ausgewertet ist.
