# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Invocation policy shared by the ARQUILO starters and Codex transport.

No environment or configuration is read here. The caller grants shell network
access explicitly; task configuration can only narrow that grant. Codex config
profiles remain useful for model/tool settings but never supply sandbox policy.
"""
from __future__ import annotations

import json
import re
from removed_features import POLICY_MIGRATION, check_removed_fields
from typing import Mapping, Sequence


class CodexPolicyError(ValueError):
    """An invocation requests authority outside ARQUILO's fixed boundary."""


# Fixed execution restrictions, independent of the CLI version string. The
# Doctor can exercise the full Decide contract with the installed CLI.
DECISION_DISABLED_FEATURES = (
    "shell_tool", "shell_snapshot", "multi_agent", "multi_agent_v2",
    "apps", "plugins", "remote_plugin", "skill_search", "skill_mcp_dependency_install",
    "hooks", "memories", "computer_use", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "image_generation", "view_image", "code_mode",
    "code_mode_host", "artifact", "goals", "tool_suggest", "sleep_tool",
    "workspace_dependencies", "daemon_auto_start",
)
DECISION_CONFIG = (
    'web_search="disabled"', "project_doc_max_bytes=0", "notify=[]",
    "suppress_unstable_features_warning=true",
    "features.skip_host_skill_discovery=true",
    *(f"features.{name}=false" for name in DECISION_DISABLED_FEATURES),
)


# Only explicitly reviewed, additive features may be absent. Never treat a
# missing security control as disabled merely because introspection omitted it.
# daemon_auto_start is absent in upstream rust-v0.154.0 and present in newer CLIs.
DECISION_OPTIONAL_FEATURES = frozenset({"daemon_auto_start"})
DECISION_EXPECTED_FEATURES = {
    **{name: False for name in DECISION_DISABLED_FEATURES},
    "skip_host_skill_discovery": True,
}
_FEATURE_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")


def parse_feature_catalog(text: str) -> dict[str, bool]:
    """Read Codex's name/stage/bool table without accepting ambiguous evidence.

    Stages may contain spaces (e.g. 'under development'). Unknown well-formed
    feature names are metadata, not new permission grants. Error messages never
    echo raw CLI output or configuration values.
    """
    features: dict[str, bool] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if (len(parts) < 3 or not _FEATURE_NAME.fullmatch(parts[0])
                or parts[-1] not in {"true", "false"}):
            raise CodexPolicyError(f"Malformed Codex feature table at line {number}.")
        if parts[0] in features:
            raise CodexPolicyError(f"Duplicate Codex feature entry at line {number}.")
        features[parts[0]] = parts[-1] == "true"
    if not features:
        raise CodexPolicyError("Codex returned an empty feature table.")
    return features


def select_decision_features(catalog: Mapping[str, bool]) -> tuple[str, ...]:
    """Select supported restrictions; only reviewed optional absences are valid."""
    missing = sorted(set(DECISION_EXPECTED_FEATURES) - set(catalog) - DECISION_OPTIONAL_FEATURES)
    if missing:
        raise CodexPolicyError("Required Decide features unavailable: " + ", ".join(missing))
    return tuple(name for name in DECISION_EXPECTED_FEATURES if name in catalog)


def decision_config_for_features(features: Sequence[str] | None = None) -> tuple[str, ...]:
    """Build only fixed ARQUILO settings, never CLI-supplied keys or values.

    None retains the full conservative policy for legacy pure-builder callers.
    Runtime execution always discovers and verifies capabilities afresh.
    """
    if features is None:
        features = tuple(DECISION_EXPECTED_FEATURES)
    if isinstance(features, str) or any(not isinstance(name, str) for name in features):
        raise CodexPolicyError("Decide feature selection must contain feature names.")
    selected = set(features)
    if len(selected) != len(features) or selected - set(DECISION_EXPECTED_FEATURES):
        raise CodexPolicyError("Invalid Decide feature selection.")
    select_decision_features({name: False for name in selected})
    # A single TOML table instead of a long series of per-feature switches.
    # These values concern tools only, never models/providers/endpoints/auth.
    controls = ", ".join(
        f"{name}={str(expected).lower()}"
        for name, expected in DECISION_EXPECTED_FEATURES.items() if name in selected
    )
    return tuple(value for value in DECISION_CONFIG if not value.startswith("features.")) + (
        "features={" + controls + "}",
    )


def decision_feature_details(catalog: Mapping[str, bool],
                             effective: Mapping[str, bool] | None = None) -> dict[str, dict]:
    """Safe, bounded diagnostics for known controls only."""
    details = {}
    for name, expected in DECISION_EXPECTED_FEATURES.items():
        present = name in catalog
        if not present:
            status = "unavailable_optional" if name in DECISION_OPTIONAL_FEATURES else "missing_required"
            if effective is not None and name in effective:
                status = "catalog_changed"
        elif effective is None:
            status = "pending_verification"
        elif name not in effective:
            status = "not_confirmed"
        else:
            status = "verified" if effective[name] is expected else "wrong_value"
        details[name] = {"status": status, "required": name not in DECISION_OPTIONAL_FEATURES,
                         "expected": expected, "available": present,
                         "observed": effective.get(name) if effective is not None else None}
    return details


def decision_arguments(*, network_access: bool, config_profile: str | None,
                       extra_args: Sequence[str],
                       features: Sequence[str] | None = None) -> list[str]:
    """Inherit trusted Codex configuration; restrict only execution/tool scope.

    No routing override, user-config suppression, strict-config mode or rules
    suppression. Configured corporate routing/authentication remains Codex-owned.
    """
    if network_access is not False or config_profile is not None or extra_args:
        raise CodexPolicyError("Decide requires network_access=False, no profile and no extra_args.")
    return ["--ephemeral",
            *(arg for value in decision_config_for_features(features) for arg in ("-c", value))]


def decision_event_violation(event: object) -> str | None:
    """Closed JSONL vocabulary: unknown items/events cannot certify a decision.

    This is an acceptance gate, not an OS read sandbox or a pre-tool hook.
    Inspect started/updated/completed items, including tails after completion.
    """
    if not isinstance(event, dict):
        return "Decision event is not an object"
    kind = event.get("type")
    if not isinstance(kind, str):
        return "Decision event type is not a string"
    if kind in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}:
        return None
    if kind in {"item.started", "item.updated", "item.completed"}:
        item = event.get("item")
        if not isinstance(item, dict):
            return "Decision item is not an object"
        labels = [item[key] for key in ("type", "item_type", "kind") if key in item]
        if (labels and all(isinstance(label, str) for label in labels)
                and len(set(labels)) == 1
                and labels[0] in {"agent_message", "assistant_message", "reasoning","error",}):
            return None
        return "Forbidden or unknown decision item: " + repr(labels)
    return "Forbidden or unknown decision event: " + repr(kind)


def parse_decision_event(line: str) -> object:
    """Reject ambiguous event types instead of losing keys during JSON parsing."""
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate key in decision event")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-JSON number in decision event")

    return json.loads(line, object_pairs_hook=pairs, parse_constant=constant)


def validate_network_access(value: bool) -> bool:
    if type(value) is not bool:
        raise CodexPolicyError("network_access muss bool sein; Freigabe nur mit --network-access.")
    return value


def validate_sandbox(value: str | None, *, starter: bool = False) -> str:
    allowed = ("workspace-write",) if starter else ("workspace-write", "read-only")
    if value not in allowed:
        raise CodexPolicyError(
            "ARQUILO startet fest mit workspace-write; unsandboxed, danger-full-access "
            "und fehlende Sandbox sind nicht erlaubt. Nur interne Leseaufrufe dürfen read-only verwenden."
        )
    return value


def validate_start_policy(*, sandbox: str | None, network_access: bool,
                          allow_read_only: bool = False) -> None:
    validate_sandbox(sandbox, starter=not allow_read_only)
    validate_network_access(network_access)


def validate_launcher(values: Sequence[str]) -> tuple[str, ...]:
    # codex_launcher resolves this one name at the process-start boundary.
    # Prefix arguments would be a second, unchecked Codex option channel.
    if (isinstance(values, str) or not isinstance(values, (list, tuple)) or len(values) != 1
            or not isinstance(values[0], str) or not values[0] or "\0" in values[0]
            or values[0].startswith("-")):
        raise CodexPolicyError("launcher muss genau eine ausführbare Datei ohne Zusatzargumente enthalten.")
    return tuple(values)


def validate_config_profile(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str)
                              or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value)
                              or ".." in value):
        raise CodexPolicyError("Codex-Profil muss ein einfacher Profilname ohne Pfad oder Optionen sein.")
    if value is not None and value.lower().replace("_", "-") in {
        "dora", "dev", "yolo", "unsandboxed", "danger-full-access", "full-access",  # historical-name: retired security profiles
    }:
        raise CodexPolicyError(f"Codex-Profil {value!r} ist ein entfernter Sicherheitsprofilname. {POLICY_MIGRATION}")
    return value


def validate_extra_args(values: Sequence[str] | None) -> tuple[str, ...]:
    """Allow presentation/session options and the existing separate web tool switch.

    In particular there are no arbitrary -c/--config values, profile selections,
    positional arguments, sandbox switches, additional roots or cwd overrides.
    """
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise CodexPolicyError("extra_args muss eine Argumentliste sein.")
    result: list[str] = []
    index = 0
    while index < len(values):
        arg = values[index]
        if not isinstance(arg, str) or "\0" in arg:
            raise CodexPolicyError("Ungültiges Codex-Zusatzargument.")
        if arg in {"--skip-git-repo-check", "--ephemeral"}:
            result.append(arg)
        elif arg == "--color" and index + 1 < len(values) and values[index + 1] in ("auto", "always", "never"):
            result.extend(values[index:index + 2])
            index += 1
        elif arg == "-c" and index + 1 < len(values) and values[index + 1] in (
            'web_search="disabled"', 'web_search="cached"', 'web_search="live"',
        ):
            result.extend(values[index:index + 2])
            index += 1
        else:
            raise CodexPolicyError(
                f"Codex-Zusatzargument {arg!r} ist nicht freigegeben. Erlaubt: "
                "--skip-git-repo-check, --ephemeral, --color auto|always|never, "
                '-c web_search="disabled|cached|live". Netzwerk nur mit --network-access.'
            )
        index += 1
    return tuple(result)


def effective_network_access(granted: bool, configured: str | None = None) -> bool:
    validate_network_access(granted)
    if configured is None:
        return granted
    if not isinstance(configured, str) or configured.strip().lower() not in {"true", "false"}:
        raise CodexPolicyError("CFG network_access muss true oder false sein.")
    requested = configured.strip().lower() == "true"
    if requested and not granted:
        raise CodexPolicyError("CFG network_access=true benötigt die explizite Starterfreigabe --network-access.")
    return requested


def reject_policy_keys(values: Mapping[str, object], *, source: str) -> None:
    """Reject misleading policy fields instead of silently ignoring them."""
    try:
        check_removed_fields(values, source=source)
    except ValueError as exc:
        raise CodexPolicyError(str(exc)) from exc
    forbidden = {
        "sandbox", "sandbox_mode", "sandbox_workspace_write", "writable_roots", "add_dir",
        "allow_yolo", "yolo", "full_auto", "approval_policy", "approvals_reviewer",
        "extra_arg", "extra_args", "profile", "codex", "codex_args", "config", "cd",
        "permissions", "default_permissions",
        "ask_for_approval", "approve_for_me", "sandbox_permissions",
        "skip_review", "no_review", "skip_checks", "review_required",
    }
    for key in values:
        normalized = key.replace("-", "_").lower().split(".", 1)[0]
        if normalized in forbidden or (source.startswith("Runtime-Profil") and normalized == "network_access"):
            raise CodexPolicyError(f"{source}: {key} darf die zentrale Codex-Aufrufpolicy nicht konfigurieren.")


def sandbox_arguments(*, sandbox: str, network_access: bool) -> list[str]:
    validate_sandbox(sandbox)
    validate_network_access(network_access)
    return [
        "--sandbox", sandbox,
        "--ignore-rules",
        "-c", 'approval_policy="never"',
        "-c", f"sandbox_workspace_write.network_access={str(network_access).lower()}",
        "-c", "sandbox_workspace_write.writable_roots=[]",
        "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
    ]


def decision_sandbox_arguments() -> list[str]:
    """No writes or approval escalation, without workspace-write-only settings."""
    return ["--sandbox", "read-only", "-c", 'approval_policy="never"']


def decision_mcp_config(names: Sequence[str]) -> tuple[str, ...]:
    """Disable configured MCP servers, without copying URLs/commands/secrets.

    An empty table would only merge with (not clear) the user's configured map.
    Server names come from Codex's own metadata resolver, not a second TOML
    configuration loader. Quoted TOML keys keep names literal.
    """
    if isinstance(names, str) or len(names) > 1024:
        raise CodexPolicyError("Invalid Decide MCP selection")
    for name in names:
        if (not isinstance(name, str) or not name or len(name) > 256
                or any(ord(c) < 32 for c in name)):
            raise CodexPolicyError("Invalid Decide MCP name")
    if len(set(names)) != len(names):
        raise CodexPolicyError("Duplicate Decide MCP name")
    if not names:
        return ()
    return ("mcp_servers={" + ", ".join(
        json.dumps(name, ensure_ascii=False) + "={enabled=false}"
        for name in sorted(names)
    ) + "}",)
