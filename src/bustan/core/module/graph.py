"""Discovery and validation of the application module graph."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ...common.types import ProviderScope
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
from ..ioc.registry import DURABLE_CONTEXT_KEY_HOOK, Binding, TokenKey, TokenMap, token_identity
from ..ioc.scopes import DurableProvider
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
    # The tokens of visibility gathered into a set, always derived from that table and
    # never computed a second way. A set of tokens keys by equality, so it cannot carry
    # the distinction the table carries: a string enum member and the bare string it
    # equals are two declarations there and one member here, and the member does not say
    # which of the two it stands for. A caller may rely on membership, and only as a
    # question about equality: a token is in this set when some visible declaration has a
    # token equal to it, whichever spelling either side was written as, and absent when
    # none does. Size and iteration under-report such a pair, so a caller that must tell
    # two declarations apart, count them, or name the module behind one reads visibility,
    # which keys by token identity.
    available_providers: frozenset[object]
    bindings: tuple[Binding, ...]
    imported_exports: Mapping[ModuleKey, frozenset[object]] = field(repr=False)
    # Every token this module can resolve, mapped to the module that declares it. The
    # module named is always the one holding the binding, never a module that merely
    # passed the token on, so a re-export resolves to its origin. This is the only
    # visibility computation in the framework, the container copies it verbatim, and
    # resolution reads it rather than available_providers.
    visibility: Mapping[object, ModuleKey] = field(repr=False)

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
        # A set of tokens keys by equality, so membership answers whether an equal token
        # is visible, never which declaration answers for it: two equal tokens of
        # different types are one member. A caller that must tell them apart reads the
        # node's visibility table instead.
        return self.get_node(key).available_providers

    @property
    def root_module(self) -> type[object]:
        """Return the root module class."""
        if isinstance(self.root_key, type):
            return self.root_key
        return self.root_key.module


@dataclass(frozen=True, slots=True)
class _Discovery:
    """Every module reachable from the root, in the order it was first visited."""

    root_key: ModuleKey
    ordered_keys: tuple[ModuleKey, ...]
    compiled_by_key: Mapping[ModuleKey, CompiledModuleDef]
    bindings_by_key: Mapping[ModuleKey, tuple[Binding, ...]]
    _key_by_input: Mapping[int | type[object], ModuleKey] = field(repr=False)

    def imported_keys(self, key: ModuleKey) -> tuple[ModuleKey, ...]:
        """Return the graph key of each module the given module imports, in order."""
        return tuple(
            self._key_by_input[_input_identity(module_input)]
            for module_input in self.compiled_by_key[key].metadata.imports
        )


@dataclass(frozen=True, slots=True)
class _VisibilityTables:
    """The one visibility computation, keyed by module."""

    visible: Mapping[ModuleKey, Mapping[object, ModuleKey]]
    imported_exports: Mapping[ModuleKey, Mapping[ModuleKey, frozenset[object]]]


def build_module_graph(root_module: type[object] | DynamicModule) -> ModuleGraph:
    """Discover modules reachable from the root and validate them."""

    discovery = _discover_modules(root_module)
    tables = _build_visibility_tables(discovery)

    nodes_by_key: dict[ModuleKey, ModuleNode] = {}
    for key in discovery.ordered_keys:
        compiled = discovery.compiled_by_key[key]
        visibility = tables.visible[key]

        _validate_exports(key, compiled.metadata, visibility)
        for controller_cls in compiled.metadata.controllers:
            _validate_controller_routes(controller_cls)
            _refuse_unservable_controller_lifetime(controller_cls)

        nodes_by_key[key] = ModuleNode(
            key=key,
            module=compiled.module,
            metadata=compiled.metadata,
            exported_providers=frozenset(compiled.metadata.exports),
            available_providers=frozenset(visibility),
            bindings=discovery.bindings_by_key[key],
            imported_exports=tables.imported_exports[key],
            visibility=visibility,
        )

    return ModuleGraph(
        root_key=discovery.root_key,
        nodes=tuple(nodes_by_key[key] for key in discovery.ordered_keys),
        _nodes_by_key=MappingProxyType(nodes_by_key),
    )


def _discover_modules(root_module: type[object] | DynamicModule) -> _Discovery:
    """Expand and validate every module reachable from the root exactly once."""

    ordered_keys: list[ModuleKey] = []
    compiled_by_key: dict[ModuleKey, CompiledModuleDef] = {}
    bindings_by_key: dict[ModuleKey, tuple[Binding, ...]] = {}
    key_by_input: dict[int | type[object], ModuleKey] = {}

    # Two cycle checks are needed: the stack carries the path that the error message
    # reports, and the id set catches a single object that re-enters its own expansion.
    visiting_stack: list[ModuleKey] = []
    visiting_ids: set[int | type[object]] = set()
    dynamic_counter = 0

    def visit(module_input: type[object] | DynamicModule) -> ModuleKey:
        nonlocal dynamic_counter

        input_id = _input_identity(module_input)
        if input_id in key_by_input:
            return key_by_input[input_id]

        # A module input has no key until it is expanded, so expansion precedes the
        # cycle checks. Each expansion of a dynamic module yields a fresh key, so a key
        # reached here is never one already discovered.
        compiled = expand_module_input(module_input, instance_id=str(dynamic_counter))
        key = compiled.key
        _reject_cycle(key, module_input, visiting_stack, visiting_ids)

        visiting_ids.add(input_id)
        visiting_stack.append(key)
        try:
            # The counter distinguishes dynamic instances, so it may only advance once
            # this expansion is committed to.
            if isinstance(module_input, DynamicModule):
                dynamic_counter += 1

            # Preserve pre-order node discovery because import-order semantics and tests
            # depend on it.
            compiled_by_key[key] = compiled
            bindings_by_key[key] = validate_module_compiled(compiled)
            ordered_keys.append(key)

            for imported_input in compiled.metadata.imports:
                _require_module_input(imported_input, owner=key)
                visit(imported_input)

            key_by_input[input_id] = key
            return key
        finally:
            visiting_stack.pop()
            visiting_ids.discard(input_id)

    root_key = visit(root_module)

    return _Discovery(
        root_key=root_key,
        ordered_keys=tuple(ordered_keys),
        compiled_by_key=MappingProxyType(compiled_by_key),
        bindings_by_key=MappingProxyType(bindings_by_key),
        _key_by_input=MappingProxyType(key_by_input),
    )


def _build_visibility_tables(discovery: _Discovery) -> _VisibilityTables:
    """Compute which module declares each token that each module can see.

    Local bindings shadow imports, an import contributes the origin of what it exports
    rather than its own key, and the exports of every global module are visible to every
    module that does not shadow them.
    """

    local_tokens = {
        key: frozenset(token_identity(binding.token) for binding in discovery.bindings_by_key[key])
        for key in discovery.ordered_keys
    }
    base: dict[ModuleKey, TokenMap[ModuleKey]] = {}
    imported_exports: dict[ModuleKey, Mapping[ModuleKey, frozenset[object]]] = {}
    export_origins: dict[ModuleKey, TokenMap[ModuleKey]] = {}

    def resolve(key: ModuleKey) -> None:
        if key in base:
            return

        metadata = discovery.compiled_by_key[key].metadata
        _validate_export_targets(key, metadata.exports)

        visible: TokenMap[ModuleKey] = TokenMap(
            (binding.token, key) for binding in discovery.bindings_by_key[key]
        )
        supplier: TokenMap[ModuleKey] = TokenMap()
        view: dict[ModuleKey, frozenset[object]] = {}

        for imported_key in discovery.imported_keys(key):
            resolve(imported_key)
            imported_metadata = discovery.compiled_by_key[imported_key].metadata
            view[imported_key] = frozenset(imported_metadata.exports)
            _merge_import(
                owner=key,
                imported_key=imported_key,
                origins=export_origins[imported_key],
                shadowed=local_tokens[key],
                visible=visible,
                supplier=supplier,
            )

        base[key] = visible
        imported_exports[key] = MappingProxyType(view)
        # A token exported but not visible here is either invalid, which the export
        # validation reports once the global layer is known, or globally visible to
        # every module anyway, so omitting it changes no importer's view.
        export_origins[key] = TokenMap(
            (token, visible[token]) for token in metadata.exports if token in visible
        )

    for key in discovery.ordered_keys:
        resolve(key)

    global_visibility = _build_global_visibility(discovery, base)
    return _VisibilityTables(
        visible={
            key: MappingProxyType(_with_global_fallback(base[key], global_visibility))
            for key in discovery.ordered_keys
        },
        imported_exports=imported_exports,
    )


def _merge_import(
    *,
    owner: ModuleKey,
    imported_key: ModuleKey,
    origins: Mapping[object, ModuleKey],
    shadowed: frozenset[TokenKey],
    visible: TokenMap[ModuleKey],
    supplier: TokenMap[ModuleKey],
) -> None:
    """Add one import's exports to the importer's view, refusing an unshadowed collision.

    A local binding shadows only the token it was written as. A token equal to it but of
    another type is a different token, so the import still contributes its own binding
    rather than disappearing behind the local one.
    """

    for token, origin in origins.items():
        if token_identity(token) in shadowed:
            # A module's own binding wins over anything an import offers for that token.
            continue

        previous = visible.get(token)
        if previous is not None and previous != origin:
            raise InvalidModuleError(
                f"{_display_name(owner)} imports both {_display_name(supplier[token])} and "
                f"{_display_name(imported_key)}, which export {_qualname(token)} from different "
                f"modules ({_display_name(previous)} and {_display_name(origin)}). Nothing in "
                "the declaration says which one wins: import one of them, provide the token "
                "locally, or export it from a single module."
            )

        visible[token] = origin
        supplier.setdefault(token, imported_key)


def _build_global_visibility(
    discovery: _Discovery, base: Mapping[ModuleKey, Mapping[object, ModuleKey]]
) -> TokenMap[ModuleKey]:
    """Map each token a global module exports to the module that declares it."""

    visibility: TokenMap[ModuleKey] = TokenMap()
    exporter: TokenMap[ModuleKey] = TokenMap()

    for key in discovery.ordered_keys:
        metadata = discovery.compiled_by_key[key].metadata
        if not metadata.is_global:
            continue

        for token in metadata.exports:
            origin = base[key].get(token)
            if origin is None:
                continue

            previous = visibility.get(token)
            if previous is not None and previous != origin:
                raise InvalidModuleError(
                    f"Global modules {_display_name(exporter[token])} and {_display_name(key)} "
                    f"both export {_qualname(token)}, from {_display_name(previous)} and "
                    f"{_display_name(origin)}. A global export reaches every module, so nothing "
                    "can choose between them: export the token from one module only."
                )

            visibility[token] = origin
            exporter.setdefault(token, key)

    return visibility


def _with_global_fallback(
    visible: Mapping[object, ModuleKey], global_visibility: Mapping[object, ModuleKey]
) -> TokenMap[ModuleKey]:
    """Return a module's own view extended with the global exports it does not shadow."""

    merged: TokenMap[ModuleKey] = TokenMap(visible)
    for token, origin in global_visibility.items():
        merged.setdefault(token, origin)
    return merged


def _validate_export_targets(owner: ModuleKey, exports: tuple[object, ...]) -> None:
    """Refuse a module in an exports list, because a module is not a provider token."""

    for export_token in exports:
        exported = export_token.module if isinstance(export_token, DynamicModule) else export_token
        if not isinstance(exported, type) or get_module_metadata(exported) is None:
            continue

        raise InvalidModuleError(
            f"{_display_name(owner)} exports the module {_display_name(exported)}. A module is "
            "not a provider token: import it, and export the tokens it exports instead."
        )


def _validate_exports(
    key: ModuleKey, metadata: ModuleMetadata, visibility: Mapping[object, ModuleKey]
) -> None:
    for export_token in metadata.exports:
        if export_token not in visibility:
            raise ExportViolationError(
                f"{_display_name(key)} exports {_qualname(export_token)}, "
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


def _refuse_unservable_controller_lifetime(controller_cls: type[object]) -> None:
    """Refuse a controller whose declared lifetime the runtime cannot serve.

    A durable lifetime is a cache partitioned by a key the class derives from the
    request. Controllers are held per module rather than per key, so a durable
    controller would be built once and handed to every caller together with whatever
    the previous caller left on it. No request makes that work, so the declaration is
    refused while the graph is built rather than served to the first tenant.

    Every way of starting an application builds the graph, so the refusal belongs here:
    a dependency-injection context and a served application read one declaration and
    must give it one verdict. Building the graph also precedes both the container plan
    and the handler scan, which is what lets the message name the declaration at fault
    rather than a constructor parameter that cannot be edited to fix it, or a context
    key hook reported as a route method missing its decorator.
    """

    # Route validation runs first and refuses any controller carrying no metadata.
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


def _input_identity(module_input: type[object] | DynamicModule) -> int | type[object]:
    """Return the value that identifies one module input across the whole walk."""

    return id(module_input) if isinstance(module_input, DynamicModule) else module_input


def _reject_cycle(
    key: ModuleKey,
    module_input: type[object] | DynamicModule,
    visiting_stack: list[ModuleKey],
    visiting_ids: set[int | type[object]],
) -> None:
    """Refuse a module that re-enters its own expansion, naming the path that closed it."""

    if key in visiting_stack:
        cycle_keys = visiting_stack[visiting_stack.index(key) :] + [key]
        raise ModuleCycleError(f"Circular module imports detected: {_format_path(cycle_keys)}")

    if not isinstance(module_input, DynamicModule):
        # A class re-entering its own expansion carries the key it already put on the
        # stack, so the check above is the whole story for it.
        return

    if id(module_input) in visiting_ids:
        # One dynamic object re-entered: it compiles to a fresh key on every expansion, so
        # the loop closes on the object rather than on a key already in the path.
        path = f"{_format_path(visiting_stack)} -> {_display_name(module_input.module)} (dynamic)"
        raise ModuleCycleError(f"Circular module dependency detected: {path}")


def _format_path(keys: list[ModuleKey]) -> str:
    return " -> ".join(_display_name(key) for key in keys)


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
