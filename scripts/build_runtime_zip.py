# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""DORA-Runtime mit Doctor und Dokumentation als ZIP für ein neues Repo exportieren."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.stage_lean import ROOT, main as stage_main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "destination", nargs="?", type=Path, default=ROOT / "dist" / "dora-lean.zip",
        help="Neues ZIP; Standard: dist/dora-lean.zip im Quellordner. "
             "Relative Zielpfade gelten ab dem aktuellen Arbeitsverzeichnis.",
    )
    args = parser.parse_args(argv)
    # Share the allowlist, validation, reproducibility and overwrite protection
    # with the existing exporter, including when run from the extracted ZIP.
    return stage_main([str(args.destination), "--zip"])


if __name__ == "__main__":
    raise SystemExit(main())
