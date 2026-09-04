"""The alphabet the construction machine speaks and the caches it reads.

Construction is written once, as a generator that yields the steps it cannot take by
itself. Two drivers take those steps: one synchronously, one awaiting. Everything that
decides *what* happens - the cache probe, the cycle check, the order of arguments -
therefore exists in exactly one place, and the drivers differ only in how they wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..scopes import CACHE_MISS

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, MutableMapping

    from ...module.dynamic import ModuleKey

__all__ = ["Guarded", "InstanceCache", "Invoke", "Machine", "Resolve", "Site", "Step"]


@dataclass(frozen=True, slots=True)
class Site:
    """Who asked for a value and where, so a failure deep in a graph names its origin.

    ``owner`` names the constructor or factory, ``detail`` the place inside it, for
    example ``parameter 'clock'``.
    """

    owner: str
    detail: str

    def __str__(self) -> str:
        return f"{self.owner} {self.detail}"


@dataclass(frozen=True, slots=True)
class Resolve:
    """Resolve a token, as seen from one module."""

    token: object
    module: ModuleKey
    site: Site


@dataclass(frozen=True, slots=True)
class Invoke:
    """Call a factory with arguments that are already resolved."""

    factory: Callable[..., object]
    arguments: tuple[object, ...]
    label: str


@dataclass(frozen=True, slots=True)
class Guarded:
    """Run a machine while holding the construction lock for one cached instance.

    The lock keeps two callers from building and caching the same shared instance
    twice, which would leave one of the two orphaned in whichever caller lost.
    """

    key: object
    machine: Machine


type Step = Resolve | Invoke | Guarded

# A construction in progress: it yields the steps it needs taken, is sent each
# result, and finally returns the instance it built.
type Machine = Generator[Step, object, object]


@dataclass(frozen=True, slots=True)
class InstanceCache:
    """The slot one binding's instance is kept in, or nothing for a transient.

    ``shared`` marks a slot that outlives the caller filling it, which is exactly the
    condition under which construction has to be serialized.
    """

    store: MutableMapping[Any, object] | None
    key: object
    shared: bool

    def get(self) -> object:
        """Return the cached instance, or ``CACHE_MISS`` when the slot is empty."""

        if self.store is None:
            return CACHE_MISS
        return self.store.get(self.key, CACHE_MISS)

    def set(self, instance: object) -> None:
        """Keep an instance for every later caller this slot serves."""

        if self.store is not None:
            self.store[self.key] = instance


NO_CACHE = InstanceCache(store=None, key=None, shared=False)
