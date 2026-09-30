# Projektvorbemerkung und dynamische Markdown-Arbeitspläne

Der normale DORA-Lauf arbeitet weiter in einem gemeinsamen, fortgeschriebenen
Workspace. Die ToDo-Datei bleibt editierbar. Produktionsagent und Reviewer
können Projektdateien, frühere `todo_result`-Berichte und neue Artefakte lesen.
Der Produktionsauftrag verweist weiterhin auf ToDo-Datei, Nummer und
Ergebnisdatei; der Runner ersetzt ihn nicht durch einen herauskopierten Task.

## Vorbemerkung

Der Text vor dem ersten echten Task-/Auftrag-/DONE-/OBSOLETE-Eintrag ist die
Projektvorbemerkung. Auch bereits erledigte und entfallene Einträge begrenzen
sie. Aufgabenbeispiele in Backtick-/Tilde-Codeblöcken und HTML-Kommentaren sind
keine ausführbaren Einträge. Eine reine `***SYNTAX marked-en***`-Zeile,
Steuerdirektiven, Trenner oder ausschließlich unsichtbare Beispiele zählen
nicht als inhaltliche Vorbemerkung. Eine Datei ohne Aufgabenheader liefert
ebenfalls keine Vorbemerkung.

```markdown
***SYNTAX marked-en***

# Projektziel
Entwickle ein überprüfbares Ergebnis aus den vorhandenen Projektdateien.

# Arbeitsweise
Auftrag 1 soll einen begrenzten Arbeitsschritt erledigen und konkrete
Folgeaufträge anlegen. Das Gesamtziel ist noch nicht seine Abnahmebedingung.

1. ***Task***: Untersuche die Eingaben und plane die nächsten Arbeitsschritte.
    Ergebnis: Dokumentierter Befund und zwei bis vier konkrete Folgeaufträge.
    Abnahme: Die nächsten Schritte besitzen eindeutige Liefergegenstände.
```

`run_todos.py --todo-preamble auto|off|required` steuert die Einbettung:

| Modus | Verhalten |
| --- | --- |
| `auto` (Standard) | Inhaltliche Vorbemerkung plus neutrale Dateisemantik einbetten; sonst den bisherigen Referenzprompt beibehalten. |
| `off` | Keine automatische Einbettung. Der Referenzprompt und die Markdown-Prüfungen bleiben aktiv. |
| `required` | Fehlende inhaltliche Vorbemerkung ist ein Fehler vor dem Modellaufruf. |

Die CLI übersteuert `DORA_TODO_PREAMBLE`; direkte Python-Aufrufe verwenden
`TodoRunner(..., todo_preamble="auto")` und lesen diese Variable nicht implizit.
Unbekannte Modi werden abgewiesen. Im CLI-Weg erfolgt die Vorprüfung sogar vor
dem optionalen Codex-Preflight. Die Capability heißt `run_todos.preamble: 1`;
der wirksame Modus steht unter `todo_directives.todo_preamble` in
`run_config.json`.

Beispiel für ein bereits eingerichtetes Zielsystem, unter Windows mit `python`
statt `python3`:

```text
python3 run_todos.py --todo-file documents/todos/todo.md --workdir . --todo-preamble required
```

Unmittelbar vor jedem zentralen AutoBuild-Aufruf wird die aktive ToDo-Datei neu
gelesen. Derselbe eingebettete Originalauftrag erreicht Produktion, Review,
Korrektur und erneuten Review. Auch Breakdown, Kinder, Parent-Review und der
optionale Python-Worker erhalten die Vorbemerkung. Bei einem Unterworkspace
zählt dessen aktive ToDo-Kopie. Innerhalb eines zentralen Aufrufs einschließlich
seiner begrenzten Versuche bleibt diese Vorbemerkung fest. Der nächste zentrale
Aufruf liest Änderungen erneut; der Review eines schon gestarteten Versuchs
erhält keinen rückwirkend geänderten Prompt. Standalone-AutoBuild erhält genau
seinen übergebenen Auftrag und lädt keine Vorbemerkung automatisch nach.

UTF-8, ein einmaliger BOM am Dateianfang und LF/CRLF werden unterstützt.
Der eingebettete Präfix bleibt einschließlich Leerzeichen und Zeilenenden
erhalten; der BOM gehört nicht zum Kontexttext. Über **65.536 UTF-8-Bytes**,
Lesefehler oder ungültige Kodierung verursachen einen Fehler; kein stilles
Abschneiden. Referenzierte Dateien werden nicht automatisch in den Präfix
expandiert. Text und Byteanzahl werden protokolliert, ohne Hashkennzeichnung,
Signierung oder zusätzliche Zugriffsrechte. Die vollständigen Prompts stehen
auch im normalen Laufarchiv und in der Dry-run-Vorschau.

## Bestehende Tasksemantik

- `<id>. Auftrag: ...`, `<id>. Task: ...` und `<id>. ***Task***: ...`
  bleiben lesbar. Neue markierte Einträge verwenden `<id>. ***Task***: ...`.
  `***SYNTAX marked-en***` und `--todo-syntax` steuern die Schreibweise;
  Beispiele oder Kommentare ändern sie nicht.
- Eindeutige, aufsteigende IDs und die vorhandene Nummerierung bleiben bestehen.
  Nur der Controller setzt einen erfolgreichen Auftrag auf DONE.
  OBSOLETE ist kein erfolgreicher Abschluss und erfüllt keine WAIT-Abhängigkeit.
- Der Runner liest die Datei im laufenden Durchlauf erneut. Ein autorisierter
  Planungsauftrag kann Folgeaufgaben hinzufügen; diese werden im selben
  Workspace gefunden und bearbeitet. Eine bewusste `--stop`-Grenze begrenzt
  den Durchlauf. Ein abgeschlossener Planungsauftrag beweist noch keinen
  Abschluss der späteren Arbeiten.
- CFG/WAIT gelten für den unmittelbar folgenden Eintrag. STOP muss direkt
  vor dem betreffenden offenen Auftrag stehen. Die Grammatik wird vor der
  Auswahl einschließlich WAIT/STOP und vor dem AutoBuild-Aufruf geprüft.
  Entfernte Features oder ungültige Direktiven werden auch bei einer sonst
  geschlossenen Liste ausdrücklich gemeldet.
- Gespeicherte DONE-Einträge erfüllen `WAIT on=todo:<id>` beziehungsweise
  `WAIT on=<id>` auch nach einem Neustart. Bloße Versuche und OBSOLETE reichen
  nicht. `group:`/`agent:` behalten ihre bestehenden Laufzustände; sie werden
  nicht aus DONE-Einträgen erfunden. Bridge-WAITs sind seit 1031 entfernt und
  werden mit Entfallmeldung zurückgewiesen.

Die vollständige Direktivenbeschreibung steht in
[todo_directives.md](todo_directives.md). Es gibt kein neues Board, keine
verpflichtende `mission.md` und keine neue Statusdatenbank. Diese Einbettung
ersetzt weder Pflichtreviews noch die tatsächliche Artefaktprüfung.
