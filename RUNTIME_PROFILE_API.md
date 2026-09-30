# DORA Runtime Profile API v1

## Grundsatz

Ein Runtime-Profil darf DORA nur um domänenspezifische Kontext- und
Prüfregeln ergänzen. Es darf keine DORA-Sicherheitskontrolle abschalten, keinen
Runzustand setzen und keinen Review oder Aufgabenabschluss als erfolgreich markieren.
JSON-Runtime-Profile gehören zum Lean-Kern und benötigen kein Zusatzpaket.
Entfernte Funktionsfelder werden auch hier abgewiesen; siehe
[Konfiguration](documents/CONFIGURATION.md) und [Migration](documents/MIGRATION.md).

## Aktivierung

```text
python3 run_todos.py --todo-file /projekt/aufgaben.md --workdir /projekt --runtime-profile /projekt/profil.json
```

In PowerShell entsprechend `py -3.11` und native Windows-Pfade verwenden.
Alternativ setzt ein Controller `DORA_RUNTIME_PROFILE` in der Umgebung des
Kindprozesses. Die öffentliche CLI-Option hat Vorrang.

## Schema

Das Profil verwendet `schema_version: dora.runtime_profile.v1` und kann
folgende neutrale Beiträge liefern:

- `activation_markers`: Aktivierung des gesamten Profils;
- `scope_activation_markers`: gesonderte Aktivierung von Scope- und
  Blockschutz;
- `protected_markers`: Namen bytegenau zu erhaltender markierter Blöcke;
- `prompt_policy`: additive Task-, Breakdown-, Parent-Review- und
  AutoBuild-Regeln;
- `preflight`: argv-basierter Befehl mit Timeout;
- `metadata`: für den Eigentümer frei nutzbare, von DORA nicht interpretierte
  Metadaten.

Unterstützte Preflight-Platzhalter sind `{python}`, `{workdir}`,
`{todo_file}`, `{profile_path}` und `{profile_dir}`.

## Capability-Vertrag

```bash
python3 run_todos.py --print-capabilities
```

liefert ausschließlich ein JSON-Objekt nach `dora.capabilities.v1`. Adapter
prüfen Featureversionen statt DORA-Quelltext, Dateinamen oder interne
Konstanten zu untersuchen.
`features` enthält die bestehenden versionierten Kernverträge;
`retained_core_options` nennt `CFG parallel`, `runtime_profile` und `--git`.
Es gibt keine Felder für installierbare Zusatzgruppen mehr.
