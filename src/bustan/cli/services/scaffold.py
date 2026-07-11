"""Service for scaffolding Bustan app files into an existing uv project."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from string import Template


def package_name_from_pyproject() -> str | None:
    """Read the project name from pyproject.toml in CWD and return a valid package name."""
    pyproject_path = Path.cwd() / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    project_name: str = data.get("project", {}).get("name", "").strip()
    if not project_name:
        return None

    return _to_package_name(project_name)


def init_project(*, package_name: str) -> None:
    """Write Bustan app files into the current uv project."""
    cwd = Path.cwd()
    package_directory = cwd / "src" / package_name
    tests_directory = cwd / "tests" / package_name

    package_directory.mkdir(parents=True, exist_ok=True)
    tests_directory.mkdir(parents=True, exist_ok=True)

    # Derive a human-readable project name from the package name.
    project_name = package_name.replace("_", " ").title()

    template_vars = {"project_name": project_name, "package_name": package_name}
    templates_root = Path(__file__).parent.parent / "templates" / "app"

    source_files = {
        cwd / "README.md": "README.md",
        package_directory / "__init__.py": "app_init.py",
        package_directory / "app_module.py": "app_module.py",
        package_directory / "app_controller.py": "app_controller.py",
        package_directory / "app_service.py": "app_service.py",
        tests_directory / "__init__.py": None,
        tests_directory / "test_app_controller.py": "test_app_controller.py",
        tests_directory / "test_app_service.py": "test_app_service.py",
        tests_directory / "test_app_module.py": "test_app_module.py",
    }

    for file_path, template_name in source_files.items():
        if template_name is None:
            file_path.touch()
            continue
        if file_path.exists() and file_path.name == "README.md":
            continue
        template_path = templates_root / template_name
        content = template_path.read_text(encoding="utf-8")
        file_path.write_text(Template(content).safe_substitute(template_vars), encoding="utf-8")

    _add_scripts_to_pyproject(package_name)


def _add_scripts_to_pyproject(package_name: str) -> None:
    """Ensure start/dev script entries exist in pyproject.toml."""
    pyproject_path = Path.cwd() / "pyproject.toml"
    if not pyproject_path.exists():
        return

    content = pyproject_path.read_text(encoding="utf-8")
    entries = {
        "start": f'start = "{package_name}:main"',
        "dev": f'dev = "{package_name}:dev"',
    }
    missing = [
        line
        for key, line in entries.items()
        if re.search(rf"^{key}\s*=", content, flags=re.MULTILINE) is None
    ]
    if not missing:
        return

    # uv init --package already creates [project.scripts]; merge into it
    # instead of appending a duplicate section header.
    if "[project.scripts]" in content:
        content = content.replace(
            "[project.scripts]",
            "[project.scripts]\n" + "\n".join(missing),
            1,
        )
        pyproject_path.write_text(content, encoding="utf-8")
        return

    scripts_block = "\n[project.scripts]\n" + "\n".join(missing) + "\n"
    pyproject_path.write_text(content.rstrip() + "\n" + scripts_block, encoding="utf-8")


def _to_package_name(project_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", project_name.strip().lower()).strip("_")
    if not sanitized:
        return "bustan_app"
    if sanitized[0].isdigit():
        return f"app_{sanitized}"
    return sanitized
