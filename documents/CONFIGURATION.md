# ARQUILO: Konfiguration

Der Kern verwendet Python-Standardbibliothek, CLI-Argumente und optional ein
JSON-Runtime-Profil. Keine `.env`-Datei wird geladen; kein YAML, API-Key oder
OpenAI-Python-SDK ist für ARQUILO erforderlich. Codex authentisiert sich selbst.
Der Import liest keine Laufkonfiguration; jeder Aufruf löst seine Werte neu auf.

## Öffentliche Kernoptionen

| Zweck | Option / Standard |
| --- | --- |
| Auftrag und Workspace | `--todo-file <datei>` und `--workdir <ordner>`; ohne workdir gilt das Verzeichnis der ToDo-Datei. Absolute Pfade sind beim Start aus einem anderen Verzeichnis eindeutig. |
| Modell | `--model <id>`; ohne Override bleibt der Codex-Default für Produktion/Review wirksam. |
| Reasoning | `--reasoning-effort <wert>`; vorhandene Werte: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`. Ob das gewählte Modell den Wert unterstützt, entscheidet Codex. |
| Shellnetzwerk | `--network-access`; standardmäßig aus. Sandbox maximal `workspace-write`, Review `read-only`. Kein Netzwerk-Env-Alias erteilt diese Freigabe. |
| Gesamtbudget | `--max-calls <zahl>`; Standard 100, gemeinsam für Auftrag, Reviews, Korrekturen, Breakdown und Decide. Details: [WORKFLOW_LIMITS.md](WORKFLOW_LIMITS.md). |
| Trockenlauf | `--dry-run --dry-run-file <datei>`; schreibt die Befehlsvorschau, führt weder Codex noch den Profil-Preflight aus und verändert keinen ToDo-Status. |
| Diagnose | `python arquilo_doctor.py --workdir <ordner> --json`; kostenfreie lokale Metadaten, keine Versionsbindung. Zusätzlich `--check-decide` für eine tatsächliche Funktionsprobe (ein möglicher kostenpflichtiger Modellaufruf); `--model`, `--reasoning-effort` und `--decide-timeout` nur für diese Probe. [Bedienung und Prüfgrenzen](QUICKSTART.md). |

AutoBuild hat dieselben Modell-/Netzwerkoptionen und nimmt `--task` oder
`--task-file` statt einer ToDo-Liste entgegen. Weitere erhaltene Optionen
für Auswahl, Vorbemerkung, Fortsetzung und Spezialpfade stehen in `--help`.
Es gibt keine neue allgemeine Konfigurationsdatei mit duplizierten CLI-Werten.

## Priorität und Normalisierung

`--model` beziehungsweise der direkte Python-Parameter hat Vorrang vor
`ARQUILO_CODEX_MODEL`. Ein globaler Modellwert hat Vorrang vor `CFG model`; ohne
globalen Wert gilt das CFG-Modell. `--reasoning-effort` hat Vorrang vor
`ARQUILO_CODEX_REASONING_EFFORT`. Leerzeichen außen werden entfernt, leere Werte
gelten als nicht gesetzt, Effort wird kleingeschrieben und validiert.
Runner und AutoBuild verwenden denselben Resolver in `runtime_config.py`.
Werte werden pro Invocation übergeben; Codex-Konfigurationsdateien werden
nicht geändert. Profile und CFG dürfen die feste Startpolicy nicht erweitern.

Decide übernimmt das wirksame Auftragsmodell/Effort, sofern kein ausdrückliches
Decide-Modell gesetzt ist. Seine isolierte Konfiguration übernimmt keine
globalen Codex-Profildefaults. Für reproduzierbare Läufe Modell/Effort explizit
angeben; die Distribution legt kein bestimmtes Modell fest.

Erhaltene Spezialoptionen:

- `--todo-syntax` / `ARQUILO_TODO_SYNTAX` und `--todo-preamble` /
  `ARQUILO_TODO_PREAMBLE`: CLI vor Umgebung, Standard jeweils `auto`.
- `--runtime-profile` / `ARQUILO_RUNTIME_PROFILE`: CLI vor Umgebung; optionales
  deklaratives JSON für Promptregeln und Preflight, siehe
  [Profilvertrag](../RUNTIME_PROFILE_API.md). Im echten Lauf bleibt sein
  Preflight verpflichtend; im Trockenlauf wird die ausgelassene Prüfung vermerkt.
- `--git`: standardmäßig aus, benötigt Git und führt nach erfolgreicher
  Abnahme Add/Commit/Push aus. Ohne diese Option benötigt ARQUILO kein Git.
- `CFG parallel` und Codex-Werkzeugprofile bleiben erhalten; siehe
  [Paketumfang](PACKAGE_SCOPE.md) und
  [ToDo-Direktiven](todo_directives.md). Websuche, Shellnetzwerk, MCP und
  Providerkommunikation sind getrennte Wege; Netzwerk aus bedeutet nicht offline.

Es gibt keine Zusatzgruppen oder Aktivierungskonfiguration dafür.
`--print-capabilities` nennt die erhaltenen Kernoptionen als
`retained_core_options`; die alten leeren Felder `optional_packages` und
`optional_defaults` sowie `retained_optional_paths` entfallen.
Die versionierten Verträge unter `features` bleiben erhalten.
Der Paketbau akzeptiert weder `--with-optional` noch Python-`optional`,
auch nicht mit leerem Wert. Details: [Distribution](DISTRIBUTION.md).

## Expertenoptionen und historische Eingabealiase

Die folgenden Einstellungen sind Expertenoptionen, keine Pflichtkonfiguration.
Historische Namen funktionieren weiterhin mit `FutureWarning`; die vollständige
[Namenszuordnung](../docs/compatibility.md) dokumentiert den Vorgängerpräfix. Ein nichtleerer
kanonischer Wert hat Vorrang; bei zwei alten Werten gilt die Reihenfolge in
der Tabelle. Warnungen nennen nur Variablennamen, keine Werte. Es werden keine
Einstellungen oder Secrets automatisch in Dateien geschrieben.

| Kanonischer Name | Alte Namen (Priorität von links nach rechts) | Standard |
| --- | --- | --- |
| `ARQUILO_DECISION_MODEL` | `AUTOBUILD_DECISION_MODEL`, `METACODEX_DECISION_MODEL` | wirksames Auftragsmodell |
| `ARQUILO_DECISION_SYSTEM_PROMPT` | `AUTOBUILD_DECISION_SYSTEM_PROMPT`, `METACODEX_DECISION_SYSTEM_PROMPT` | bestehende Entscheideranweisung |
| `ARQUILO_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | `AUTOBUILD_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | 120 Sekunden |
| `ARQUILO_CODEX_STALL_TIMEOUT_SECONDS` | `AUTOBUILD_CODEX_STALL_TIMEOUT_SECONDS` | 7200 Sekunden |
| `ARQUILO_CODEX_KILL_GRACE_SECONDS` | `AUTOBUILD_CODEX_KILL_GRACE_SECONDS` | 10 Sekunden |

Timeoutwerte müssen endlich und nichtnegativ sein; ungültige Werte sind
Konfigurationsfehler. Beim direkten Transportadapter gilt dessen explizites
`env` statt der Prozessumgebung; explizite `TransportTimeouts` haben Vorrang.
Diese drei Env-Optionen betreffen AutoBuild; Decide behält seine begrenzten
eigenen `DecisionExecSettings`/Timeouts.

## Historische Migration

Entfernte Vorgängerfunktionen sind keine aktuellen ARQUILO-Optionen. Die
vollständigen [historischen Migrationshinweise](HISTORICAL_MIGRATION.md) bleiben
als Referenz erhalten. Für unterstützte alte Umgebungsnamen siehe
[Kompatibilität und Namensmigration](../docs/compatibility.md).
