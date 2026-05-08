"""Compiled route contracts for the HTTP runtime."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import NoneType
from typing import get_origin, get_type_hints

from ...common.types import ControllerMetadata
from ...core.errors import RouteDefinitionError
from ...core.ioc.container import Container
from ...core.ioc.tokens import APP_FILTER, APP_GUARD, APP_INTERCEPTOR, APP_PIPE
from ...core.module.dynamic import ModuleKey
from ...core.module.graph import ModuleGraph
from ...pipeline.metadata import (
    PolicyMetadata,
    PipelineMetadata,
    get_controller_policy_metadata,
    get_controller_pipeline_metadata,
    get_handler_policy_metadata,
    get_handler_pipeline_metadata,
    merge_policy_metadata,
    merge_pipeline_metadata,
)
from ...pipeline.guards import PolicyGuard
from .metadata import ControllerRouteDefinition
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
        merged_policy = merge_policy_metadata(
            get_controller_policy_metadata(scanned_handler.controller_cls, inherit=True)
            or PolicyMetadata(),
            get_handler_policy_metadata(scanned_handler.handler) or PolicyMetadata(),
        )
        route_versions = normalize_versions(scanned_handler.route.version)
        controller_versions = normalize_versions(scanned_handler.controller_metadata.version)
        route_hosts = scanned_handler.route.hosts
        controller_hosts = scanned_handler.controller_metadata.hosts
        policy_plan = PolicyPlan(
            auth=merged_policy.auth,
            public=merged_policy.public,
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

    declared_type = raw_annotations.get("return", inspect.signature(route_definition.handler).return_annotation)
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