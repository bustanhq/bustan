"""Unit tests for injection tokens."""

from __future__ import annotations
from bustan.core.ioc.tokens import InjectionToken


def test_injection_token_repr() -> None:
    token = InjectionToken("MyService")
    assert token.name == "MyService"
    assert repr(token) == "InjectionToken('MyService')"
