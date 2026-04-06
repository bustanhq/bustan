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
    Binding,
    ControllerMetadata,
    DynamicModule,
    ModuleInstanceKey,
    ModuleKey,
    ModuleMetadata,
    get_controller_metadata,
    get_module_metadata,
    iter_controller_routes,
    normalize_provider,
)
from .utils import _display_name, _join_paths, _qualname


@dataclass(frozen=True, slots=True)
class CompiledModuleDef:
    """Expansion of a module input into its final metadata and unique key."""

    key: ModuleKey
    module: type[object]
    metadata: ModuleMetadata


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

    def available_providers_for(self, key: ModuleKey) -> frozenset[object]:
        return self.get_node(key).available_providers


def build_module_graph(root_module: type[object] | DynamicModule) -> ModuleGraph:
    """Discover modules reachable from the root and validate them."""

    ordered_keys: list[ModuleKey] = []
    compiled_by_key: dict[ModuleKey, CompiledModuleDef] = {}
    # We track visited inputs by identity for DynamicModule to avoid unhashable 
    # dictionary errors and to treat each registration as unique.
    visited_inputs: dict[int | type[object], ModuleKey] = {}
    visiting_inputs: set[int | type[object]] = set()
    visiting_stack: list[ModuleKey] = []
    bindings_by_key: dict[ModuleKey, tuple[Binding, ...]] = {}
    dynamic_counter = 0

    def visit(module_input: type[object] | DynamicModule) -> ModuleKey:
        nonlocal dynamic_counter

        input_id = id(module_input) if isinstance(module_input, DynamicModule) else module_input
        if input_id in visited_inputs:
            return visited_inputs[input_id]

        if input_id in visiting_inputs:
            # Recursion on the same input object before a key is assigned
            raise ModuleCycleError(
                f"Circular module dependency detected on {_display_name(module_input)}"
            )

        compiled = _expand_module_input(module_input, instance_id=str(dynamic_counter))
        if isinstance(module_input, DynamicModule):
            dynamic_counter += 1

        key = compiled.key
        # We must check key in stack here as well for mixed static/dynamic re-entry 
        # (Though unique keys for dynamic should prevent this for dynamic instances themselves)
        if key in visiting_stack:
            cycle_start = visiting_stack.index(key)
            cycle_keys = visiting_stack[cycle_start:] + [key]
            cycle_path = " -> ".join(_display_name(k) for k in cycle_keys)
            raise ModuleCycleError(f"Circular module imports detected: {cycle_path}")

        compiled_by_key[key] = compiled

        # Discovery
        visiting_inputs.add(input_id)
        visiting_stack.append(key)
        try:
            bindings = _validate_module_compiled(compiled)
            bindings_by_key[key] = bindings

            # Pre-order traversal preserves declaration order
            ordered_keys.append(key)
            for imported_input in compiled.metadata.imports:
                visit(imported_input)
        finally:
            visiting_inputs.remove(input_id)
            visiting_stack.pop()

        visited_inputs[input_id] = key
        return key

    root_key = visit(root_module)

    nodes_by_key: dict[ModuleKey, ModuleNode] = {}
    for key in ordered_keys:
        compiled = compiled_by_key[key]
        metadata = compiled.metadata
        bindings = bindings_by_key[key]

        imported_exports = {}
        for imported_input in metadata.imports:
            # We must resolve the unique key assigned to this specific import registration
            input_id = id(imported_input) if isinstance(imported_input, DynamicModule) else imported_input
            imported_key = visited_inputs[input_id]
            imported_exports[imported_key] = frozenset(compiled_by_key[imported_key].metadata.exports)

        available_providers: set[object] = {b.token for b in bindings}
        for exported_tokens in imported_exports.values():
            available_providers.update(exported_tokens)

        nodes_by_key[key] = ModuleNode(
            key=key,
            module=compiled.module,
            metadata=metadata,
            exported_providers=frozenset(metadata.exports),
            available_providers=frozenset(available_providers),
            bindings=bindings,
            imported_exports=MappingProxyType(imported_exports),
        )

    graph = ModuleGraph(
        root_key=root_key,
        nodes=tuple(nodes_by_key[key] for key in ordered_keys),
        _nodes_by_key=MappingProxyType(nodes_by_key),
    )
    return validate_module_graph(graph)


def _expand_module_input(
    module_input: type[object] | DynamicModule, *, instance_id: str
) -> CompiledModuleDef:
    if isinstance(module_input, DynamicModule):
        base_metadata = get_module_metadata(module_input.module)
        if base_metadata is None:
            raise InvalidModuleError(
                f"{_qualname(module_input.module)} is not a valid base module for dynamic registration"
            )

        merged = ModuleMetadata(
            imports=tuple(base_metadata.imports) + tuple(module_input.imports),
            controllers=tuple(base_metadata.controllers) + tuple(module_input.controllers),
            providers=tuple(base_metadata.providers) + tuple(module_input.providers),
            exports=tuple(dict.fromkeys(tuple(base_metadata.exports) + tuple(module_input.exports))),
        )
        return CompiledModuleDef(
            key=ModuleInstanceKey(module_input.module, instance_id),
            module=module_input.module,
            metadata=merged,
        )

    base_metadata = get_module_metadata(module_input)
    if base_metadata is None:
        raise InvalidModuleError(
            f"{_qualname(module_input)} is not a valid module. Did you forget @Module?"
        )

    return CompiledModuleDef(
        key=module_input,
        module=module_input,
        metadata=base_metadata,
    )


def validate_module_graph(graph: ModuleGraph) -> ModuleGraph:
    """Run graph-wide validations that require the fully built graph."""

    for node in graph.nodes:
        _validate_exports(node)
        for controller_cls in node.controllers:
            _validate_controller_routes(controller_cls)
    return graph


def _validate_module_compiled(
    compiled: CompiledModuleDef,
) -> tuple[Binding, ...]:
    owner = compiled.key
    metadata = compiled.metadata

    _validate_unique_entries(owner, "imports", metadata.imports)
    _validate_unique_entries(owner, "controllers", metadata.controllers)
    _validate_unique_entries(owner, "exports", metadata.exports)

    for imported_input in metadata.imports:
        _require_module_input(imported_input, owner=owner)

    for controller_cls in metadata.controllers:
        _require_controller(controller_cls, owner=owner)

    bindings: list[Binding] = []
    seen_tokens: set[object] = set()

    for provider_entry in metadata.providers:
        try:
            binding = normalize_provider(provider_entry, owner)
        except TypeError as exc:
            raise InvalidProviderError(f"Invalid provider in {_display_name(owner)}: {exc}") from exc

        if binding.token in seen_tokens:
            raise InvalidModuleError(
                f"{_display_name(owner)} declares duplicate entries in providers: {binding.token!r}"
            )
        seen_tokens.add(binding.token)
        bindings.append(binding)

    return tuple(bindings)


def _validate_exports(node: ModuleNode) -> None:
    # A module can export its own providers OR providers imported from other modules (re-export)
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


def _require_module_input(
    module_candidate: object, *, owner: ModuleKey
) -> type[object] | DynamicModule:
    if isinstance(module_candidate, DynamicModule):
        _require_module_input(module_candidate.module, owner=owner)
        return module_candidate

    if not isinstance(module_candidate, type):
        raise InvalidModuleError(
            f"{_display_name(owner)} imports {module_candidate!r}, which is not a decorated module"
        )

    module_metadata = get_module_metadata(module_candidate)
    if not isinstance(module_metadata, ModuleMetadata):
        raise InvalidModuleError(
            f"{_display_name(owner)} imports {_qualname(module_candidate)}, "
            "which is not decorated with @Module"
        )

    return module_candidate


def _require_controller(controller_candidate: object, *, owner: ModuleKey) -> type[object]:
    if not isinstance(controller_candidate, type):
        raise InvalidControllerError(
            f"{_display_name(owner)} declares {controller_candidate!r} as a controller, but it is not a class"
        )

    controller_metadata = get_controller_metadata(controller_candidate)
    if not isinstance(controller_metadata, ControllerMetadata):
        raise InvalidControllerError(
            f"{_display_name(owner)} declares {_qualname(controller_candidate)} as a controller, "
            "but it is not decorated with @Controller"
        )

    return controller_candidate


def _validate_unique_entries(
    owner: ModuleKey,
    field_name: str,
    entries: tuple[object, ...],
) -> None:
    seen_identities: set[int | object] = set()
    for entry in entries:
        ident_val = id(entry) if isinstance(entry, DynamicModule) else entry
        if ident_val in seen_identities:
            raise InvalidModuleError(
                f"{_display_name(owner)} declares duplicate entries in {field_name}: {entry!r}"
            )
        seen_identities.add(ident_val)
