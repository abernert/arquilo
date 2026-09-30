# Auftragsgebundener Pflichtreview

Jeder erfolgreiche Produktions- oder Korrekturversuch erhält einen eigenen
Codex-Exec-Review im selben Workspace mit `read-only`. Der Reviewer prüft den
Originalauftrag, die wirksame Vorbemerkung, frühere Ergebnisberichte und die
tatsächlichen aktuellen Artefakte. Der normale Produktionsprompt bleibt der
Referenzauftrag aus der ToDo-Datei. Es gibt keine zusätzliche Beweis- oder
Ledgerpflicht für Erzählungen, Analysen oder andere Fachaufträge.

Die reinen Regeln, JSON-Prüfung und Promptbausteine stehen in
[`review_contract.py`](../review_contract.py). AutoBuild und Parent-Abnahme
verwenden dieselben Regeln; Runtime-Profile ergänzen sie. Eine leere Liste
zusätzlicher Profilregeln entfernt die allgemeinen Regeln nicht.

## Ergebnis und Korrektur

Ein aktueller Review liefert diesen Vertrag:

```json
{
  "verdict": "PASS",
  "short_summary": "Die geforderten Ergebnisse liegen vor.",
  "blocking_issues": [],
  "non_blocking_observations": [],
  "breakdown_recommended": false,
  "breakdown_reason": null
}
```

Ein Blocker enthält eine nichtleere `summary`, die verletzte `requirement`
und ein überprüfbares `acceptance_criterion`. `type` unterscheidet lokale
Korrektur, Zerlegungsbedarf, fehlende Eingabe, tatsächlichen Auftragskonflikt,
technischen Fehler und externe Blockierung. Angegebene IDs sind eindeutig;
Referenzen sind Textlisten. PASS mit Blockern, FAIL ohne Blocker, gemischte
alte/neue Issuefelder, doppelte Schlüssel, unbekannte Felder, falsche Typen,
NaN/Infinity, beschädigtes Unicode und widersprüchliche Breakdownangaben sind
ungültig. Ein ungültiger Pflichtreview ergibt Exit 8 und löst keine blinde
Wiederholung der Produktion aus. Ein ausgefallener Modellaufruf bleibt ein
technischer Fehler mit erhaltener Vorarbeit und Logs.

Für eindeutige ältere JSON-Reviews mit `verdict` und `issues` bleibt die
Kompatibilität erhalten. Fehlende historische Anzeige-/Metadaten werden wie
bisher normalisiert. Freier Legacy-Reviewtext benötigt weiterhin einen
erfolgreichen expliziten Codex-Entscheid; strukturierter PASS/FAIL braucht
diesen zusätzlichen Aufruf nicht. Der Ergebnisvertrag prüft diese Grenze auch
zwischen Runner und Python-Worker. Die Parent-Abnahme selbst verlangt einen
strukturierten JSON-Befund.

Ein Korrekturlauf prüft jeden behaupteten Blocker zuerst am Auftrag und den
Artefakten. Bestätigte Fehler werden mit der kleinsten zusammenhängenden
Änderung behoben. Falsche Kritik oder eine Forderung außerhalb des Scopes
wird mit Auftrags- und Dateibezug im Ergebnisbericht widerlegt; korrekte
Fachartefakte bleiben dabei unverändert. Anschließend folgt immer ein neuer
unabhängiger Review. Die Behauptung „Kritik widerlegt“ allein schließt den
Auftrag nicht ab. Optionale Stilwünsche und erst später beauftragte Arbeiten
werden nicht zur Pflicht.

Bei einer korrekt durchgeführten Dokumentenanalyse sind Quellenfehler,
qualifizierte Ergebnisse und mehrere vertretbare Lesarten zulässig, soweit
der Auftrag das erlaubt. Bei Erzählungen gelten die verlangten inhaltlichen
und erzählerischen Bedingungen. Fehler im untersuchten Gegenstand sind von
Fehlern des Analyse- oder Auditauftrags zu unterscheiden.

## Originalauftrag und Parent-Abnahme

AutoBuild hält den vor der ersten Ausführung erfassten Auftrag für den gesamten
lokalen Korrekturlauf fest. Vor jedem Review schreibt es aus diesem Speicher
eine normale UTF-8-Datei `review_contract_<id>.json` neben seine Logs. Review
und Korrektur erhalten denselben Snapshot inline im Prompt; ein Shell-Lesezugriff
auf die Archivdatei ist dafür nicht erforderlich. Dadurch ersetzen
zwischenzeitliche ToDo-Änderungen die ursprünglichen Kriterien nicht. Die
Datei enthält `original_request`, `task_text` und `source`; die wirksame
Vorbemerkung steckt im Originalprompt, sodass `auto|off|required` erhalten
bleibt. Ein Archivierungsfehler verhindert den Review und Abschluss.

Der Runner hält zusätzlich `original_contract.json` im ersten Tasklog fest.
Nach Bearbeitung der Kinder verwendet die Parent-Abnahme diese ursprünglichen
Kriterien und prüft die integrierten aktuellen Ergebnisse. Erfolgreiche Kinder
allein erzeugen kein DONE für den Elternauftrag. Ein korrekt ausgeführter
Parent-Audit kann FAIL über seinen Gegenstand melden; sein eigener erfolgreicher
Pflichtreview hebt diesen FAIL nicht auf.

Die Bindung gilt innerhalb des laufenden Runners. Ein neu gestarteter Runner
erfasst die dann aktuelle autoritative Aufgabenfassung; alte Aufträge werden
nicht automatisch aus fremden Läufen importiert. Die Dateien sind normale
Laufprotokolle ohne Hashes, Signaturen oder Unveränderlichkeitsbehauptung.
Der eigenständige Decide-Kontext pro Versuch bleibt erhalten.

## Lokale Abnahme

```text
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
```

Die Tests im öffentlichen Entwicklungsrepo verwenden Standardbibliothek und
simulierte Codex-Ergebnisse. Sie prüfen unter anderem die Übergabe des
Originalvertrags, begrenzte Korrekturen und Archivierungsfehler. Das Runtime-ZIP
enthält die Tests nicht; dort bleiben die Paketprüfung und CLI-Hilfe verfügbar.

Die CI-Matrix in `.github/workflows/ci.yml` prüft Python 3.11 und 3.13 auf Linux,
Windows und macOS. Maßgeblich ist das tatsächliche Ergebnis des jeweiligen Runs.
Fakes belegen nicht die Urteilskraft eines realen Modells oder die native
Codex-Sandbox. Siehe [Testanleitung](../docs/testing.md) und
[Architektur](../docs/architecture.md).
