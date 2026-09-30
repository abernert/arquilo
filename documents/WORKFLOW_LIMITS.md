# Fortsetzung und gemeinsame Aufrufgrenzen

Seit ToDo 1021 gilt `--max-calls 100` als gemeinsame Obergrenze je numerischem
Aufgabenbaum und Runnerlauf. `12`, `12.1`, deren Breakdown, Korrekturen,
Decide-Aufrufe und Parent-Reviews teilen dasselbe Budget. Ein separater
Top-Level-Auftrag `13` erhält ein eigenes Budget. Standalone-AutoBuild nutzt
dieselbe Option für seinen einzelnen Auftrag.

Ein Aufruf zählt unmittelbar vor dem Ausführungsversuch. Produktion, Korrektur,
Pflichtreview, Breakdown-Produktion/-Review, Kinder und Parent-Audit/-Review
kosten jeweils einen Aufruf. Jede tatsächliche Decide-Ausführung zählt ebenfalls,
einschließlich der optionalen zweiten Formatprüfung aus ToDo 1013.
Deterministische JSON-Auswertung, CLI-Versionsprobe und Python-Workerstart
sind keine Modellaufrufe. Fehlgeschlagene Versuche werden nicht gutgeschrieben.
Das ist eine Aufrufgrenze, kein Token-, Kosten- oder Laufzeitlimit.

`max_steps × max_retries` begrenzt im Runner die Produktions-/Korrekturschritte
eines AutoBuild-Auftrags. `--max-retries` bleibt als Kompatibilitätsparameter
erhalten, bedeutet jetzt einen **Fortsetzungsfaktor**. Es gibt einen AutoBuild-
Aufruf und eine Summary mit allen Produktions-, Korrektur- und Reviewversuchen.
Nach einem gültigen fachlichen FAIL folgt eine gezielte Korrektur gegen den
ursprünglichen Auftrag und die konkreten Blocker; danach folgt ein neuer Review.
Ein Gesamtauftrag mit möglichen Seiteneffekten wird nicht erneut abgespielt.
Die frühere AutoBuild-Queue ist seit 1033 entfernt. Standalone-AutoBuild nutzt
`max_steps`; Parallel-CFG verwendet weiterhin Python-Worker und dieselben Budgets.

`breakdown_max_rounds`, `breakdown_max_children` und `max_depth` bleiben
zusätzliche Grenzen. Sie vergrößern das gemeinsame Aufrufbudget nicht.
Ein zusammenhängender Restmangel bleibt innerhalb der lokalen Schritte oder
wird höchstens einem fokussierten Reparaturkind zugewiesen. Unabhängige
Restarbeiten dürfen mehrere Kinder erhalten. Nach den Kindern bleibt die
gesonderte Parent-Abnahme einschließlich ihres Pflichtreviews erforderlich.
Ein negativer Parent-Befund kann nur innerhalb der verbleibenden Grenzen zu
einer weiteren Reparaturwelle führen.

## Budgetende und Fehler

Vor jedem weiteren Modellaufruf wird das gemeinsame Budget geprüft.
Ein PASS auf dem letzten erlaubten Aufruf bleibt gültig. Fehlt noch ein
Pflichtreview, bleiben korrigierte Artefakte erhalten und der Auftrag offen.
Die AutoBuild-Summary enthält `call_budget`, bei Verweigerung zusätzlich
`budget_exhausted`; Standalone-AutoBuild liefert dann Exit 9.
Der Runner führt die bestehende terminale Controllerbehandlung aus:
Diagnose `shared_call_budget_exhausted`, Exit 6 und eine Controller-Stopdatei.
Diese Runtime-Regel bleibt erhalten. Die Entwicklungsprüfungen zu 1021 bilden
Stopdateien ausschließlich virtuell ab und erzeugen keine reale `process_stop`.

Quoten-, Authentisierungs-, Transport- und Protokollfehler bleiben technische
Fehler (Exit 7 beziehungsweise ungültiger Review Exit 8), keine fachlichen
Breakdowngründe. Sie lösen keine Wiederholung des Gesamtauftrags aus.
Auch eine Parent-Abnahme, die abgebrochen wird, startet keine Reparatur.
STOP, WAIT, Fragenablage und `process_stop_policy` behalten ihre bisherige Rolle.
Budgetmangel allein erzeugt keine Nutzerfrage.

## Protokolle, Parallelität und bewusste Fortsetzung

Unter `<controller-state>/<plan>/call_budgets/task_<root>/` stehen `budget.json`,
`reservations.json` (monotoner Zähler) und
fortlaufende `call_000001.json`-Dateien mit Root, Aufgabe, Phase, Limit und Zeit.
Exklusive Dateierzeugung reserviert jeden Platz auch über parallele Python-
Worker hinweg genau einmal. Der Controller vergibt den Pfad; Kinder/Worker
erhalten keinen neuen Vorrat. Gleiche Budgetverzeichnisse dürfen weder das
Limit noch die Root-ID wechseln. Ein fehlgeschlagenes Schreiben kann einen
Platz verbrauchen, startet aber keinen Modellprozess. Summaries und Run-Log
enthalten die Zähler und Verweise; Rohstreams bleiben unverändert erhalten.
Das sind normale Logdateien ohne kryptographische Nachweiswirkung.

Ein ausdrücklich neu gestarteter Runner eröffnet einen neuen Lauf mit neuem
Aufrufbudget. Bereits validierte Breakdown-Pläne werden anhand der aufgezeichneten
Kinder geprüft. Bestehende Kinder werden weiterbearbeitet und danach der Parent
geprüft; seine Produktion wird nicht wiederholt. Gespeicherte DONE-Kinder bleiben
erledigt, OBSOLETE ist weiterhin kein erfolgreicher Abschluss. Ein fehlendes
oder zusätzliches unvalidiertes Kind sowie ein beschädigter Plan blockieren mit
`invalid_breakdown_resume`. Erfolgreiche frühere Breakdown-Runden zählen weiter
gegen `breakdown_max_rounds`.

Ohne validierten Plan ist ein Neustart ein bewusster neuer Bearbeitungsversuch
auf dem vorhandenen Workspace. Vor einem Neustart nach technischen Fehlern
müssen Nutzer/Controller mögliche Seiteneffekte und Teiländerungen prüfen.
Der Runner startet sich nicht selbst erneut. Es gibt keine Session-Wiederaufnahme,
kein neues Board und keine zusätzliche Schedulerinstanz.

Die Regeln sind mit lokalen Fakes unter macOS geprüft. Native Windows-/Linux-
und Live-Codex-Abnahmen bleiben offen. Die manuell startbare CI-Matrix ist in
`.github/workflows/lean-limits.yml` definiert.

Ab 0.3.0 bleiben Reservierungen über einen Neustart erhalten; gelöschte Diagnose-
Claims geben keine Aufrufe frei. [Details](../docs/controller-safety.md).
