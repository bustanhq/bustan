"""Shared type definitions and protocols for the framework."""

from __future__ import annotations

from collections.abc import Callable
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
class ClassProvider:
    """Bind a token to a class the container constructs for it.

    Leave ``scope`` unset to take the lifetime the class itself declares. A lifetime
    named here may narrow that one but never widen it, because a wider lifetime keeps
    one caller's state on an instance that outlives them.
    """

    provide: object
    use_class: type[object]
    scope: ProviderScope | None = None


@dataclass(frozen=True, slots=True)
class FactoryProvider:
    """Bind a token to a callable the container calls to build the value.

    ``inject`` names the tokens to resolve and pass as positional arguments, in the
    order the callable takes them. Writing a single token needs a one-element tuple:
    the callable is given each entry of the sequence, never the sequence itself.
    """

    provide: object
    use_factory: Callable[..., object]
    inject: tuple[object, ...] = ()
    scope: ProviderScope | None = None


@dataclass(frozen=True, slots=True)
class ValueProvider:
    """Bind a token to one object that already exists.

    The object is handed to every consumer as it is written, so it names no lifetime:
    there is one of it for as long as the application runs.
    """

    provide: object
    use_value: object


@dataclass(frozen=True, slots=True)
class ExistingProvider:
    """Bind a token as a second name for a token another provider already binds.

    An alias holds nothing of its own and names no lifetime, so what a consumer gets is
    whatever the token it points at would have handed them.
    """

    provide: object
    use_existing: object


# The four ways to declare a provider beside naming a class. Which arm a declaration is
# says which target it binds and which of ``scope`` and ``inject`` it may carry, so a
# declaration that names two targets, or none, or a key no arm has, is not writable.
type ProviderDefinition = ClassProvider | FactoryProvider | ValueProvider | ExistingProvider

# A class named on its own binds under its own identity with the lifetime it declares,
# which is the shortest declaration and the one most providers use.
type Provider = type[object] | ProviderDefinition


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
