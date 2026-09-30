# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Build a licensed ARQUILO runtime ZIP and SHA-256 sidecar (standard library)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.stage_lean import zip_package
from scripts.check_release import check_release


def build_distribution(destination: Path, *, source: Path = ROOT) -> dict:
    """Refuse existing outputs; a checksum is integrity metadata, not a signature."""
    source = source.resolve()
    check_release(source)
    destination = destination.absolute()
    if destination.suffix.lower() != ".zip":
        raise ValueError("Destination must end in .zip")
    checksum = destination.with_name(destination.name + ".sha256")
    for path in (destination, checksum):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {path}")
    result = zip_package(destination, source=source)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Exclusive sidecar creation also protects against a concurrent builder.
    # Keep the valid ZIP if writing the sidecar fails; never remove someone else's file.
    with checksum.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{digest}  {destination.name}\n")
    return result | {"project": "ARQUILO", "sha256": digest, "checksum": str(checksum)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("destination", nargs="?", type=Path,
                        help="New ZIP path; default: dist/arquilo-VERSION.zip in the source tree")
    args = parser.parse_args(argv)
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        destination = args.destination or ROOT / "dist" / f"arquilo-{version}.zip"
        result = build_distribution(destination)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        print(json.dumps({"status": "FAIL", "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
