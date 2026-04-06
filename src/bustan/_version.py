"""Version helpers for the published package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

PACKAGE_NAME = "bustan"
DEFAULT_VERSION = "0.0.0"
PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def get_installed_version(*, default: str = DEFAULT_VERSION) -> str:
    """Return the installed distribution version when available.

    Falling back to a baked default keeps local editable imports working even
    before the package has been built or installed into the active environment.
    """

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return _read_local_version() or default


def _read_local_version() -> str | None:
    """Return the project version from pyproject.toml when available."""

    try:
        pyproject_data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None

    project_data = pyproject_data.get("project")
    if not isinstance(project_data, dict):
        return None

    version_value = project_data.get("version")
    return version_value if isinstance(version_value, str) else None


__version__ = get_installed_version()
