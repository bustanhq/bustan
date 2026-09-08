"""Compiled route contracts for the HTTP runtime."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import NoneType
from typing import cast, get_origin, get_type_hints

from ..common.types import ControllerMetadata
from ..kernel.errors import AuthenticatorRegistryError, RouteDefinitionError
from ..kernel.ioc.container import Container
from ..kernel.ioc.registry import Binding
from ..kernel.ioc.tokens import APP_FILTER, APP_GUARD, APP_INTERCEPTOR, APP_PIPE, InjectionToken
from ..kernel.module.compiler import _in_declaration_order
from ..kernel.module.dynamic import ModuleKey
from ..kernel.module.graph import ModuleGraph
from ..kernel.utils import _display_name
from ..pipeline.auth import AUTHENTICATOR_REGISTRY
from ..pipeline.guards import PolicyGuard
from ..pipeline.metadata import (
    PipelineMetadata,
    PolicyMetadata,
    get_controller_pipeline_metadata,
    get_controller_policy_metadata,
    get_handler_pipeline_metadata,
    get_handler_policy_metadata,
    merge_pipeline_metadata,
    merge_policy_metadata,
)
from .metadata import ControllerRouteDefinition
from .params import HandlerBindingPlan, compile_parameter_bindings
from .scanner import ControllerScanner, ScannedHandler
from .versioning import normalize_versions

# The binding kinds that name the component they build. A class names it directly and a
# value is it; every other kind produces its component only by running something, so what
# it will produce cannot be read before the first request exists.
_READABLE_RESOLVER_KINDS = frozenset({"class", "value"})


@dataclass(frozen=True, slots=True)
class GlobalPipelineProvider:
    """A pipeline component declared under a global token and built for each request.

    A route contract records where a global guard, pipe, interceptor or filter comes
    from rather than which instance it is. Resolving it while routes are compiled would
    freeze an answer that is not yet settled: the provider may be request-scoped, may be
    built by an asynchronous factory that nothing has been able to await yet, and may be
    replaced by an override registered after the application was built.

    One token may stand for several components: a module that binds a list under it
    registers every entry, and they run in the order the list was written.

    ``declared_component`` is the class, value or list the declaring module bound, which
    is what the compiler reads when a rule has to be checked before any request exists. A
    module that declared the token several times over reads back as the list of everything
    it declared, so a rule sees the same components whichever way they were written. It is
    ``None`` for a component only a factory can produce.
    """

    token: InjectionToken[object]
    module: ModuleKey
    declared_component: object | None = None

    @property
    def label(self) -> str:
        """Name the component or components for a diagnostic, falling back to its token."""

        declared = self.declared_component
        if isinstance(declared, (list, tuple)):
            return ", ".join(_component_name(entry) for entry in declared) or self.token.name
        if declared is None:
            return self.token.name
        return _component_name(declared)


@dataclass(frozen=True, slots=True)
class PipelinePlan(PipelineMetadata):
    """Compiled pipeline metadata attached to one route contract."""


class ResponseStrategy(StrEnum):
    """Supported runtime response handling strategies."""

    STANDARD = "standard"
    RAW = "raw"
    STREAM = "stream"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class DeclaredResponse:
    """Declared response metadata attached to one route contract."""

    status: int
    schema: object | None = None
    description: str | None = None
    media_types: tuple[str, ...] = ("application/json",)


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    """Compiled response metadata attached to one route contract."""

    declared_type: object | None
    strategy: ResponseStrategy = ResponseStrategy.STANDARD
    default_status_code: int = 200
    declared_responses: tuple[DeclaredResponse, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyPlan(PolicyMetadata):
    """Compiled policy metadata attached to one route contract."""


@dataclass(frozen=True, slots=True)
class RouteContract:
    """Authoritative runtime representation of one discovered route."""

    module_key: ModuleKey
    controller_cls: type[object]
    controller_metadata: ControllerMetadata
    route_definition: ControllerRouteDefinition
    binding_plan: HandlerBindingPlan
    pipeline_plan: PipelinePlan
    response_plan: ResponsePlan
    policy_plan: PolicyPlan
    full_path: str
    versions: tuple[str, ...]
    hosts: tuple[str, ...] = ()

    @property
    def handler(self):
        return self.route_definition.handler

    @property
    def handler_name(self) -> str:
        return self.route_definition.handler_name

    @property
    def method(self) -> str:
        return self.route_definition.route.method

    @property
    def path(self) -> str:
        return self.full_path

    @property
    def name(self) -> str:
        return self.route_definition.route.name


class RouteCompiler:
    """Compile startup scan results into stable route contracts."""

    def __init__(self, module_graph: ModuleGraph, container: Container) -> None:
        self._module_graph = module_graph
        self._container = container

    def compile(self) -> tuple[RouteContract, ...]:
        scan_result = ControllerScanner(self._module_graph).scan()
        global_pipeline = PipelineMetadata(
            guards=self._global_providers(APP_GUARD),
            pipes=self._global_providers(APP_PIPE),
            interceptors=self._global_providers(APP_INTERCEPTOR),
            filters=self._global_providers(APP_FILTER),
        )
        return tuple(
            self._compile_handler_contract(scanned_handler, global_pipeline)
            for scanned_handler in scan_result.handlers
        )

    def _global_providers(
        self, token: InjectionToken[object]
    ) -> tuple[GlobalPipelineProvider, ...]:
        """Name every module-declared component for one global token, in module order.

        A module may declare the token more than once, and every declaration runs, in
        the order the modules were registered and then the order they were written.
        """

        return tuple(
            GlobalPipelineProvider(token, module, self._declared_component(token, module))
            for module in self._container.get_global_pipeline_providers(token)
        )

    def _declared_component(
        self, token: InjectionToken[object], module: ModuleKey
    ) -> object | None:
        """Return the class or value a module bound to a global token, if it bound one."""

        binding = self._container.registry.get_binding((module, token))
        if binding is None:
            return None
        if binding.resolver_kind in _READABLE_RESOLVER_KINDS:
            return binding.target
        if binding.resolver_kind == "factory":
            return self._joined_components(binding, module)
        return None

    def _joined_components(self, binding: Binding, module: ModuleKey) -> list[object] | None:
        """Return the components a module declared one at a time under a single token.

        A module that declares a pipeline token more than once has its declarations joined
        into one binding that builds them all. That binding is a factory, so it names no
        component of its own, and a rule checked before any request exists would otherwise
        see nothing where the module declared several components. Reading the joined
        declarations gives it the same view it has of one declaration naming a list.

        A joined declaration that only a factory can produce, or that aliases another
        token, names no component, so it is left out and the declarations beside it are
        still read. ``None`` means no declaration in the binding named a component, which
        is also what a lone factory declaration returns.

        Only a factory binding is ever passed here, because only a factory holds the
        arguments a join is made of.
        """

        factory, entry_tokens = cast("tuple[object, tuple[object, ...]]", binding.target)
        # The join is recognised by the callable that performs it rather than by the shape
        # of the binding, because a factory an author wrote has the same shape and its
        # injected dependencies are its arguments, not components declared for the token.
        if factory is not _in_declaration_order:
            return None

        declared: list[object] = []
        for entry_token in entry_tokens:
            entry = self._container.registry.get_binding((module, entry_token))
            if entry is None or entry.resolver_kind not in _READABLE_RESOLVER_KINDS:
                continue
            if isinstance(entry.target, (list, tuple)):
                declared.extend(entry.target)
            else:
                declared.append(entry.target)
        return declared or None

    def _compile_handler_contract(
        self,
        scanned_handler: ScannedHandler,
        global_pipeline: PipelineMetadata,
    ) -> RouteContract:
        controller_pipeline = (
            get_controller_pipeline_metadata(scanned_handler.controller_cls, inherit=True)
            or PipelineMetadata()
        )
        handler_pipeline = (
            get_handler_pipeline_metadata(scanned_handler.handler) or PipelineMetadata()
        )
        merged_pipeline = merge_pipeline_metadata(
            global_pipeline,
            controller_pipeline,
            handler_pipeline,
        )
        controller_policy = (
            get_controller_policy_metadata(scanned_handler.controller_cls, inherit=True)
            or PolicyMetadata()
        )
        handler_policy = get_handler_policy_metadata(scanned_handler.handler) or PolicyMetadata()
        merged_policy = merge_policy_metadata(controller_policy, handler_policy)
        resolved_public = _resolve_public_policy(
            controller_policy,
            handler_policy,
            scanned_handler,
        )
        route_versions = normalize_versions(scanned_handler.route.version)
        controller_versions = normalize_versions(scanned_handler.controller_metadata.version)
        route_hosts = scanned_handler.route.hosts
        controller_hosts = scanned_handler.controller_metadata.hosts
        policy_plan = PolicyPlan(
            auth=merged_policy.auth,
            public=resolved_public,
            roles=merged_policy.roles,
            permissions=merged_policy.permissions,
            rate_limit=merged_policy.rate_limit,
            cache=merged_policy.cache,
            idempotency=merged_policy.idempotency,
            audit=merged_policy.audit,
            owner=merged_policy.owner,
            deprecation=merged_policy.deprecation,
        )
        self._validate_authenticator_registry(scanned_handler, policy_plan)
        guards = merged_pipeline.guards
        if _has_policy(policy_plan):
            guards = (PolicyGuard, *guards)

        response_plan = self._compile_response_plan(scanned_handler.route_definition)
        _validate_interceptor_response_compatibility(
            scanned_handler,
            merged_pipeline.interceptors,
            response_plan,
        )

        return RouteContract(
            module_key=scanned_handler.module_key,
            controller_cls=scanned_handler.controller_cls,
            controller_metadata=scanned_handler.controller_metadata,
            route_definition=scanned_handler.route_definition,
            binding_plan=compile_parameter_bindings(
                scanned_handler.controller_cls,
                scanned_handler.route_definition,
            ),
            pipeline_plan=PipelinePlan(
                guards=guards,
                pipes=merged_pipeline.pipes,
                interceptors=merged_pipeline.interceptors,
                filters=merged_pipeline.filters,
            ),
            response_plan=response_plan,
            policy_plan=policy_plan,
            full_path=scanned_handler.full_path,
            versions=route_versions or controller_versions,
            hosts=route_hosts or controller_hosts,
        )

    def _validate_authenticator_registry(
        self,
        scanned_handler: ScannedHandler,
        policy_plan: PolicyPlan,
    ) -> None:
        """Refuse a route that authenticates callers with wiring that cannot authenticate.

        A route carrying an authentication policy reads its authenticators out of the
        registry bound under the authenticator registry token. That registry has to be
        visible from the module the route is declared in, and has to be buildable without
        being awaited, because the guard reads it synchronously in the middle of the
        request. Neither fact can be seen from the route itself: both are settled by which
        module binds the token and how it binds it.

        Left to the request, a registry that fails either test refuses every caller of the
        route with the same answer a wrong credential gets, on every request the route
        will ever serve, which is a mistake in the application wearing the face of a
        mistake by the caller. It is refused here instead, while the application is being
        built, where it is still somebody's to fix and nobody has been misinformed yet.

        A route whose policy resolved to public never reaches the registry, so it is not
        held to this.
        """

        if policy_plan.auth is None or policy_plan.public:
            return

        module = scanned_handler.module_key
        binding = self._visible_authenticator_registry(module)
        route_label = (
            f"{scanned_handler.controller_cls.__qualname__}."
            f"{scanned_handler.route_definition.handler_name}"
        )
        if binding is None:
            raise AuthenticatorRegistryError(
                f"{route_label} authenticates its callers, and no provider for "
                f"{AUTHENTICATOR_REGISTRY.name} is visible to {_display_name(module)}. "
                "Declare one in that module, or import a module that exports it"
            )
        if _resolves_only_by_awaiting(binding):
            raise AuthenticatorRegistryError(
                f"{route_label} authenticates its callers, and the provider for "
                f"{AUTHENTICATOR_REGISTRY.name} visible to {_display_name(module)} is built "
                "by an async factory, which the guard that reads it cannot await. Declare "
                "it as a value or build it with a synchronous factory"
            )

    def _visible_authenticator_registry(self, module: ModuleKey) -> Binding | None:
        """Return the authenticator registry binding one module can see, if it can see one."""

        visibility = self._container.registry.module_visibility.get(module)
        if visibility is None:
            return None
        declaring_module = visibility.get(AUTHENTICATOR_REGISTRY)
        if declaring_module is None:
            return None
        return self._container.registry.get_binding((declaring_module, AUTHENTICATOR_REGISTRY))

    def _compile_response_plan(self, route_definition: ControllerRouteDefinition) -> ResponsePlan:
        declared_type = _resolve_declared_return_type(route_definition)
        default_status_code = 204 if declared_type in {None, NoneType} else 200
        strategy = _compile_response_strategy(declared_type)
        return ResponsePlan(
            declared_type=declared_type,
            strategy=strategy,
            default_status_code=default_status_code,
            declared_responses=(DeclaredResponse(status=default_status_code),),
        )


# The response base classes of the transports a handler may return a response from, named
# rather than imported. Compiling a route runs on every application's startup path, and no
# layer below an adapter may make a transport a hard dependency of that, so each entry is
# read from the modules already imported instead. That is the whole answer rather than a
# weaker one: a declared return type can only be one of these classes when the module
# defining it has been imported, so an entry naming a module nobody imported cannot match
# any annotation, and neither can one whose transport is not installed at all.
_TRANSPORT_RESPONSE_BASES: tuple[tuple[str, str], ...] = (("starlette.responses", "Response"),)


def _compile_response_strategy(declared_type: object | None) -> ResponseStrategy:
    from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator
    from os import PathLike
    from pathlib import Path

    from ..contracts import HttpResponse

    if declared_type in {None, NoneType}:
        return ResponseStrategy.STANDARD
    if isinstance(declared_type, type):
        if issubclass(declared_type, HttpResponse) or _is_transport_response(declared_type):
            return ResponseStrategy.RAW
        if issubclass(declared_type, (Path, PathLike)):
            return ResponseStrategy.FILE

    origin = get_origin(declared_type)
    if origin in {Iterator, Generator, AsyncIterator, AsyncGenerator}:
        return ResponseStrategy.STREAM
    return ResponseStrategy.STANDARD


def _is_transport_response(declared_type: type) -> bool:
    """Return whether a declared return type is a transport's own response class."""

    for module_name, class_name in _TRANSPORT_RESPONSE_BASES:
        base = getattr(sys.modules.get(module_name), class_name, None)
        if isinstance(base, type) and issubclass(declared_type, base):
            return True
    return False


def _resolve_declared_return_type(route_definition: ControllerRouteDefinition) -> object | None:
    try:
        raw_annotations = inspect.get_annotations(route_definition.handler, eval_str=False)
    except (NameError, TypeError):
        raw_annotations = {}

    declared_type = raw_annotations.get(
        "return", inspect.signature(route_definition.handler).return_annotation
    )
    if declared_type is inspect.Signature.empty:
        return None
    if not isinstance(declared_type, str):
        return declared_type

    handler_globals = getattr(route_definition.handler, "__globals__", {})
    try:
        return _resolve_annotation_string(
            declared_type,
            globalns=handler_globals,
            localns=handler_globals,
        )
    except (NameError, TypeError):
        return declared_type


def _resolve_annotation_string(
    annotation: str,
    *,
    globalns: Mapping[str, object],
    localns: Mapping[str, object],
) -> object:
    def _annotation_holder() -> None:
        return None

    _annotation_holder.__annotations__ = {"value": annotation}
    return get_type_hints(
        _annotation_holder,
        globalns=dict(globalns),
        localns=dict(localns),
        include_extras=True,
    )["value"]


def _declares_access_requirements(policy: PolicyMetadata) -> bool:
    return policy.auth is not None or bool(policy.roles) or bool(policy.permissions)


def _resolve_public_policy(
    controller_policy: PolicyMetadata,
    handler_policy: PolicyMetadata,
    scanned_handler: ScannedHandler,
) -> bool:
    """Resolve the effective `public` flag across declaration levels.

    `@Public()` combined with `@Auth`/`@Roles`/`@Permissions` at the same
    level is contradictory and rejected. Across levels, the handler's own
    access requirements always win over a controller-level `@Public()`.
    """

    route_label = (
        f"{scanned_handler.controller_cls.__name__}.{scanned_handler.route_definition.handler_name}"
    )
    for level, policy in (("controller", controller_policy), ("handler", handler_policy)):
        if policy.public and _declares_access_requirements(policy):
            raise RouteDefinitionError(
                f"{route_label} declares @Public together with auth/roles/permissions "
                f"at the {level} level; remove one of the contradictory declarations"
            )

    if _declares_access_requirements(handler_policy):
        return handler_policy.public
    if handler_policy.public:
        return True
    return controller_policy.public


def _has_policy(policy_plan: PolicyPlan) -> bool:
    return any(
        (
            policy_plan.auth is not None,
            policy_plan.public,
            bool(policy_plan.roles),
            bool(policy_plan.permissions),
            policy_plan.rate_limit is not None,
            policy_plan.cache is not None,
            policy_plan.idempotency is not None,
            policy_plan.audit is not None,
            policy_plan.owner is not None,
            policy_plan.deprecation is not None,
        )
    )


def _resolves_only_by_awaiting(binding: Binding) -> bool:
    """Report whether a binding can be built only by awaiting the factory behind it."""

    if binding.resolver_kind != "factory":
        return False
    target = binding.target
    factory = target[0] if isinstance(target, tuple) else target
    return inspect.iscoroutinefunction(factory)


def _component_name(component: object) -> str:
    """Name one pipeline component, whether it was declared as a class or a value."""

    return component.__name__ if isinstance(component, type) else type(component).__name__


def _declared_interceptors(interceptor: object) -> tuple[object, ...]:
    """Return the interceptors a declaration names, seeing through a global reference."""

    if not isinstance(interceptor, GlobalPipelineProvider):
        return (interceptor,)
    declared = interceptor.declared_component
    if isinstance(declared, (list, tuple)):
        return tuple(declared)
    return () if declared is None else (declared,)


def _interceptor_name(interceptor: object) -> str:
    """Name an interceptor for a diagnostic, however it was declared."""

    if isinstance(interceptor, GlobalPipelineProvider):
        return interceptor.label
    return _component_name(interceptor)


def _validate_interceptor_response_compatibility(
    scanned_handler: ScannedHandler,
    interceptors: tuple[object, ...],
    response_plan: ResponsePlan,
) -> None:
    if response_plan.strategy is not ResponseStrategy.RAW:
        return

    incompatible_interceptors = tuple(
        interceptor
        for interceptor in interceptors
        if any(
            bool(getattr(declared, "mutates_response_body", False))
            for declared in _declared_interceptors(interceptor)
        )
    )
    if not incompatible_interceptors:
        return

    route_owner = (
        f"{scanned_handler.controller_cls.__qualname__}."
        f"{scanned_handler.route_definition.handler_name}"
    )
    interceptor_names = ", ".join(
        _interceptor_name(interceptor) for interceptor in incompatible_interceptors
    )
    raise RouteDefinitionError(
        f"{route_owner} uses raw response mode and cannot apply interceptor "
        f"{interceptor_names} because it mutates the response body"
    )


def compile_route_contracts(
    module_graph: ModuleGraph,
    container: Container,
) -> tuple[RouteContract, ...]:
    """Compile all discovered handlers into stable route contracts."""

    return RouteCompiler(module_graph, container).compile()
