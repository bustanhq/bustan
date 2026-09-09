"""Plan every class a module graph can build, and refuse the graph if any of them cannot.

This is the whole of the container's bootstrap-time reasoning. It reads the binding
table, the per-module visibility map and the controllers, and produces one immutable
construction plan per class. Along the way it answers the two questions that used to
be answered on a live request: can every dependency be found, and may its owner hold
it for as long as the owner lives.

Both answers are collected rather than raised. An author who has made five mistakes
across a graph should see five messages, not fix one and redeploy to discover the
next, so a graph that fails is reported once with every reason it failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ....common.constants import BUSTAN_CONTROLLER_ATTR
from ....common.types import ControllerMetadata, ProviderScope
from ....contracts import HttpRequest, HttpResponse, names_native_request
from ...errors import InvalidControllerError, ProviderResolutionError
from ...utils import _display_name, _get_metadata, _qualname
from ..registry import Binding, BindingTable
from .annotations import ConstructorDependency, plan_constructor_dependencies
from .plan import (
    CONTAINER_TOKEN_SOURCES,
    ActiveRequest,
    ActiveResponse,
    ArgumentSource,
    ConstructionPlan,
    ContainerPlan,
    FixedValue,
    PlannedArgument,
    ProvidedToken,
    TargetKey,
)
from .scopes import BindingKey, ScopeDependency, plan_scopes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ...module.dynamic import ModuleKey

__all__ = [
    "NativeRequestDependency",
    "controller_scope",
    "native_request_dependencies",
    "plan_container",
    "plan_target",
]

# A parameter may name the state the container owns either by token or by the
# contract type standing for it, and both spellings plan to the same argument.
_CONTAINER_SOURCES: tuple[tuple[object, ArgumentSource], ...] = (
    *CONTAINER_TOKEN_SOURCES,
    (HttpRequest, ActiveRequest()),
    (HttpResponse, ActiveResponse()),
)


@dataclass(frozen=True, slots=True)
class NativeRequestDependency:
    """One constructor parameter that named its transport's own request object.

    ``target`` is the class whose constructor asked for it, ``parameter`` is the name it
    was written on, and ``annotation`` is the request type it named. Such a parameter is
    handed the transport's object rather than the neutral contract wrapped around it, so
    the annotation is true only under the transport that builds what it named. Which
    transport that is cannot be settled while the plan is built, so the plan reports the
    claim and whoever holds the serving adapter holds the parameter to it.
    """

    target: type[object]
    parameter: str
    annotation: object


def controller_scope(controller_cls: type[object]) -> ProviderScope:
    """Return the lifetime a controller is cached at, which defaults to singleton.

    Raises ``InvalidControllerError`` for a lifetime no controller can be served
    under. A durable instance is selected by a context key, and a controller is
    cached per module rather than per key, so nothing can hold that lifetime. The
    module graph refuses such a declaration before any of this runs; returning it
    here anyway would enter the controller into the scope table as a durable owner
    and report the defect against a constructor parameter, which is one line below
    the declaration that is actually wrong and cannot be edited to fix it.
    """

    metadata = _get_metadata(controller_cls, BUSTAN_CONTROLLER_ATTR, inherit=False)
    if not isinstance(metadata, ControllerMetadata):
        return ProviderScope.SINGLETON
    if metadata.scope is ProviderScope.DURABLE:
        raise InvalidControllerError(
            f"{_qualname(controller_cls)} declares scope {metadata.scope.value!r}, which a "
            "controller cannot have; declare a singleton, request or transient controller "
            "and keep the per-key state in a durable provider"
        )
    return metadata.scope


def plan_container(
    *,
    bindings: Mapping[BindingKey, Binding],
    visibility: Mapping[ModuleKey, Mapping[object, ModuleKey]],
    controllers: Mapping[type[object], ModuleKey],
) -> ContainerPlan:
    """Plan every class in the graph, or refuse the graph naming every reason at once.

    ``bindings`` is the binding table keyed by declaring module and token,
    ``visibility`` maps each module to the module declaring every token it can see,
    and ``controllers`` names the module each controller belongs to. Raises
    ``ProviderResolutionError`` listing every dependency that cannot be found and
    every one its owner would outlive.
    """

    plans: dict[TargetKey, ConstructionPlan] = {}
    dependencies: dict[type[object], tuple[ScopeDependency, ...]] = {}
    failures: list[str] = []
    attempted: set[TargetKey] = set()

    for module, target in _planning_targets(bindings, controllers):
        if (module, target) in attempted:
            continue
        attempted.add((module, target))
        plan = _plan_target(target, module, visibility.get(module, {}), failures)
        if plan is None:
            continue
        plans[(module, target)] = plan
        dependencies.setdefault(target, plan.held)

    scope_plan = plan_scopes(
        _scope_bindings(bindings, controllers),
        visibility=visibility,
        class_dependencies=dependencies,
    )
    failures.extend(violation.message for violation in scope_plan.violations)

    if failures:
        raise _refusal(failures)
    return ContainerPlan(constructions=MappingProxyType(plans))


def plan_target(
    target: type[object],
    module: ModuleKey,
    visible: Mapping[object, ModuleKey],
) -> ConstructionPlan:
    """Plan one class the module graph does not declare, such as a test replacement.

    ``visible`` is what the module building it can see. Raises
    ``ProviderResolutionError`` naming every argument that cannot be settled.
    """

    failures: list[str] = []
    plan = _plan_target(target, module, visible, failures)
    if plan is None:
        raise _refusal(failures)
    return plan


def native_request_dependencies(plan: ContainerPlan) -> tuple[NativeRequestDependency, ...]:
    """Return every constructor parameter a plan settles to the transport's own request.

    The plan is built before any transport adapter exists, so which transport such a
    parameter named cannot be judged while it is planned: there is nothing yet to
    compare the annotation against. What the plan can report is which parameters made
    the claim and what each of them named, which is what the check against the serving
    adapter is made from once that adapter is known.

    One entry is returned per parameter. A class more than one module can build is
    planned once per module and those plans name the same parameters, so one mistake is
    reported once rather than once per module that could have made it.
    """

    found: dict[NativeRequestDependency, None] = {}
    for construction in plan.constructions.values():
        asked_for = _tokens_by_site(construction)
        for argument in construction.arguments:
            source = argument.source
            if not isinstance(source, ActiveRequest) or not source.native:
                continue
            found[
                NativeRequestDependency(
                    target=construction.target,
                    parameter=argument.name,
                    annotation=asked_for[_parameter_site(argument.name)],
                )
            ] = None
    return tuple(found)


def _tokens_by_site(construction: ConstructionPlan) -> Mapping[str, object]:
    """Return what each of a plan's arguments asked for, keyed by where it asked.

    A planned argument records where its value comes from and not what was written to
    ask for it, so the token an author wrote survives only in what the built instance is
    charged with holding. Every argument but one settled to a constant is charged, and a
    parameter name is unique within the constructor declaring it, so an argument this
    does not answer for is one that holds nothing.
    """

    return {dependency.site: dependency.token for dependency in construction.held}


def _parameter_site(name: str) -> str:
    """Return how a constructor parameter is named where one is reported."""

    return f"parameter {name!r}"


def _planning_targets(
    bindings: Mapping[BindingKey, Binding],
    controllers: Mapping[type[object], ModuleKey],
) -> tuple[TargetKey, ...]:
    """Return every class the graph can build, paired with the module that builds it."""

    targets: list[TargetKey] = [
        (key[0], binding.target)
        for key, binding in bindings.items()
        if binding.resolver_kind == "class" and isinstance(binding.target, type)
    ]
    targets.extend((module, controller) for controller, module in controllers.items())
    return tuple(targets)


def _plan_target(
    target: type[object],
    module: ModuleKey,
    visible: Mapping[object, ModuleKey],
    failures: list[str],
) -> ConstructionPlan | None:
    """Plan one class, appending a message for every argument that cannot be settled."""

    try:
        dependencies = plan_constructor_dependencies(target, visible)
    except ProviderResolutionError as exc:
        failures.append(str(exc))
        return None

    arguments: list[PlannedArgument] = []
    held: list[ScopeDependency] = []
    planned = True
    for dependency in dependencies:
        settled = _source_for(dependency, visible)
        if settled is None:
            failures.append(_unsatisfied_message(target, module, dependency))
            planned = False
            continue
        charged, source = settled
        arguments.append(
            PlannedArgument(name=dependency.name, positional=dependency.positional, source=source)
        )
        if not isinstance(source, FixedValue):
            held.append(ScopeDependency(token=charged, site=_parameter_site(dependency.name)))

    if not planned:
        return None
    return ConstructionPlan(
        target=target, module=module, arguments=tuple(arguments), held=tuple(held)
    )


def _source_for(
    dependency: ConstructorDependency, visible: Mapping[object, ModuleKey]
) -> tuple[object, ArgumentSource] | None:
    """Decide where one parameter's value comes from, or return ``None`` if nothing can.

    The token returned beside the source is the one the parameter is charged with for
    the scope rules, which is the spelling the author actually wrote: an error about a
    parameter declared ``Inject(REQUEST)`` names REQUEST and not ``HttpRequest``. A
    parameter with no Inject marker is charged with its annotation, because the planner
    reports the evaluated annotation as the token in that case.

    A parameter naming the transport's own request type is settled after the binding
    table rather than before it, so a provider registered under such a class is still
    resolved from the table and only a class nothing declares is read as that request.
    Which transport it named is not settled here at all: the plan is built before an
    adapter exists, so the annotation is held to the adapter that will serve once that
    adapter is known and before it is asked to serve anything.
    """

    for candidate, source in _CONTAINER_SOURCES:
        if dependency.token is candidate:
            return dependency.token, source
    if _is_visible(dependency.token, visible):
        return dependency.token, ProvidedToken(dependency.token)
    if names_native_request(dependency.token):
        return dependency.token, ActiveRequest(native=True)
    if dependency.optional:
        # The planner sees no binding and there can be no override for a token nothing
        # declares, so the parameter is settled here rather than probed on every build.
        return dependency.token, FixedValue(None)
    return None


def _is_visible(token: object, visible: Mapping[object, ModuleKey]) -> bool:
    try:
        return token in visible
    except TypeError:
        # An unhashable annotation cannot be a key in a visibility mapping.
        return False


def _scope_bindings(
    bindings: Mapping[BindingKey, Binding],
    controllers: Mapping[type[object], ModuleKey],
) -> Mapping[BindingKey, Binding]:
    """Return the binding table with each controller added as the class binding it is.

    A controller is cached exactly the way a provider of the same scope is cached, so
    the scope rules have to reach it. It is keyed by its own class, which no module
    declares as a token, so it can never shadow a real binding.

    The merged table keys tokens the way the binding table does, so two equal tokens of
    different types stay two bindings here as well.
    """

    merged = BindingTable()
    merged.update(bindings)
    for controller, module in controllers.items():
        key = (module, controller)
        merged.setdefault(
            key,
            Binding(
                token=controller,
                declaring_module=module,
                resolver_kind="class",
                target=controller,
                scope=controller_scope(controller),
            ),
        )
    return merged


def _unsatisfied_message(
    target: type[object], module: ModuleKey, dependency: ConstructorDependency
) -> str:
    """Return the error for a parameter no module visible to its owner can supply."""

    return (
        f"{_qualname(target)}.__init__ parameter {dependency.name!r} needs "
        f"{_qualname(dependency.token)}, which {_display_name(module)} cannot see. Declare it "
        "in that module, import a module that exports it, or give the parameter a default"
    )


def _refusal(failures: list[str]) -> ProviderResolutionError:
    """Return the one error reporting every reason a graph cannot be built."""

    if len(failures) == 1:
        return ProviderResolutionError(failures[0])
    listed = "\n".join(f"  - {failure}" for failure in failures)
    return ProviderResolutionError(
        f"The application cannot be built. {len(failures)} problems were found:\n{listed}"
    )
