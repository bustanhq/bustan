"""Command implementation for creating new Bustan projects."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..services.scaffold import (
    default_package_name,
    is_valid_package_name,
    scaffold_project,
)


def run_create_command(arguments: argparse.Namespace) -> int:
    """Validate input and scaffold a new application project."""

    project_name = arguments.name.strip()
    if not project_name:
        print("Project name cannot be empty.", file=sys.stderr)
        return 1

    package_name = arguments.package_name or default_package_name(project_name)
    if not is_valid_package_name(package_name):
        print(
            f"Package name {package_name!r} is not a valid Python package identifier.",
            file=sys.stderr,
        )
        return 1

    target_directory = Path(arguments.directory).expanduser().resolve() / project_name
    if target_directory.exists() and any(target_directory.iterdir()):
        print(
            f"Target directory already exists and is not empty: {target_directory}",
            file=sys.stderr,
        )
        return 1

    scaffold_project(target_directory, project_name=project_name, package_name=package_name)
    print(f"Created Bustan application at {target_directory}")
    print("Next steps:")
    print(f"  cd {target_directory}")
    print("  uv sync --group dev")
    print(f"  uv run uvicorn {package_name}.app:app --reload")
    return 0
