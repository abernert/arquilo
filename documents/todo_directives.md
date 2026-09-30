# Erweitertes ToDo-Format (Directive-Modus)

Dieses Dokument beschreibt das in `run_todos.py` umgesetzte, rueckwaertskompatible Directive-Format aus ToDo 21.8/21.9.

## Ziel
- Parallele Bearbeitung von ToDos in Unterworkspaces
- Aktivierung unterschiedlicher Agentenhinweise je ToDo
- Ablaufsteuerung ueber Wartebedingungen
- Modell- und Web-Recherche-Optionen je ToDo

## Rueckwaertskompatibilitaet
- Bisherige Zeilen im Format `<id>. Auftrag: ...` bleiben unveraendert gueltig.
- Ohne Directives arbeitet `run_todos.py` wie bisher.
- `***STOP***` bleibt unveraendert aktiv und muss direkt vor dem betreffenden ToDo stehen.

## Directive-Syntax
Directive-Zeilen stehen direkt oberhalb eines ToDos:

```text
***CFG key=value key2=value2***
***WAIT on=... mode=... timeout=... on_timeout=...***
<id>. ***Task***: ...
```

- Werte koennen bei Bedarf in Anfuehrungszeichen gesetzt werden.
- Mehrere `CFG`/`WAIT`-Zeilen vor demselben ToDo sind erlaubt.
- `CFG`-Werte werden fuer das naechste ToDo zusammengefuehrt.
- Codebeispiele und HTML-Kommentare bleiben unsichtbar. Eine nachgestellte
  HTML-Notiz hinter einer echten Directive verdeckt diese nicht.
- Die vollständige aktuelle Datei wird vor der Auswahl (auch WAIT/STOP) und
  vor AutoBuild geprüft. Ungültige oder entfernte Schlüssel sind Fehler;
  sie werden nicht als Standardwerte oder erfolgreicher Leerlauf behandelt.
- Die Quote-Grammatik ist auf allen Plattformen die bestehende POSIX-Textgrammatik,
  keine Shellausführung. Windows-Backslashpfade einfach quotieren, z. B.
  `workspace='C:\Projekt Raum\Teil'`, oder Schrägstriche verwenden. Der Pfad
  muss zum Host passen und innerhalb des Hauptworkspaces liegen. Es findet
  keine Variablen-, Tilde- oder Kommandosubstitution durch die Quote-Grammatik statt.

## CFG-Optionen
Unterstuetzte Schluessel:

- `workspace=<relativer_pfad>`: Unterworkspace fuer dieses ToDo.
  Default: Hauptworkspace aus `--workdir` (kein Unterworkspace).
- `parallel=<gruppenname>`: Markiert das ToDo als Teil einer Parallelgruppe.
  Default: nicht gesetzt (sequentielle Ausfuehrung).
- `agent=<name>`: Agentenhinweis fuer den Prompt dieses ToDos.
  Default: nicht gesetzt (kein zusaetzlicher Agentenhinweis und kein Profil-Override).
  - Derselbe geprüfte Name wird als `config_profile` übergeben und erzeugt
    `codex exec --profile <name>`. Historische Sicherheitsprofile aus dem
    Vorgängerprojekt sowie `dev`, `yolo`, `unsandboxed` und Full-Access-Namen
    werden zurückgewiesen; siehe [historische Migration](HISTORICAL_MIGRATION.md).
    Andere Modell-/Werkzeugprofile können die feste Sandbox nicht ersetzen.
- `model=<modell_id>`: Modell-Override fuer dieses ToDo.
  Ein explizites globales Modell aus `run_todos.py --model` beziehungsweise
  dessen Umgebungsdefault hat Vorrang; ohne globalen Wert greift CFG.
- `web_search=live|cached|disabled`: Web-Recherche-Mode fuer dieses ToDo.
  Default: nicht gesetzt (kein ToDo-Override; globaler `web_search`-Wert aus der Codex-Config bleibt wirksam).
- `websearch=live|cached|disabled`: Alias zu `web_search`.
  Default: wie `web_search`.
- `network_access=true|false`: Netzfreigabe fuer `sandbox_workspace_write` per Config-Override.
  Default: Starterfreigabe, ohne `--network-access` ausdrücklich `false`.
  `true` benötigt die Starterfreigabe; `false` darf sie pro ToDo einschränken.
  Die Netzwerkfreigabe erweitert keine Dateischreibrechte.
- `result_file=<todo_result_*.md>`: Lokaler Ergebnisdateiname für diesen Auftrag.
- `completion_anchor=<todo_result_*.md>`: Alternativer Ergebnisdateiname;
  `result_file` hat Vorrang, wenn beide gesetzt sind. Keine Pfadkomponenten.
- `breakdown=minimal|legacy|off`: Bestehende Zerlegungspolitik pro Auftrag.
  Aliasse: `structured` für minimal, `none|disabled|false` für off.
- `breakdown_max_children=1..12`, `breakdown_max_rounds=1..8`:
  Grenzen der bestehenden Zerlegung; keine neuen Schedulerbudgets.

## WAIT-Optionen
Unterstuetzte Schluessel:

- `on=<ausdruck>`: Wartebedingung. Erlaubte Praefixe:
  - `todo:<id>`
  - `<id>` als Kurzform für `todo:<id>`
  - `group:<gruppenname>`
  - `agent:<agentname>`
- `mode=all|any`: Bei mehreren Bedingungen (kommagetrennt) muessen alle oder eine erfuellt sein.
- `timeout=<dauer>`: z. B. `30s`, `5m`, `1h`, `1d`.
- `on_timeout=stop|continue`: Verhalten bei Timeout.

Gespeicherte DONE-Einträge erfüllen ToDo-Abhängigkeiten auch nach einem Neustart.
OBSOLETE, ein unvollständiger Auftrag oder bloß versuchte Arbeit erfüllen sie
nicht. Gruppen-/Agenten-Bedingungen verwenden ihre bestehenden
Laufzustände. Mehrere WAIT-Zeilen werden nacheinander geprüft. `timeout=0s`
prüft sofort; ohne Timeout wird ebenfalls nur der aktuelle Zustand geprüft.
Eine unerfüllte Bedingung beendet den Lauf mit Exit 9, sofern nicht ausdrücklich
`on_timeout=continue` gesetzt ist. Leere Listenelemente, unbekannte IDs und
ungültige Modi werden als Grammatikfehler gemeldet. STOP ist kein WAIT-Zustand
und erzeugt keine `process_stop`-Datei.

Bridge-WAITs (`bridge:resume[:token]`, `bridge:retry[:token]`,
`bridge:escalation` und `bridge:escalated`) sind seit 1031 entfernt. Linter und
Runner melden sie ausdrücklich als Konfigurationsfehler vor dem betreffenden
Modellaufruf, auch bei dynamisch angelegten Tasks, gemischten WAIT-Bedingungen,
`mode=any` und `on_timeout=continue`. Es gibt keine Aktivierungsoption mehr.
Codebeispiele und HTML-Kommentare bleiben unsichtbar.
Hinweise zum Anpassen alter Eingaben stehen in [MIGRATION.md](MIGRATION.md).

## Ausfuehrungsregeln
- Directives gelten immer nur fuer das unmittelbar folgende ToDo.
- `parallel`-Ausführung bleibt optional verfügbar; sie benötigt keinen Modusschalter.
- In Parallelgruppen muss jedes ToDo einen eigenen `workspace` haben.
- `WAIT`-Direktiven werden in Parallelgruppen fuer jedes einzelne ToDo geprueft, bevor die Gruppe gestartet wird.
- `workspace` muss nach Pfadauflösung innerhalb des Hauptworkspaces liegen.
- YOLO-/Full-Auto-/No-Check-Felder und Sicherheitsprofilfelder werden mit
  Fehler zurückgewiesen, auch bei früheren Standardwerten `false`.
  Pflichtreviews gelten in seriellen und parallelen Abläufen.
- Sämtliche `logician`-/`logician_*`-Direktiven sind in Lean entfernt, auch
  frühere Standardwerte `off`/`lite`. Entferne diese Einträge; normale Reviews
  und Audits benötigen keinen Ledger. Siehe [Migration](MIGRATION.md).
- ACE-, IACT-, OpenClaw-/Bridge- und Servicefelder sind ebenfalls entfernt,
  auch mit `false`, `off`, `null` oder leeren Werten. Es gibt keine
  Zusatzgruppe, die diese Direktiven wieder aktiviert. Parallel-CFG,
  allgemeine Runtime-Profile und Git-Opt-in bleiben Kernoptionen.
- Ruecksync aus Unterworkspaces ist nicht-destruktiv: Ergebnisse/Fragen werden gemerged statt als ganze Datei ueberschrieben.
- Bei `WAIT ... on_timeout=stop` wird der Lauf kontrolliert beendet.

## Web-Recherche (Bezug ToDo 21.7)
Integrierte Websuche wird separat durch `web_search=live|cached|disabled`
konfiguriert. `network_access` betrifft vom Agenten gestartete Shellbefehle
in `workspace-write`; Providerkommunikation und MCP/Apps sind ebenfalls
getrennte Wege. Deshalb behauptet `network_access=false` keine vollständige
Offline-Ausführung. Es gibt keinen unbeschränkten Sandboxmodus in ARQUILO.

Hinweis:
- Die Directive-Optionen `web_search` und `network_access` werden als temporaere Codex-Config-Overrides (`-c ...`) je ToDo gesetzt.
- `agent=<name>` setzt ein Codex-Modell-/Werkzeugprofil (`--profile <name>`).
  Die explizite CLI-Sandboxpolicy bleibt auch bei abweichenden Profildefaults wirksam.
- Alternativ bleibt die globale/isolierte Konfiguration ueber `CODEX_HOME/config.toml` moeglich.

## Beispiel

```md
***CFG parallel=grp_mod workspace=workspaces/analyse agent=analyst web_search=disabled network_access=false***
21.8.1. ***Task***: Analysiere die betroffenen Module und dokumentiere Risiken.

***CFG parallel=grp_mod workspace=workspaces/tests agent=tester web_search=disabled network_access=false***
21.8.2. ***Task***: Ergaenze Regressionstests fuer dieselben Module.

***WAIT on=group:grp_mod mode=all timeout=120m on_timeout=stop***
21.8.3. ***Task***: Fuehre die Ergebnisse aus Analyse und Tests zusammen.
```

## Empfohlener Laufaufruf

```text
python3 /programme/arquilo-lean/run_todos.py --todo-file /projekt/aufgaben.md --workdir /projekt
```

Natives Windows/PowerShell:

```powershell
py -3.11 C:\Arquilo\lean\run_todos.py --todo-file C:\Projekt\aufgaben.md --workdir C:\Projekt
```

Für Shellnetzwerk muss der Starter zusätzlich `--network-access` erhalten.
Die [Migration](MIGRATION.md) erklärt die entfernten
Schalter sowie den Unterschied zwischen Approval-Policy und Sandbox.

Die [Projektvorbemerkung](TODO_PREAMBLE.md) erklärt `auto|off|required`,
Referenzprompts, Markdown-Sichtbarkeit und dynamische Folgeaufgaben.
