"""Middleware abstractions and route-matching helpers."""

from __future__ import annotations

import fnmatch
import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ..core.module.dynamic import ModuleKey

if TYPE_CHECKING:
    from ..core.module.graph import ModuleGraph
    from ..platform.http.compiler import RouteContract

CallNext = Callable[[Request], Awaitable[Response]]


class RequestMethod(StrEnum):
    """Supported middleware route methods."""

    ALL = "ALL"
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


@dataclass(frozen=True, slots=True)
class RouteInfo:
    """Structured middleware route target."""

    path: str
    method: RequestMethod | None = None
    host: str | None = None


class MiddlewareHandler(Protocol):
    def __call__(self, request: Request, call_next: CallNext) -> Awaitable[Response] | Response: ...


class Middleware:
    """Base class for request middleware."""

    async def use(self, request: Request, call_next: CallNext) -> Response:
        return await call_next(request)


@dataclass(slots=True)
class MiddlewareBinding:
    """One middleware registration collected from module configuration."""

    middlewares: list[object] = field(default_factory=list)
    routes: list[object] = field(default_factory=list)
    excluded: list[object] = field(default_factory=list)


class MiddlewareRegistration:
    """Fluent middleware registration builder."""

    def __init__(self, binding: MiddlewareBinding) -> None:
        self._binding = binding

    def for_routes(self, *routes: object) -> MiddlewareRegistration:
        self._binding.routes.extend(routes)
        return self

    def exclude(self, *routes: object) -> MiddlewareRegistration:
        self._binding.excluded.extend(routes)
        return self


class MiddlewareConsumer:
    """Collect middleware bindings from module configuration callbacks."""

    def __init__(self) -> None:
        self.bindings: list[MiddlewareBinding] = []

    def apply(self, *middlewares: object) -> MiddlewareRegistration:
        binding = MiddlewareBinding(middlewares=list(middlewares))
        self.bindings.append(binding)
        return MiddlewareRegistration(binding)


@dataclass(frozen=True, slots=True)
class MiddlewareRouteTarget:
    """Normalized route target for middleware matching."""

    path: str | None = None
    method: RequestMethod | None = None
    host: str | None = None
    controller: type[object] | None = None
    controller_module_keys: tuple[ModuleKey, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledMiddlewareBinding:
    """Middleware registration compiled from module configuration."""

    declaring_module: ModuleKey
    middlewares: tuple[object, ...]
    routes: tuple[MiddlewareRouteTarget, ...]
    excluded: tuple[MiddlewareRouteTarget, ...]


@dataclass(frozen=True, slots=True)
class ResolvedRouteMiddleware:
    """Concrete middleware attachment for one route contract."""

    declaring_module: ModuleKey
    middleware: object


class MiddlewareRegistry:
    """Resolve canonical middleware chains for compiled routes."""

    def __init__(self, bindings: tuple[CompiledMiddlewareBinding, ...]) -> None:
        self._bindings = bindings

    def resolve_for(self, route_contract: RouteContract) -> tuple[ResolvedRouteMiddleware, ...]:
        resolved: list[ResolvedRouteMiddleware] = []

        for binding in self._bindings:
            if not _matches_any_target(route_contract, binding.routes):
                continue
            if binding.excluded and _matches_any_target(route_contract, binding.excluded):
                continue
            for middleware in binding.middlewares:
                resolved.append(
                    ResolvedRouteMiddleware(
                        declaring_module=binding.declaring_module,
                        middleware=middleware,
                    )
                )

        return tuple(resolved)


def compile_middleware_registry(
    module_graph: ModuleGraph,
) -> MiddlewareRegistry:
    """Compile module middleware declarations into a canonical registry."""

    compiled_bindings: list[CompiledMiddlewareBinding] = []
    controller_owners = _controller_owner_map(module_graph)

    for node in module_graph.nodes:
        configure = getattr(node.module(), "configure", None)
        if not callable(configure):
            continue

        consumer = MiddlewareConsumer()
        configure(consumer)
        for binding in consumer.bindings:
            compiled_bindings.append(
                CompiledMiddlewareBinding(
                    declaring_module=node.key,
                    middlewares=tuple(binding.middlewares),
                    routes=tuple(
                        _normalize_route_target(target, controller_owners)
                        for target in binding.routes
                    ),
                    excluded=tuple(
                        _normalize_route_target(target, controller_owners)
                        for target in binding.excluded
                    ),
                )
            )

    return MiddlewareRegistry(tuple(compiled_bindings))


def path_matches(path: str, patterns: list[str]) -> bool:
    """Return whether the path matches any glob patterns."""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _matches_any_target(
    route_contract: RouteContract,
    targets: tuple[MiddlewareRouteTarget, ...],
) -> bool:
    if not targets:
        return True
    return any(_route_matches_target(route_contract, target) for target in targets)


def _route_matches_target(
    route_contract: RouteContract,
    target: MiddlewareRouteTarget,
) -> bool:
    if target.controller is not None:
        return (
            route_contract.controller_cls is target.controller
            and route_contract.module_key in target.controller_module_keys
        )

    if target.method is not None and target.method is not RequestMethod.ALL:
        if route_contract.method != target.method.value:
            return False

    if target.path is not None and not fnmatch.fnmatch(route_contract.path, target.path):
        return False

    if target.host is not None and not _route_host_matches(route_contract.hosts, target.host):
        return False

    return True


def _route_host_matches(hosts: tuple[str, ...], pattern: str) -> bool:
    if not hosts:
        return False

    normalized_pattern = _normalize_host_pattern(pattern)
    return any(fnmatch.fnmatch(_normalize_host_pattern(host), normalized_pattern) for host in hosts)


def _normalize_route_target(
    target: object,
    controller_owners: dict[type[object], tuple[ModuleKey, ...]],
) -> MiddlewareRouteTarget:
    if isinstance(target, str):
        return MiddlewareRouteTarget(path=target)

    if isinstance(target, RouteInfo):
        return MiddlewareRouteTarget(
            path=target.path,
            method=target.method,
            host=target.host,
        )

    if isinstance(target, type):
        return MiddlewareRouteTarget(
            controller=target,
            controller_module_keys=controller_owners.get(target, ()),
        )

    raise TypeError(f"Unsupported middleware route target: {type(target).__name__}")


def _controller_owner_map(module_graph: ModuleGraph) -> dict[type[object], tuple[ModuleKey, ...]]:
    owners: dict[type[object], list[ModuleKey]] = {}
    for node in module_graph.nodes:
        for controller_cls in node.controllers:
            owners.setdefault(controller_cls, []).append(node.key)
    return {controller_cls: tuple(module_keys) for controller_cls, module_keys in owners.items()}


def _normalize_host_pattern(value: str) -> str:
    return re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "*", value)


class ConditionalMiddleware(BaseHTTPMiddleware):
    """Starlette adapter that conditionally runs a Bustan middleware."""

    def __init__(
        self,
        app,
        *,
        handler: object,
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self._handler = handler
        self._include = list(include)
        self._exclude = list(exclude)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not path_matches(request.url.path, self._include):
            return await call_next(request)
        if self._exclude and path_matches(request.url.path, self._exclude):
            return await call_next(request)

        if hasattr(self._handler, "use"):
            result = cast(Middleware, self._handler).use(request, call_next)
        else:
            result = cast(MiddlewareHandler, self._handler)(request, call_next)

        if inspect.isawaitable(result):
            return await cast(Awaitable[Response], result)
        return result
