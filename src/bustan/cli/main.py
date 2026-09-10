"""Command-line interface entry point for Bustan."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping

from .._version import get_installed_version
from ..kernel.errors import BustanError
from .commands.config import register_config_command, run_config_command
from .commands.doctor import register_doctor_command, run_doctor_command
from .commands.governance import register_governance_commands, run_governance_command
from .commands.graph import register_graph_command, run_graph_command
from .commands.init import run_init_command
from .commands.routes import register_routes_commands, run_routes_command
from .services.failures import report_failure

_HANDLERS: Mapping[str, Callable[[argparse.Namespace], int]] = {
    "config": run_config_command,
    "doctor": run_doctor_command,
    "governance": run_governance_command,
    "graph": run_graph_command,
    "init": run_init_command,
    "routes": run_routes_command,
}


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the appropriate command handler."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    command = getattr(arguments, "command", None)

    if getattr(arguments, "version", False):
        # The flag is the whole of the invocation, so a command standing beside it is
        # refused rather than dropped: printing the version and exiting zero for a
        # command that never ran would let anything appending the flag turn a failing
        # gate into a pass, and a gate that did not run must never read as one passed.
        if command is not None:
            parser.error("--version prints the installed version and takes no command")
        print(f"bustan {get_installed_version()}")
        return 0

    if command is None:
        parser.print_help()
        return 1

    handler = _HANDLERS.get(command)
    if handler is None:
        parser.error(f"Unsupported command: {command}")
        return 2

    try:
        return handler(arguments)
    except BustanError as error:
        # The last line of defence. Every command states its own refusals, and this
        # catches the one a command did not anticipate: a message and a failing status
        # are what an operator can act on, where a traceback out of the framework's
        # internals names files that are none of their business.
        return report_failure(error)


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the `bustan` command."""

    parser = argparse.ArgumentParser(
        prog="bustan",
        description="Scaffold, inspect and diagnose Bustan applications.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the installed bustan version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "init",
        help="Initialise a Bustan app in the current uv project.",
    )
    register_governance_commands(subparsers)
    register_routes_commands(subparsers)
    register_doctor_command(subparsers)
    register_graph_command(subparsers)
    register_config_command(subparsers)

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
