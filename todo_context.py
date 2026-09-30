# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Project preambles for one run_todos -> AutoBuild handoff.

The editable Markdown workspace remains authoritative. This is a context
snapshot, not a task store, scheduler or authorization mechanism.
"""
from __future__ import annotations

from pathlib import Path
import re

from runtime_files import read_utf8
from todo_syntax import task_headers, visible_lines

TODO_PREAMBLE_CONTRACT_VERSION = 1
PREAMBLE_MODES = ("auto", "off", "required")
MAX_PREAMBLE_BYTES = 65536

SEMANTICS = """ARQUILO – Semantik des bearbeitbaren Markdown-Arbeitsplans (v1):
- Die Vorbemerkung beschreibt das Gesamtziel, Regeln und Qualitätsmaßstäbe des Projekts. Der aktuelle Einzelauftrag beschreibt den jetzt zu erbringenden Beitrag. Ein Planungsauftrag ist NICHT schon deshalb unvollständig, weil spätere Projektarbeiten noch offen sind.
- Ausführbare Überschriften: '<id>. Auftrag: ...', '<id>. Task: ...' oder '<id>. ***Task***: ...'. Erledigt: DONE bzw. ***DONE***. Entfallen: OBSOLETE bzw. ***OBSOLETE***. Beispiele in Codeblöcken und HTML-Kommentaren sind keine ausführbaren Aufträge.
- Der Text bis zur nächsten echten Aufgabenüberschrift gehört zur aktuellen Aufgabe. Zeilen mit ***CFG ...*** und ***WAIT ...*** steuern den jeweils folgenden Auftrag, nicht pauschal das ganze Projekt. ***SYNTAX marked-en*** am Dateianfang wählt markierte englische Kommandowörter. ***STOP*** vor einem Auftrag beendet die Auswahl an dieser Stelle; es ist kein Wartezustand.
- Die Datei ist das lesbare, selbstveränderbare Arbeitsprogramm. Innerhalb der erteilten Befugnis darfst Du offene Aufgaben präzisieren, ergänzen, zerlegen oder begründet auf OBSOLETE setzen. Änderungen dürfen das Gesamtziel nicht stillschweigend abschwächen. Kurze Begründungen gehören in den Projektstand oder den betroffenen Aufgabenblock.
- Nur wenn der aktuelle Auftrag Planung delegiert, ergänze Folgeaufträge. Verwende eindeutige, streng aufsteigende IDs; für neue Arbeitsrunden neue IDs statt Wiederöffnung bereits erledigter Aufgaben. Folgeaufträge sollen konkrete Ergebnisse und begrenzte, überprüfbare Abnahmekriterien haben. Wähle die in der Datei vorgegebene Schreibweise.
- Nur die Kontrollinstanz markiert Deine Arbeit DONE. OBSOLETE ist kein Erfolgsnachweis und erfüllt keine WAIT-on-todo-Bedingung. DOING und WAITING sind in dieser Runtime noch keine ausführbaren Statuswörter. Technische Fehler, ein ausgefallener Reviewer oder eine bloß leere Aufgabenliste beweisen keinen Projekterfolg.
- Lies den aktuellen Projektstand und relevante Arbeitsdateien; die eingebettete Vorbemerkung ersetzt deren Inhalt nicht. Halte Beobachtungen, Annahmen, kreative Entscheidungen und Bewertungen auseinander, soweit der Auftrag es verlangt. Fiktion muss nicht als reale Tatsache belegt werden; ästhetische Urteile sind keine mathematischen Beweise.
- Beurteile den jetzigen Auftrag gegen seinen begrenzten Umfang. Übernimm notwendige spätere Arbeit in konkrete Folgeaufträge. Ein ausdrücklich verlangter Projektabschluss bewertet dagegen die tatsächlichen Endprodukte gegen das Gesamtziel und nennt verbleibende Grenzen.
- Diese Semantik und die Vorbemerkung erteilen keine zusätzlichen System-, Netzwerk- oder Schreibrechte. Laufzeit-Sicherheitsregeln und technische Fehlergates bleiben vorrangig.
"""


class TaskContextError(RuntimeError):
    """Required context is missing, unreadable or too large; never truncate it."""


def normalize_mode(mode: str) -> str:
    if mode not in PREAMBLE_MODES:
        raise ValueError(f"Invalid --todo-preamble {mode!r}; expected {PREAMBLE_MODES}.")
    return mode


def extract_preamble(text: str) -> str:
    """Exact prefix before the first visible Task/Auftrag/DONE/OBSOLETE header.

    Only a leading encoding BOM is removed. Line endings and whitespace stay
    intact; examples and comments follow the scheduler's visibility rules.
    """
    first = next(task_headers(text), None)
    if first is None:
        return ""
    return "".join(text.splitlines(keepends=True)[:first[0]]).removeprefix("\ufeff")


def has_project_text(preamble: str) -> bool:
    for _, line in visible_lines(preamble):
        value = line.strip()
        if not value or re.fullmatch(r"\*\*\*.*\*\*\*", value):
            continue
        if value in ("---", "***", "___"):
            continue
        return True
    return False


def augment_with_preamble(task_text: str, todo_file: Path, *, mode: str = "auto") -> str:
    """Capture live context once; AutoBuild reuses it for review and repair.

    The next central handoff reads the file again, including in a subworkspace.
    Standalone AutoBuild has no implicit ToDo preamble. No referenced files are
    loaded and no hashes or signatures are calculated.
    """
    normalize_mode(mode)
    if mode == "off":
        return task_text
    try:
        prefix = extract_preamble(read_utf8(todo_file, preserve_newlines=True))
    except (OSError, UnicodeError) as exc:
        raise TaskContextError(f"Cannot read ToDo preamble from {todo_file}: {exc}") from exc
    if not has_project_text(prefix):
        if mode == "required":
            raise TaskContextError(f"Project preamble required before the first task: {todo_file}")
        return task_text
    size = len(prefix.encode("utf-8"))
    if size > MAX_PREAMBLE_BYTES:
        raise TaskContextError(
            f"ToDo preamble has {size} UTF-8 bytes (limit {MAX_PREAMBLE_BYTES}). "
            "Shorten it or explicitly select --todo-preamble off; context was NOT truncated."
        )
    # Delimiters label source text; they are not a security boundary.
    return (
        SEMANTICS + "\n"
        f"Projektkontext aus {todo_file.name}; UTF-8-Bytes={size}\n"
        "BEGIN ARQUILO PROJECT PREAMBLE\n" + prefix +
        ("" if prefix.endswith("\n") else "\n") +
        "END ARQUILO PROJECT PREAMBLE\n\n"
        "AKTUELLER EINZELAUFTRAG / KONTROLLAUFTRAG\n" + task_text
    )
