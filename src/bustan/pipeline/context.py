"""Context objects shared across request pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request

from ..platform.http.metadata import ControllerRouteDefinition

if TYPE_CHECKING:
    from ..core.ioc.container import Container
    from ..core.module.dynamic import ModuleKey


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Request-wide context passed to guards and exception filters."""

    request: Request
    module: ModuleKey
    controller_type: type[object]
    controller: object
    route: ControllerRouteDefinition
    container: Container


@dataclass(frozen=True, slots=True)
class ParameterContext:
    """Per-parameter context passed to pipes."""

    request_context: RequestContext
    name: str
    source: str
    annotation: object
    value: object


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Handler invocation context passed to interceptors."""

    request_context: RequestContext
    arguments: tuple[object, ...]
    keyword_arguments: Mapping[str, object]
