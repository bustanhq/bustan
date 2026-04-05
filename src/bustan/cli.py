"""Command-line scaffolding for Bustan applications."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import sys
from pathlib import Path
from textwrap import dedent


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch the selected command."""

    parser = _build_parser()
    arguments = parser.parse_args(argv)

    command = getattr(arguments, "command", None)
    if command is None:
        parser.print_help()
        return 1

    if command == "create":
        return _run_new_command(arguments)

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


def _run_new_command(arguments: argparse.Namespace) -> int:
    """Validate input and scaffold a new application project."""

    project_name = arguments.name.strip()
    if not project_name:
        print("Project name cannot be empty.", file=sys.stderr)
        return 1

    package_name = arguments.package_name or _default_package_name(project_name)
    if not _is_valid_package_name(package_name):
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

    files = {
        target_directory / ".gitignore": _build_gitignore(),
        target_directory / "README.md": _build_readme(project_name=project_name, package_name=package_name),
        target_directory / "pyproject.toml": _build_pyproject(
            project_name=project_name,
            package_name=package_name,
        ),
        package_directory / "__init__.py": _build_package_init(),
        package_directory / "app.py": _build_app_module(project_name=project_name, package_name=package_name),
        tests_directory / "test_app.py": _build_app_test(
            project_name=project_name,
            package_name=package_name,
        ),
    }

    for file_path, content in files.items():
        file_path.write_text(content, encoding="utf-8")


def _build_gitignore() -> str:
    """Return the generated .gitignore content for scaffolded projects."""

    return dedent(
        """\
        .DS_Store
        .coverage
        .coverage.*
        .pytest_cache/
        .ruff_cache/
        .venv/
        __pycache__/
        build/
        dist/
        htmlcov/
        *.egg-info/
        *.py[cod]
        """
    )


def _build_readme(*, project_name: str, package_name: str) -> str:
    """Return the scaffolded README content."""

    return dedent(
        f"""\
        # {project_name}

        This project was scaffolded with `bustan`.

        ## Quick start

        ```bash
        uv sync --group dev
        uv run uvicorn {package_name}.app:app --reload
        ```

        ## Quality checks

        ```bash
        uv run ruff check .
        uv run ty check src tests
        uv run pytest
        ```
        """
    )


def _build_pyproject(*, project_name: str, package_name: str) -> str:
    """Return the scaffolded pyproject content."""

    bustan_version = _installed_bustan_version()
    return dedent(
        f"""\
        [project]
        name = "{project_name}"
        version = "0.1.0"
        description = "A Bustan application"
        readme = "README.md"
        requires-python = ">=3.13"
        dependencies = [
            "bustan>={bustan_version}",
            "uvicorn>=0.30.0,<1.0.0",
        ]

        [dependency-groups]
        dev = [
            "httpx>=0.28.0,<1.0.0",
            "pytest>=8.3.0,<9.0.0",
            "ruff>=0.11.0,<0.12.0",
            "ty",
        ]

        [tool.pytest.ini_options]
        addopts = "-ra"
        testpaths = ["tests"]

        [tool.ruff]
        line-length = 100
        target-version = "py313"

        [build-system]
        requires = ["uv_build>=0.11.1,<0.12.0"]
        build-backend = "uv_build"
        """
    )


def _build_package_init() -> str:
    """Return the scaffolded package __init__ module."""

    return "from .app import app\n\n__all__ = [\"app\"]\n"


def _build_app_module(*, project_name: str, package_name: str) -> str:
    """Return the scaffolded application module."""

    return dedent(
        f"""\
        from bustan import Controller, create_app, Get, Injectable, Module


        @Injectable
        class AppService:
            def get_message(self) -> dict[str, str]:
                return {{"message": "Hello from {project_name}"}}


        @Controller("/")
        class AppController:
            def __init__(self, app_service: AppService) -> None:
                self.app_service = app_service

            @Get("/")
            def read_root(self) -> dict[str, str]:
                return self.app_service.get_message()


        @Module(controllers=[AppController], providers=[AppService], exports=[AppService])
        class AppModule:
            pass


        app = create_app(AppModule)


        def main() -> None:
            import uvicorn

            uvicorn.run("{package_name}.app:app", reload=True)


        if __name__ == "__main__":
            main()
        """
    )


def _build_app_test(*, project_name: str, package_name: str) -> str:
    """Return the scaffolded smoke test."""

    return dedent(
        f"""\
        from starlette.testclient import TestClient

        from {package_name}.app import app


        def test_read_root() -> None:
            with TestClient(app) as client:
                response = client.get("/")

            assert response.status_code == 200
            assert response.json() == {{"message": "Hello from {project_name}"}}
        """
    )


def _default_package_name(project_name: str) -> str:
    """Convert a project name into a safe Python package name."""

    sanitized_name = re.sub(r"[^a-zA-Z0-9_]+", "_", project_name.strip().lower())
    sanitized_name = sanitized_name.strip("_")
    if not sanitized_name:
        return "star_app"
    if sanitized_name[0].isdigit():
        return f"app_{sanitized_name}"
    return sanitized_name


def _is_valid_package_name(package_name: str) -> bool:
    """Return whether the supplied package name is import-safe."""

    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", package_name))


def _installed_bustan_version() -> str:
    """Return the installed version of bustan for scaffolded dependencies."""

    try:
        return importlib.metadata.version("bustan")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.1"


if __name__ == "__main__":
    raise SystemExit(main())