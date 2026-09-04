"""The immutable description of how the container builds each class it knows about.

A plan is produced once, while the application is booting, and read on every
construction afterwards. It carries no runtime state and no reflection: each argument
already names either a token to resolve, a value the runtime owns for the call in
flight, or a constant. Executing one is therefore a walk over a tuple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE
from .scopes import ScopeDependency

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ...module.dynamic import ModuleKey

__all__ = [
    "ActiveApplication",
    "ActiveInquirer",
    "ActiveRequest",
    "ActiveResponse",
    "CONTAINER_TOKEN_SOURCES",
    "ArgumentSource",
    "ConstructionPlan",
    "ContainerPlan",
    "FixedValue",
    "PlannedArgument",
    "ProvidedToken",
    "TargetKey",
]

# A class is planned once per module that can build it, because what a name in its
# constructor resolves to depends on what that module can see.
type TargetKey = tuple[ModuleKey, type[object]]


@dataclass(frozen=True, slots=True)
class ProvidedToken:
    """A dependency the container resolves through the binding table."""

    token: object


@dataclass(frozen=True, slots=True)
class FixedValue:
    """A value settled while planning, used for an optional dependency nothing supplies."""

    value: object


@dataclass(frozen=True, slots=True)
class ActiveRequest:
    """The request currently being served."""


@dataclass(frozen=True, slots=True)
class ActiveResponse:
    """The response being assembled for the request currently being served."""


@dataclass(frozen=True, slots=True)
class ActiveApplication:
    """The running application."""


@dataclass(frozen=True, slots=True)
class ActiveInquirer:
    """The class whose construction asked for the owner of this argument."""


type ArgumentSource = (
    ProvidedToken | FixedValue | ActiveRequest | ActiveResponse | ActiveApplication | ActiveInquirer
)


# The tokens the container answers itself. No module declares them, so they are never
# looked up in the binding table and visibility says nothing about them.
CONTAINER_TOKEN_SOURCES: tuple[tuple[object, ArgumentSource], ...] = (
    (REQUEST, ActiveRequest()),
    (RESPONSE, ActiveResponse()),
    (APPLICATION, ActiveApplication()),
    (INQUIRER, ActiveInquirer()),
)


@dataclass(frozen=True, slots=True)
class PlannedArgument:
    """One constructor argument, and where its value comes from.

    ``positional`` decides how the value reaches the constructor. An argument the
    planner left to its parameter's default is absent from the plan entirely.
    """

    name: str
    positional: bool
    source: ArgumentSource


@dataclass(frozen=True, slots=True)
class ConstructionPlan:
    """Everything needed to build one class, with nothing left to look up.

    ``held`` names what an instance of this class keeps hold of once it is built,
    which is what the scope rules are applied to. It omits the arguments settled to a
    constant, because those tie the instance to nothing.
    """

    target: type[object]
    module: ModuleKey
    arguments: tuple[PlannedArgument, ...]
    held: tuple[ScopeDependency, ...] = ()


@dataclass(frozen=True, slots=True)
class ContainerPlan:
    """The plan for every class the container can build, keyed by module and class."""

    constructions: Mapping[TargetKey, ConstructionPlan]

    def for_target(self, module: ModuleKey, target: type[object]) -> ConstructionPlan | None:
        """Return the plan for building ``target`` inside ``module``, if there is one."""

        return self.constructions.get((module, target))
