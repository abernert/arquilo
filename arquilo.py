# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""ARQUILO command-line entry point; current public runtime commands."""
from __future__ import annotations
import argparse
import sys
from collections.abc import Sequence
from runtime_profile import ARQUILO_RUNTIME_VERSION

__version__ = ARQUILO_RUNTIME_VERSION

RUN_MIGRATION_NOTICE = (
    "ARQUILO: 'arquilo run' is now 'arquilo tasklist run' (compatibility alias)."
)


def _tasklist_main(args: list[str]) -> int:
    # The existing runner still owns every run flag, help action and exit code.
    if args and args[0] == "run":
        from run_todos import main as run_main
        return run_main(args[1:])
    parser = argparse.ArgumentParser(
        prog="arquilo tasklist",
        description="Execute Markdown task lists with mandatory review.",
        epilog="Use 'python arquilo.py tasklist run --help' for runner options.",
        allow_abbrev=False,
    )
    parser.add_argument("command", nargs="?", choices=("run",))
    parser.parse_args(args)
    parser.print_help()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Dispatch first, so each existing CLI owns its flags, help and exit codes.
    if args and args[0] == "tasklist":
        return _tasklist_main(args[1:])
    if args and args[0] == "run":
        # Keep stdout machine-readable and never echo user arguments (secrets).
        print(RUN_MIGRATION_NOTICE, file=sys.stderr)
        return _tasklist_main(["run", *args[1:]])
    if args and args[0] == "doctor":
        from arquilo_doctor import main as doctor_main
        return doctor_main(args[1:])
    if args and args[0] == "capabilities":
        from run_todos import main as run_main
        return run_main(["--print-capabilities", *args[1:]])
    if args and args[0] == "package":
        from scripts.build_runtime_zip import main as package_main
        return package_main(args[1:])
    parser = argparse.ArgumentParser(
        description="ARQUILO — reviewed task execution from Markdown.",
        epilog=("Use 'python arquilo.py tasklist run --help' for runner options. "
                "'run' is a compatibility alias for 'tasklist run'."),
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"ARQUILO {__version__}")
    parser.add_argument("command", nargs="?", choices=("tasklist", "run", "doctor", "capabilities", "package"))
    parser.parse_args(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
