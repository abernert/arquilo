# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""Lokale Diagnose; --check-decide prüft Decide und kann Modellkosten verursachen."""
from __future__ import annotations
from controller_state import default_state_root

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping, Sequence
from uuid import uuid4

from codex_launcher import CodexLauncher, resolve_launcher
from codex_transport import (TransportTimeouts, metadata_probe_arguments, probe_cli_metadata,
                             inspect_decision_features)
from runtime_files import validate_path


REQUIRED_EXEC_FLAGS = (
    "--json", "--output-schema", "--output-last-message", "--skip-git-repo-check",
    "--sandbox", "--config", "--model", "--profile", "--ephemeral",
    "--ignore-user-config", "--ignore-rules", "--strict-config",
)
PROBE_TIMEOUT_SECONDS = 10
DECIDE_TIMEOUT_SECONDS = 120


def _decision_probe(*, workspace: Path, launcher: CodexLauncher, env: Mapping[str, str],
                    model: str | None, reasoning_effort: str | None, timeout: float) -> dict:
    """One public Decide call with normal isolation, validation and full logs.

    A valid but wrong choice is a failed smoke test. Never retry, weaken the
    policy, or echo arbitrary model/provider diagnostics into the report.
    """
    import decide
    from decision_request import DecisionRequest

    probe = {"status": "FAIL", "model_calls": 0, "archive": None,
             "timeout_seconds": timeout, "max_attempts": 1,
             "detail": "Decide-Funktionsprobe fehlgeschlagen; Archiv und lokale Einrichtung prüfen."}
    try:
        request = DecisionRequest(
            question="What is 2 + 2? Choose FOUR for 4 or FIVE for 5 and explain briefly. Do not use tools.",
            options=("FOUR", "FIVE"), context=(), run_id=f"doctor-{uuid4().hex}",
            task_id="decide-smoke", phase="diagnostic", attempt_id="1",
            model=model, reasoning_effort=reasoning_effort,
        )
        settings = decide.DecisionExecSettings(
            project_root=workspace, trusted_codex_home=Path.home() / ".codex", env=env,
            log_root=workspace / ".codex_runs" / "arquilo_doctor", launcher=launcher.source,
            timeouts=TransportTimeouts(total=timeout), max_attempts=1,
            process_stop_path=workspace / "process_stop",
        )
        # The transport retains full raw streams and readable logs itself. Its
        # console echo would corrupt --json and expose arbitrary provider text.
        with open(os.devnull, "w", encoding="utf-8") as console, \
                redirect_stdout(console), redirect_stderr(console):
            call = decide.run_decision(request, settings=settings)
        probe["archive"] = str(call.directory) if call.directory is not None else None
        probe["model"] = call.request.model if call.request is not None else model
        probe["reasoning_effort"] = reasoning_effort
        probe["model_calls"] = sum(
            row.attempt is not None and "launcher" in row.attempt.result.trace.capture
            for row in call.attempts
        )
        if call.result.valid and call.result.option == "FOUR":
            probe.update(status="PASS", detail="Decide: erwartete Auswahl, gültige Antwort und vollständiges Archiv.")
        elif call.result.valid:
            probe["error_code"] = "doctor_decide_wrong_answer"
        else:
            failure = call.result.failure or (call.result.execution.failure if call.result.execution else None)
            probe["error_code"] = failure.code if failure else "decision_cancelled"
    except KeyboardInterrupt:
        probe["error_code"] = "decision_cancelled"
    except (OSError, ValueError, RuntimeError) as exc:
        probe.update(error_code="doctor_decide_setup_failed", error_type=type(exc).__name__)
    return probe


def _probe(name: str, launcher: CodexLauncher, *, cwd: Path, env: Mapping[str, str]) -> tuple[dict, str]:
    argv = [*launcher.argv, *metadata_probe_arguments(name)]
    record = {"argv": argv, "status": "FAIL", "exit_code": None,
              "timeout_seconds": PROBE_TIMEOUT_SECONDS}
    try:
        result = probe_cli_metadata(probe=name, launcher=(launcher.source,), cwd=cwd,
                                    env=env, timeout=PROBE_TIMEOUT_SECONDS)
        record.update(exit_code=result.returncode, stderr_present=bool(result.stderr))
        # Do not expose arbitrary CLI diagnostics/configuration (or credentials).
        output = result.stdout
        record["status"] = "PASS" if result.returncode == 0 else "FAIL"
        if result.returncode:
            record["error"] = "CLI-Leseprobe fehlgeschlagen; Installation/Konfiguration prüfen."
        return record, output
    except subprocess.TimeoutExpired:
        record["error"] = "CLI-Leseprobe überschritt das Zeitlimit; keine Wiederholung."
    except (OSError, UnicodeError) as exc:
        record["error"] = f"CLI-Leseprobe nicht lesbar/ausführbar ({type(exc).__name__})."
    except KeyboardInterrupt:
        record.update(error="Diagnose abgebrochen; keine weiteren CLI-Proben.", interrupted=True)
    return record, ""


def collect_report(*, workdir: Path | None = None, todo_file: Path | None = None,
                   env: Mapping[str, str] | None = None, check_decide: bool = False,
                   model: str | None = None, reasoning_effort: str | None = None,
                   decide_timeout: float = DECIDE_TIMEOUT_SECONDS) -> dict:
    """Resolve paths like run_todos; metadata by default, Decide only by opt-in.

    No profile command, task, authentication read, configuration write or model
    transport call without check_decide. A successful functional test proves the
    effective Codex model's Decide contract, not general model quality or OS isolation.
    """
    if type(check_decide) is not bool:
        raise ValueError("check_decide muss bool sein.")
    if (type(decide_timeout) not in (int, float) or not math.isfinite(decide_timeout)
            or decide_timeout <= 0):
        raise ValueError("decide_timeout muss eine endliche positive Sekundenzahl sein.")
    if not check_decide and (model is not None or reasoning_effort is not None
                             or decide_timeout != DECIDE_TIMEOUT_SECONDS):
        raise ValueError("Decide-Optionen benötigen --check-decide.")
    environment = dict(os.environ if env is None else env)
    root = Path(__file__).resolve().parent
    report = {
        "schema_version": "arquilo.doctor.v1",
        "recorded_at": datetime.now().astimezone().isoformat(),
        "status": "FAIL", "checks_status": "FAIL",
        "python": {"version": sys.version.split()[0], "executable": sys.executable,
                   "platform": sys.platform, "minimum": "3.11"},
        "arquilo_version": None, "codex_version": None, "launcher": None,
        "codex_compatibility": "functional_contract",
        "paths": {"installation": str(root), "caller_cwd": str(Path.cwd())},
        "checks": [], "probes": [], "exec_flags": {}, "decision_features": {},
        "decision_feature_details": {}, "unavailable_optional_features": [],
        "model_calls": 0,
        "decision_probe": {"status": "NOT_RUN", "requested": check_decide,
                           "detail": "Funktionsprobe nur mit --check-decide; kann Modellkosten verursachen."},
        "not_verified": ["Decide-Funktion, Codex-Anmeldung und Modellzugang", "native Sandboxwirkung",
                         "Windows-Sandbox-Einrichtung", "Live-Werkzeugausführung und andere Modellaufgaben"],
        "notes": ["CLI-Version ist Metadatum; keine Versionsliste oder Mindestversion.",
                  "Ohne --check-decide nur --version, exec --help und features list, kein Modellprompt.",
                  "--check-decide: höchstens ein Modellaufruf; keine automatische Wiederholung.",
                  "--check-decide ohne --model nutzt das von Codex/Provider konfigurierte Default-Modell.",
                  "Keine Auth-Datei oder Umgebungs-/Konfigurationsdumps im Bericht.",
                  "ToDo-Inhalt und Profil-Preflight separat mit --dry-run prüfen.",
                  "Runner logs live under the default external controller state root (or --state-dir); the runner prints the exact per-plan path.",
                  "CLI-Stderr wird nur als vorhanden markiert; keine geheimen Fehlertexte ausgeben."],
    }

    def check(name: str, passed: bool, detail: str) -> None:
        report["checks"].append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    check("python", sys.version_info >= (3, 11), "Python >=3.11 erforderlich.")
    try:
        report["arquilo_version"] = (root / "VERSION").read_text(encoding="utf-8").strip()
        check("runtime_version", bool(report["arquilo_version"]), "VERSION aus dieser Installation.")
    except (OSError, UnicodeError):
        check("runtime_version", False, "VERSION fehlt oder ist nicht als UTF-8 lesbar.")
    try:
        for value in (workdir, todo_file):
            if value is not None:
                validate_path(value)
        todo = todo_file.expanduser().resolve() if todo_file is not None else None
        workspace = workdir.expanduser().resolve() if workdir is not None else (todo.parent if todo else Path.cwd())
        report["paths"].update(workdir=str(workspace), todo_file=str(todo) if todo else None,
                               logs=str(workspace / ".codex_runs"),
                               runner_state_root=str(default_state_root()))
        check("workdir", workspace.is_dir(), "Workspace muss bereits als Verzeichnis vorhanden sein.")
        if todo is not None:
            check("todo_file", todo.is_file(), "ToDo-Datei muss vorhanden sein; keine Inhaltsprüfung im Doctor.")
        if not all(item["status"] == "PASS" for item in report["checks"]):
            return report
        launcher = resolve_launcher("codex", cwd=workspace, env=environment)
        report["launcher"] = launcher.metadata()
        check("launcher", True, "Shellfreier Runtime-Resolver; unter Windows EXE oder geprüfter npm-Wrapper.")
    except (OSError, ValueError, RuntimeError) as exc:
        check("paths_or_launcher", False, str(exc))
        return report

    outputs = {name: "" for name in ("version", "help")}
    for name in ("version", "help"):
        record, output = _probe(name, launcher, cwd=workspace, env=environment)
        record["name"] = name
        report["probes"].append(record)
        check("probe_" + name, record["status"] == "PASS", record.get("error", "Lokale CLI-Leseprobe."))
        outputs[name] = output if record["status"] == "PASS" else ""
        if record.get("interrupted"):
            report["interrupted"] = True
            break
    version = outputs["version"].strip()
    if re.fullmatch(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
        report["codex_version"] = version
    # Unknown version banners are not a compatibility verdict; do not expose
    # arbitrary output (potential credentials) when the banner is unrecognised.
    flags = set(re.findall(r"^\s*(?:-[A-Za-z],\s*)?(--[a-z-]+)(?=\s|$)", outputs["help"], re.MULTILINE))
    report["exec_flags"] = {flag: flag in flags for flag in REQUIRED_EXEC_FLAGS}
    check("exec_flags", all(report["exec_flags"].values()), "Alle benötigten Exec-Schalter im lokalen --help.")
    if not report.get("interrupted") and all(row["status"] == "PASS" for row in report["probes"]):
        compatibility = inspect_decision_features(
            launcher=(launcher.source,), cwd=workspace, env=environment,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        report["probes"].extend(compatibility["probes"])
        for record in compatibility["probes"]:
            check("probe_" + record["name"], record["status"] == "PASS",
                  record.get("error", "Lokale CLI-Leseprobe."))
        report["decision_feature_details"] = compatibility["features"]
        report["decision_features"] = {name: row["status"] in {"verified", "unavailable_optional"}
                                       for name, row in compatibility["features"].items()}
        report["unavailable_optional_features"] = compatibility["unavailable_optional"]
        if compatibility["interrupted"]:
            report["interrupted"] = True
        check("decision_features", compatibility["status"] == "PASS", compatibility["detail"])
    else:
        check("decision_features", False, "Nicht geprüft: CLI-Metadaten fehlen oder Diagnose abgebrochen.")
    if check_decide and all(item["status"] == "PASS" for item in report["checks"]):
        report["decision_probe"] = _decision_probe(
            workspace=workspace, launcher=launcher, env=environment, model=model,
            reasoning_effort=reasoning_effort, timeout=decide_timeout,
        ) | {"requested": True}
        report["model_calls"] = report["decision_probe"]["model_calls"]
        passed = report["decision_probe"]["status"] == "PASS"
        check("decide", passed, report["decision_probe"]["detail"])
        if passed:
            report["not_verified"].remove("Decide-Funktion, Codex-Anmeldung und Modellzugang")
            report["not_verified"].append("Weitere Modelle und allgemeine Modellurteilsgüte")
    elif check_decide:
        report["decision_probe"]["detail"] = "Nicht ausgeführt: lokale Voraussetzungen fehlen oder Diagnose abgebrochen."
    if all(item["status"] == "PASS" for item in report["checks"]):
        report.update(status="QUALIFIED", checks_status="PASS")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, help="Vorhandener Projektworkspace; Standard: ToDo-Ordner, sonst cwd.")
    parser.add_argument("--todo-file", type=Path, help="Optionaler Pfad zur bestehenden ToDo-Datei.")
    parser.add_argument("--json", action="store_true", help="Strukturierten Bericht auf stdout ausgeben, auch bei Fehlern.")
    parser.add_argument("--check-decide", action="store_true",
                        help="Decide tatsächlich prüfen: höchstens ein Modellaufruf, kann Kosten verursachen.")
    parser.add_argument("--model", help="Modell für --check-decide; Standard wie decide.py.")
    parser.add_argument("--reasoning-effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
                        help="Reasoning-Effort für --check-decide.")
    parser.add_argument("--decide-timeout", type=float, default=None,
                        help=f"Zeitlimit der Funktionsprobe in Sekunden (Standard {DECIDE_TIMEOUT_SECONDS}, plus Metadaten/Prozessbereinigung).")
    args = parser.parse_args(argv)
    if not args.check_decide and any(value is not None for value in (args.model, args.reasoning_effort, args.decide_timeout)):
        parser.error("--model, --reasoning-effort und --decide-timeout benötigen --check-decide.")
    if args.decide_timeout is not None and (not math.isfinite(args.decide_timeout) or args.decide_timeout <= 0):
        parser.error("--decide-timeout muss eine endliche positive Sekundenzahl sein.")
    report = collect_report(workdir=args.workdir, todo_file=args.todo_file, check_decide=args.check_decide,
                            model=args.model, reasoning_effort=args.reasoning_effort,
                            decide_timeout=DECIDE_TIMEOUT_SECONDS if args.decide_timeout is None else args.decide_timeout)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print(f"ARQUILO Doctor: {report['status']} (lokale Prüfungen: {report['checks_status']})")
        print(f"Python: {report['python']['version']} ({report['python']['executable']})")
        print(f"ARQUILO: {report['arquilo_version']}; Codex: {report['codex_version'] or 'nicht erkannt'}")
        for key, value in report["paths"].items():
            print(f"{key}: {value}")
        if report["launcher"]:
            print(f"Codex-Launcher: {report['launcher']['source']} ({report['launcher']['kind']})")
        for flag, supported in report["exec_flags"].items():
            print(f"Exec {flag}: {'vorhanden' if supported else 'fehlt'}")
        for check in report["checks"]:
            print(f"[{check['status']}] {check['name']}: {check['detail']}")
        for name, feature in report.get("decision_feature_details", {}).items():
            if feature["status"] == "unavailable_optional":
                print(f"[INFO] {name}: in dieser CLI nicht verfügbar; optionaler Override entfällt.")
            elif feature["status"] != "verified":
                print(f"[FAIL] {name}: {feature['status']}; erwartet={feature['expected']}, "
                      f"beobachtet={feature['observed']}")
        if any(probe.get("stderr_present") for probe in report["probes"]):
            print("CLI hat Diagnosehinweise auf stderr ausgegeben; Details lokal prüfen.")
        print("Nicht verifiziert: " + "; ".join(report["not_verified"]))
        probe = report["decision_probe"]
        print(f"Decide: {probe['status']}. {probe['detail']}")
        if probe.get("error_code"):
            print(f"Decide-Fehler: {probe['error_code']}")
        if probe.get("archive"):
            print(f"Decide-Archiv: {probe['archive']}")
        print(f"Modellaufrufe (gestartete Exec-Prozesse): {report['model_calls']}. JSON-Details: --json.")
    return 0 if report["checks_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
