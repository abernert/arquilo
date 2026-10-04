# Copyright 2026 Alexander Bernert
# SPDX-License-Identifier: Apache-2.0
"""ARQUILO command-line entry point; current public runtime commands."""
from __future__ import annotations
import argparse
import sys
from collections.abc import Sequence
from runtime_profile import ARQUILO_RUNTIME_VERSION

__version__ = ARQUILO_RUNTIME_VERSION


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Dispatch first, so each existing CLI owns its flags, help and exit codes.
    if args and args[0] == "run":
        from run_todos import main as run_main
        return run_main(args[1:])
    if args and args[0] == "doctor":
        from arquilo_doctor import main as doctor_main
        return doctor_main(args[1:])
    if args and args[0] == "capabilities":
        from run_todos import main as run_main
        return run_main(["--print-capabilities", *args[1:]])
    if args and args[0] == "ask":
        from ask import main as ask_main
        return ask_main(args[1:])
    if args and args[0] == "workbench":
        from workbench import main as workbench_main
        return workbench_main(args[1:])
    if args and args[0] == "package":
        from scripts.build_runtime_zip import main as package_main
        return package_main(args[1:])
    parser = argparse.ArgumentParser(
        description="ARQUILO — reviewed task execution from Markdown.",
        epilog="Use 'python arquilo.py COMMAND --help' for command options.",
    )
    parser.add_argument("--version", action="version", version=f"ARQUILO {__version__}")
    parser.add_argument("command", nargs="?", choices=("run", "doctor", "capabilities", "ask", "workbench", "package"))
    parser.parse_args(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
