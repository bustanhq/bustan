"""Command-line interface entry point for Bustan."""

from __future__ import annotations

import argparse

from .commands.create import run_create_command


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the appropriate command handler."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)

    command = getattr(arguments, "command", None)
    if command is None:
        parser.print_help()
        return 1

    if command == "create":
        return run_create_command(arguments)

    parser.error(f"Unsupported command: {command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the `bustan` command."""

    parser = argparse.ArgumentParser(
        prog="bustan",
        description="Scaffold and manage Bustan applications.",
    )
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser(
        "create",
        help="Create a new Bustan application.",
    )
    new_parser.add_argument("name", help="Project directory name.")
    new_parser.add_argument(
        "--directory",
        default=".",
        help="Parent directory where the project will be created.",
    )
    new_parser.add_argument(
        "--package-name",
        help="Python package name to use inside src/. Defaults to a sanitized project name.",
    )

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
