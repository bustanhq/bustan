"""Shared type definitions and protocols for the framework."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

# Shared by the decorator modules, which preserve the decorated class's own type.
ClassT = TypeVar("ClassT", bound=type[object])
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


class PipelineOverrides[MetadataT](Protocol):
    """A source of replacements for the pipeline components a route declared.

    A test assembles an application with substitutes for some of its guards, pipes,
    interceptors or filters, and the registry holding them is threaded through route
    compilation to the point where a pipeline is resolved. Compilation neither builds
    that registry nor reads anything else on it, so this one call is all it asks for,
    and asking for only this is what keeps route compilation independent of the test
    support that assembles applications on top of it.

    ``MetadataT`` is the pipeline metadata of whoever is compiling: a replacement is
    substituted into the declaration and the same kind of declaration comes back.
    """

    def apply_to_metadata(self, metadata: MetadataT) -> MetadataT:
        """Return the metadata with each component that has a replacement replaced."""

        raise NotImplementedError


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
