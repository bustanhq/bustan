"""Unit tests for the Bustan CLI init command."""

import os
from pathlib import Path

from bustan.cli.main import main

_PYPROJECT_TOML = """\
[project]
name = "{name}"
version = "0.1.0"
description = "Test project"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.6,<0.12.0"]
build-backend = "uv_build"
"""


def _write_pyproject(directory: Path, name: str) -> None:
    (directory / "pyproject.toml").write_text(
        _PYPROJECT_TOML.format(name=name), encoding="utf-8"
    )


def test_init_creates_expected_files(tmp_path: Path, capsys) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert (tmp_path / "README.md").exists()
    pkg = tmp_path / "src" / "hello_bustan"
    assert (pkg / "__init__.py").exists()
    assert (pkg / "app_module.py").exists()
    assert (pkg / "app_controller.py").exists()
    assert (pkg / "app_service.py").exists()
    tests = tmp_path / "tests" / "hello_bustan"
    assert (tests / "test_app_controller.py").exists()
    assert (tests / "test_app_service.py").exists()
    assert (tests / "test_app_module.py").exists()
    stdout = capsys.readouterr().out
    assert "hello_bustan" in stdout


def test_init_adds_scripts_to_pyproject(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "my-app")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
    finally:
        os.chdir(old_cwd)

    content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.scripts]' in content
    assert 'start = "my_app:main"' in content
    assert 'dev = "my_app:dev"' in content


def test_init_fails_without_pyproject(tmp_path: Path, capsys) -> None:
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 1
    assert "pyproject.toml" in capsys.readouterr().err


def test_init_init_py_contains_bootstrap_and_scripts(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "demo-app")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
    finally:
        os.chdir(old_cwd)

    content = (tmp_path / "src" / "demo_app" / "__init__.py").read_text(encoding="utf-8")
    assert "def bootstrap" in content
    assert "def main" in content
    assert "def dev" in content

