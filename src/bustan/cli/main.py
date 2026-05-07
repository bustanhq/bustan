"""Command-line interface entry point for Bustan."""

from __future__ import annotations

import argparse

from .commands.init import run_init_command


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the appropriate command handler."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)

    command = getattr(arguments, "command", None)
    if command is None:
        parser.print_help()
        return 1

    if command == "init":
        return run_init_command(arguments)

    parser.error(f"Unsupported command: {command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the `bustan` command."""

    parser = argparse.ArgumentParser(
        prog="bustan",
        description="Scaffold and manage Bustan applications.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "init",
        help="Initialise a Bustan app in the current uv project.",
    )

    return parser

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
