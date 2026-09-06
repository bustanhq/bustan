#!/usr/bin/env python3

"""Install the built distribution the way a user would, and check what they get.

Two environments are built, because the package makes two separate promises. The first
installs the wheel with no extras and is where the promise that ``bustan`` is not a web
server is either true or not: the kernel must import with neither Starlette nor Uvicorn
present, and asking it to serve HTTP must say which extra to install. The second
installs the ``starlette`` extra and is where the promise that a scaffolded project runs
is checked, because that project uses the adapter the extra brings.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
# Both environments live under the one directory the repository already ignores, so a
# run interrupted before its cleanup still leaves the working tree clean.
SMOKE_ROOT_DIR = ROOT / ".package-smoke"
KERNEL_VENV_DIR = SMOKE_ROOT_DIR / "no-extras"
SMOKE_VENV_DIR = SMOKE_ROOT_DIR / "starlette-extra"

# Run in the no-extras environment. Two separate claims: that nothing a plain install
# pulled in is a web server, and that no web server is installed at all, so a later
# import cannot quietly find one.
_KERNEL_IMPORT_CHECK = """
import sys

import bustan

web_servers = ("starlette", "uvicorn")

loaded = sorted({name.split(".")[0] for name in sys.modules}.intersection(web_servers))
if loaded:
    raise SystemExit(f"importing bustan loaded a web server: {loaded}")

for name in web_servers:
    try:
        __import__(name)
    except ModuleNotFoundError:
        continue
    raise SystemExit(f"{name} is installed in an environment that asked for no extras")

print(f"bustan {bustan.__version__} imported with no web server present")
"""

# Also run in the no-extras environment. What a reader sees is the deliverable here, so
# the message is printed as well as asserted.
_MISSING_EXTRA_CHECK = """
from bustan import Module, create_app


@Module()
class RootModule:
    pass


try:
    create_app(RootModule)
except ImportError as error:
    message = str(error)
else:
    raise SystemExit("create_app served HTTP with no web server installed")

for expected in ("Starlette", "pip install 'bustan[starlette]'", "adapter="):
    if expected not in message:
        raise SystemExit(f"the error does not mention {expected!r}: {message!r}")

print("create_app without the extra says:")
print(message)
"""

# Run in the environment that installed the extra, against the project the scaffolder
# just wrote. Building the application compiles its module graph, its controller and its
# routes, so a scaffold that no longer works fails here rather than at the user's first
# request.
_SCAFFOLD_RUNS_CHECK = """
import sys

sys.path.insert(0, "src")

from bustan import create_app

from smoke_app.app_module import AppModule

application = create_app(AppModule)
if not application.routes:
    raise SystemExit("the scaffolded application compiled no routes")

print(f"scaffolded application built with routes: {sorted(application.routes)}")
"""


def _run(*command: str, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd or ROOT, check=True)


def _venv_bin_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir: Path) -> Path:
    executable = "python.exe" if os.name == "nt" else "python"
    python_path = _venv_bin_dir(venv_dir) / executable
    if not python_path.exists():
        raise FileNotFoundError(
            f"Python executable not found in virtual environment: {python_path}"
        )
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

    raise FileNotFoundError(
        f"Bustan console entry point not found in virtual environment: {scripts_dir}"
    )


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
        raise RuntimeError(
            f"Scaffolded project is missing expected pyproject entries: {missing_entries}"
        )


def _build_venv(venv_dir: Path) -> Path:
    """Create a clean virtual environment and return the interpreter inside it."""

    shutil.rmtree(venv_dir, ignore_errors=True)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    _run("uv", "run", "python", "-m", "venv", str(venv_dir))
    venv_python = _venv_python(venv_dir)
    _run(str(venv_python), "-m", "pip", "install", "--upgrade", "pip")
    return venv_python


def _check_kernel_installs_without_a_web_server(wheel: Path) -> None:
    """Install the wheel with no extras and check what that install can and cannot do."""

    kernel_python = _build_venv(KERNEL_VENV_DIR)
    _run(str(kernel_python), "-m", "pip", "install", str(wheel))
    _run(str(kernel_python), "-c", _KERNEL_IMPORT_CHECK)
    _run(str(kernel_python), "-c", _MISSING_EXTRA_CHECK)
    _run(*_bustan_command(KERNEL_VENV_DIR), "--help")


def _check_scaffold_works_with_the_extra(wheel: Path) -> None:
    """Install the wheel with the starlette extra and scaffold a project against it."""

    smoke_python = _build_venv(SMOKE_VENV_DIR)
    _run(str(smoke_python), "-m", "pip", "install", f"{wheel}[starlette]")
    bustan_command = _bustan_command(SMOKE_VENV_DIR)
    _run(str(smoke_python), "-c", "import bustan; print(bustan.__version__)")
    _run(*bustan_command, "--help")

    with tempfile.TemporaryDirectory() as temp_dir:
        smoke_root = Path(temp_dir)
        _write_smoke_pyproject(smoke_root)
        _run(*bustan_command, "init", cwd=smoke_root)
        _verify_scaffold(smoke_root)
        _run(str(smoke_python), "-c", _SCAFFOLD_RUNS_CHECK, cwd=smoke_root)


def main() -> int:
    shutil.rmtree(DIST_DIR, ignore_errors=True)

    try:
        _run("uv", "build")

        distributions = sorted(
            [*DIST_DIR.glob("*.whl"), *DIST_DIR.glob("*.tar.gz")],
        )
        if not distributions:
            raise RuntimeError("No distributions were built.")
        _run("uvx", "--from", "twine", "twine", "check", *(str(path) for path in distributions))

        wheels = sorted(DIST_DIR.glob("*.whl"))
        if not wheels:
            raise RuntimeError("No wheel artifact was built.")
        if len(wheels) > 1:
            raise RuntimeError(f"Expected one wheel artifact, found {len(wheels)}.")
        wheel = wheels[0]

        _check_kernel_installs_without_a_web_server(wheel)
        _check_scaffold_works_with_the_extra(wheel)

    finally:
        shutil.rmtree(SMOKE_ROOT_DIR, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
