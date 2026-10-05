# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Evidence-only metadata checks through the existing Codex process boundary."""
from __future__ import annotations

import subprocess
from ask_policy import config_arguments, validate_metadata
import codex_transport as transport
from process_tree import REAP_TIMEOUT, finish_cleanup, ProcessTreeError
from workbench_files import strict_json, WorkbenchError


def inspect_ask_configuration(request: transport.CodexExecRequest) -> None:
    """Fail closed: metadata must establish disabled native shell/MCP paths.

    Feature/MCP listing is metadata, not model inference. Trusted Codex hooks and
    provider authentication remain host code; this is not an OS confinement proof.
    """
    if not request.decision_only or tuple(request.extra_args) != tuple(config_arguments()):
        raise WorkbenchError("Ask requires the complete evidence-only policy")
    report = transport.inspect_decision_cli(launcher=request.launcher, cwd=request.cwd,
        env=request.env, model=request.model, config_profile=request.config_profile,
        cancel_requested=request.cancel_requested)
    if report["status"] != "PASS":
        raise WorkbenchError("Required Codex Exec contract could not be verified", code="ask_preflight")
    outputs = []
    for suffix in (("features", "list"), ("mcp", "list", "--json")):
        if request.cancel_requested and request.cancel_requested():
            raise InterruptedError("Ask cancelled before metadata check")
        argv = [*request.launcher, *config_arguments()]
        if request.config_profile:
            argv += ["--profile", request.config_profile]
        argv += list(suffix)
        proc = transport._start_process(argv, cwd=request.cwd, env=request.env)
        try:
            out, _err = proc.communicate(timeout=10)
            if proc.returncode != 0 or len(out) > 262144:
                raise WorkbenchError("Restricted Codex metadata check failed", code="ask_preflight")
            outputs.append(out.decode("utf-8"))
        except subprocess.TimeoutExpired as exc:
            raise WorkbenchError("Restricted Codex metadata check timed out", code="ask_preflight") from exc
        finally:
            cleanup = transport._terminate_process_group(proc, grace_seconds=0.1, reason="ask_metadata_exit")
            if proc.poll() is None:
                proc.communicate(timeout=REAP_TIMEOUT)
            finish_cleanup(proc.arquilo_process_tree.close, cleanup)
            if cleanup.errors:
                raise ProcessTreeError("Ask metadata process cleanup failed")
    validate_metadata(outputs[0], strict_json(outputs[1]))
