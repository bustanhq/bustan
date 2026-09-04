"""Compiled route contracts for the HTTP runtime."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import NoneType
from typing import get_origin, get_type_hints

from ...common.types import ControllerMetadata, ProviderScope
from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.ioc.container import Container
from ...core.ioc.registry import DURABLE_CONTEXT_KEY_HOOK
from ...core.ioc.scopes import DurableProvider
from ...core.ioc.tokens import APP_FILTER, APP_GUARD, APP_INTERCEPTOR, APP_PIPE
from ...core.module.dynamic import ModuleKey
from ...core.module.graph import ModuleGraph
from ...core.utils import _qualname
from ...pipeline.guards import PolicyGuard
from ...pipeline.metadata import (
    PipelineMetadata,
    PolicyMetadata,
    get_controller_pipeline_metadata,
    get_controller_policy_metadata,
    get_handler_pipeline_metadata,
    get_handler_policy_metadata,
    merge_pipeline_metadata,
    merge_policy_metadata,
)
from .metadata import ControllerRouteDefinition, get_controller_metadata
from .params import HandlerBindingPlan, compile_parameter_bindings
from .scanner import ControllerScanner, ScannedHandler
from .versioning import normalize_versions


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
    headers: tuple[tuple[str, str], ...] = ()
    redirect_to: str | None = None
    raw_response_parameter: str | None = None


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
        _refuse_unservable_controller_lifetimes(self._module_graph)
        scan_result = ControllerScanner(self._module_graph).scan()
        global_pipeline = PipelineMetadata(
            guards=self._container.get_global_pipeline_providers(APP_GUARD),
            pipes=self._container.get_global_pipeline_providers(APP_PIPE),
            interceptors=self._container.get_global_pipeline_providers(APP_INTERCEPTOR),
            filters=self._container.get_global_pipeline_providers(APP_FILTER),
        )
        return tuple(
            self._compile_handler_contract(scanned_handler, global_pipeline)
            for scanned_handler in scan_result.handlers
        )

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


def _compile_response_strategy(declared_type: object | None) -> ResponseStrategy:
    from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator
    from os import PathLike
    from pathlib import Path

    from starlette.responses import Response

    from .abstractions import HttpResponse

    if declared_type in {None, NoneType}:
        return ResponseStrategy.STANDARD
    if isinstance(declared_type, type):
        if issubclass(declared_type, (Response, HttpResponse)):
            return ResponseStrategy.RAW
        if issubclass(declared_type, (Path, PathLike)):
            return ResponseStrategy.FILE

    origin = get_origin(declared_type)
    if origin in {Iterator, Generator, AsyncIterator, AsyncGenerator}:
        return ResponseStrategy.STREAM
    return ResponseStrategy.STANDARD


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


def _refuse_unservable_controller_lifetimes(module_graph: ModuleGraph) -> None:
    """Refuse every controller whose declared lifetime the runtime cannot serve.

    A durable lifetime is a cache partitioned by a key the class derives from the
    request. Controllers are held per module rather than per key, so a durable
    controller would be built once and handed to every caller together with whatever
    the previous caller left on it. No request makes that work, so the declaration is
    refused while the application is built rather than served to the first tenant.

    This runs before handlers are scanned so that the refusal names the lifetime the
    author declared, rather than reporting the context key hook as a route method that
    is missing its decorator.
    """

    for node in module_graph.nodes:
        for controller_cls in node.controllers:
            # The module graph has already refused any controller carrying no metadata.
            metadata = get_controller_metadata(controller_cls)
            label = _qualname(controller_cls)

            if metadata is not None and metadata.scope is ProviderScope.DURABLE:
                raise InvalidControllerError(
                    f"{label} declares scope {metadata.scope.value!r}, which a controller "
                    "cannot have; a durable instance is cached per context key and a "
                    "controller is not partitioned that way, so declare a singleton, request "
                    "or transient controller and keep the per-key state in a durable provider"
                )

            if isinstance(controller_cls, DurableProvider):
                raise InvalidControllerError(
                    f"{label} declares '{DURABLE_CONTEXT_KEY_HOOK}', the hook that partitions "
                    "a durable provider across requests; a controller cannot have a durable "
                    "lifetime, so the hook is never called, and it belongs on the durable "
                    "provider that keeps the per-key state"
                )


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
        if bool(getattr(interceptor, "mutates_response_body", False))
    )
    if not incompatible_interceptors:
        return

    route_owner = (
        f"{scanned_handler.controller_cls.__qualname__}."
        f"{scanned_handler.route_definition.handler_name}"
    )
    interceptor_names = ", ".join(
        interceptor.__name__ if isinstance(interceptor, type) else type(interceptor).__name__
        for interceptor in incompatible_interceptors
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
