"""Turn a class's constructor annotations into the list of dependencies it needs.

This is a pure function of the class and the tokens visible to it. It reads no
container, no registry and no request, so the result can be computed once while the
application is booting and reused for every construction afterwards.
"""

from __future__ import annotations

import inspect
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ForwardRef, Union, get_args, get_origin

from ....common.decorators.injectable import InjectMarker, OptionalDependencyMarker
from ...errors import ProviderResolutionError
from ...utils import _qualname
from ..tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

__all__ = ["ConstructorDependency", "plan_constructor_dependencies"]

# Tokens the container itself supplies. They are never declared by a module, so
# visibility says nothing about them and a parameter asking for one is always planned.
_CONTAINER_TOKENS: tuple[object, ...] = (APPLICATION, INQUIRER, REQUEST, RESPONSE)

# A quoted annotation under postponed evaluation needs two rounds; the bound only
# exists so that a name resolving to its own spelling terminates.
_MAX_DEREFERENCE_ROUNDS = 8

_POSITIONAL_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)
_VARIADIC_KINDS = (
    inspect.Parameter.VAR_POSITIONAL,
    inspect.Parameter.VAR_KEYWORD,
)


@dataclass(frozen=True, slots=True)
class ConstructorDependency:
    """One constructor parameter and the token that has to satisfy it.

    ``token`` is what the caller resolves: the evaluated annotation, or the token
    named by an ``Inject`` marker when one is present. ``annotation`` is the
    evaluated annotation with ``Annotated`` metadata and any ``None`` union member
    stripped off, kept for error messages. ``optional`` means the caller may pass
    ``None`` when the token resolves to nothing. ``positional`` means the value must
    be passed positionally; anything else is passed by keyword.
    """

    name: str
    token: object
    annotation: object
    optional: bool
    positional: bool


@dataclass(frozen=True, slots=True)
class _Requirement:
    """What a single parameter's annotation asks for, once interpreted."""

    token: object
    annotation: object
    optional: bool


class _ConstructorNamespace(Mapping[str, object]):
    """Resolves a name in a constructor annotation the way Python itself would.

    The module that defines the constructor is consulted first, so an inherited
    ``__init__`` is read in the namespace it was written in rather than the
    subclass's. Only a name that module does not define falls through to the visible
    tokens, and a name that two visible tokens both claim is reported as ambiguous
    rather than guessed at.

    The defining module's globals are read lazily, because a constructor that has no
    annotations to evaluate - one implemented in C, for instance - has no globals to
    offer and must not be asked for them.
    """

    def __init__(
        self, constructor: Callable[..., object], visible_tokens: Collection[object]
    ) -> None:
        self._constructor = constructor
        self._lexical_scope: dict[str, object] | None = None
        self._tokens_by_name = _index_tokens_by_name(visible_tokens)

    def __getitem__(self, name: str) -> object:
        lexical = self._lexical()
        if name in lexical:
            return lexical[name]

        candidates = self._tokens_by_name.get(name, [])
        if not candidates:
            raise KeyError(name)
        if len(candidates) > 1:
            named = ", ".join(sorted(_qualname(candidate) for candidate in candidates))
            raise ProviderResolutionError(
                f"the name {name!r} is ambiguous between {named}, and the module declaring "
                "the constructor does not define it"
            )
        return candidates[0]

    def __iter__(self) -> Iterator[str]:
        lexical = self._lexical()
        yield from lexical
        yield from (name for name in self._tokens_by_name if name not in lexical)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def _lexical(self) -> dict[str, object]:
        if self._lexical_scope is None:
            self._lexical_scope = getattr(self._constructor, "__globals__", {})
        return self._lexical_scope


def _index_tokens_by_name(visible_tokens: Collection[object]) -> dict[str, list[type[object]]]:
    """Group the visible classes by their bare name, keeping every same-named claimant."""

    by_name: dict[str, list[type[object]]] = {}
    for token in visible_tokens:
        if not isinstance(token, type):
            continue
        candidates = by_name.setdefault(token.__name__, [])
        if not any(token is candidate for candidate in candidates):
            candidates.append(token)
    return by_name


def plan_constructor_dependencies(
    target: type[object],
    visible_tokens: Collection[object] = (),
) -> tuple[ConstructorDependency, ...]:
    """List the dependencies ``target`` needs, in constructor parameter order.

    ``visible_tokens`` is everything the module owning ``target`` can see, which is
    used for two things: resolving an annotation naming a class the constructor's own
    module does not import, and deciding that a parameter with a default cannot be
    satisfied and should be left to that default. Pass the module's visibility
    mapping, or any collection of tokens.

    A parameter left to its default is absent from the result, so the caller passes
    nothing for it and Python applies the default. Every other parameter appears
    exactly once. Raises ``ProviderResolutionError`` when the constructor cannot be
    read, an annotation cannot be evaluated, or the annotation is ambiguous.
    """

    constructor = _select_constructor(target)
    if constructor is None:
        return ()

    namespace = _ConstructorNamespace(constructor, visible_tokens)
    dependencies: list[ConstructorDependency] = []
    left_to_default = False

    for parameter in _injectable_parameters(target, constructor):
        requirement = _requirement_for(target, parameter, namespace)
        if requirement is None or (
            _has_default(parameter) and not _is_satisfiable(requirement.token, visible_tokens)
        ):
            left_to_default = True
            continue
        dependencies.append(
            _dependency_for(target, parameter, requirement, after_default=left_to_default)
        )

    return tuple(dependencies)


def _select_constructor(target: type[object]) -> Callable[..., object] | None:
    """Return the callable whose parameters describe how ``target`` is built.

    A class that overrides ``__new__`` and inherits ``object.__init__`` declares its
    dependencies on ``__new__``, so that is where the plan comes from.
    """

    initializer = target.__init__
    if initializer is not object.__init__:
        return initializer

    allocator = target.__new__
    if allocator is not object.__new__:
        return allocator

    return None


def _injectable_parameters(
    target: type[object], constructor: Callable[..., object]
) -> tuple[inspect.Parameter, ...]:
    """Return the constructor's parameters without the instance or class parameter.

    The first parameter is dropped by position rather than by the name ``self``,
    because the name is a convention and a constructor is free to spell it otherwise.
    """

    try:
        signature = inspect.signature(constructor)
    except (TypeError, ValueError) as exc:
        raise ProviderResolutionError(
            f"Could not read the constructor of {_qualname(target)}: {exc}"
        ) from exc

    parameters = list(signature.parameters.values())
    if parameters and parameters[0].kind in _POSITIONAL_KINDS:
        parameters.pop(0)

    for parameter in parameters:
        if parameter.kind in _VARIADIC_KINDS:
            raise ProviderResolutionError(
                f"Could not read the constructor of {_qualname(target)}: parameter "
                f"{parameter.name!r} is variadic and cannot be injected"
            )

    return tuple(parameters)


def _requirement_for(
    target: type[object],
    parameter: inspect.Parameter,
    namespace: _ConstructorNamespace,
) -> _Requirement | None:
    """Interpret one parameter, or return ``None`` when it is left to its default."""

    if parameter.annotation is inspect.Parameter.empty:
        if _has_default(parameter):
            return None
        raise ProviderResolutionError(
            f"{_qualname(target)} constructor parameter {parameter.name!r} has no type "
            "annotation, so there is nothing to inject"
        )

    return _interpret(target, parameter.name, parameter.annotation, namespace)


def _dereference(
    target: type[object],
    parameter_name: str,
    annotation: object,
    namespace: _ConstructorNamespace,
) -> object:
    """Evaluate source text or a forward reference until it names a real object.

    ``from __future__ import annotations`` turns every annotation into source text, so
    an annotation that was already quoted arrives quoted twice and has to be evaluated
    more than once. The number of rounds is bounded because a name that resolves to
    its own spelling would otherwise loop forever.
    """

    value = annotation
    for _round in range(_MAX_DEREFERENCE_ROUNDS):
        if isinstance(value, str):
            source = value
        elif isinstance(value, ForwardRef):
            source = value.__forward_arg__
        else:
            return value

        try:
            # Empty globals force every name through the namespace, which is what
            # gives the defining module precedence over the visible tokens.
            value = eval(source, {}, namespace)
        except Exception as exc:
            raise ProviderResolutionError(
                f"Could not evaluate the annotation of {_qualname(target)} constructor "
                f"parameter {parameter_name!r}: {exc}"
            ) from exc

    raise ProviderResolutionError(
        f"Could not evaluate the annotation of {_qualname(target)} constructor parameter "
        f"{parameter_name!r}: it never resolves to anything but another name"
    )


def _interpret(
    target: type[object],
    parameter_name: str,
    annotation: object,
    namespace: _ConstructorNamespace,
) -> _Requirement:
    """Strip ``Annotated`` metadata and a ``None`` union member off an annotation."""

    markers: list[InjectMarker] = []
    optional = False
    current = annotation

    while True:
        current = _dereference(target, parameter_name, current, namespace)

        if get_origin(current) is Annotated:
            arguments = get_args(current)
            current = arguments[0]
            for marker in arguments[1:]:
                if isinstance(marker, InjectMarker):
                    markers.append(marker)
                elif isinstance(marker, OptionalDependencyMarker):
                    optional = True
            continue

        members = _union_members_without_none(current)
        if members is None:
            break

        optional = True
        if len(members) != 1:
            raise ProviderResolutionError(
                f"{_qualname(target)} constructor parameter {parameter_name!r} is annotated "
                "with a union that does not name exactly one type to inject"
            )
        current = members[0]

    if len(markers) > 1:
        raise ProviderResolutionError(
            f"{_qualname(target)} constructor parameter {parameter_name!r} carries "
            f"{len(markers)} Inject markers, so the token to inject is ambiguous"
        )

    token = markers[0].token if markers else current
    return _Requirement(token=token, annotation=current, optional=optional)


def _union_members_without_none(annotation: object) -> tuple[object, ...] | None:
    """Return a union's non-``None`` members, or ``None`` if this is not such a union."""

    origin = get_origin(annotation)
    if origin is not Union and origin is not types.UnionType:
        return None

    arguments = get_args(annotation)
    members = tuple(argument for argument in arguments if argument is not types.NoneType)
    if len(members) == len(arguments):
        return None
    return members


def _dependency_for(
    target: type[object],
    parameter: inspect.Parameter,
    requirement: _Requirement,
    *,
    after_default: bool,
) -> ConstructorDependency:
    """Build the planned dependency, deciding how its value has to be passed."""

    if after_default:
        # An earlier parameter is being left to its default, so its slot is empty and
        # nothing after it can still be passed positionally.
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise ProviderResolutionError(
                f"{_qualname(target)} constructor parameter {parameter.name!r} is "
                "positional-only and follows a parameter left to its default, so it "
                "cannot be supplied"
            )
        positional = False
    else:
        positional = parameter.kind in _POSITIONAL_KINDS

    return ConstructorDependency(
        name=parameter.name,
        token=requirement.token,
        annotation=requirement.annotation,
        optional=requirement.optional,
        positional=positional,
    )


def _has_default(parameter: inspect.Parameter) -> bool:
    return parameter.default is not inspect.Parameter.empty


def _is_satisfiable(token: object, visible_tokens: Collection[object]) -> bool:
    """Report whether anything could supply ``token``, ignoring runtime overrides."""

    if any(token is container_token for container_token in _CONTAINER_TOKENS):
        return True
    try:
        return token in visible_tokens
    except TypeError:
        # An unhashable annotation cannot be a key in a visibility mapping.
        return False
