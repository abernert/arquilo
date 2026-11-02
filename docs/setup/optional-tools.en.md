# Optional helper tools for ARQUILO on a Mac

[Deutsch](optional-tools.de.md) · [Fresh-Mac setup](macos-from-scratch.en.md) · [User Guide](../guides/user-guide.en.md)

**None of the tools below is required for ARQUILO core.** Install them only when a **specific task** needs to read a Word document, inspect a scanned PDF, process spreadsheets or examine video. Deliberately, there is **no install-everything command**.

Examples target macOS with Homebrew; the [fresh-Mac setup guide](macos-from-scratch.en.md) covers Homebrew and Python. Check whether a tool works before installing it (`command -v TOOL`, `TOOL --version`; for apps `open -a APP`). All `input.*` names below are **placeholders** to replace with your own files. Prefer conversion on disposable copies in a separate output directory.

## Quick reference: tools by format

| Task / format | Helper | Install only when needed | Check |
| --- | --- | --- | --- |
| Project, code, Markdown, JSON or YAML editing | VS Code | `brew install --cask visual-studio-code` | `code --version` |
| GitHub issues and pull requests in Terminal | GitHub CLI (`gh`) | `brew install gh` | `gh --version` |
| PDF with a **text layer**, page rendering | Poppler | `brew install poppler` | `pdftotext -v` / `pdfinfo -v` |
| OCR for scans/images | Tesseract; extra languages separate | `brew install tesseract`; for German `brew install tesseract-lang` | `tesseract --list-langs` |
| DOCX/HTML/EPUB/Markdown conversion | Pandoc | `brew install pandoc` | `pandoc --version` |
| Visual inspection/export for DOCX, XLSX, PPTX | LibreOffice | `brew install --cask libreoffice` | `open -a LibreOffice` |
| Query JSON/YAML | `jq` / `yq` | `brew install jq yq` | `jq --version` / `yq --version` |
| Transform CSV/TSV | Miller (`mlr`) | `brew install miller` | `mlr --version` |
| Image conversion and metadata | ImageMagick / ExifTool | `brew install imagemagick exiftool` | `magick -version` / `exiftool -ver` |
| Inspect/convert audio/video or frames | FFmpeg/FFprobe | `brew install ffmpeg` | `ffmpeg -version` / `ffprobe -version` |
| Read/extract 7z archives | 7-Zip (`7zz`) | `brew install sevenzip` | `7zz --help` |

**Already included with macOS:** `file` (identify file type), `unzip` (ZIP), `sips` (image info), Quick Look (space bar in Finder), usually `plutil` (property lists). JSON can also be checked using `python3 -m json.tool`. These basic capabilities need no third-party install.

## 1. VS Code: edit project files

```sh
command -v code || brew install --cask visual-studio-code
code --version
code "$HOME/projects/arquilo-smoke"
```

If `code` is missing after manually installing VS Code, open VS Code → `Cmd+Shift+P` → **Shell Command: Install 'code' command in PATH**, then reopen Terminal. See [Microsoft's macOS setup guide](https://code.visualstudio.com/docs/setup/mac).

VS Code is **optional** and does not replace the agent CLI or an Office suite. Markdown, JSON, YAML and source code can be edited directly; binary Office formats need suitable viewers or converters. Only install trusted extensions; installing a VS Code extension does not automatically expose it to ARQUILO's CLI.

## 2. PDFs: text layer vs scanned pages

**PDFs containing extractable text:**

```sh
brew install poppler                    # only if pdftotext is absent
pdfinfo "input.pdf"
pdftotext -layout "input.pdf" "output.txt"
```

`pdftotext` is **not OCR**. If pages are scans, render them to images first and then run OCR:

```sh
brew install tesseract
brew install tesseract-lang             # extra languages, e.g. German
tesseract --list-langs

# Render only page 1 of a sample PDF:
pdftoppm -f 1 -l 1 -r 200 -png "scan.pdf" "page"
# OCR the resulting "page-1.png":
tesseract "page-1.png" stdout -l deu+eng
```

OCR can be wrong, particularly on tables, handwriting and low-resolution scans. Check results against the original. Consider where subsequent model processing occurs when the material is confidential. PDF export and PDF text extraction are different tasks.

## 3. Word, PowerPoint, Excel and other document formats

**Convert Word/HTML/EPUB/Markdown to text:** Pandoc can read `.docx`, among other inputs, but is **not** a universal reader for `.pptx` or `.xlsx`.

```sh
brew install pandoc                     # only if needed
pandoc -f docx -t markdown "input.docx" -o "output.md"
```

**Review layout or open Office files:** LibreOffice supports DOCX, PPTX and XLSX. Its installed application can perform PDF conversion without a globally configured `soffice` command:

```sh
brew install --cask libreoffice         # only if needed
open -a LibreOffice "input.xlsx"

mkdir -p "$HOME/projects/converted"
"/Applications/LibreOffice.app/Contents/MacOS/soffice" \
  --headless --convert-to pdf \
  --outdir "$HOME/projects/converted" "input.docx"
```

Complex formulas, fonts, embedded objects and layout may not survive conversion exactly. **Inspect converted output**, and handle macros, external links and unknown documents cautiously. Programmatic cell/slide extraction may instead call for Python libraries (section 7).

## 4. JSON, YAML, CSV and structured text

```sh
brew install jq yq miller               # select only the packages you need
jq '.' "input.json"
yq '.' "input.yaml"
mlr --csv --ojson cat "input.csv"
```

Without extra tools, `python3 -m json.tool input.json` validates and formats JSON. CSV is not automatically Excel: check separators, character encoding, decimal conventions and embedded line breaks. Python's standard library also offers XML/HTML parsers; prefer structural parsing over brittle text replacements.

## 5. Images, metadata, audio, video and archives

```sh
# Image information without installation:
sips -g pixelWidth -g pixelHeight "input.png"

# Optional image/EXIF tools:
brew install imagemagick exiftool
magick identify "input.png"
exiftool "input.jpg"

# Optional media tools:
brew install ffmpeg
ffprobe -v error -show_format "input.mp4"

# Optional 7z handling:
brew install sevenzip
7zz l "input.7z"
```

`ffmpeg` transforms audio/video; it does **not** transcribe speech on its own. Transcription requires another speech-to-text tool/model. Extract untrusted archives into a separate, controlled directory first.

## 6. Node.js only for chosen npm-based tools

The native Codex/Claude Code Homebrew installs in the [fresh-Mac guide](macos-from-scratch.en.md) **do not require Node.js**. Only if you deliberately choose npm-based tooling:

```sh
command -v node || brew install node
node --version
npm --version
```

Do not globally install npm packages with `sudo`; prefer vetted project-specific dependencies.

## 7. Separate Python environment for programmatic formats

If a task must **programmatically** parse PDF, DOCX, PPTX or XLSX, useful packages may include `pypdf`, `python-docx`, `python-pptx` and `openpyxl`. These are **not ARQUILO dependencies**. Do not install them into system Python or blindly via ARQUILO's `requirements.txt`. Create a dedicated virtual environment:

```sh
PYTHON="$(command -v python3.13 || command -v python3)"
mkdir -p "$HOME/.venvs"
"$PYTHON" -m venv "$HOME/.venvs/arquilo-formats"
"$HOME/.venvs/arquilo-formats/bin/python" -m pip install \
  pypdf python-docx python-pptx openpyxl
"$HOME/.venvs/arquilo-formats/bin/python" -c \
  'import pypdf, docx, pptx, openpyxl; print("format libraries OK")'
```

Use `"$HOME/.venvs/arquilo-formats/bin/python"` explicitly in task scripts. `pypdf` does not perform OCR, and structured Office libraries do not verify visual rendering.

## 8. Operating and security considerations

- Install only task-relevant tools; do not give the agent blanket permission to add system software. Tools and resolved symlink targets must remain **outside** task-writable workspaces.
- Installed tools may still be unavailable under sandbox, network or model policies. Test them with disposable examples and describe expected input/output formats in the task.
- Do not pass confidential files to external models or online converters without authorization. A locally running converter does not make subsequent model processing local-only.
- Review conversions and OCR against originals: PDF OCR, Office layout and complex spreadsheets may lose information.

Further reading: [User Guide](../guides/user-guide.en.md), [Operator Guide](../guides/operator-guide.en.md) and [Security](../../SECURITY.md).
