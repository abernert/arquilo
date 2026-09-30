# DORA Lean: Paketumfang und erhaltene Kernoptionen

Die verbindliche Positivliste steht in [lean_package.json](lean_package.json). ToDo 1028
gibt die Entfernung der Zusatzgruppen frei. ACE (1030), OpenClaw/Computer-Use/Bridge (1031),
IACT (1032), Queue-/HTTP-/Prometheus-Dienste (1033) und historische
Fach-/Betriebshilfen (1034) sind vollständig entfernt.
Seit 1039 enthält die Liste **45 Dateien**: die 42 Kerndateien aus der
Paketkonsolidierung 1035 sowie README, `.gitignore` und den direkten
ZIP-Einstieg `scripts/build_runtime_zip.py` für eine neue Repo-Basis. Keine
der 22 ehemaligen Zusatzdateien ist enthalten. Die leere Verwaltung `runtime_features.py`
ist ebenfalls entfernt; `runtime_file_count` weist die aktuelle Dateizahl aus.
Es gibt keine optionalen Paketgruppen. Historische Projekte, Logs und Nachweise
werden beim Zusammenstellen eines Pakets weder eingelesen noch gelöscht.
Die Scopequelle 1028 und die Ergebnisse 1030–1035 liegen als externe
Entwicklungsbelege unter `documents/todos/` im Checkout, außerhalb des Pakets.

Ein frisches Runtime-ZIP erzeugen, aus dem Checkout mit Python >=3.11:

```text
python3 -B scripts/build_runtime_zip.py /pfad/zu/neuem/dora-lean.zip
```

Unter Windows `py -3.11` verwenden; das Ziel ist beispielsweise
`C:\Dora\dora-lean.zip`. Die Zieldatei darf noch nicht existieren. Es werden nur ausdrücklich aufgeführte Dateien
kopiert; kein rekursives Kopieren des Arbeitsrepositorys, keine Installation und
kein Überschreiben einer laufenden Runtime.
`python3 scripts/stage_lean.py /pfad/zu/neuem/dora-lean` erzeugt alternativ
ein neues Verzeichnis aus derselben Positivliste. Abhängigkeiten und Verwendung sind in
[DISTRIBUTION.md](DISTRIBUTION.md), die Konfiguration in
[CONFIGURATION.md](CONFIGURATION.md) beschrieben. Installation, Doctor und
Bedienung stehen in der [Kurzanleitung](QUICKSTART.md), Anpassungen in der
[Migration](MIGRATION.md).

`--with-optional` und Python-`optional` sind vollständig stillgelegt. Jede
Angabe wird vor Quellzugriff oder Zielanlage mit Entfallmeldung abgewiesen,
auch unbekannte Gruppen, `optional=()`, `None` oder ein leerer CLI-Wert.
`package_files(source)`, `stage_package(destination, source=source)` und
`zip_package(destination, source=source)` verwenden dieselbe Positivliste.
Der Exportbericht enthält `file_count` und `files`, keine Gruppenauswahl.

**ACE ist entfernt:** Playbook-Injektion, Online-Updates, Reflect/Curate und
ACE-Laufexport sind nicht mehr verfügbar. `--ace-mode`, Python-/Worker-`ace_mode`,
`AGENT_SYSTEM_ACE_CONTEXT`, `AGENT_SYSTEM_ACE_RUN_LOGGING` und die Paketauswahl
`ace` werden ausdrücklich zurückgewiesen, auch bei bisherigen Aus-Werten.
Vorhandene Playbooks und Exporte werden weder gelesen noch geändert.

**OpenClaw/Computer-Use/Bridge ist entfernt:** Keine Requests, Receipts,
Delivery-Logs, Backend-Probes oder Bridge-Worker werden mehr verarbeitet bzw.
gestartet. `--openclaw-bridge`, Python-/Worker-`bridge_enabled`, zugehörige
CFG-/Profilfelder, die früheren `DORA_CUA_*`-Variablen und die Paketauswahl
`openclaw` liefern Entfallmeldungen. `WAIT on=bridge:…` wird auch bei dynamischen
Aufgaben, gemischten Bedingungen und `on_timeout=continue` vor dem betreffenden
Aufruf abgewiesen. Bestehende `.bridge/`-Daten bleiben unangetastet.
Allgemeine WAIT-/STOP-Regeln bleiben erhalten; Details in [Migration](MIGRATION.md).

**IACT ist entfernt:** Kein Baum-/Event-Export, keine Retention-Löschung,
Größenbegrenzung oder Phase-3-DoD. `--iact`, alle vier `--iact-…`-Grenzoptionen,
Python-`iact_enabled` und zugehörige Limits, CFG-/Profil-/Workerfelder sowie
Paketauswahl `iact` werden früh zurückgewiesen, auch bei `false`, `null` oder `0`.
Alte IACT-Daten bleiben unangetastet. `--print-capabilities` bietet IACT nicht an.
Details einschließlich der abgefangenen Umgebungsnamen in
[CONFIGURATION.md](CONFIGURATION.md).

**Queue-/HTTP-/Prometheus-Dienste sind entfernt:** `autobuild.py queue …`,
`--queue-state`, `--prometheus-port`, alte Python-Exporte und Paketauswahl
`services` liefern Entfallmeldungen. Es gibt keine Service-Nachinstallation.
Alte Queuezustände werden weder gelesen noch geändert; es startet kein
Queueworker oder HTTP-Server. Der direkte Aufruf, Standalone-AutoBuild und
Python-Worker für Parallel-CFG bleiben erhalten.

**Historische Fach-/Betriebshilfen sind entfernt:** `sli_metrics.py`,
`rollout_plan.py`, `phase9_dod.py`, `run_quality_suite.py` und
`scripts/run_smoke_test.sh` werden weder mitgeliefert noch im aktiven Checkout
bereitgestellt. `--with-optional legacy-tools` wird vor Anlage eines Pakets
mit Entfallmeldung zurückgewiesen. Keine Nachinstallation und kein Ersatzdienst.
Alte Analyse-, Audit-, Quality- und Smoke-Ergebnisse bleiben unverändert.
Die Runbooks dazu sind historische Dokumentation, keine Lean-Startanleitung.

`todo_lint.py`, `dora_doctor.py` und `scripts/stage_lean.py` bleiben im Paket;
`scripts/build_runtime_zip.py` ist der direkte ZIP-Einstieg.
Die Lean-Testtreiber mit ihren lokalen Fakes und der lesende RC5-Vergleich
bleiben im Entwicklungscheckout erhalten; ihre Ausführung benötigt keines
der entfernten Hilfsprogramme oder deren frühere Quality-Werkzeuge.

Im Kern bleiben Referenzprompt, Vorbemerkung, Ergebnisse, volle Rohstreams,
finale Antworten, Tasklogs, Reviews, Reparaturen, Breakdown/Parent-Abnahme und
Decide-Archive. Diese Protokolle sind unabhängig vom entfernten IACT-Export.

Parallel-CFG, JSON-Runtime-Profile und `--git` bleiben unverändert verfügbar.
Parallelgruppen verwenden echte Python-Worker und getrennte Unterworkspaces.
Ein Runtime-Profil erweitert keine Sandboxrechte. `--git` bleibt standardmäßig
aus und führt bei expliziter Aktivierung weiterhin Add/Commit/Push aus.
Die Entwicklungstests zeichnen diese Git-Kommandos nur mit Fakes auf; sie
führen keinen Commit oder Push aus.

Frage 1001-01 ist durch 1028 beantwortet. Die offene Nutzungsfrage 1001-02
blockiert den Erhalt von Parallel-CFG, Runtime-Profilen und Git-Opt-in nicht.
Native Windows-/Linux- und Live-Codex-Abnahmen werden nur mit tatsächlichem
Nachweis als ausgeführt geführt. Die frühere Prometheus-Abnahme ist entfallen,
nicht bestanden.
