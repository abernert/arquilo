# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Durable Decide manifests without environment/configuration dumps or hashes.

Raw captures stay where the shared transport wrote them, inside each attempt.
Missing/partial outputs are described, never synthesized from a prior answer.
The archive is sensitive: inputs, responses and raw streams are unredacted.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import stat

import codex_policy
from runtime_contracts import DecisionResult
from runtime_files import atomic_write_text


def timestamp() -> str:
    return datetime.now().astimezone().isoformat()


def write_json(path: Path, value: dict) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n")


def file_state(path: Path, directory: Path) -> dict:
    """Do not follow links or open special output files for a manifest."""
    entry = {"path": str(path.relative_to(directory))}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return entry | {"state": "absent"}
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        return entry | {"state": "not_regular"}
    return entry | {"state": "present", "bytes": info.st_size}


def initial_manifest(request, settings, *, decision_id: str, number: int,
                     retry_of: str | None, retry_reason: str | None) -> dict:
    """Only deliberately selected, non-secret host settings are recorded."""
    from codex_transport import TransportTimeouts

    return {
        "schema_version": "arquilo.decision_attempt.v2",
        "identity": {"run_id": request.run_id, "task_id": request.task_id,
                     "phase": request.phase, "input_attempt_id": request.attempt_id,
                     "decision_id": decision_id, "attempt_number": number},
        "started_at": timestamp(), "finished_at": None,
        "status": "preparing", "archive_complete": False,
        "retry": {"max_attempts": settings.max_attempts, "retry_of": retry_of,
                  "reason": retry_reason, "scheduled": False,
                  "policy": "only decision_invalid_response after successful execution; at most one replay"},
        "settings": {
            "model": request.model, "reasoning_effort": request.reasoning_effort,
            "max_input_bytes": request.max_input_bytes,
            "timeouts": asdict(settings.timeouts or TransportTimeouts(total=120)),
            "sandbox": "read-only", "network_access": False,
            "model_provider": settings.model_provider, "config_profile": settings.config_profile,
            "configuration_policy": "inherit-trusted-host",
            "enforced_cli_arguments": None,
            "requested_policy_arguments": codex_policy.decision_arguments(
                network_access=False, config_profile=settings.config_profile, extra_args=()),
            "environment": "trusted host environment inherited; values are not archived",
            "auth": "Codex configuration/CODEX_HOME inherited; credentials not read or copied",
        },
        "cli_version": None, "cwd": None,
        "cleanup_policy": "retain workdir; explicit cleanup only after all attempts are archived",
        "artifacts": {}, "result": None,
    }


def finish_manifest(manifest: dict, *, directory: Path, result: DecisionResult,
                    attempt, retry_scheduled: bool) -> dict:
    """Verify retained captures before committing a terminal attempt manifest.

    An execution error can have a complete archive of its partial outputs.
    A capture I/O error cannot certify a complete archive, even if the model
    happened to provide a valid answer. The caller preserves both results.
    """
    artifacts = {name: file_state(directory / filename, directory) for name, filename in (
        ("input", "input.json"), ("prompt", "prompt.md"), ("schema", "schema.json"),
        ("response", "response.json"), ("events", "events.jsonl"), ("pretty", "pretty.log"))}
    for name in ("input", "prompt", "schema"):
        if artifacts[name]["state"] != "present":
            raise OSError(f"Required decision artifact is missing or not regular: {name}")
    capture = {}
    for name in ("transport", "stdin", "stdout", "stderr"):
        artifacts[name] = {"path": None, "state": "not_started"}
    if attempt is not None:
        trace = attempt.result.trace
        capture = trace.capture
        if trace.capture_dir is None:
            raise OSError("Transport did not allocate a capture directory")
        if not trace.capture_dir.resolve().is_relative_to(directory.resolve()):
            raise OSError("Transport capture escaped the decision archive")
        for name, filename in (("transport", "capture.json"), ("stdin", "prompt.utf8"),
                               ("stdout", "stdout.bin"), ("stderr", "stderr.bin")):
            artifacts[name] = file_state(trace.capture_dir / filename, directory)
            if artifacts[name]["state"] != "present":
                raise OSError(f"Transport archive is missing or not regular: {name}")
        for name in ("stdout", "stderr"):
            stats = capture.get(name, {})
            if (artifacts[name]["bytes"] != stats.get("archived_bytes")
                    or stats.get("received_bytes") != stats.get("archived_bytes")):
                raise OSError(f"Incomplete archive of received {name} bytes")
            artifacts[name]["stream_complete"] = stats.get("complete", False)
        if (directory / "prompt.md").read_bytes() != (trace.capture_dir / "prompt.utf8").read_bytes():
            raise OSError("Archived prompt differs from the transport input")
        if any(row.get("type") == "log_error" for row in trace.stream_errors):
            raise OSError("Transport reported a log/archive error")
        # Check the persisted capture too: in-memory state alone cannot attest
        # a successfully committed terminal transport record.
        saved = json.loads((trace.capture_dir / "capture.json").read_text(encoding="utf-8"))
        if "finished_at" not in saved or saved != capture:
            raise OSError("Terminal transport capture was not fully committed")
    status = ("succeeded" if result.valid else "invalid_response" if result.failure
              else result.execution.status.value)
    settings = dict(manifest["settings"])
    compatibility = capture.get("decision_cli_compatibility", {})
    if compatibility.get("status") == "PASS":
        settings["enforced_cli_arguments"] = codex_policy.decision_arguments(
            network_access=False, config_profile=settings.get("config_profile"), extra_args=())
    return manifest | {
        "settings": settings, "cli_compatibility": compatibility,
        "finished_at": timestamp(), "status": status, "archive_complete": True,
        "result": asdict(result), "artifacts": artifacts,
        "retry": manifest["retry"] | {"scheduled": retry_scheduled},
        "cwd": str(attempt.cwd) if attempt else None,
        "cli_version": capture.get("decision_cli_version"),
        "argv": capture.get("argv"), "resolved_argv": capture.get("resolved_argv"),
        "launcher": capture.get("launcher"),
    }
