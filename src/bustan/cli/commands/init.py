"""Command implementation for initialising a Bustan project."""

from __future__ import annotations

import argparse
import sys

from ..services.scaffold import init_project, package_name_from_pyproject


def run_init_command(arguments: argparse.Namespace) -> int:
    """Detect the package name and scaffold app files into the current project."""

    package_name = package_name_from_pyproject()
    if package_name is None:
        print(
            "Could not find a pyproject.toml in the current directory.\n"
            "Run 'uv init --package <name>' first, then re-run 'bustan init'.",
            file=sys.stderr,
        )
        return 1

    init_project(package_name=package_name)
    print(f"Initialised Bustan app for package '{package_name}'.")
    print("Next steps:")
    print("  uv add bustan")
    print("  uv add --dev ty ruff pytest")
    print("  uv run start")
    print("  uv run dev")
    return 0
