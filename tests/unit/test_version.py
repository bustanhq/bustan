"""Unit tests for version resolution helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path

import bustan._version as version_module


def test_get_installed_version_prefers_installed_distribution(monkeypatch) -> None:
    monkeypatch.setattr(version_module, "version", lambda package_name: "1.2.3")

    assert version_module.get_installed_version(default="0.0.0") == "1.2.3"


def test_get_installed_version_falls_back_to_local_pyproject(monkeypatch, tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")

    monkeypatch.setattr(version_module, "version", _raise_package_not_found)
    monkeypatch.setattr(version_module, "PYPROJECT_PATH", pyproject_path)

    assert version_module.get_installed_version(default="0.0.0") == "0.2.0"


def test_get_installed_version_uses_default_when_local_version_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_pyproject_path = tmp_path / "missing.toml"

    monkeypatch.setattr(version_module, "version", _raise_package_not_found)
    monkeypatch.setattr(version_module, "PYPROJECT_PATH", missing_pyproject_path)

    assert version_module.get_installed_version(default="9.9.9") == "9.9.9"


def test_read_local_version_returns_none_for_invalid_toml(monkeypatch, tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text('[project\nversion = "0.2.0"\n', encoding="utf-8")

    monkeypatch.setattr(version_module, "PYPROJECT_PATH", pyproject_path)

    assert version_module._read_local_version() is None


def test_read_local_version_returns_none_for_non_string_versions(
    monkeypatch, tmp_path: Path
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text("[project]\nversion = 1\n", encoding="utf-8")

    monkeypatch.setattr(version_module, "PYPROJECT_PATH", pyproject_path)

    assert version_module._read_local_version() is None


def _raise_package_not_found(package_name: str) -> str:
    raise PackageNotFoundError(package_name)
