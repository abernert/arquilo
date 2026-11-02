# ARQUILO auf macOS: Einrichtung ab einem neuen Mac

[English](macos-from-scratch.en.md) · [Optionale Werkzeuge](optional-tools.de.md) · [Benutzerhandbuch](../guides/user-guide.de.md) · [README](../../README.de.md)

Diese Anleitung beginnt **vor** der ARQUILO-Installation: bei einem Mac, auf dem Homebrew, Git, Python und eine Agenten-CLI möglicherweise noch fehlen. Sie gilt für macOS mit Apple Silicon oder Intel und die übliche Terminal-Shell `zsh`. Installiere nur, was fehlt. Befehle mit `brew` sind eine bequeme Installationsvariante, **keine** technische Pflicht für ARQUILO.

**Minimal nötig:** Python **ab 3.11** (in der CI werden 3.11–3.13 geprüft), der vollständige ARQUILO-Code und **entweder** eine authentifizierte Codex-CLI (Standard) **oder** Claude Code (mit `--backend claude-code`). Für den Git-Checkout benötigst du Git; mit einem offiziellen Runtime-ZIP geht es auch ohne Git. `gh`, VS Code, Node.js und Programme zum Lesen weiterer Formate sind **nicht** für den ARQUILO-Kern erforderlich.

## 0. Terminal öffnen und System prüfen

Öffne **Terminal** (Programme → Dienstprogramme → Terminal). Die Kommandos beziehen sich auf ein normales Benutzerkonto, nicht auf eine Root-Shell.

```sh
sw_vers -productVersion
uname -m             # arm64 = Apple Silicon; x86_64 = Intel
echo "$SHELL"       # üblicherweise /bin/zsh
```

Lasse eine laufende Installation abschließen, bevor du den nächsten Schritt ausführst. Auf verwalteten Firmenrechnern müssen Softwarefreigaben, Proxy, Zertifikate und Authentifizierung zur Unternehmensrichtlinie passen. Installationsskripte aus dem Internet nur nach Prüfung der offiziellen Quelle ausführen.

## 1. Apple Command Line Tools und Git

Prüfe zuerst, ob die Apple-Entwicklerwerkzeuge und Git bereits verfügbar sind:

```sh
xcode-select -p
git --version
```

Wenn `xcode-select -p` scheitert, starte die Apple-Installation und bestätige den macOS-Dialog. Danach die Prüfung wiederholen:

```sh
xcode-select --install
```

Die Command Line Tools stellen auf vielen Macs bereits Git bereit. Falls `git --version` danach noch nicht funktioniert, kannst du Git nach Schritt 2 mit `brew install git` installieren. Ein GitHub-Konto ist für das **öffentliche** ARQUILO-Repository nicht erforderlich.

## 2. Homebrew installieren, sofern nicht vorhanden

```sh
command -v brew
brew --version
```

Wenn Homebrew fehlt, verwende den [offiziellen Installer](https://brew.sh/). Der folgende Befehl stammt von der Homebrew-Projektseite:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

**Wichtig:** Befolge die `Next steps`, die der Installer ausgibt. Häufig muss Homebrew in die Shell-Konfiguration (`~/.zprofile`) aufgenommen werden. Nur falls `brew` danach nicht gefunden wird, kannst du den Pfad für die aktuelle Sitzung setzen — **genau eine** der beiden Varianten wählen:

```sh
# Apple Silicon:
eval "$(/opt/homebrew/bin/brew shellenv)"
# ODER Intel:
# eval "$(/usr/local/bin/brew shellenv)"
brew --version
```

Übernimm für **dauerhafte** PATH-Einstellungen die konkrete `shellenv`-Zeile aus der Installer-Ausgabe in `~/.zprofile`; vermeide doppelte Einträge. [Homebrew-Installationsdokumentation](https://docs.brew.sh/Installation).

## 3. Git prüfen; GitHub CLI optional ergänzen

```sh
git --version
# Nur wenn Git nach Schritt 1 nicht verfügbar ist:
# brew install git
```

`gh` ist hilfreich für Issues, Pull Requests und private Repositories, aber **kein Muss**, um das öffentliche ARQUILO zu klonen:

```sh
command -v gh || brew install gh
gh --version
```

Nur wenn du GitHub-Funktionen verwendest, die eine Anmeldung verlangen:

```sh
gh auth login
gh auth status
```

Die GitHub-Anmeldung ist **nicht** die Codex-/Claude-Anmeldung. Gib Tokens nicht in Aufgabenlisten, Shell-Skripte oder Repo-Dateien ein. [Offizielle GitHub-CLI-Anleitung](https://cli.github.com/manual/gh_auth_login).

## 4. Geeignetes Python bereitstellen

macOS kann ein zu altes `python3` mitbringen. Prüfe nicht nur, ob Python existiert, sondern auch seine Version:

```sh
python3 --version
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
```

Wenn `python3` fehlt oder der zweite Befehl einen Fehler liefert, installiere die in der CI geprüfte Version 3.13:

```sh
brew install python@3.13
python3.13 --version
```

Wähle danach für **diese Terminal-Sitzung** den Interpreter aus. Ein versioniertes `python3.13` wird bevorzugt, damit ein älteres macOS-`python3` keine Befehle übernimmt:

```sh
PYTHON="$(command -v python3.13 || command -v python3)"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), sys.version; print(sys.version)'
```

In den restlichen Befehlen steht `"$PYTHON"` für den geprüften Interpreter. Nach Öffnen eines neuen Terminals die Zuweisung wiederholen oder direkt `python3.13` verwenden. Du brauchst **kein** `pip install -r requirements.txt` für den ARQUILO-Kern; er verwendet die Python-Standardbibliothek. Python-Versionen oberhalb der CI-Matrix (3.11–3.13) sind möglicherweise noch nicht getestet.

## 5. Genau ein Agenten-Backend installieren und anmelden

**Variante A – Codex (Standard):**

```sh
command -v codex || brew install --cask codex
codex --version
codex login status
```

Falls noch nicht angemeldet, führe `codex login` aus und folge dem Anmeldeverfahren. Alternativ kannst du den [offiziellen Codex-Installer](https://github.com/openai/codex#installing-and-running-codex-cli) verwenden. Die CLI ist **nicht** mit der Desktop-App gleichzusetzen.

**Variante B – Claude Code (Alternative, kein Codex erforderlich):**

```sh
command -v claude || brew install --cask claude-code
claude --version
```

Starte `claude` bei Bedarf einmal interaktiv und folge der Anmeldung. Die offizielle [Claude-Code-Installationsanleitung](https://docs.anthropic.com/en/docs/claude-code/getting-started) nennt auch den nativen Installer. Für dieses Homebrew-Verfahren benötigst du **kein Node.js**; Node wird nur gebraucht, falls du selbst einen npm-basierten Launcher wählst. Die CLI-Installation ersetzt kein passendes Modell-/Provider-Konto.

**Sicherheitsgrenze:** Installiere Git, Agenten-CLIs und deren tatsächliche Ziele außerhalb von Verzeichnissen, die ARQUILO-Aufgaben beschreiben dürfen. ARQUILO-Verzeichnis, Projekt-Workspace und privater Controller-State müssen getrennt sein. Keine Tokens im Projekt ablegen.

## 6. ARQUILO installieren

Das öffentliche Repository lässt sich ohne `gh auth login` klonen:

```sh
mkdir -p "$HOME/tools" "$HOME/projects"
cd "$HOME/tools"
git clone https://github.com/abernert/arquilo.git
cd arquilo
```

Falls `$HOME/tools/arquilo` bereits existiert, **nicht** erneut klonen und nicht blind überschreiben; prüfe zuerst `git -C "$HOME/tools/arquilo" status` und die [Update-Hinweise](../guides/user-guide.de.md).

**Ohne Git:** Lade unter [Releases](https://github.com/abernert/arquilo/releases) das **vollständige versionierte Runtime-ZIP** herunter, entpacke es an einem separaten Ort und wechsle im Terminal in das Verzeichnis mit `arquilo.py`. Eine einzelne Python-Datei reicht nicht.

## 7. Funktionstest ohne Modellkosten

Führe diese Befehle aus dem ARQUILO-Installationsverzeichnis aus (`cd "$HOME/tools/arquilo"` bei Git-Installation). Der erste Test braucht weder Anmeldung noch Modellaufrufe:

```sh
"$PYTHON" -B arquilo.py --version
"$PYTHON" -B arquilo.py tasklist run --help
```

Lege einen **separaten** Wegwerf-Workspace an und erstelle einen Dry Run:

```sh
mkdir -p "$HOME/projects/arquilo-smoke"
cp examples/minimal_todo.md "$HOME/projects/arquilo-smoke/tasks.md"

"$PYTHON" -B arquilo.py tasklist run \
  --workdir "$HOME/projects/arquilo-smoke" \
  --todo-file "$HOME/projects/arquilo-smoke/tasks.md" \
  --dry-run \
  --dry-run-file "$HOME/projects/arquilo-smoke/preview.md" \
  --process-stop-policy controller-only \
  --max-calls 8 --mcp none --skills none
```

Prüfe anschließend `$HOME/projects/arquilo-smoke/preview.md`. Ein `--dry-run` prüft die Aufgabenplanung, **nicht** die tatsächliche Provider-/Modellverbindung. Für den reinen Metadatencheck:

```sh
# Codex:
"$PYTHON" -B arquilo.py doctor --workdir "$HOME/projects/arquilo-smoke"
# Nur bei Claude Code stattdessen:
# "$PYTHON" -B arquilo.py doctor --backend claude-code --workdir "$HOME/projects/arquilo-smoke"
```

**Noch keinen echten Lauf starten?** Dann bist du fertig. Der [erste echte Lauf](../guides/user-guide.de.md#first-run) kann externe Modellaufrufe und Kosten erzeugen. Bei Claude Code `--backend claude-code` angeben; benannte ARQUILO-MCP-Server sind dort in Version 0.10.0 nicht unterstützt.

## 8. Häufige Probleme und Updates

| Problem | Prüfen / Vorgehen |
| --- | --- |
| `brew: command not found` | `Next steps` des Homebrew-Installers und `~/.zprofile`; Terminal neu öffnen. |
| Python meldet `3.9`/`3.10` | Explizit `python3.13` bzw. `"$PYTHON"` nutzen, nicht das alte macOS-`python3`. |
| `codex`/`claude` nicht gefunden | `command -v codex` oder `command -v claude`, Homebrew PATH und ggf. Terminal-Neustart prüfen. |
| `git` funktioniert nicht | Apple Command Line Tools abschließen oder `brew install git`. |
| Anmeldung scheitert | Richtigen Backend-Provider, Konto, Berechtigungen, Proxy und Zertifikate prüfen; `gh auth login` löst keine Modell-Anmeldung. |
| Firmen-Mac blockiert Installer | Freigabe der IT einholen; keine Sicherheitskontrollen oder Signaturprüfungen umgehen. |

Vor Updates aktive ARQUILO-Läufe beenden, eigene Aufgaben/Controller-Nachweise sichern und im Git-Checkout **zuerst** `git status` prüfen. Nur bei sauberem Checkout: `git pull --ff-only`. Niemals alte und neue Python-Module mischen; anschließend einen neuen Dry Run durchführen.

## Nächste Schritte

- [Benutzerhandbuch Deutsch: Aufgaben, Ergebnisse, erster echter Lauf](../guides/user-guide.de.md)
- [Optionale Werkzeuge: VS Code, Office, PDF/OCR, Bilder, Audio/Video, Formate](optional-tools.de.md)
- [Sicherheitsgrenzen und bekannte Einschränkungen](../../SECURITY.md)
