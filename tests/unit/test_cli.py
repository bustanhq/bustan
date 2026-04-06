"""Unit tests for the project scaffolding CLI."""

from pathlib import Path

from bustan.cli import main


def test_cli_new_scaffolds_a_project_with_expected_files(tmp_path: Path, capsys) -> None:
    exit_code = main(["create", "hello-bustan", "--directory", str(tmp_path)])

    assert exit_code == 0
    project_directory = tmp_path / "hello-bustan"
    assert project_directory.exists()
    assert (project_directory / "pyproject.toml").exists()
    assert (project_directory / "README.md").exists()
    assert (project_directory / ".gitignore").exists()
    assert (project_directory / "src" / "hello_bustan" / "app.py").exists()
    assert (project_directory / "tests" / "test_app.py").exists()

    pyproject_content = (project_directory / "pyproject.toml").read_text(encoding="utf-8")
    app_content = (project_directory / "src" / "hello_bustan" / "app.py").read_text(
        encoding="utf-8"
    )
    stdout = capsys.readouterr().out

    assert "bustan.cli:main" not in pyproject_content
    assert '"uvicorn>=0.30.0,<1.0.0"' in pyproject_content
    assert 'uvicorn.run("hello_bustan.app:app", reload=True)' in app_content
    assert "Created Bustan application" in stdout


def test_cli_create_alias_scaffolds_a_project(tmp_path: Path) -> None:
    exit_code = main(["create", "demo-app", "--directory", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "demo-app" / "src" / "demo_app" / "__init__.py").exists()


def test_cli_rejects_non_empty_target_directory(tmp_path: Path, capsys) -> None:
    target_directory = tmp_path / "existing-app"
    target_directory.mkdir()
    (target_directory / "README.md").write_text("occupied", encoding="utf-8")

    exit_code = main(["create", "existing-app", "--directory", str(tmp_path)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "already exists and is not empty" in stderr
