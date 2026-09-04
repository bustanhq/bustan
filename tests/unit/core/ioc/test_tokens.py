"""Unit tests for injection tokens."""

from __future__ import annotations

from bustan import Module, create_app_context
from bustan.core.ioc.tokens import InjectionToken


def test_injection_token_repr() -> None:
    token = InjectionToken("MyService")
    assert token.name == "MyService"
    assert repr(token) == "InjectionToken('MyService')"


def test_two_tokens_of_the_same_name_are_two_tokens() -> None:
    # The name is what a token is called, not what it is, so a token built twice is two
    # tokens and a provider declared under one is invisible to the other.
    first = InjectionToken("CONFIG")
    second = InjectionToken("CONFIG")

    assert first != second
    assert len({first, second}) == 2

    @Module(providers=[{"provide": first, "use_value": "declared"}])
    class AppModule:
        pass

    context = create_app_context(AppModule)

    assert context.get(first) == "declared"
    assert context.container.has_override(second) is False


def test_one_token_is_the_same_token_wherever_it_is_written() -> None:
    token = InjectionToken("CONFIG")

    @Module(providers=[{"provide": token, "use_value": "declared"}], exports=[token])
    class SharedModule:
        pass

    @Module(imports=[SharedModule])
    class AppModule:
        pass

    context = create_app_context(AppModule)

    assert context.get(token) == "declared"
