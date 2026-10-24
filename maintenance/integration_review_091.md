# Reviewunterlage: gemeinsamer Stand aus PR #33, #35 und #36

**Schritt 1A · unveröffentlicht · 24. Oktober 2026 · Versionsnummer weiterhin 0.9.1.**
Diese Unterlage erleichtert die Eigentümerprüfung; sie ersetzt sie nicht. Der
Integrationsbranch verändert weder `main` noch die drei ursprünglichen PR-Branches.
Es gibt keinen neuen Tag, Release oder Ersatz des veröffentlichten Runtime-ZIPs.

## Festgelegte Eingänge

| Bestandteil | Commit |
| --- | --- |
| Release-/Main-Basis | `0c4de8a76d40821578a9aa6f544dcf5fb45d26d5` |
| #35: Zustands-I/O | `557f4f1b9b1959002a0677315f809426de1aab9b` |
| #36: Git, einschließlich #35 | `48331c7210d63787c578bf925ade41da9eb806a8` |
| #33: Handbücher | `0e57df59ea067596b0ab0db987347aa31e7870de` |

Der Anwendungscode einschließlich Promptkatalogen, Versionsdateien und Workflows
bleibt bytegleich zu #36. Dazu kommen die Dokumentation aus #33, redaktionelle
Konfliktlösungen, zehn additive Integrationstests und diese Unterlage. Das
Paketmanifest enthält die Vereinigung beider Paketlisten plus die neue
`docs/integration-status.md`: 105 Runtime-Dateien. Tests und Maintenance-Dateien
werden weiterhin nicht ausgeliefert.

## Die drei getrennten Reviewentscheidungen

| PR | Problem und Änderung | Nutzerauswirkung | Nachweis und verbleibende Grenze |
| --- | --- | --- | --- |
| #35 | Windows-Metadatenleser blockierten den atomaren Austausch; gleichzeitiges erstmaliges Öffnen permanenter POSIX-Sperren war nicht robust. Eng begrenztes Read/Delete-Sharing, atomarer Windows-Austausch und exklusives POSIX-Anlegen. | Keine neuen CLI-Optionen; vorhandene Identitäten/Journale/Budgets bleiben bestehen. Unterstütztes Dateisystem erforderlich. | Ursprüngliche Tests plus zehn gezielte Tests. Kernursache des ursprünglichen macOS-ENOENT nicht als bewiesen behauptet; keine pauschale Ausnahmebehandlung. |
| #36 | Review, Commit-Inhalt und tatsächlicher Remotezustand waren nicht ausreichend gebunden. Privater Vorab-Prüfstand, gebundene Annahme, private Objekterzeugung, Index-/Ref-Sperren und festgelegtes Pushziel mit explizitem alten OID. | Git-Automatik nur seriell; Taskplan/Berichte nicht auswählen. Links/Spezialdateien und große Kontexte werden abgewiesen. Ohne `--git` kein neuer Snapshotpfad. | 35 Git-Tests einschließlich Windows-Langpfaden. Keine Modellwahrheitsgarantie, keine Same-UID-Isolation und keine atomare Transaktion über Journal, Index, Branch und Remote. |
| #33 | Anleitungen waren verteilt und nicht durchgehend zweisprachig. User Guides DE/EN, Operator Guide EN, Technical Guide EN sowie Pflege-/Manifest-/Beispielprüfungen. | Zusammenhängende Lesepfade; vorhandene Referenzpfade bleiben bestehen. | Neun Dokumentationstests. Struktur- und Befehlsparität beweisen keine vollständige semantische Übersetzungsqualität. Ursprünglicher Branch bleibt als 0.9.1-Dokumentationsbasis erhalten. |

## Abgleich in diesem Integrationsbranch

Das ältere Operator-Beispiel mit `--git-path tasks.md` und einem nachträglich
veränderten Ergebnisbericht wurde durch eine reine Ausgabedateiauswahl ersetzt.
Alle vier Guides unterscheiden jetzt veröffentlichtes 0.9.1 und den
Integrationscheckout. Git-Verhalten, Status-/Recovery-Aussagen, State-I/O,
Architekturfluss und Manifestquellen sind aktualisiert. Die deutsch/englischen
User Guides behalten dieselben Kapitelanker und 13 ausführbaren Befehlsbeispiele.

In `docs/controller-safety.md` bleibt der neue Git-Vertrag aus #36 erhalten; die
Guide-Verweise aus #33 kommen hinzu. `docs/testing.md` enthält beide Testbereiche.
Das Paketmanifest wird vereinigt, nicht durch die ältere Liste überschrieben.

## Konkrete Alltagsszenarien

`tests/test_integration_091.py` ergänzt zehn Tests. Die Modellantworten sind
synthetisch, der Controller, private Zustandsübergänge und lokale Git-Objekte sind
real. Es werden keine Produktionsdaten, Credentials oder externen Pushziele verwendet.

| Szenario | Geprüfte Aussage |
| --- | --- |
| Dokumentenbeispiel aus dem Guide | Quellbrief im Prüfstand, Daten/Offene-Frage-Summary, genau diese Commitbytes, DONE im privaten Journal. |
| Softwarebeispiel mit zwei Aufgaben | Produktion und separater Review beider Tasks; drei bekannte unittest-Fälle auf der Reviewkopie; Taskplan/Berichte nicht im Ausgabecommit. |
| Andere vorgemerkte Datei | Bleibt im Index erhalten, wird aber nicht in den Ausgabestand committed. |
| Gleicher Ablauf ohne Git | Review bleibt im normalen Workspace; kein Git-Prüfstand und keine Git-Historienänderung. |
| Verlinkte virtuelle Umgebung | Lauf bleibt vor Review/DONE/Commit stehen, aber erst nach Produktion; Ziel außerhalb des Workspace bleibt unberührt. |
| Zu große nicht ausgewählte Kontextdatei | Derselbe späte Abbruchzeitpunkt bei Quotenüberschreitung; kleine Testquote statt Speicher-/Durchsatzbenchmark. |
| Parallel + Git | Erste parallele Gruppe wird vor Modellaufruf abgewiesen; keine Behauptung eines universellen Start-Preflights. |
| Taskplan als Git-Ausgabe | Ablehnung bei Einrichtung. |
| Manifest/Paket/Guide-Abgleich | Quellcommits getrennt, beide Paketerweiterungen enthalten, veraltete Git-Empfehlungen nicht mehr im Operator Guide. |

## Verbleibender Befund: vollständiger Kontextcheck kommt spät

Die Link-/Größenprüfung des gesamten Reviewkontexts liegt in der Snapshotanlage
nach der Produktion. Eine schon vorher vorhandene verlinkte `.venv` oder zu große
Kontextdatei kann deshalb einen Produktionsaufruf kosten, bevor der Lauf anhält.
Auch eine Dry-run-Vorschau ist kein Eignungstest für den vollständigen Snapshot.
Die neuen Tests dokumentieren diesen bestehenden Ablauf, **sie reparieren ihn nicht**.
Die Guides nennen kleine dedizierte Worktrees bzw. manuelle Veröffentlichung als
Alternative; keine Empfehlung zum blinden Löschen von Abhängigkeiten.

Mögliche Folgearbeit nach der Integration: nichtschreibender Snapshot-Preflight
mit denselben Regeln vor dem ersten Modellaufruf. Die Prüfung vor Review bleibt
trotzdem zwingend, weil Produktion den Kontext anschließend ändern kann. Dies
ist nicht Teil von 1A und wird nicht still in die reviewbereiten Code-PRs eingebaut.

## Abnahme und Herkunft

Die PR-Beschreibung hält den tatsächlich geprüften Integrationscommit, Tree,
lokale Ergebnisse und native CI-Läufe fest. Ein grüner Elterncommit ist kein
Nachweis für die kombinierte Fassung. Plattform-Skips separat ausweisen. Eine
vom Werkzeug unterbrochene Suite nicht als bestanden zählen. Keine Tests,
Branchschutzregeln oder Release-Gates abschwächen.

Reproduzierbare Befehle aus einem vollständigen Checkout:

```sh
python3 -B -m unittest discover -s tests -p test_documentation_guides.py -v
python3 -B -m unittest discover -s tests -p test_integration_091.py -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py /absolute/new/path/integration-runtime.zip
```

## Spätere Integration nach Eigentümerfreigabe

Zuerst #35 prüfen/übernehmen, dann #36 gegen den tatsächlichen `main`-Stand
retargeten und erneut prüfen. Für #33 die hier erhaltene Dokumentation und
Konfliktlösung verwenden; die ursprüngliche Dokumentationsfassung nicht darüber
kopieren. Bei Squash-/Rebase-Merges ändern sich Commitidentitäten: Ancestry nicht
blind voraussetzen, resultierenden Tree vergleichen und CI wiederholen. Der
Integrations-PR ist ein Prüfstand, kein automatischer Sammelmergeauftrag.

Prozessaufsicht, allgemeine Ausgabequoten/Deadlines, strengere Kontrollstreams,
weiteres Recovery-/Ressourcenhardening und ein dauerhaftes Release-Gate bleiben
außerhalb dieses Auftrags. Keine Behauptung, dass alle 42 Auditbefunde geschlossen sind.
