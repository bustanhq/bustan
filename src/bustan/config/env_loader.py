"""Environment loading helpers for the config module."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(
    env_file: str | list[str] | None = None,
    *,
    ignore_env_file: bool = False,
) -> dict[str, str]:
    """Load environment variables from files and the process environment."""
    loaded: dict[str, str] = {}
    if not ignore_env_file and env_file:
        files = [env_file] if isinstance(env_file, str) else env_file
        for file_name in files:
            loaded.update(_load_env_file(Path(file_name)))

    loaded.update(os.environ)
    return loaded


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values
