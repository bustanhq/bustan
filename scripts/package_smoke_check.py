#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
SMOKE_VENV_DIR = ROOT / ".package-smoke"


def _run(*command: str, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd or ROOT, check=True)


def _venv_bin_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir: Path) -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    python_path = _venv_bin_dir(venv_dir) / executable
    if not python_path.exists():
        raise FileNotFoundError(f"Python executable not found in virtual environment: {python_path}")
    return python_path


def _bustan_command(venv_dir: Path) -> list[str]:
    scripts_dir = _venv_bin_dir(venv_dir)
    candidates: tuple[tuple[str, bool], ...]
    if os.name == "nt":
        candidates = (
            ("bustan.exe", False),
            ("bustan.cmd", False),
            ("bustan-script.py", True),
            ("bustan", False),
        )
    else:
        candidates = (("bustan", False),)

    python_path = _venv_python(venv_dir)
    for filename, needs_python in candidates:
        path = scripts_dir / filename
        if not path.exists():
            continue
        if needs_python:
            return [str(python_path), str(path)]
        return [str(path)]

    raise FileNotFoundError(f"Bustan console entry point not found in virtual environment: {scripts_dir}")


def _write_smoke_pyproject(smoke_root: Path) -> None:
    (smoke_root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "smoke-app"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.13"\n'
        "dependencies = []\n\n"
        "[build-system]\n"
        'requires = ["uv_build"]\n'
        'build-backend = "uv_build"\n',
        encoding="utf-8",
    )


def _verify_scaffold(smoke_root: Path) -> None:
    required_paths = (
        smoke_root / "README.md",
        smoke_root / "src" / "smoke_app" / "__init__.py",
        smoke_root / "src" / "smoke_app" / "app_module.py",
        smoke_root / "src" / "smoke_app" / "app_controller.py",
        smoke_root / "src" / "smoke_app" / "app_service.py",
        smoke_root / "tests" / "smoke_app" / "test_app_controller.py",
        smoke_root / "tests" / "smoke_app" / "test_app_service.py",
        smoke_root / "tests" / "smoke_app" / "test_app_module.py",
    )
    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        missing = ", ".join(str(path.relative_to(smoke_root)) for path in missing_paths)
        raise FileNotFoundError(f"Scaffolded project is missing expected files: {missing}")

    pyproject_text = (smoke_root / "pyproject.toml").read_text(encoding="utf-8")
    expected_entries = ('start = "smoke_app:main"', 'dev = "smoke_app:dev"')
    missing_entries = [entry for entry in expected_entries if entry not in pyproject_text]
    if missing_entries:
        raise RuntimeError(f"Scaffolded project is missing expected pyproject entries: {missing_entries}")


def main() -> int:
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(SMOKE_VENV_DIR, ignore_errors=True)

    try:
        _run("uv", "build")

        distributions = sorted(
            [*DIST_DIR.glob("*.whl"), *DIST_DIR.glob("*.tar.gz")],
        )
        if not distributions:
            raise RuntimeError("No distributions were built.")
        _run("uvx", "--from", "twine", "twine", "check", *(str(path) for path in distributions))

        _run("uv", "run", "python", "-m", "venv", str(SMOKE_VENV_DIR))

        smoke_python = _venv_python(SMOKE_VENV_DIR)

        _run(str(smoke_python), "-m", "pip", "install", "--upgrade", "pip")

        wheels = sorted(DIST_DIR.glob("*.whl"))
        if not wheels:
            raise RuntimeError("No wheel artifact was built.")
        _run(str(smoke_python), "-m", "pip", "install", *(str(path) for path in wheels))
        bustan_command = _bustan_command(SMOKE_VENV_DIR)
        _run(str(smoke_python), "-c", "import bustan; print(bustan.__version__)")
        _run(*bustan_command, "--help")

        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_root = Path(temp_dir)
            _write_smoke_pyproject(smoke_root)
            _run(*bustan_command, "init", cwd=smoke_root)
            _verify_scaffold(smoke_root)

    finally:
        shutil.rmtree(SMOKE_VENV_DIR, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())