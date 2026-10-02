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


# Decide deliberately inherits trusted Codex configuration. No model/provider,
# authentication, proxy, certificate, feature, or transport defaults live here.
# The read-only/never pair prevents broadening the filesystem sandbox through a
# configured default. Tool events still invalidate a decision; this is NOT a
# pre-tool authorization hook. See docs/decide-configuration.md.
DECISION_CONFIG = ('approval_policy="never"',)
DECISION_REQUIRED_EXEC_FLAGS = (
    "--json", "--output-schema", "--output-last-message", "--skip-git-repo-check",
    "--sandbox", "--config",
)


def decision_arguments(*, network_access: bool, config_profile: str | None,
                       extra_args: Sequence[str]) -> list[str]:
    """Minimal protocol/sandbox policy; leave provider configuration to Codex."""
    if network_access is not False or extra_args:
        raise CodexPolicyError("Decide does not accept extra arguments or a shell network grant.")
    validate_config_profile(config_profile)
    return ["--sandbox", "read-only", "-c", DECISION_CONFIG[0]]


def validate_model_provider(value: str | None) -> str | None:
    """Only a named provider selection, never a URL, token or config fragment."""
    if value is not None and (not isinstance(value, str) or
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value)):
        raise CodexPolicyError("model_provider must be a configured provider ID, not a URL or credentials.")
    return value


def decision_required_flags(*, model: str | None = None,
                            config_profile: str | None = None) -> tuple[str, ...]:
    return DECISION_REQUIRED_EXEC_FLAGS + (("--model",) if model is not None else ()) + (
        ("--profile",) if config_profile is not None else ())


def exec_help_flags(text: str) -> set[str]:
    """Parse flag names only; never expose arbitrary help or configuration text."""
    return set(re.findall(r"^\s*(?:-[A-Za-z],\s*)?(--[a-z-]+)(?=\s|$)", text, re.MULTILINE))


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
        "logs_in_workdir", "allow_todo_modifications", "max_calls",
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
