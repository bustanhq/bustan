"""Config service implementation."""

from __future__ import annotations

from typing import Any


class ConfigService:
    """Typed access to resolved configuration values."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def get_or_throw(self, key: str) -> Any:
        if key not in self._values:
            raise KeyError(f"Configuration key {key!r} is not defined")
        return self._values[key]
