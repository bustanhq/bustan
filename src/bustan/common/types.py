"""Shared type definitions and protocols for the framework."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar
from dataclasses import dataclass

T = TypeVar("T")
ClassT = TypeVar("ClassT", bound=type[object])
DecoratedT = TypeVar("DecoratedT", bound=object)
HostInput = str | list[str] | tuple[str, ...]


class ProviderScope(StrEnum):
    """Supported provider lifetimes."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    REQUEST = "request"
    DURABLE = "durable"


@dataclass(frozen=True, slots=True)
class ControllerMetadata:
    """Static metadata captured from a @Controller declaration."""

    prefix: str = ""
    scope: ProviderScope = ProviderScope.SINGLETON
    version: str | list[str] | None = None
    hosts: tuple[str, ...] = ()
    binding_mode: str = "infer"
    validation_mode: str = "auto"
    validate_custom_decorators: bool = False


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    """Static metadata captured from an HTTP method decorator."""

    method: str
    path: str
    name: str
    version: str | list[str] | None = None
    hosts: tuple[str, ...] = ()


def normalize_hosts(value: HostInput | None) -> tuple[str, ...]:
    """Normalize one or many declared route hosts into a stable tuple."""

    if value is None:
        return ()

    raw_hosts = (value,) if isinstance(value, str) else tuple(value)
    normalized_hosts: list[str] = []
    for raw_host in raw_hosts:
        if not isinstance(raw_host, str):
            raise ValueError("Host metadata must be a string or collection of strings")

        normalized_host = raw_host.strip()
        if not normalized_host:
            raise ValueError("Host metadata cannot contain empty values")
        if normalized_host not in normalized_hosts:
            normalized_hosts.append(normalized_host)

    return tuple(normalized_hosts)
