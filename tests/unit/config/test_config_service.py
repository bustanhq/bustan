"""Unit tests for config service accessors."""

from __future__ import annotations

import pytest

from bustan.config.config_service import ConfigService


def test_config_service_get_and_get_or_throw() -> None:
    service = ConfigService({"APP_NAME": "bustan"})

    assert service.get("APP_NAME") == "bustan"
    assert service.get("MISSING", "fallback") == "fallback"
    assert service.get_or_throw("APP_NAME") == "bustan"

    with pytest.raises(KeyError):
        service.get_or_throw("MISSING")
