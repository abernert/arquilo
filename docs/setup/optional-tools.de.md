# Optionale Werkzeuge für ARQUILO auf dem Mac

[English](optional-tools.en.md) · [Mac-Ersteinrichtung](macos-from-scratch.de.md) · [Benutzerhandbuch](../guides/user-guide.de.md)

**Keines der folgenden Programme ist Voraussetzung für den ARQUILO-Kern.** Du benötigst sie nur, wenn die **konkrete Aufgabe** beispielsweise Word-Dateien, eingescannte PDFs, Tabellen oder Videos bearbeiten soll. Es gibt bewusst **keinen** pauschalen `brew install`-Befehl für alle Tools.

Die Beispiele gelten für macOS und Homebrew; die [Einrichtung ab einem neuen Mac](macos-from-scratch.de.md) erklärt Homebrew und Python. Vor jedem Installieren prüfen, ob das Programm bereits funktioniert (`command -v PROGRAMM`, `PROGRAMM --version`; bei Apps `open -a APP`). Alle `eingabe.*`-Dateinamen unten sind **Platzhalter**, die durch eigene Dateien ersetzt werden müssen. Führe Konvertierungen vorzugsweise mit Kopien in einem separaten Ausgabeordner aus.

## Übersicht: welches Programm für welchen Dateityp?

| Aufgabe / Format | Werkzeug | Installation bei Bedarf | Kontrolle |
| --- | --- | --- | --- |
| Projekt, Code, Markdown, JSON, YAML lesen/bearbeiten | VS Code | `brew install --cask visual-studio-code` | `code --version` |
| GitHub-Issues und Pull Requests im Terminal | GitHub CLI (`gh`) | `brew install gh` | `gh --version` |
| PDF mit **Textschicht** lesen; Seiten rendern | Poppler | `brew install poppler` | `pdftotext -v` / `pdfinfo -v` |
| Scan/Bild per OCR lesen | Tesseract; weitere Sprachen separat | `brew install tesseract`; für Deutsch `brew install tesseract-lang` | `tesseract --list-langs` |
| DOCX/HTML/EPUB/Markdown konvertieren | Pandoc | `brew install pandoc` | `pandoc --version` |
| DOCX, XLSX, PPTX visuell prüfen/als PDF exportieren | LibreOffice | `brew install --cask libreoffice` | `open -a LibreOffice` |
| JSON/YAML abfragen | `jq` / `yq` | `brew install jq yq` | `jq --version` / `yq --version` |
| CSV/TSV transformieren | Miller (`mlr`) | `brew install miller` | `mlr --version` |
| Bildkonvertierung, Metadaten | ImageMagick / ExifTool | `brew install imagemagick exiftool` | `magick -version` / `exiftool -ver` |
| Audio/Video prüfen, umwandeln, Einzelbilder | FFmpeg/FFprobe | `brew install ffmpeg` | `ffmpeg -version` / `ffprobe -version` |
| 7z-Archive lesen/entpacken | 7-Zip (`7zz`) | `brew install sevenzip` | `7zz --help` |

**Schon in macOS vorhanden:** `file` (Format erkennen), `unzip` (ZIP), `sips` (Bildinformationen), Quick Look (Leertaste im Finder), meist `plutil` (Property-Listen). JSON lässt sich auch mit `python3 -m json.tool` prüfen. Für diese Grundfunktionen musst du nichts zusätzlich installieren.

## 1. VS Code: Editor und Dateien öffnen

```sh
command -v code || brew install --cask visual-studio-code
code --version
code "$HOME/projects/arquilo-smoke"
```

Falls `code` nach einer manuellen VS-Code-Installation nicht gefunden wird: VS Code öffnen → `Cmd+Shift+P` → **Shell Command: Install 'code' command in PATH**; danach Terminal neu öffnen. Siehe [offizielle Anleitung für macOS](https://code.visualstudio.com/docs/setup/mac).

VS Code ist **optional** und ersetzt weder die Agenten-CLI noch ein Office-Programm. Du kannst Markdown, JSON, YAML und Programmcode bearbeiten; für die Darstellung binärer Office-Dateien nutze ein geeignetes Tool. Erweiterungen nur aus vertrauenswürdigen Quellen installieren; ein VS-Code-Plugin ist nicht automatisch für die ARQUILO-CLI verfügbar.

## 2. PDF: extrahierbarer Text oder Scan?

**PDF mit echter Textschicht:**

```sh
brew install poppler                    # nur falls pdftotext fehlt
pdfinfo "eingabe.pdf"
pdftotext -layout "eingabe.pdf" "ausgabe.txt"
```

`pdftotext` ist kein OCR-Programm. Wenn das PDF nur gescannte Seiten enthält, müssen die Seiten als Bilder gerendert und anschließend mittels OCR gelesen werden:

```sh
brew install tesseract
brew install tesseract-lang             # zusätzliche Sprachen, etwa Deutsch
tesseract --list-langs

# Nur Seite 1 eines Beispiel-PDFs als PNG rendern:
pdftoppm -f 1 -l 1 -r 200 -png "scan.pdf" "seite"
# Beispieldatei "seite-1.png" nach OCR:
tesseract "seite-1.png" stdout -l deu+eng
```

Das OCR-Ergebnis kann fehlerhaft sein, besonders bei Tabellen, Handschrift und geringer Auflösung. Stichprobenweise gegen das Original prüfen; bei sensiblen Dokumenten prüfen, wo Modellaufrufe verarbeitet werden. PDF-Export und PDF-Textauswertung sind unterschiedliche Aufgaben.

## 3. Word, PowerPoint, Excel und andere Dokumentformate

**Word/HTML/EPUB/Markdown als Text aufbereiten:** Pandoc kann unter anderem `.docx` einlesen, ist aber **kein** universeller Importer für `.pptx` oder `.xlsx`.

```sh
brew install pandoc                     # nur falls nicht vorhanden
pandoc -f docx -t markdown "eingabe.docx" -o "ausgabe.md"
```

**Layout prüfen oder Office-Dateien öffnen:** LibreOffice unterstützt DOCX, PPTX und XLSX. Eine PDF-Umwandlung über die installierte App benötigt keinen globalen `soffice`-PATH-Eintrag:

```sh
brew install --cask libreoffice         # nur falls nicht vorhanden
open -a LibreOffice "eingabe.xlsx"

mkdir -p "$HOME/projects/converted"
"/Applications/LibreOffice.app/Contents/MacOS/soffice" \
  --headless --convert-to pdf \
  --outdir "$HOME/projects/converted" "eingabe.docx"
```

Bei komplexen Dokumenten können Formeln, Layout, eingebettete Objekte oder Schriftarten abweichen. **Prüfe die exportierten Dateien**; Makros, externe Links und unbekannte Office-Dateien vorsichtig behandeln. Für strukturierte Zellwerte oder Folieninhalte sind gegebenenfalls Python-Bibliotheken geeigneter (Abschnitt 7).

## 4. JSON, YAML, CSV und Textdaten

```sh
brew install jq yq miller               # nur benötigte Pakete auswählen
jq '.' "eingabe.json"
yq '.' "eingabe.yaml"
mlr --csv --ojson cat "eingabe.csv"
```

Alternativ ohne zusätzliche Installation: `python3 -m json.tool eingabe.json`. CSV ist nicht automatisch Excel: Trennzeichen, Zeichensatz, Dezimalkomma und Zeilenumbrüche beachten. Für XML/HTML gibt es außerdem Parser der Python-Standardbibliothek; verwende strukturierte Parser statt fragiler Text-Ersetzungen.

## 5. Bilder, Metadaten, Audio, Video und Archive

```sh
# Bildinformationen ohne Installation:
sips -g pixelWidth -g pixelHeight "eingabe.png"

# Bei Bedarf Bilder/EXIF:
brew install imagemagick exiftool
magick identify "eingabe.png"
exiftool "eingabe.jpg"

# Bei Bedarf Medien:
brew install ffmpeg
ffprobe -v error -show_format "eingabe.mp4"

# Bei Bedarf 7z:
brew install sevenzip
7zz l "eingabe.7z"
```

`ffmpeg` wandelt Audio/Video um, transkribiert **nicht** automatisch Sprache; dafür wäre ein gesondertes Speech-to-Text-Werkzeug/Modell erforderlich. Entpacke fremde Archive zunächst in ein separates, kontrolliertes Verzeichnis.

## 6. Node.js nur für ausgewählte npm-Werkzeuge

Für die in der [Mac-Ersteinrichtung](macos-from-scratch.de.md) empfohlenen nativen Codex-/Claude-Code-Installationen per Homebrew ist Node.js **nicht** erforderlich. Falls du bewusst andere npm-basierte Tools einsetzen willst:

```sh
command -v node || brew install node
node --version
npm --version
```

Installiere keine globalen npm-Pakete mit `sudo`. Wähle möglichst projektspezifische, geprüfte Abhängigkeiten.

## 7. Python-Bibliotheken nur in einer separaten Umgebung

Für **programmatisches** Lesen von PDF, DOCX, PPTX oder XLSX sind je nach Aufgabe beispielsweise `pypdf`, `python-docx`, `python-pptx` oder `openpyxl` sinnvoll. Sie sind **keine ARQUILO-Abhängigkeiten**. Installiere sie nicht in das System-Python oder blind über die ARQUILO-`requirements.txt`, sondern in eine dedizierte virtuelle Umgebung:

```sh
PYTHON="$(command -v python3.13 || command -v python3)"
mkdir -p "$HOME/.venvs"
"$PYTHON" -m venv "$HOME/.venvs/arquilo-formats"
"$HOME/.venvs/arquilo-formats/bin/python" -m pip install \
  pypdf python-docx python-pptx openpyxl
"$HOME/.venvs/arquilo-formats/bin/python" -c \
  'import pypdf, docx, pptx, openpyxl; print("format libraries OK")'
```

Nutze bei entsprechenden Skripten explizit `"$HOME/.venvs/arquilo-formats/bin/python"`. `pypdf` ersetzt kein OCR, und Bibliotheken für Office-Dateien prüfen nicht automatisch die visuelle Darstellung.

## 8. Betrieb und Sicherheit

- Installiere nur die für den konkreten Task benötigten Tools; der Agent soll nicht unkontrolliert Systemsoftware nachinstallieren. Werkzeuge und Symlink-Ziele gehören **außerhalb** des beschreibbaren Task-Workspaces.
- Ein installiertes Tool ist nicht automatisch durch Sandbox-, Netzwerk- oder Modell-Policies nutzbar. Teste es mit einer entbehrlichen Beispieldatei und dokumentiere im Task die erwarteten Ein-/Ausgabeformate.
- Vertrauliche Dateien nicht ungeprüft an externe Modelle oder Online-Konverter übermitteln. Ein lokal laufendes Konvertierungsprogramm bedeutet nicht, dass die anschließende Modellverarbeitung lokal bleibt.
- Nach Konvertierung/OCR das Ergebnis fachlich prüfen; insbesondere PDF/OCR, Office-Layout und komplexe Tabellen können Informationen verlieren.

Weiterlesen: [Benutzerhandbuch](../guides/user-guide.de.md), [Operator Guide](../guides/operator-guide.en.md) und [Security](../../SECURITY.md).
