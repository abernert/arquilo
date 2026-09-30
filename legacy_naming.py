# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Input-only compatibility for the historical DORA project name.

ARQUILO is the active name. These aliases do not enable features or relax
validation. New output always uses the canonical arquilo.* schema namespace.
No environment or file content is read at import time.
"""
from __future__ import annotations
import warnings


def historical_environment_aliases(name: str) -> tuple[str, ...]:
    """Return the predecessor spelling for an active ARQUILO setting."""
    if not name.startswith("ARQUILO_"):
        return ()
    return ("DORA_" + name[len("ARQUILO_"):],)


def schema_matches(value: object, expected: str) -> bool:
    """Accept only the exact current schema or its same-version historical name."""
    if not isinstance(value, str):
        return False
    if value == expected:
        return True
    if expected.startswith("arquilo.") and value == "dora." + expected[len("arquilo."):]:
        warnings.warn(f"Historical schema {value!r} is deprecated; use {expected!r}.",
                      FutureWarning, stacklevel=2)
        return True
    return False
