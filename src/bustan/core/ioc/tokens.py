"""Typed tokens for dependency injection."""

from __future__ import annotations


class InjectionToken[T]:
    """A typed token representing a dependency for injection.

    A token is its own identity: two tokens are the same token only when they are the
    same object, so build each one once at module level and import it wherever it is
    declared, injected or overridden. The name is what the token is called in errors;
    the container never matches two tokens by comparing names.
    """

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"InjectionToken({self.name!r})"


APP_GUARD = InjectionToken("APP_GUARD")
APP_PIPE = InjectionToken("APP_PIPE")
APP_INTERCEPTOR = InjectionToken("APP_INTERCEPTOR")
APP_FILTER = InjectionToken("APP_FILTER")
REQUEST = InjectionToken("REQUEST")
RESPONSE = InjectionToken("RESPONSE")
APPLICATION = InjectionToken("APPLICATION")
INQUIRER = InjectionToken("INQUIRER")
