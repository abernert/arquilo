# Historical migration notes — former DORA runtime

DORA is the historical project name, not an active ARQUILO product or mode.
The settings and development identifiers below describe retired predecessor
features. They are rejected, not supported configuration examples.
Current configuration is documented in [CONFIGURATION.md](CONFIGURATION.md).

## Archivierte Hinweise zu entfernten Funktionen

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
