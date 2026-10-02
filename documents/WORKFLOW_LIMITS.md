# Aufrufbudget, Fortsetzung und weitere Grenzen

`--max-calls 0` ist der Standard: keine Obergrenze der gezählten Codex-
Ausführungsversuche. Ein positiver Wert begrenzt je numerischem Hauptaufgabenbaum
über Neustarts hinweg. `12`, `12.1`, deren Kinder, Breakdown, Korrekturen, Reviews
und Decide teilen einen Zähler; Hauptauftrag `13` erhält seinen eigenen.

Gezählt wird vor einem Ausführungsversuch, nicht jeder interne Modellrequest von
Codex. Start-/Provider-/Archivfehler werden nicht gutgeschrieben. Ein einzelnes
`codex exec` kann mehrere Modellanfragen enthalten. Das Budget ist kein Geld-,
Token- oder Zeitlimit. CLI-Metadatenproben, reine Python-Workerstarts und
JSON-Auswertung zählen nicht. Der separate Sandbox-Preflight ist nicht Teil
des Aufgabenbaum-Zählers. Bei unbegrenztem Budget wird der Verbrauch weiter gezählt.

## Bereits begonnene Läufe

Der Runner übernimmt beim Start das gewählte Limit für vorhandene Budgets im
bisherigen Controller-Zustand. Ohne Parameter werden auch frühere Limits von
100 oder erschöpfte Limits auf **0 = unbegrenzt** umgestellt. Reservierungen und
Claims bleiben erhalten; Änderungen werden unter `limit_changes/` protokolliert.
Nur der Betreiber/Runner darf Limits ändern, nicht ein Worker. Ein ausdrücklich
gewähltes endliches Limit muss mindestens den bereits verbrauchten Wert umfassen.
Beschädigte Zustände werden nicht automatisch gelöscht oder zurückgesetzt.

Workspace, Aufgabenlistenpfad und `--state-dir` bei Fortsetzung beibehalten.
Neue Laufzeitstempel und andere Logorte eröffnen keinen neuen Zähler. Alte
`process_stop`-Dateien bleiben als separate Stoppanweisung bestehen, auch wenn
sie ursprünglich durch ein erschöpftes Budget entstanden sind. Vor ihrer
bewussten Entfernung die Ursache, Teiländerungen und die Fortsetzung prüfen.

## Weitere Schleifen- und Abbruchgrenzen

`max_steps × max_retries` begrenzt im Runner die Produktions-/Korrekturschritte
eines AutoBuild-Auftrags (Standard 3 × 2). `max_retries` ist ein Fortsetzungsfaktor,
kein vollständiges Wiederholen des Auftrags. Nach gültigem fachlichem FAIL kann
eine gezielte Korrektur gegen den ursprünglichen Auftrag mit neuem Review folgen.
Standalone-AutoBuild verwendet `max_steps`. Parallel-CFG verwendet Python-Worker
und die vom Controller vergebenen gemeinsamen Budgetverzeichnisse.

`breakdown_max_rounds`, `breakdown_max_children`, `max_depth`, Aufruf-Timeouts,
STOP/WAIT/Fragen und `--stop` gelten unabhängig vom Aufrufbudget weiter.
Unbegrenzt bedeutet weder endlose technische Retries noch unbegrenzte Tiefe.
Quoten-, Authentifizierungs-, Transport- und Protokollfehler bleiben technische
Fehler und lösen kein automatisches Replay des gesamten Auftrags aus.

Bei explizit endlichem Budget wird vor dem nächsten Aufruf geprüft. Ein PASS
auf dem letzten erlaubten Aufruf bleibt gültig. Fehlt noch ein Pflichtreview,
bleiben Teilresultate erhalten, der Auftrag aber offen. AutoBuild meldet
`budget_exhausted` mit Exit 9; der Runner meldet `shared_call_budget_exhausted`
mit Exit 6 und `process_stop`. Unbegrenzte Budgets erschöpfen nicht.

## Daten und Operatoroptionen

Maßgeblich bleiben externe `budget.json`, `reservations.json` und nummerierte
Claims unter `<controller-state>/<plan>/call_budgets/task_<root>/`. Reservierung
und Dateioperationen sind prozessübergreifend gesperrt; ein fehlender Diagnose-
Claim gibt keinen Aufruf frei. Die letzte Reservierungsnummer steigt weiter.

Neue Budget-/Claim-Schemas sind `arquilo.call_budget.v2` und
`arquilo.call_claim.v2`. Bei unbegrenzt gilt `limit=0`, `remaining=null`,
`unlimited=true`; `used` bleibt eine Zahl. Endliche v1-Daten werden weiterhin
validiert gelesen. Es wird keine JSON-Unendlichkeit geschrieben.

`--logs-in-workdir` verschiebt nur neue Diagnoseprotokolle, nicht diese Zähler.
`--allow-todo-modifications` erlaubt bewusst einen veränderlichen Hauptplan.
Für Planung in derselben Datei: Aufgabe 2 erzeugt weitere offene Aufgaben;
`--stop 2` hält nach ihrer Abnahme und vor deren Ausführung an. Danach prüft der
Mensch den Plan und startet separat weiter. Die Optionen und ausführliche
PowerShell-Beispiele stehen unter [Operatorsteuerung](../docs/operator-controls.md).
