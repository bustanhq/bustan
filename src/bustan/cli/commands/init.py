"""Command implementation for initialising a Bustan project."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..services.failures import COMMAND_FAILURES, report_failure
from ..services.scaffold import ScaffoldReport, init_project, package_name_from_pyproject

# What `bustan init --help` answers. It says what lands on disk and that nothing already
# there is replaced, because this is the only command in the tool that writes files and
# the reader deciding whether to run it a second time is the one who needs to know.
_DESCRIPTION = (
    "Write a Bustan application into the uv project in the current directory: an entry "
    "point, a root module, a controller and a service under src/<package>, a test for "
    "each of them under tests/<package>, and a README. The manifest gains the transport "
    "dependency, a 'dev' dependency group and the 'start' and 'dev' scripts wherever it "
    "does not already declare them. A file already there is kept and reported rather than "
    "overwritten, so running this again destroys no work; pass --force to replace it."
)

_NO_PROJECT_MESSAGE = (
    "Could not find a pyproject.toml in the current directory.\n"
    "Run 'uv init --package <name>' first, then re-run 'bustan init'."
)


def register_init_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "init",
        help="Initialise a Bustan app in the current uv project.",
        description=_DESCRIPTION,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a file that already exists instead of keeping it.",
    )


def run_init_command(arguments: argparse.Namespace) -> int:
    """Detect the package name and scaffold app files into the current project."""

    try:
        package_name = package_name_from_pyproject()
        if package_name is None:
            print(_NO_PROJECT_MESSAGE, file=sys.stderr)
            return 1
        report = init_project(package_name=package_name, force=arguments.force)
    except COMMAND_FAILURES as error:
        return report_failure(error)

    _print_report(package_name, report)
    return 0


def _print_report(package_name: str, report: ScaffoldReport) -> None:
    """Name every path the run wrote, every path it kept, and what to run next."""

    print(f"Initialised Bustan app for package '{package_name}'.")
    _print_paths("Wrote", report.written)
    _print_paths("Kept", report.skipped)
    if report.skipped:
        print("Pass --force to replace a file that was kept.")
    for edit in report.manifest_edits:
        print(f"Manifest: {edit}.")

    # One install command, because the manifest now declares what a scaffolded project
    # needs to serve and to test itself.
    print("Next steps:")
    print("  uv sync")
    print("  uv run start")
    print("  uv run dev")


def _print_paths(label: str, paths: tuple[Path, ...]) -> None:
    """Print a labelled block of project-relative paths, or nothing where there are none."""

    if not paths:
        return
    print(f"{label}:")
    for path in paths:
        print(f"  {path.as_posix()}")
