"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request

from ..errors import InvalidModuleError
from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph
from ..utils import _display_name, _qualname
from .overrides import OverrideManager
from .registry import Registry
from .resolver import Resolver
from .scopes import ScopeManager
from .tokens import InjectionToken


class Container:
    """Resolve providers and controllers against a validated module graph.

    This class acts as a high-level orchestrator for the dependency injection
    system, delegating specialized tasks to the Registry, ScopeManager,
    Resolver, and OverrideManager.
    """

    def __init__(self, module_graph: ModuleGraph) -> None:
        self.module_graph = module_graph
        self.registry = Registry()
        self.scope_manager = ScopeManager()
        self.override_manager = OverrideManager(self.registry)
        self.resolver = Resolver(self.registry, self.scope_manager, self.override_manager)

        self._build_bindings()

    def _build_bindings(self) -> None:
        """Populate the registry and visibility rules from the module graph."""
        for node in self.module_graph.nodes:
            for binding in node.bindings:
                self.registry.register_binding((node.key, binding.token), binding)

            # Visibility is computed once, by the graph. Copying it here rather than
            # recomputing the rule is what keeps the documented graph view and the
            # resolvable set the same set.
            self.registry.set_visibility(node.key, dict(node.visibility))

            for controller_cls in node.controllers:
                self.registry.register_controller(controller_cls, node.key)

        self._verify_visibility_is_backed_by_bindings()

    def _verify_visibility_is_backed_by_bindings(self) -> None:
        """Assert the invariant that every visible token names a module that binds it.

        Visibility a binding does not back is a promise kept only until the first
        request that needs the token, so it is refused at bootstrap instead.
        """
        for module_key, visibility in self.registry.module_visibility.items():
            for token, declaring_module in visibility.items():
                if (declaring_module, token) in self.registry.bindings:
                    continue
                raise InvalidModuleError(
                    f"{_qualname(token)} is visible to {_display_name(module_key)} through "
                    f"{_display_name(declaring_module)}, which declares no provider for it"
                )

    def resolve(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider visible from the given module.

        The resolver honors overrides against the token's declaring module,
        so overriding an exported provider also applies to importing modules.
        """
        return self.resolver.resolve(token, module=module, request=request)

    async def resolve_async(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider, awaiting async factories when required."""

        return await self.resolver.resolve_async(token, module=module, request=request)

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a fresh controller or class instance."""
        return self.resolver.instantiate_class(cls, module=module, request=request)

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve parameters and call the factory."""
        return self.resolver.call_factory(factory, inject, module=module, request=request)

    def override(self, token: object, value: object, *, module: ModuleKey | None = None) -> None:
        """Register a replacement object for a provider."""
        self.override_manager.override(token, value, module=module)
        self.scope_manager.clear_controller_singletons()

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider."""
        self.override_manager.clear_override(token, module=module)
        self.scope_manager.clear_controller_singletons()

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        return self.override_manager.has_override(token, module=module)

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        return self.override_manager.get_override(token, module=module)

    def get_global_pipeline_providers(self, token: InjectionToken[object]) -> tuple[object, ...]:
        """Resolve APP_* providers in module registration order."""
        resolved: list[object] = []
        for node in self.module_graph.nodes:
            if (node.key, token) not in self.registry.bindings:
                continue
            resolved.append(self.resolve(token, module=node.key))
        return tuple(resolved)


def build_container(module_graph: ModuleGraph) -> Container:
    """Build the runtime container for a validated module graph."""
    return Container(module_graph)
