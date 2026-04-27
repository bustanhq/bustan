"""Unit tests for the project scaffolding CLI."""

import importlib
import sys
from pathlib import Path

from starlette.testclient import TestClient

from bustan.cli.main import main


def test_cli_new_scaffolds_a_project_with_expected_files(tmp_path: Path, capsys) -> None:
    exit_code = main(["create", "hello-bustan", "--directory", str(tmp_path)])

    assert exit_code == 0
    project_directory = tmp_path / "hello-bustan"
    assert project_directory.exists()
    assert (project_directory / "pyproject.toml").exists()
    assert (project_directory / "README.md").exists()
    assert (project_directory / ".gitignore").exists()
    assert (project_directory / "src" / "hello_bustan" / "__init__.py").exists()
    assert (project_directory / "src" / "hello_bustan" / "main.py").exists()
    assert (project_directory / "src" / "hello_bustan" / "app.module.py").exists()
    assert (project_directory / "src" / "hello_bustan" / "app.controller.py").exists()
    assert (project_directory / "src" / "hello_bustan" / "app.service.py").exists()
    assert not (project_directory / "src" / "hello_bustan" / "app.py").exists()
    assert (project_directory / "tests" / "test_app.py").exists()

    pyproject_content = (project_directory / "pyproject.toml").read_text(encoding="utf-8")
    init_content = (project_directory / "src" / "hello_bustan" / "__init__.py").read_text(
        encoding="utf-8"
    )
    main_content = (project_directory / "src" / "hello_bustan" / "main.py").read_text(
        encoding="utf-8"
    )
    stdout = capsys.readouterr().out

    assert "bustan.cli:main" not in pyproject_content
    assert '"uvicorn>=0.30.0,<1.0.0"' in pyproject_content
    assert '"hello_bustan.main:main"' in pyproject_content
    assert 'uvicorn.run("hello_bustan:app", reload=True)' in main_content
    assert "app = _create_bustan_app(AppModule)" in init_content
    assert "Created Bustan application" in stdout


def test_cli_create_alias_scaffolds_a_project(tmp_path: Path) -> None:
    exit_code = main(["create", "demo-app", "--directory", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "demo-app" / "src" / "demo_app" / "__init__.py").exists()


def test_cli_scaffolded_package_is_importable_and_serves_the_root_route(tmp_path: Path) -> None:
    exit_code = main(["create", "demo-import", "--directory", str(tmp_path)])

    assert exit_code == 0
    project_directory = tmp_path / "demo-import"
    sys.path.insert(0, str(project_directory / "src"))
    try:
        module = importlib.import_module("demo_import")
        with TestClient(module.app) as client:
            response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello from demo-import"}
    finally:
        sys.path.pop(0)
        for module_name in [
            "demo_import",
            "demo_import._app_service",
            "demo_import._app_controller",
            "demo_import._app_module",
        ]:
            sys.modules.pop(module_name, None)


def test_cli_rejects_non_empty_target_directory(tmp_path: Path, capsys) -> None:
    target_directory = tmp_path / "existing-app"
    target_directory.mkdir()
    (target_directory / "README.md").write_text("occupied", encoding="utf-8")

    exit_code = main(["create", "existing-app", "--directory", str(tmp_path)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "already exists and is not empty" in stderr
