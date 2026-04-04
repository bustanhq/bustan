"""Discovery and validation of the application module graph."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .errors import (
    ExportViolationError,
    InvalidControllerError,
    InvalidModuleError,
    InvalidProviderError,
    ModuleCycleError,
    RouteDefinitionError,
)
from .metadata import (
    ControllerMetadata,
    ModuleMetadata,
    ProviderMetadata,
    get_controller_metadata,
    get_module_metadata,
    get_provider_metadata,
    iter_controller_routes,
)


@dataclass(frozen=True, slots=True)
class ModuleNode:
    """Validated graph node for one decorated module."""

    module: type[object]
    metadata: ModuleMetadata
    exported_providers: frozenset[type[object]]
    available_providers: frozenset[type[object]]
    imported_exports: Mapping[type[object], frozenset[type[object]]] = field(repr=False)

    @property
    def imports(self) -> tuple[type[object], ...]:
        return self.metadata.imports

    @property
    def controllers(self) -> tuple[type[object], ...]:
        return self.metadata.controllers

    @property
    def providers(self) -> tuple[type[object], ...]:
        return self.metadata.providers

    @property
    def exports(self) -> tuple[type[object], ...]:
        return self.metadata.exports


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """Validated view of the full module import graph."""

    root_module: type[object]
    nodes: tuple[ModuleNode, ...]
    _nodes_by_module: Mapping[type[object], ModuleNode] = field(repr=False)

    def get_node(self, module_cls: type[object]) -> ModuleNode:
        return self._nodes_by_module[module_cls]

    def exports_for(self, module_cls: type[object]) -> frozenset[type[object]]:
        return self.get_node(module_cls).exported_providers

    def available_providers_for(self, module_cls: type[object]) -> frozenset[type[object]]:
        return self.get_node(module_cls).available_providers


def build_module_graph(root_module: type[object]) -> ModuleGraph:
    """Discover modules reachable from the root module and validate them."""

    ordered_modules: list[type[object]] = []
    metadata_by_module: dict[type[object], ModuleMetadata] = {}
    visited_modules: set[type[object]] = set()
    visiting_stack: list[type[object]] = []

    def visit(module_cls: type[object]) -> None:
        if module_cls in visiting_stack:
            cycle_start = visiting_stack.index(module_cls)
            cycle_modules = visiting_stack[cycle_start:] + [module_cls]
            cycle_path = " -> ".join(_display_name(module) for module in cycle_modules)
            raise ModuleCycleError(f"Circular module imports detected: {cycle_path}")

        if module_cls in visited_modules:
            return

        module_metadata = _validate_module_definition(module_cls)
        metadata_by_module[module_cls] = module_metadata

        # Pre-order traversal preserves declaration order for deterministic
        # provider registration and lifecycle execution later on.
        visiting_stack.append(module_cls)
        ordered_modules.append(module_cls)
        for imported_module in module_metadata.imports:
            visit(imported_module)
        visiting_stack.pop()

        visited_modules.add(module_cls)

    visit(root_module)

    nodes_by_module: dict[type[object], ModuleNode] = {}
    for module_cls in ordered_modules:
        module_metadata = metadata_by_module[module_cls]
        imported_exports = {
            imported_module: frozenset(metadata_by_module[imported_module].exports)
            for imported_module in module_metadata.imports
        }
        available_providers = set(module_metadata.providers)
        # Imported providers are visible only through explicit exports.
        for exported_providers in imported_exports.values():
            available_providers.update(exported_providers)

        nodes_by_module[module_cls] = ModuleNode(
            module=module_cls,
            metadata=module_metadata,
            exported_providers=frozenset(module_metadata.exports),
            available_providers=frozenset(available_providers),
            imported_exports=MappingProxyType(imported_exports),
        )

    graph = ModuleGraph(
        root_module=root_module,
        nodes=tuple(nodes_by_module[module_cls] for module_cls in ordered_modules),
        _nodes_by_module=MappingProxyType(nodes_by_module),
    )
    return validate_module_graph(graph)


def validate_module_graph(graph: ModuleGraph) -> ModuleGraph:
    """Run graph-wide validations that require the fully built graph."""

    for node in graph.nodes:
        _validate_exports(node)
        for controller_cls in node.controllers:
            _validate_controller_routes(controller_cls)
    return graph


def _validate_module_definition(module_cls: type[object]) -> ModuleMetadata:
    module_metadata = get_module_metadata(module_cls)
    if module_metadata is None:
        raise InvalidModuleError(
            f"{_qualname(module_cls)} is not a valid module. Did you forget to decorate it with @module?"
        )

    _validate_unique_entries(module_cls, "imports", module_metadata.imports)
    _validate_unique_entries(module_cls, "controllers", module_metadata.controllers)
    _validate_unique_entries(module_cls, "providers", module_metadata.providers)
    _validate_unique_entries(module_cls, "exports", module_metadata.exports)

    for imported_module in module_metadata.imports:
        _require_module(imported_module, owner=module_cls)

    for controller_cls in module_metadata.controllers:
        _require_controller(controller_cls, owner=module_cls)

    for provider_cls in module_metadata.providers:
        _require_provider(provider_cls, owner=module_cls, field_name="providers")

    for exported_provider in module_metadata.exports:
        _require_provider(exported_provider, owner=module_cls, field_name="exports")

    return module_metadata


def _validate_exports(node: ModuleNode) -> None:
    provider_set = set(node.providers)
    for exported_provider in node.exports:
        if exported_provider not in provider_set:
            raise ExportViolationError(
                f"{_qualname(node.module)} exports {_qualname(exported_provider)}, "
                "but that provider is not declared in providers"
            )


def _validate_controller_routes(controller_cls: type[object]) -> None:
    seen_routes: dict[tuple[str, str], str] = {}
    controller_metadata = get_controller_metadata(controller_cls)
    assert isinstance(controller_metadata, ControllerMetadata)

    for route_definition in iter_controller_routes(controller_cls):
        route_key = (route_definition.route.method, route_definition.route.path)
        previous_handler = seen_routes.get(route_key)
        if previous_handler is not None:
            raise RouteDefinitionError(
                f"{_qualname(controller_cls)} defines duplicate route "
                f"{route_definition.route.method} {_join_paths(controller_metadata.prefix, route_definition.route.path)} "
                f"on handlers {previous_handler} and {route_definition.handler_name}"
            )
        seen_routes[route_key] = route_definition.handler_name


def _require_module(module_candidate: object, *, owner: type[object]) -> type[object]:
    if not isinstance(module_candidate, type):
        raise InvalidModuleError(
            f"{_qualname(owner)} imports {module_candidate!r}, which is not a decorated module"
        )

    module_metadata = get_module_metadata(module_candidate)
    if not isinstance(module_metadata, ModuleMetadata):
        raise InvalidModuleError(
            f"{_qualname(owner)} imports {_qualname(module_candidate)}, "
            "which is not decorated with @module"
        )

    return module_candidate


def _require_controller(controller_candidate: object, *, owner: type[object]) -> type[object]:
    if not isinstance(controller_candidate, type):
        raise InvalidControllerError(
            f"{_qualname(owner)} declares {controller_candidate!r} as a controller, but it is not a class"
        )

    controller_metadata = get_controller_metadata(controller_candidate)
    if not isinstance(controller_metadata, ControllerMetadata):
        raise InvalidControllerError(
            f"{_qualname(owner)} declares {_qualname(controller_candidate)} as a controller, "
            "but it is not decorated with @controller"
        )

    return controller_candidate


def _require_provider(
    provider_candidate: object,
    *,
    owner: type[object],
    field_name: str,
) -> type[object]:
    if not isinstance(provider_candidate, type):
        raise InvalidProviderError(
            f"{_qualname(owner)} declares {provider_candidate!r} in {field_name}, but it is not a class"
        )

    provider_metadata = get_provider_metadata(provider_candidate)
    if not isinstance(provider_metadata, ProviderMetadata):
        raise InvalidProviderError(
            f"{_qualname(owner)} declares {_qualname(provider_candidate)} in {field_name}, "
            "but it is not decorated with @injectable"
        )

    return provider_candidate


def _validate_unique_entries(
    owner: type[object],
    field_name: str,
    entries: tuple[object, ...],
) -> None:
    seen_entries: list[object] = []
    for entry in entries:
        if entry in seen_entries:
            raise InvalidModuleError(
                f"{_qualname(owner)} declares duplicate entries in {field_name}: {entry!r}"
            )
        seen_entries.append(entry)


def _qualname(target: object) -> str:
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"
    return repr(target)


def _display_name(target: object) -> str:
    if isinstance(target, type):
        return target.__name__
    return repr(target)


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return path
    if path == "/":
        return prefix
    return f"{prefix}{path}"