# Migration bestehender Projekte zu DORA Lean

Die neue Runtime in einen eigenen Ordner installieren; laufende Installation,
deren Python-Umgebung, Projekte, alte Logs und Nachweise erhalten. Vorhandene
ToDo-Dateien weiterverwenden: gemeinsamer Workspace, Referenzprompt, Vorbemerkung,
`todo_result`-Berichte, Review, Korrektur und Parent-Abnahme bleiben erhalten.
Keine Umnummerierung oder neue Boardstruktur erforderlich. Der Agent setzt
Aufträge nicht selbst auf DONE; vorhandene Controllerstatus nicht zurücksetzen.

Vor dem ersten echten Start die Liste und Startbefehle wie folgt anpassen,
dann [Doctor und Trockenlauf](QUICKSTART.md) ausführen. Alte Schalter und
entfernte CFG-/Profilfelder werden auch bei `false`/`off` zurückgewiesen.

| Bisher | Anpassung und Ersatz |
| --- | --- |
| `--dora`, `--no-dora`, `--audit-dir`, `--verify-after` | Entfernen. Normale `.codex_runs`-Logs und Ergebnisdateien bleiben; kein Evidence-/Hash-/Signaturmodus. `--verify-after` hat keinen kryptographischen Ersatz; Pflichtreviews laufen weiter. |
| `--init-workspace-guard`, `--guard-bootstrap-reason`; Schlüssel-/Evidence-/Bundlefelder in Profilen oder Python-Aufrufen | Entfernen. Keine Guardinitialisierung, Schlüsseldatei oder Nachweiserzeugung nötig. Alte Nachweise nicht löschen oder in Lean als validiert ausgeben. |
| Alle `--logician`-/`--logician-*`-Schalter und `CFG logician*` | Entfernen, auch `off`, `lite` und Limits. Normale Audits, Reviews und Reparaturen benötigen keinen Ledger; keine formale Verifikation als Ersatz behauptet. |
| `--allow-yolo`, `--yolo`, `--unsandboxed`, `--dangerously-bypass-approvals-and-sandbox`; Full-Access-Sandbox | Entfernen. DORA startet mit `workspace-write`; Zugriffsprobleme lokal beheben. Keine unbeschränkte Alternative. |
| `--full-auto`, `--no-check` oder entsprechende Felder | Entfernen. Pflichtreview kann nicht abgeschaltet werden; Korrekturen werden erneut geprüft. |
| `--profile dora` / `--profile dev` und alte Sicherheitsprofilnamen | Entfernen. Allgemeine JSON-`--runtime-profile` bleiben erhalten; Codex-Modell-/Werkzeugprofile via `CFG agent=<name>` bzw. AutoBuild `--codex-profile <name>`. Sicherheitsprofilnamen sind dort ebenfalls verboten. |
| `CFG network_access=true` ohne Starterfreigabe | Beim bewussten Start zusätzlich `--network-access` setzen oder CFG auf `false` ändern. Kein Netzwerk-Env-Alias erteilt Freigabe. |
| Freie Codex-Extraargumente / Sandbox-Overrides | Nur dokumentierte harmlose AutoBuild-`--extra-arg`-Werte bleiben; keine freien Konfigurations-, Session- oder Schreibwurzel-Overrides. Siehe `codex_policy.py`. |
| `OPENAI_API_KEY`, Base-URL-/dotenv-Setup für DORA-Decide | DORA lädt diese nicht mehr. Codex separat anmelden; eigene API-Setups anderer Anwendungen nicht löschen. Alle DORA-Modellentscheidungen laufen über Codex Exec. |
| Alter AutoBuild-Aufruf mit `--max-retries` | Bei Standalone-AutoBuild `--max-steps`, optional `--auto-continue`, und `--max-calls` verwenden. Im Runner bleibt `--max-retries` der dokumentierte Fortsetzungsfaktor. |
| ACE: `--ace-mode`, Python-/Worker-`ace_mode`, CFG/Profil-`ace` oder `ace_mode`, `--with-optional ace` | Vollständig entfernt (1030). Alle entsprechenden Eingaben entfernen, auch `off`, `false`, `null` oder leere Werte. Kein Ersatzexport oder nachinstallierbares ACE-Paket. |
| `AGENT_SYSTEM_ACE_CONTEXT`, `AGENT_SYSTEM_ACE_RUN_LOGGING` | Beide Umgebungsvariablen entfernen; bereits ihre Anwesenheit erzeugt vor Modellstart eine Entfallmeldung. Alte Playbooks, Deltas und Laufexporte bleiben unangetastet. |
| OpenClaw/Computer-Use/Bridge: `--openclaw-bridge`, Python-/Worker-`bridge_enabled`, CFG-/Profilfelder, `--with-optional openclaw` | Vollständig entfernt (1031), auch `false`/`null` sind Fehler. Kein nachinstallierbares Paket, keine Backend-Probes oder Workerstarts. Alte `.bridge/`-Daten bleiben unverändert; kein automatischer Import oder Umzug. |
| Bisher ausgewertete `DORA_CUA_*`-Variablen | Alle neun in [CONFIGURATION.md](CONFIGURATION.md) aufgeführten Variablen entfernen, auch leere Werte. Runner, AutoBuild und Python-Worker weisen sie vor Modellstart zurück. |
| `WAIT on=bridge:resume/retry/escalation/escalated` (mit oder ohne Token) | Entfallen. Abhängigkeit anhand des Auftrags anpassen; keine automatische Umdeutung. Gemischte Bedingungen, `mode=any` und `on_timeout=continue` umgehen den Fehler nicht. Allgemeine `todo:`/`group:`/`agent:`-WAITs, STOP und `process_stop` bleiben erhalten. Markdown-Codebeispiele und Kommentare sind weiterhin inaktiv. |
| IACT: `--iact`, alle vier `--iact-…`-Grenzen, Python-`iact_enabled` samt Limits, Worker-/CFG-/Profilfelder, `--with-optional iact` | Vollständig entfernt (1032), auch `false`/`null`/`0` sind Fehler. Kein Baum, Eventexport, Retention oder Ersatzdienst; alte IACT-Daten bleiben unverändert. Abgefangene DORA-Umgebungsnamen und Migration alter Python-Positionsargumente in [CONFIGURATION.md](CONFIGURATION.md). |
| `autobuild.py queue enqueue/list/show/cancel/run-worker`, `--queue-state`, `--prometheus-port` und Queueworker-Grenzen | Vollständig entfernt (1033), auch `false`/`null`/`0` oder leere Werte. Für einen Auftrag Standalone-AutoBuild oder `autobuild.start` verwenden; Aufgabenlisten weiter über `run_todos`. Keine automatische Übernahme gespeicherter Jobs. |
| Python-`queue_main`, `QueuedJob`, `QueueState`, `QueueWorker`, `TelemetryMetrics`; Paketgruppe `services` | Entfernt, auch die bisherigen dynamischen Exporte aus `autobuild`. Alte Zugriffe liefern eine Entfallmeldung; kein Ersatzscheduler, HTTP-Server oder nachinstallierbares Servicepaket. Parallel-CFG nutzt weiterhin Python-Worker. |
| Servicefelder in Python-/Worker-/CFG-/Profileingaben und `DORA_QUEUE_STATE`/`DORA_PROMETHEUS_PORT` | Entfernen. Sie scheitern vor Modellstart; alle abgefangenen Felder stehen in [CONFIGURATION.md](CONFIGURATION.md). Alte Queuezustände bleiben unverändert und werden nicht gelesen. |
| `sli_metrics.py`, `rollout_plan.py`, `phase9_dod.py`, `run_quality_suite.py`, `scripts/run_smoke_test.sh`; Paketgruppe `legacy-tools` | Vollständig entfernt (1034). Alte Wrapper-/CI-Aufrufe entfernen; die Dateien sind nicht mehr vorhanden. Die Paketauswahl liefert vor Anlage eines Ziels eine Entfallmeldung. Kein Ersatz für historische SLI-/Rollout-/Phase-9-Auswertungen. Lean-Prüfer, Testtreiber und Fakes bleiben im Entwicklungscheckout erhalten. |
| Paketbau: `--with-optional`, Python-`optional`, zweites Positionsargument von `package_files` | Seit 1035 vollständig entfernt, auch unbekannte Gruppen und leere Auswahlen wie `optional=()` oder `None`. Das ganze Auswahlargument entfernen. Fehler vor Quellzugriff und Zielanlage; keine optionale Nachinstallation. |
| `runtime_features.py`, Manifest-`optional_groups`, Capabilities-`optional_packages`/`optional_defaults`/`retained_optional_paths` | Leere Zusatzverwaltung entfernt. Manifest nutzt `runtime_files` und `runtime_file_count` (45 seit 1039); Exportberichte `files` und `file_count`. Capabilities nennen `retained_core_options`; die versionierten `features` bleiben erhalten. Adapter dürfen die alten Gruppenfelder nicht mehr voraussetzen. |

Python-Drittpakete aus der alten Runtime werden für den Kern nicht gebraucht.
Neue leere venv verwenden statt die laufende Controller-venv zu bereinigen.
Queue-/HTTP-/Prometheus-Dienste und historische Hilfen sind vollständig entfernt.
Bestehende Audit-, Analyse-, Quality- und Smoke-Ergebnisse werden nicht
automatisch gelesen, migriert oder gelöscht. Die frühere Quality-Suite verlangt
keine Nachinstallation von Entwicklerwerkzeugen; der Lean-Testumfang steht im
Entwicklungscheckout in `documents/TEST_MATRIX.md`. Aktueller Paketumfang:
[PACKAGE_SCOPE.md](PACKAGE_SCOPE.md). Parallel-CFG, Runtime-Profile und explizite
Git-Automation sind erhalten. `--git` führt Add/Commit/Push aus und ist ohne
diese ausdrückliche Option deaktiviert.

Alte Zeilen `<id>. Auftrag: Text` bleiben lesbar; neue Einträge verwenden
`<id>. ***Task***: Text`. `***SYNTAX marked-en***`, `***DONE***`,
`***OBSOLETE***`, CFG/WAIT/STOP und `--todo-preamble auto|off|required` bleiben
unterstützt. OBSOLETE erfüllt keine DONE-Abhängigkeit. Windows-Pfade in CFG
einfach quotieren, etwa `workspace='C:\Projekt\Teil'`; die CFG-Textgrammatik
ist keine PowerShell. Details: [ToDo-Semantik](TODO_PREAMBLE.md) und
[Direktiven](todo_directives.md).

In der mitgelieferten [Beispielliste](../examples/lean_todo.md) ist Shellnetzwerk
pro ToDo aus. Eine frühere Zeile mit beispielsweise
`***CFG logician=off allow_yolo=false network_access=false***` wird zu
`***CFG network_access=false***`. Den inhaltlichen Auftrag dabei erhalten.
Es ist kein Ersatzauftrag nötig, nur weil entfernte Optionen in Eingaben stehen.

Seit 1038 entfällt die Bindung an eine bestimmte Codex-Version in Doctor und
Decide-Transport. Die Nummer bleibt Diagnose-/Archivmetadatum. Statt einer
Versionsfreigabeliste prüft `dora_doctor.py --check-decide` die Funktion über
`decide.py` mit der installierten CLI; höchstens ein Modellaufruf, der Kosten
verursachen kann. Ohne diese Option bleibt die Diagnose kostenfrei und Decide
ausdrücklich `NOT_RUN`. Das bisherige JSON-Feld `accepted_codex_versions`
entfällt; für die Funktionsprüfung `decision_probe.status` auswerten.
Fehlende CLI-Fähigkeiten, fehlerhafte Antworten und verletzte Ausführungsgrenzen
bleiben Fehler. Die Ausführungsregeln werden nicht automatisch gelockert.
Der Doctor installiert oder aktualisiert Codex nicht. Ein bestandener
Funktionscheck belegt keine native Sandboxwirkung oder allgemeine Modellgüte. Der
echte Runnerstart einschließlich Preflight kann Modellkosten verursachen;
vorher den ausdrücklich kostenfreien Trockenlauf verwenden.
