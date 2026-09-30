# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Prevent the historical DORA name from returning as active ARQUILO branding."""
from __future__ import annotations
import os
from pathlib import Path
import re
from typing import Iterable

# These files are explicitly historical or exercise historical input compatibility.
HISTORY_ONLY = frozenset({
    'NOTICE', 'CHANGELOG.md', 'docs/compatibility.md',
    'documents/HISTORICAL_MIGRATION.md', 'legacy_naming.py', 'removed_features.py',
    'scripts/check_naming.py', 'tests/test_naming.py',
})
FORMER_NAME = re.compile(r'(?<![a-z0-9])dora(?![a-z0-9])', re.IGNORECASE)
TEXT_SUFFIXES = {'.py', '.md', '.json', '.txt', '.yml', '.yaml', '.cff'}
SKIP_DIRS = {'.git', '.codex', '.codex_runs', '.local-work', '.venv', 'venv',
             '__pycache__', 'dist', 'build', 'var', 'node_modules'}


def source_paths(source: Path) -> Iterable[str]:
    """Inspect source only; do not open user workspaces or generated archives."""
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not re.fullmatch(r'var\d+', d)
                   and not (Path(directory) / d).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.suffix in TEXT_SUFFIXES or name == 'NOTICE':
                yield path.relative_to(source).as_posix()


def check_naming(source: Path, names: Iterable[str] | None = None) -> None:
    source = source.resolve()
    findings = []
    for name in source_paths(source) if names is None else names:
        if FORMER_NAME.search(name):
            findings.append(f'{name}: historical name in an active file path')
        if name in HISTORY_ONLY:
            continue
        path = source / name
        if path.suffix not in TEXT_SUFFIXES and name != 'NOTICE':
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not FORMER_NAME.search(line):
                continue
            if (name == 'codex_policy.py' and
                    '# historical-name: retired security profiles' in line):
                continue  # Literal predecessor profile name remains rejection-only.
            findings.append(f'{name}:{number}: historical name used outside history/compatibility')
    if findings:
        raise ValueError('Active naming regression: ' + '; '.join(findings))
