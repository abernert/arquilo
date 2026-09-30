# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Offline public-distribution checks; no network, credentials or model calls."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.stage_lean import package_files
from scripts.check_naming import check_naming


def check_release(source: Path = ROOT) -> dict:
    source = source.resolve()
    names = package_files(source)
    check_naming(source, names)
    required = {"LICENSE", "NOTICE", "VERSION", "README.md", "arquilo.py", "arquilo_doctor.py", "SECURITY.md"}
    if not required.issubset(names):
        raise ValueError("Missing required distribution files: " + ", ".join(sorted(required - set(names))))
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"0\.\d+\.\d+|[1-9]\d*\.\d+\.\d+", version):
        raise ValueError("VERSION must use major.minor.patch")
    tree = ast.parse((source / "runtime_profile.py").read_text(encoding="utf-8"))
    runtime_versions = [ast.literal_eval(node.value) for node in tree.body
                        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
                        and t.id == "ARQUILO_RUNTIME_VERSION" for t in node.targets)]
    if runtime_versions != [version]:
        raise ValueError("VERSION and runtime version disagree")
    citation = (source / "CITATION.cff").read_text(encoding="utf-8")
    if f'version: "{version}"' not in citation:
        raise ValueError("CITATION.cff version disagrees")
    license_text = (source / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
        raise ValueError("Apache-2.0 license text is missing")
    if "Copyright 2026 Alexander Bernert" not in (source / "NOTICE").read_text(encoding="utf-8"):
        raise ValueError("NOTICE is missing project attribution")
    code_count = 0
    for name in names:
        p = Path(name)
        if any(part in {".git", ".codex", ".codex_runs", ".local-work", "var", "var2", "tests", ".github"} for part in p.parts):
            raise ValueError("Private/development data selected for distribution: " + name)
        if p.suffix == ".py":
            text = (source / name).read_text(encoding="utf-8")
            ast.parse(text, filename=name)
            if "SPDX-License-Identifier: Apache-2.0" not in text[:300]:
                raise ValueError("Missing SPDX header: " + name)
            code_count += 1
    # Check relative document targets, not external availability or fragment IDs.
    bad_links = []
    for name in names:
        if not name.endswith(".md"):
            continue
        path = source / name
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"(?<!!)\[[^]\n]*\]\(([^)\s]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(source) or not destination.exists():
                bad_links.append(f"{name}: {target}")
    if bad_links:
        raise ValueError("Broken local links: " + "; ".join(bad_links))
    return {"status": "PASS", "version": version, "runtime_files": len(names),
            "python_files": code_count, "checks": ["allowlist", "license", "attribution",
            "version", "python_syntax", "headers", "local_document_links", "active_naming"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = check_release(args.source)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        print(json.dumps({"status": "FAIL", "message": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
