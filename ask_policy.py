# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Fixed evidence-only Ask restrictions; never generated from model output."""
from __future__ import annotations

# These restrict only the new evidence-only path. Production/review/Decide stay unchanged.
# Shell/MCP/feature metadata is checked before the model call. This is still not
# a substitute for host/OS isolation against a hostile same-user process.
ASK_CONFIG = (
    'web_search="disabled"', 'notify=[]',
    'features.shell_tool=false', 'features.unified_exec=false',
    'features.shell_snapshot=false', 'features.hooks=false', 'features.codex_hooks=false',
    'features.apps=false', 'features.multi_agent=false', 'features.memories=false',
    'features.remote_plugin=false', 'features.skill_mcp_dependency_install=false',
    'features.goals=false', 'features.js_repl=false', 'features.apply_patch_freeform=false',
)


def config_arguments() -> list[str]:
    return [part for value in ASK_CONFIG for part in ("-c", value)]


def validate_metadata(features: str, mcp: object) -> None:
    states = {}
    for line in features.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] in {"true", "false"}:
            if parts[0] in states:
                raise ValueError("Ambiguous Ask feature metadata")
            states[parts[0]] = parts[-1] == "true"
    for key in ("shell_tool", "unified_exec", "multi_agent"):
        if states.get(key) is not False:
            raise ValueError(f"Cannot verify disabled Codex {key}; evidence-only Ask was not started")
    for key in ("shell_snapshot", "hooks", "codex_hooks", "apps", "memories", "remote_plugin",
                "skill_mcp_dependency_install", "goals", "js_repl", "apply_patch_freeform"):
        if states.get(key) is True:
            raise ValueError(f"Codex {key} is still enabled; evidence-only Ask was not started")
    if not isinstance(mcp, list) or any(not isinstance(item, dict) or item.get("enabled", True) is not False for item in mcp):
        raise ValueError("Ask requires no enabled MCP servers. Use an owner-configured restricted Codex home/profile; no settings were changed.")
