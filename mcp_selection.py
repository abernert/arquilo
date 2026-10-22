# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Per-process MCP selection; native config inventory, never global config writes.

Inventory may access configuration, keyrings and HTTP auth discovery. It does
not initialize STDIO tools or make model calls. Raw inventory can contain
credentials, so it must never be archived, printed or included in exceptions.
"""
from __future__ import annotations
import json
from task_resources import ResourceError, selection

# Native integrations outside the direct mcp_servers table must not silently
# enter an explicit allowlist. Existing behavior is untouched without a list.
class McpInventoryCancelled(RuntimeError):
    """Operator stop while inspecting configuration, before any model call."""


ISOLATION_CONFIG = ("features.plugins=false", "features.apps=false")


def parse_inventory(raw: bytes | str) -> dict[str, bool]:
    try:
        if len(raw) > 2_097_152:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, list) or len(data) > 256:
            raise ValueError()
        result = {}
        for item in data:
            if not isinstance(item, dict):
                raise ValueError()
            name = item.get("name")
            values = selection([name])
            if len(values) != 1 or name in result or type(item.get("enabled")) is not bool:
                raise ValueError()
            # Only direct STDIO/HTTP servers are supported in the first adapter.
            transport = item.get("transport")
            if not isinstance(transport, dict) or transport.get("type") not in {"stdio", "streamable_http"}:
                raise ValueError()
            result[name] = item["enabled"] and not item.get("disabled_reason")
        return result
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ResourceError("Cannot validate Codex MCP inventory. No model call started; inspect Codex mcp list locally. Inventory output was withheld.") from None


def config_values(selected, inventory) -> tuple[str, ...]:
    selected = selection(selected)
    if selected is None:
        return ()
    names = selection(tuple(inventory))
    # Codex CLI keys use a literal dot-separated path, not TOML key quoting.
    # A dot inside a server ID cannot be addressed without replacing transport
    # configuration; refuse instead of creating a different accidental server.
    if any("." in name for name in (*selected, *(names or ()))):
        raise ResourceError("Explicit MCP selection requires server IDs without dots; rename the local config alias. No model call started.")
    values = list(ISOLATION_CONFIG)
    for name in sorted(set(names or ()) | set(selected)):
        prefix = "mcp_servers." + name
        enabled = name in selected
        values.append(prefix + ".enabled=" + str(enabled).lower())
        # Required servers must initialize; a missing service cannot be ignored.
        values.append(prefix + ".required=" + str(enabled).lower())
    return tuple(values)


def inventory_arguments(*, profile=None, values=()) -> list[str]:
    # Native profile files apply at the root CLI, before the MCP subcommand.
    args = ["--profile", profile] if profile is not None else []
    args.extend(["mcp", "list", "--json"])
    for value in (*ISOLATION_CONFIG, *values):
        args.extend(["-c", value])
    return args


def resolve_inventory(selected, *, profile, probe) -> tuple[str, ...]:
    """Two native config reads: discover then verify the exact effective subset.

    The callback uses the existing owned process-start/cleanup boundary.
    Disabled or policy-denied services are never re-enabled by a task list.
    """
    selected = selection(selected)
    if selected is None:
        return ()
    before = parse_inventory(probe(inventory_arguments(profile=profile)))
    denied = [name for name in selected if before.get(name) is not True]
    if denied:
        raise ResourceError("MCP servers missing, disabled or policy-denied: " + ", ".join(denied))
    values = config_values(selected, before)
    after = parse_inventory(probe(inventory_arguments(profile=profile, values=values)))
    active = {name for name, enabled in after.items() if enabled}
    if active != set(selected) or set(after) != set(before):
        raise ResourceError("Codex did not honor the exclusive MCP selection, or configuration changed. No model call started.")
    return tuple(sorted(before))
