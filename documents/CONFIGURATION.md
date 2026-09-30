# DORA Lean: Konfiguration

Der Kern verwendet Python-Standardbibliothek, CLI-Argumente und optional ein
JSON-Runtime-Profil. Keine `.env`-Datei wird geladen; kein YAML, API-Key oder
OpenAI-Python-SDK ist für DORA erforderlich. Codex authentisiert sich selbst.
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
| Diagnose | `python dora_doctor.py --workdir <ordner> --json`; kostenfreie lokale Metadaten, keine Versionsbindung. Zusätzlich `--check-decide` für eine tatsächliche Funktionsprobe (ein möglicher kostenpflichtiger Modellaufruf); `--model`, `--reasoning-effort` und `--decide-timeout` nur für diese Probe. [Bedienung und Prüfgrenzen](QUICKSTART.md). |

AutoBuild hat dieselben Modell-/Netzwerkoptionen und nimmt `--task` oder
`--task-file` statt einer ToDo-Liste entgegen. Weitere erhaltene Optionen
für Auswahl, Vorbemerkung, Fortsetzung und Spezialpfade stehen in `--help`.
Es gibt keine neue allgemeine Konfigurationsdatei mit duplizierten CLI-Werten.

## Priorität und Normalisierung

`--model` beziehungsweise der direkte Python-Parameter hat Vorrang vor
`DORA_CODEX_MODEL`. Ein globaler Modellwert hat Vorrang vor `CFG model`; ohne
globalen Wert gilt das CFG-Modell. `--reasoning-effort` hat Vorrang vor
`DORA_CODEX_REASONING_EFFORT`. Leerzeichen außen werden entfernt, leere Werte
gelten als nicht gesetzt, Effort wird kleingeschrieben und validiert.
Runner und AutoBuild verwenden denselben Resolver in `runtime_config.py`.
Werte werden pro Invocation übergeben; Codex-Konfigurationsdateien werden
nicht geändert. Profile und CFG dürfen die feste Startpolicy nicht erweitern.

Decide übernimmt das wirksame Auftragsmodell/Effort, sofern kein ausdrückliches
Decide-Modell gesetzt ist. Seine isolierte Konfiguration übernimmt keine
globalen Codex-Profildefaults. Für reproduzierbare Läufe Modell/Effort explizit
angeben; die Distribution legt kein bestimmtes Modell fest.

Erhaltene Spezialoptionen:

- `--todo-syntax` / `DORA_TODO_SYNTAX` und `--todo-preamble` /
  `DORA_TODO_PREAMBLE`: CLI vor Umgebung, Standard jeweils `auto`.
- `--runtime-profile` / `DORA_RUNTIME_PROFILE`: CLI vor Umgebung; optionales
  deklaratives JSON für Promptregeln und Preflight, siehe
  [Profilvertrag](../RUNTIME_PROFILE_API.md). Im echten Lauf bleibt sein
  Preflight verpflichtend; im Trockenlauf wird die ausgelassene Prüfung vermerkt.
- `--git`: standardmäßig aus, benötigt Git und führt nach erfolgreicher
  Abnahme Add/Commit/Push aus. Ohne diese Option benötigt DORA kein Git.
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

## Migration alter Umgebungsnamen

Die folgenden Einstellungen sind Expertenoptionen, keine Pflichtkonfiguration.
Alte Namen funktionieren weiterhin mit `FutureWarning`. Ein nichtleerer
kanonischer Wert hat Vorrang; bei zwei alten Werten gilt die Reihenfolge in
der Tabelle. Warnungen nennen nur Variablennamen, keine Werte. Es werden keine
Einstellungen oder Secrets automatisch in Dateien geschrieben.

| Kanonischer Name | Alte Namen (Priorität von links nach rechts) | Standard |
| --- | --- | --- |
| `DORA_DECISION_MODEL` | `AUTOBUILD_DECISION_MODEL`, `METACODEX_DECISION_MODEL` | wirksames Auftragsmodell |
| `DORA_DECISION_SYSTEM_PROMPT` | `AUTOBUILD_DECISION_SYSTEM_PROMPT`, `METACODEX_DECISION_SYSTEM_PROMPT` | bestehende Entscheideranweisung |
| `DORA_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | `AUTOBUILD_CODEX_POST_TURN_EXIT_GRACE_SECONDS` | 120 Sekunden |
| `DORA_CODEX_STALL_TIMEOUT_SECONDS` | `AUTOBUILD_CODEX_STALL_TIMEOUT_SECONDS` | 7200 Sekunden |
| `DORA_CODEX_KILL_GRACE_SECONDS` | `AUTOBUILD_CODEX_KILL_GRACE_SECONDS` | 10 Sekunden |

Timeoutwerte müssen endlich und nichtnegativ sein; ungültige Werte sind
Konfigurationsfehler. Beim direkten Transportadapter gilt dessen explizites
`env` statt der Prozessumgebung; explizite `TransportTimeouts` haben Vorrang.
Diese drei Env-Optionen betreffen AutoBuild; Decide behält seine begrenzten
eigenen `DecisionExecSettings`/Timeouts.
ACE ist entfernt: `AGENT_SYSTEM_ACE_CONTEXT` und `AGENT_SYSTEM_ACE_RUN_LOGGING`
müssen aus der Umgebung entfernt werden, auch bei `off`, `false` oder leerem Wert.
Runner und AutoBuild weisen sie vor Modellstart mit Migrationshinweis zurück.
`--ace-mode`, Python-/Worker-`ace_mode` und entsprechende CFG-/Profilfelder
sind ebenfalls entfallen; alte Playbooks und ACE-Exporte werden nicht verarbeitet.

OpenClaw/Computer-Use/Bridge ist seit 1031 entfernt. `--openclaw-bridge`,
Python-/Worker-`bridge_enabled` und entsprechende CFG-/Profilfelder werden
auch bei `false`/`null` zurückgewiesen. Diese tatsächlich zuvor ausgewerteten
Umgebungsvariablen müssen entfernt werden; bereits ihre Anwesenheit ist ein Fehler:

- `DORA_CUA_APPROVE_ALL`, `DORA_CUA_APPROVED_ACTIONS`
- `DORA_CUA_PREFLIGHT_HOST_OS_DARWIN`, `DORA_CUA_PREFLIGHT_PLAYWRIGHT`
- `DORA_CUA_PREFLIGHT_OSASCRIPT`, `DORA_CUA_PREFLIGHT_ACCESSIBILITY`
- `DORA_CUA_PREFLIGHT_AUTOMATION`, `DORA_CUA_PREFLIGHT_TESSERACT`
- `DORA_CUA_PREFLIGHT_SCREEN_RECORDING`

Alte `.bridge/`-Dateien werden nicht gelesen, verändert oder migriert.
Bridge-WAITs müssen im Auftrag angepasst werden; allgemeine ToDo-/Gruppen-/
Agenten-WAITs, STOP und `process_stop` bleiben erhalten.

IACT ist seit 1032 entfernt. `--iact`, `--iact-retention-runs`,
`--iact-max-events`, `--iact-max-log-bytes` und `--iact-max-tree-bytes` sind auch
mit `0`, negativen oder leeren Werten Fehler. Python-`iact_enabled` und die
vier gleichnamigen Grenzparameter mit Unterstrichen entfallen ebenfalls;
`None` und `False` werden nicht still ignoriert. Das gilt auch für Worker-,
CFG- und Profilfelder (`iact`, `iact_lite`, `iact_limits` eingeschlossen).

Der alte Export wertete selbst keine IACT-Umgebungsvariable aus. Damit Wrapper
keine scheinbare Aktivierung vornehmen, werden zusätzlich die entsprechenden
DORA-Namen bereits bei Anwesenheit abgewiesen: `DORA_IACT`, `DORA_IACT_ENABLED`,
`DORA_IACT_RETENTION_RUNS`, `DORA_IACT_MAX_EVENTS`, `DORA_IACT_MAX_LOG_BYTES` und
`DORA_IACT_MAX_TREE_BYTES`. Werte werden dabei nicht interpretiert.

Beim direkten `TodoRunner` bleiben die ersten 15 Positionsparameter erhalten.
Ab Position 16 (ehemals `iact_enabled`) und 17 (ehemals `bridge_enabled`)
werden alte Positionsargumente ausdrücklich zurückgewiesen. Erhaltene spätere
Optionen, beispielsweise `breakdown_policy` und `max_calls`, als
Schlüsselwortargumente übergeben. Kein Ersatzexport und keine automatische
Migration, Retention oder Löschung alter IACT-Dateien; Kernlogs bleiben vollständig.

AutoBuild-Queue und HTTP-/Prometheus-Dienste sind seit 1033 entfernt.
`autobuild.py queue` einschließlich `enqueue`, `list`, `show`, `cancel` und
`run-worker` liefert vor jedem Datei- oder Modellzugriff Exit 2. Das gilt
ebenso für `--queue-state`, `--prometheus-port`, `--poll-interval` und `--max-jobs`.
Die Python-/Worker-/CFG-/Profilfelder `queue`, `queue_state`, `prometheus_port`,
`poll_interval` und `max_jobs` werden auch bei `False`, `None`, `0` oder leeren
Werten abgewiesen. Die früheren Python-Exporte `queue_main`, `QueuedJob`,
`QueueState`, `QueueWorker` und `TelemetryMetrics` sind nicht mehr verfügbar;
Zugriffe über `autobuild` erzeugen einen erklärenden `ImportError`.

Die alten Dienste hatten keine eigene ENV-Auswertung. Für entsprechende
Wrapper werden `DORA_QUEUE_STATE` und `DORA_PROMETHEUS_PORT` bereits bei
Anwesenheit zurückgewiesen, auch im Profil-Preflight. Vorhandene Queuezustände
bleiben unberührt. Standalone-AutoBuild, der direkte `autobuild.start`-Aufruf,
Parallel-CFG samt Python-Workern, volle Logs, Pflichtreviews, Prozessabbruch
und gemeinsame Budgets bleiben erhalten. `--max-retries` bleibt die separate
Runneroption gemäß [WORKFLOW_LIMITS.md](WORKFLOW_LIMITS.md).

Die früheren API-Key-/Base-URL-Variablen für DORA-Decide werden nicht mehr
ausgewertet. Entfernte Evidence-, Logician-, YOLO- und No-Check-Schalter werden
weiterhin ausdrücklich zurückgewiesen. Die alten Aliasnamen sind ein
Migrationspfad; neue Konfigurationen verwenden die Optionen oben.
