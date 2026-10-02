# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Rejection-only migration errors for retired historical DORA runtime features.

ARQUILO is the active project. None of the predecessor names below enables a
feature; both historical and renamed spellings are rejected.
"""
from __future__ import annotations

import argparse
import os
from typing import Mapping


REMOVED_OPTIONS = frozenset({
    "dora", "no_dora", "audit_dir", "verify_after", "init_workspace_guard",
    "guard_bootstrap_reason", "workspace_guard", "guard_bootstrap",
    "signing_key", "signing_key_path", "private_key", "public_key", "active_key",
    "key_id", "evidence", "evidence_dir", "run_root", "bundle_dir",
})
MIGRATION = (
    "Evidence-, Hash- und Signaturmodus wurde entfernt. Option entfernen; "
    "Laufprotokolle liegen standardmäßig im externen Controller-Verzeichnis; --logs-in-workdir wählt <workdir>/.codex_runs/run_todos/, Ergebnisse weiter im Workspace. "
    "Keine Schlüssel oder Guard-Initialisierung nötig. Allgemeine --runtime-profile "
    "und Codex-Modellprofile bleiben unabhängig davon nutzbar."
)
LOGICIAN_OPTIONS = frozenset({
    "logician", "logician_level", "logician_verify", "logician_verify_level",
    "logician_verify_ledger", "logician_max_concurrency", "logician_max_steps",
    "logician_max_evidence",
})
LOGICIAN_MIGRATION = (
    "Logician samt Ledger-Erzeugung und Nachprüfung wurde entfernt. "
    "Alle Logician-Optionen entfernen, auch off/lite und frühere Limits. "
    "Normale Aufträge, Audits, Pflichtreviews und Korrekturen benötigen keinen Ledger; "
    "bestehende Ledger bleiben historische Workspace-Dateien."
)
REMOVED_POLICY_OPTIONS = frozenset({
    "allow_yolo", "yolo", "dangerously_bypass_approvals_and_sandbox",
    "full_auto", "no_check", "profile", "unsandboxed",
})
POLICY_MIGRATION = (
    "YOLO, Full Access, --full-auto, --no-check und die Sicherheitsprofile dora/dev "
    "sind entfernt. Option entfernen, auch bei false. ARQUILO verwendet höchstens "
    "workspace-write und immer Pflichtreviews; --network-access erweitert nur "
    "die Netzwerkfreigabe. Allgemeine --runtime-profile und Codex-Modellprofile "
    "ändern diese Grenzen nicht. Zugriffsfehler werden ohne Rechteerweiterung gemeldet."
)
ACE_OPTIONS = frozenset({"ace", "ace_mode"})
ACE_ENVIRONMENT = ("AGENT_SYSTEM_ACE_CONTEXT", "AGENT_SYSTEM_ACE_RUN_LOGGING")
ACE_MIGRATION = (
    "ACE mit Playbooks, Reflect/Curate und Laufexport wurde entfernt. "
    "ACE-Optionen und die Umgebungsvariablen AGENT_SYSTEM_ACE_CONTEXT sowie "
    "AGENT_SYSTEM_ACE_RUN_LOGGING entfernen, auch bei off/false/leeren Werten. "
    "Alte Playbooks und ACE-Laufdaten bleiben unangetastet; vollständige "
    "Kernlogs und Pflichtreviews bleiben erhalten."
)
BRIDGE_OPTIONS = frozenset({"openclaw", "openclaw_bridge", "bridge_enabled", "computer_use", "cua"})
BRIDGE_ENVIRONMENT = (
    "DORA_CUA_APPROVE_ALL", "DORA_CUA_APPROVED_ACTIONS",
    "DORA_CUA_PREFLIGHT_HOST_OS_DARWIN", "DORA_CUA_PREFLIGHT_PLAYWRIGHT",
    "DORA_CUA_PREFLIGHT_OSASCRIPT", "DORA_CUA_PREFLIGHT_ACCESSIBILITY",
    "DORA_CUA_PREFLIGHT_AUTOMATION", "DORA_CUA_PREFLIGHT_TESSERACT",
    "DORA_CUA_PREFLIGHT_SCREEN_RECORDING",
)
BRIDGE_MIGRATION = (
    "OpenClaw, Computer-Use und Bridge-Verarbeitung wurden entfernt. "
    "--openclaw-bridge, Python-/Worker-bridge_enabled, zugehörige CFG-/Profilfelder "
    "und DORA_CUA_*-Umgebungsvariablen entfernen, auch bei false/null/leeren Werten. "
    "WAIT on=bridge:… ist entfallen; Abhängigkeiten im Auftrag anpassen. "
    "Allgemeine WAIT-Bedingungen todo:/group:/agent:, STOP und process_stop bleiben "
    "erhalten. Bestehende .bridge/-Daten bleiben unangetastet."
)
IACT_OPTIONS = frozenset({
    "iact", "iact_enabled", "iact_lite", "iact_limits", "iact_retention_runs",
    "iact_max_events", "iact_max_log_bytes", "iact_max_tree_bytes",
})
# The retired exporter had no environment reader. Reserve the corresponding
# DORA names as migration errors too, so config wrappers cannot silently opt in.
IACT_ENVIRONMENT = (
    "DORA_IACT", "DORA_IACT_ENABLED", "DORA_IACT_RETENTION_RUNS",
    "DORA_IACT_MAX_EVENTS", "DORA_IACT_MAX_LOG_BYTES", "DORA_IACT_MAX_TREE_BYTES",
)
IACT_MIGRATION = (
    "IACT-Baum-/Event-Export einschließlich Retention, Größenlimits und Phase-3-DoD "
    "wurde entfernt. --iact, alle --iact-…-Grenzen und zugehörige Python-/Worker-/"
    "CFG-/Profil-/DORA_IACT*-Eingaben entfernen, auch bei false/null/0/leeren Werten. "
    "Alte IACT-Daten bleiben unangetastet; vollständige Kernlogs, Tasklogs, "
    "Decide-Archive und Pflichtreviews bleiben erhalten."
)
SERVICE_OPTIONS = frozenset({
    "queue", "queue_state", "prometheus_port", "poll_interval", "max_jobs",
})
# The retired services did not read ENV themselves. Reject these corresponding
# wrapper names explicitly, just as for the removed IACT options.
SERVICE_ENVIRONMENT = ("DORA_QUEUE_STATE", "DORA_PROMETHEUS_PORT")
SERVICE_MIGRATION = (
    "AutoBuild-Queue und HTTP-/Prometheus-Dienste wurden entfernt. "
    "queue-Unterbefehle, --queue-state, --prometheus-port und zugehörige "
    "Python-/Worker-/CFG-/Profil-/ENV-Eingaben entfernen, auch bei false/null/0. "
    "Vorhandene Queuezustände bleiben unangetastet. autobuild.start, Standalone-"
    "AutoBuild und Python-Worker für Parallel-CFG bleiben mit Pflichtreviews, "
    "vollständigen Logs und gemeinsamen Aufrufbudgets erhalten."
)


def reject_bridge_wait_conditions(expression: str) -> None:
    if any(part.strip().lower().startswith("bridge:") for part in expression.split(",")):
        raise ValueError(f"WAIT on=bridge: ist entfernt. {BRIDGE_MIGRATION}")


def check_removed_environment(env: Mapping[str, str] | None = None) -> None:
    environment = os.environ if env is None else env
    # Normalize only removed-feature lookups; never mutate the caller environment.
    environment = dict(environment) | {
        "DORA_" + key[len("ARQUILO_"):]: value
        for key, value in environment.items() if key.startswith("ARQUILO_")
    }
    for keys, migration in ((ACE_ENVIRONMENT, ACE_MIGRATION), (BRIDGE_ENVIRONMENT, BRIDGE_MIGRATION),
                            (IACT_ENVIRONMENT, IACT_MIGRATION),
                            (SERVICE_ENVIRONMENT, SERVICE_MIGRATION)):
        for key in keys:
            if key in environment:
                raise ValueError(f"Umgebung: {key} ist entfernt. {migration}")


def migration_for(key: str) -> str | None:
    normalized = key.lstrip("-").replace("-", "_").lower().split(".", 1)[0]
    if normalized.startswith("arquilo_"):
        normalized = "dora_" + normalized[len("arquilo_"):]
    if normalized in ACE_OPTIONS or normalized.upper() in ACE_ENVIRONMENT:
        return ACE_MIGRATION
    if normalized in BRIDGE_OPTIONS or normalized.upper() in BRIDGE_ENVIRONMENT:
        return BRIDGE_MIGRATION
    if normalized in IACT_OPTIONS or normalized.upper() in IACT_ENVIRONMENT:
        return IACT_MIGRATION
    if normalized in SERVICE_OPTIONS or normalized.upper() in SERVICE_ENVIRONMENT:
        return SERVICE_MIGRATION
    if normalized in REMOVED_POLICY_OPTIONS:
        return POLICY_MIGRATION
    if normalized in LOGICIAN_OPTIONS:
        return LOGICIAN_MIGRATION
    if normalized in REMOVED_OPTIONS:
        return MIGRATION
    return None


def reject_removed_options(values: Mapping[str, object], *, source: str) -> None:
    for key in values:
        migration = migration_for(key)
        if migration:
            raise ValueError(f"{source}: {key} ist entfernt. {migration}")
        raise TypeError(f"{source}: unbekannter Parameter {key!r}")


def check_removed_fields(values: Mapping[str, object], *, source: str) -> None:
    for key in values:
        migration = migration_for(key)
        if migration:
            raise ValueError(f"{source}: {key} ist entfernt. {migration}")


class RemovedArgument(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parser.error(f"{option_string} ist entfernt. {migration_for(option_string)}")


def add_removed_arguments(parser: argparse.ArgumentParser) -> None:
    # Hidden diagnostic stubs never store values or activate historical modes.
    parser.add_argument("--ace-mode", nargs="?", action=RemovedArgument, help=argparse.SUPPRESS)
    parser.add_argument("--openclaw-bridge", nargs="?", action=RemovedArgument, help=argparse.SUPPRESS)
    for name in ("queue-state", "prometheus-port", "poll-interval", "max-jobs"):
        parser.add_argument("--" + name, nargs="?", action=RemovedArgument, help=argparse.SUPPRESS)
    for name in ("iact", "iact-retention-runs", "iact-max-events", "iact-max-log-bytes", "iact-max-tree-bytes"):
        parser.add_argument("--" + name, nargs="?", action=RemovedArgument, help=argparse.SUPPRESS)
    for name in ("dora", "no-dora", "verify-after", "init-workspace-guard"):
        parser.add_argument("--" + name, nargs=0, action=RemovedArgument, help=argparse.SUPPRESS)
    for name in ("audit-dir", "guard-bootstrap-reason", "profile"):
        parser.add_argument("--" + name, action=RemovedArgument, help=argparse.SUPPRESS)
    for name in sorted(LOGICIAN_OPTIONS):
        parser.add_argument("--" + name.replace("_", "-"), nargs="?",
                            action=RemovedArgument, help=argparse.SUPPRESS)
    for name in sorted(REMOVED_POLICY_OPTIONS - {"profile"}):
        parser.add_argument("--" + name.replace("_", "-"), nargs="?",
                            action=RemovedArgument, help=argparse.SUPPRESS)
