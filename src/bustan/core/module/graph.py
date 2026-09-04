"""Discovery and validation of the application module graph."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ...platform.http.metadata import (
    get_controller_metadata,
    iter_controller_routes,
)
from ..errors import (
    ExportViolationError,
    InvalidControllerError,
    InvalidModuleError,
    ModuleCycleError,
    RouteDefinitionError,
)
from ..ioc.registry import Binding
from ..utils import _display_name, _join_paths, _qualname
from .compiler import CompiledModuleDef, expand_module_input, validate_module_compiled
from .dynamic import DynamicModule, ModuleKey
from .metadata import ModuleMetadata, get_module_metadata


@dataclass(frozen=True, slots=True)
class ModuleNode:
    """Validated graph node for one decorated module instance."""

    key: ModuleKey
    module: type[object]
    metadata: ModuleMetadata
    exported_providers: frozenset[object]
    available_providers: frozenset[object]
    bindings: tuple[Binding, ...]
    imported_exports: Mapping[ModuleKey, frozenset[object]] = field(repr=False)

    @property
    def imports(self) -> tuple[type[object] | DynamicModule, ...]:
        return self.metadata.imports

    @property
    def controllers(self) -> tuple[type[object], ...]:
        return self.metadata.controllers

    @property
    def providers(self) -> tuple[object, ...]:
        """Return the token for each provider registered in this module."""
        return tuple(b.token for b in self.bindings)

    @property
    def exports(self) -> tuple[object, ...]:
        return self.metadata.exports


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """Validated view of the full module import graph."""

    root_key: ModuleKey
    nodes: tuple[ModuleNode, ...]
    _nodes_by_key: Mapping[ModuleKey, ModuleNode] = field(repr=False)

    def get_node(self, key: ModuleKey) -> ModuleNode:
        return self._nodes_by_key[key]

    def exports_for(self, key: ModuleKey) -> frozenset[object]:
        return self.get_node(key).exported_providers

    def controllers_for(self, key: ModuleKey) -> tuple[type[object], ...]:
        return self.get_node(key).controllers

    def available_providers_for(self, key: ModuleKey) -> frozenset[object]:
        return self.get_node(key).available_providers

    @property
    def root_module(self) -> type[object]:
        """Return the root module class."""
        if isinstance(self.root_key, type):
            return self.root_key
        return self.root_key.module


def build_module_graph(root_module: type[object] | DynamicModule) -> ModuleGraph:
    """Discover modules reachable from the root and validate them."""

    ordered_keys: list[ModuleKey] = []
    compiled_by_key: dict[ModuleKey, CompiledModuleDef] = {}

    input_to_key: dict[int | type[object], ModuleKey] = {}

    # Two cycle checks are needed: the stack carries the path that the error message
    # reports, and the id set catches a single object that re-enters its own expansion.
    visiting_stack: list[ModuleKey] = []
    visiting_ids: set[int | type[object]] = set()

    bindings_by_key: dict[ModuleKey, tuple[Binding, ...]] = {}
    dynamic_counter = 0

    def visit(module_input: type[object] | DynamicModule) -> ModuleKey:
        nonlocal dynamic_counter

        input_id = id(module_input) if isinstance(module_input, DynamicModule) else module_input

        if input_id in input_to_key:
            return input_to_key[input_id]

        # A module input has no key until it is expanded, so expansion precedes the
        # cycle checks and is discarded below when the key turns out to be known.
        compiled = expand_module_input(module_input, instance_id=str(dynamic_counter))
        key = compiled.key

        if key in visiting_stack:
            cycle_start = visiting_stack.index(key)
            cycle_keys = visiting_stack[cycle_start:] + [key]
            cycle_path = " -> ".join(_display_name(k) for k in cycle_keys)
            raise ModuleCycleError(f"Circular module imports detected: {cycle_path}")

        if input_id in visiting_ids:
            raise ModuleCycleError(
                f"Circular module dependency detected on {_display_name(module_input)}"
            )

        visiting_ids.add(input_id)
        visiting_stack.append(key)
        try:
            # The counter distinguishes dynamic instances, so it may only advance once
            # this expansion is committed to.
            if isinstance(module_input, DynamicModule):
                dynamic_counter += 1

            # Another dynamic module may already have produced this key.
            if key in compiled_by_key:
                input_to_key[input_id] = key
                return key

            # Preserve pre-order node discovery because import-order semantics and tests
            # depend on it.
            compiled_by_key[key] = compiled
            bindings_by_key[key] = validate_module_compiled(compiled)

            ordered_keys.append(key)

            for imported_input in compiled.metadata.imports:
                _require_module_input(imported_input, owner=key)
                visit(imported_input)

            input_to_key[input_id] = key
            return key
        finally:
            visiting_stack.pop()
            visiting_ids.discard(input_id)

    root_key = visit(root_module)

    # Nodes are built by recursive descent so that a module's imports exist before it
    # does, while the graph is still emitted in the pre-order sequence of ordered_keys.
    nodes_by_key: dict[ModuleKey, ModuleNode] = {}

    def ensure_node(key: ModuleKey) -> ModuleNode:
        if key in nodes_by_key:
            return nodes_by_key[key]

        compiled = compiled_by_key[key]
        metadata = compiled.metadata

        imported_exports: dict[ModuleKey, frozenset[object]] = {}
        available_providers: set[object] = {b.token for b in bindings_by_key[key]}

        for imported_input in metadata.imports:
            imp_id = (
                id(imported_input) if isinstance(imported_input, DynamicModule) else imported_input
            )
            imported_key = input_to_key[imp_id]

            dep_node = ensure_node(imported_key)
            exports = dep_node.exported_providers
            imported_exports[imported_key] = exports
            available_providers.update(exports)

        node = ModuleNode(
            key=key,
            module=compiled.module,
            metadata=metadata,
            exported_providers=frozenset(metadata.exports),
            available_providers=frozenset(available_providers),
            bindings=bindings_by_key[key],
            imported_exports=MappingProxyType(imported_exports),
        )

        _validate_exports(node)
        for controller_cls in node.controllers:
            _validate_controller_routes(controller_cls)

        nodes_by_key[key] = node
        return node

    for key in ordered_keys:
        ensure_node(key)

    return ModuleGraph(
        root_key=root_key,
        nodes=tuple(nodes_by_key[key] for key in ordered_keys),
        _nodes_by_key=MappingProxyType(nodes_by_key),
    )


def _validate_exports(node: ModuleNode) -> None:
    valid_tokens = {b.token for b in node.bindings}
    for imported_tokens in node.imported_exports.values():
        valid_tokens.update(imported_tokens)

    for export_token in node.exports:
        if export_token not in valid_tokens:
            raise ExportViolationError(
                f"{_display_name(node.key)} exports {_qualname(export_token)}, "
                "but that provider is not available (neither provided nor imported)"
            )


def _validate_controller_routes(controller_cls: type[object]) -> None:
    seen_routes: dict[tuple[str, str], str] = {}
    controller_metadata = get_controller_metadata(controller_cls)
    if controller_metadata is None:
        raise InvalidControllerError(
            f"{_qualname(controller_cls)} is not decorated with @Controller"
        )

    for route_definition in iter_controller_routes(controller_cls):
        route_key = (route_definition.route.method, route_definition.route.path)
        previous_handler = seen_routes.get(route_key)
        if previous_handler is not None:
            raise RouteDefinitionError(
                f"{_qualname(controller_cls)} defines duplicate route "
                f"{route_definition.route.method} "
                f"{_join_paths(controller_metadata.prefix, route_definition.route.path)} "
                f"on handlers {previous_handler} and {route_definition.handler_name}"
            )
        seen_routes[route_key] = route_definition.handler_name


def _require_module_input(
    module_candidate: object, *, owner: ModuleKey
) -> type[object] | DynamicModule:
    if isinstance(module_candidate, DynamicModule):
        _require_module_input(module_candidate.module, owner=owner)
        return module_candidate

    if not isinstance(module_candidate, type):
        raise InvalidModuleError(
            f"{_display_name(owner)} imports {_qualname(module_candidate)}, "
            "which is not a decorated module"
        )

    if get_module_metadata(module_candidate) is None:
        raise InvalidModuleError(
            f"{_display_name(owner)} imports {_qualname(module_candidate)}, "
            "which is not a decorated module"
        )

    return module_candidate
