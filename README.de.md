# ARQUILO

**Markdown-Aufgaben ausführen und Ergebnisse unabhängig reviewen.**

[English](README.md) · [Dokumentationsübersicht](docs/README.md)

ARQUILO bearbeitet Aufgaben aus einer Markdown-Liste in einem Projekt-Workspace. Auf Produktions- und Korrekturschritte folgt ein separater Review gegen den ursprünglichen Auftrag. Der Controller entscheidet über Abnahme, Korrektur, Zerlegung verbleibender Arbeit oder Stopp. Ergebnisdateien, Reviews und Ausführungsprotokolle bleiben nachvollziehbar. Ein Modell-PASS ist keine Garantie für inhaltliche Richtigkeit.

**Laufzeitversion: 0.9.1 — öffentliche Vorschau.** Dieser Branch ist ein **unveröffentlichter Integrationsstand** mit Zustands- und Git-Reparaturen, die nicht im bereits veröffentlichten v0.9.1-ZIP enthalten sind. Die unveränderte Versionsnummer ist keine neue Veröffentlichung. Maßgeblich sind [Quellstand und Grenzen](docs/integration-status.md).

## Das passende Handbuch

| Anliegen | Anleitung |
| --- | --- |
| Installieren, erste Aufgabe ausführen und wichtige Optionen kennenlernen | [Benutzerhandbuch Deutsch](docs/guides/user-guide.de.md) oder [User Guide English](docs/guides/user-guide.en.md) |
| Modelle, Reasoning, Ressourcen, parallele Aufgaben und Wiederaufnahme konfigurieren; sämtliche CLI-Parameter nachschlagen | [Advanced / Operator Guide](docs/guides/operator-guide.en.md) |
| Architektur, Sicherheitsregeln, Tests und Paketbau verstehen | [Technical / Architecture Guide](docs/guides/technical-guide.en.md) |

Die Handbücher sind die maßgeblichen Anleitungen. Die [Dokumentationsübersicht](docs/README.md) führt außerdem zu Beispielen und zum separaten Review-JSON-Protokoll. Frühere Tutorials, Cookbook- und Konfigurationsseiten sind in die Handbücher eingearbeitet und bilden keinen zusätzlichen Lesepfad mehr.

## Voraussetzungen und erster Check

Der Kern benötigt Python 3.11+ mit Standardbibliothek und eine separat installierte, angemeldete Codex-CLI. Trenne ARQUILO-Installation, Hostprogramme, Projekt-Workspace und privaten Steuerzustand. Codex einschließlich seines tatsächlichen ausführbaren Ziels muss außerhalb der von Aufgaben beschreibbaren Workspaces liegen. Provider und Anmeldung bleiben in der Codex-Hostkonfiguration; Zugangsdaten gehören nicht in Aufgabenlisten. Git wird nur für Git-basierte Installation/Updates oder ausdrücklich aktivierte Git-Veröffentlichung benötigt.

Aus einem vollständigen Checkout oder entpackten Runtime-ZIP kannst du ohne Modellaufruf Version und Hilfe anzeigen:

```sh
python3 -B arquilo.py --version
python3 -B arquilo.py tasklist run --help
```

Unter nativem Windows verwende deinen installierten Interpreter, beispielsweise `py -3.11 -B .\arquilo.py`. In WSL gelten Linux-Python und Linux-Pfade. Führe vor produktiver Arbeit die [erste sichere Vorschau](docs/guides/user-guide.de.md#preview) aus. Das Handbuch verwendet isolierte Beispieldaten und ein endliches Aufrufbudget. Echte Modellaufrufe können gemäß deiner Providervereinbarung Kosten verursachen.

## Betriebsgrenzen

Review, Statusänderungen, gemeinsame Budgets und Stopps sind Controllerregeln, nicht nur Promptanweisungen. Workspaces und Rohlogs können vertrauliche Daten enthalten. Ein lesender Reviewer und deaktiviertes Shellnetzwerk bedeuten weder rein lokale Inferenz noch ausschließlich lesende externe Werkzeuge.

Git-Automatik ist standardmäßig aus. In diesem Branch bindet sie den Review an begrenzte private Snapshots; Kapazitätsfehler können deshalb noch den normalen Ablauf blockieren. Die besprochene Entkopplung optionaler Veröffentlichung ist nicht implementiert. Lies vor dem Einschalten das [Git-Kapitel](docs/guides/operator-guide.en.md#git). Teams, GUI, MCP-Service und alternative Backend-Branches sind nicht Teil dieses Checkouts.

[Mitwirken](CONTRIBUTING.md) · [Sicherheit und Meldungen](SECURITY.md) · [Apache-2.0-Lizenz](LICENSE) · [NOTICE](NOTICE) · [Autoren](AUTHORS.md) · [Drittkomponenten](THIRD_PARTY.md) · [Änderungsverlauf](CHANGELOG.md)
