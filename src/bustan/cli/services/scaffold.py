"""Service for scaffolding new Bustan application projects."""

from __future__ import annotations

import importlib.metadata
import re
from pathlib import Path
from string import Template


def scaffold_project(
    target_directory: Path,
    *,
    project_name: str,
    package_name: str,
) -> None:
    """Write the generated project layout to disk."""

    package_directory = target_directory / "src" / package_name
    tests_directory = target_directory / "tests"

    target_directory.mkdir(parents=True, exist_ok=True)
    package_directory.mkdir(parents=True, exist_ok=True)
    tests_directory.mkdir(parents=True, exist_ok=True)

    bustan_version = _installed_bustan_version()
    template_vars = {
        "project_name": project_name,
        "package_name": package_name,
        "bustan_version": bustan_version,
    }

    templates_root = Path(__file__).parent.parent / "templates" / "app"

    files = {
        target_directory / ".gitignore": ".gitignore",
        target_directory / "README.md": "README.md",
        target_directory / "pyproject.toml": "pyproject.toml",
        package_directory / "__init__.py": "__init__.py",
        package_directory / "app.py": "app.py",
        tests_directory / "test_app.py": "test_app.py",
    }

    for file_path, template_name in files.items():
        template_path = templates_root / template_name.strip()
        content = template_path.read_text(encoding="utf-8")
        file_path.write_text(Template(content).safe_substitute(template_vars), encoding="utf-8")


def default_package_name(project_name: str) -> str:
    sanitized_name = re.sub(r"[^a-zA-Z0-9_]+", "_", project_name.strip().lower())
    sanitized_name = sanitized_name.strip("_")
    if not sanitized_name:
        return "bustan_app"
    if sanitized_name[0].isdigit():
        return f"app_{sanitized_name}"
    return sanitized_name


def is_valid_package_name(package_name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", package_name))


def _installed_bustan_version() -> str:
    try:
        return importlib.metadata.version("bustan")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.1"
