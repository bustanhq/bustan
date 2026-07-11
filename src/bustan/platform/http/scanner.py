"""Startup-time controller discovery and validation."""

from __future__ import annotations

from dataclasses import dataclass

from ...common.types import ControllerMetadata, RouteMetadata
from ...core.errors import InvalidControllerError, RouteDefinitionError
from ...core.module.dynamic import ModuleKey
from ...core.module.graph import ModuleGraph
from ...core.utils import _join_paths, _qualname, _unwrap_handler
from .metadata import (
    ControllerRouteDefinition,
    get_controller_metadata,
    get_route_metadata,
    iter_controller_routes,
)


@dataclass(frozen=True, slots=True)
class ScannedController:
    """One controller discovered from the module graph."""

    module_key: ModuleKey
    controller_cls: type[object]
    metadata: ControllerMetadata
    routes: tuple[ControllerRouteDefinition, ...]


@dataclass(frozen=True, slots=True)
class ScannedHandler:
    """One route-bearing handler discovered during startup scanning."""

    module_key: ModuleKey
    controller_cls: type[object]
    controller_metadata: ControllerMetadata
    route_definition: ControllerRouteDefinition
    full_path: str

    @property
    def handler_name(self) -> str:
        return self.route_definition.handler_name

    @property
    def handler(self):
        return self.route_definition.handler

    @property
    def route(self) -> RouteMetadata:
        return self.route_definition.route


@dataclass(frozen=True, slots=True)
class ControllerScanResult:
    """Deterministic controller scan result for downstream compilation."""

    controllers: tuple[ScannedController, ...]
    handlers: tuple[ScannedHandler, ...]


class ControllerScanner:
    """Discover controller handlers once before adapter registration."""

    def __init__(self, module_graph: ModuleGraph) -> None:
        self._module_graph = module_graph

    def scan(self) -> ControllerScanResult:
        controllers: list[ScannedController] = []
        handlers: list[ScannedHandler] = []

        for node in self._module_graph.nodes:
            for controller_cls in node.controllers:
                scanned_controller = self.scan_controller(node.key, controller_cls)
                controllers.append(scanned_controller)

                for route_definition in scanned_controller.routes:
                    handlers.append(
                        ScannedHandler(
                            module_key=node.key,
                            controller_cls=controller_cls,
                            controller_metadata=scanned_controller.metadata,
                            route_definition=route_definition,
                            full_path=_join_paths(
                                scanned_controller.metadata.prefix,
                                route_definition.route.path,
                            ),
                        )
                    )

        return ControllerScanResult(
            controllers=tuple(controllers),
            handlers=tuple(handlers),
        )

    def scan_controller(
        self,
        module_key: ModuleKey,
        controller_cls: type[object],
    ) -> ScannedController:
        metadata = get_controller_metadata(controller_cls)
        if metadata is None:
            raise InvalidControllerError(
                f"{_qualname(controller_cls)} is not decorated with @Controller"
            )

        self._validate_declared_handlers(controller_cls, module_key)

        return ScannedController(
            module_key=module_key,
            controller_cls=controller_cls,
            metadata=metadata,
            routes=iter_controller_routes(controller_cls),
        )

    def _validate_declared_handlers(
        self,
        controller_cls: type[object],
        module_key: ModuleKey,
    ) -> None:
        for member_name, member in controller_cls.__dict__.items():
            if member_name == "__init__" or member_name.startswith("_"):
                continue

            handler = _unwrap_handler(member)
            if handler is None:
                continue

            if get_route_metadata(handler) is None:
                raise RouteDefinitionError(
                    f"{_qualname(controller_cls)}.{member_name} in {_qualname(module_key)} "
                    "is missing an HTTP route decorator"
                )