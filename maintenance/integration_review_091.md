# Reviewunterlage: gemeinsamer Backend-, Git- und Handbuchstand

**Unveröffentlichte Integration · 25. Oktober 2026 · Versionsnummer 0.9.1.**
Diese Unterlage beschreibt den kombinierten Arbeitsstand. Sie ist keine
rückwirkende Freigabe der Vorgänger oder der bereits veröffentlichten ZIP-Datei.

## Eingänge und bereits erfolgte Integration

| Eingang | Commit | Bedeutung |
| --- | --- | --- |
| Öffentliches 0.9.1 | `0c4de8a76d40821578a9aa6f544dcf5fb45d26d5` | Frühere Releasebasis. |
| Main mit #35 und #30 | `cded22f337a0033a3b0934709a82e1ce3db7cdb3` | Zustands-I/O und Claude bereits in main übernommen. |
| Konsolidierter #37-Stand | `209d5a709da9d53bad987720b3f5dcc6cbc3a837` | Enthält #36, #33 und die Handbuchkonsolidierung. |

Die Anleitung „erst #35, danach #30 mergen“ gehört zur früheren Entwicklung
und ist für diesen Stand überholt. Die neue Integration übernimmt die
konsolidierten vier Handbücher, ergänzt die Claude-Architektur und verändert
den Git-Ablauf. Sie ist deshalb weder eine reine Dokumentationsänderung noch
bytegleich zum früheren #36-Produktcode.

## Gewünschtes Verhalten und Prüffälle

| Szenario | Erforderliches Ergebnis |
| --- | --- |
| Codex oder Claude | Gemeinsame fachliche Abnahme-/Plan-/STOP-/Budgetregeln; Claude ohne Codex-Fallback. |
| Claude mit benanntem MCP | Ablehnung vor Modellarbeit; keine stillschweigende Erweiterung. |
| Gewöhnlicher Lauf ohne Git | Normaler Workspace und verpflichtender Review. |
| Git mit nicht ausgewählter verlinkter Umgebung oder großer Kontextdatei | Kein vollständiger Kontextsnapshot; solche Nachbardateien blockieren den normalen Review nicht. |
| Ausgewählte Ausgabe | Vor Review eingefrorene Bytes, verbindliche Reviewreferenz und spätere Bindungsprüfung. |
| Snapshot vor Review nicht verfügbar | Gewöhnlicher Review möglich; Veröffentlichung ohne akzeptierten Kandidaten blockiert. |
| Token-/Snapshot-/Ausgabemanipulation nach Review | Fachliche Abnahme scheitert; kein Ausweichen auf „nur Git-Fehler“. |
| Optionale Commit-/Push-Störung | Fachlich DONE bleibt erhalten; Auslieferungsstatus getrennt, normale Fortsetzung möglich. |
| `--git-required` und Auslieferung offen | Fachlich DONE bleibt; Lauf hält mit unvollständiger Auslieferung an. |
| Unklare Pushantwort | Privaten Beleg und exakten geprüften Commit erhalten; tatsächliche Remote-/HEAD-/Indexlage vor Wiederholung abgleichen. |
| `git status` / `git retry` | Keine Modell-/Reviewaufrufe und keine blinde Commitneuerzeugung. |
| Parallele Git-Automatik | Weiterhin unzulässige Konfiguration. |
| Paket/Handbücher | Beide Backendpfade, aktuelle CLI, DE/EN-Parität und konsolidierte Navigation. |

Die alten #37-Tests belegten noch einen Abbruch nach Produktion vor Review bei
ungeeignetem Vollkontext. Dieses damalige Verhalten ist historische Evidenz und
keine Sollvorgabe für die neue Entkopplung. Eine frühere Größenprüfung allein
hätte den Produktkonflikt nicht gelöst.

## Abnahme des tatsächlichen Endstands

Prüfe Runtime und Dokumentation gemeinsam. Erfasse den endgültigen Commit/Tree,
volle Suite und gezielte Backend-/Git-/Recovery-/Dokumentationsregressionen,
Paketvalidierung sowie native CI für genau diese Fassung. Plattform-Skips sind
keine ausgeführten Tests. Alte grüne Elternprüfungen ersetzen diese Abnahme nicht.
Die Parserinventur muss nach den letzten CLI-Änderungen neu erzeugt und geprüft
werden. Gegenüber dem bisherigen #37 kommt kein neues Versionsversprechen hinzu.

```sh
python3 -B scripts/documentation_reference.py --check
python3 -B -m unittest discover -s tests -p 'test_documentation*.py' -v
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_release.py
python3 -B scripts/build_runtime_zip.py /absolute/new/path/integration-runtime.zip
```

Es gibt keine automatische Freigabe, Veröffentlichung oder rückwirkende
Reparatur historischer DONE-Einträge. Allgemeine Prozessaufsicht,
Ausgabequoten/Deadlines, Ressourcengrenzen und dauerhaft erzwungene Release-Gates
bleiben eigene Pakete. Die Integration schließt nicht pauschal alle Auditbefunde.
