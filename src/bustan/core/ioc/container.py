"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request

from ..module.dynamic import ModuleKey
from ..module.graph import ModuleGraph
from .registry import Registry
from .scopes import ScopeManager
from .resolver import Resolver
from .overrides import OverrideManager


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
            # Register bindings
            for binding in node.bindings:
                self.registry.register_binding((node.key, binding.token), binding)

            # Determine visibility
            accessible_provider_modules: dict[object, ModuleKey] = {
                b.token: node.key for b in node.bindings
            }

            for imported_key in node.imported_exports:
                for exported_token in self.module_graph.exports_for(imported_key):
                    # Local bindings are authoritative: only add imported exports
                    # for tokens not already defined locally.
                    if exported_token not in accessible_provider_modules:
                        accessible_provider_modules[exported_token] = imported_key

            self.registry.set_visibility(node.key, accessible_provider_modules)

            # Register controllers
            for controller_cls in node.controllers:
                self.registry.register_controller(controller_cls, node.key)

    def resolve(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider visible from the given module.

        Checks for overrides first, then delegates to the recursive resolver.
        """
        if self.override_manager.has_override(token, module=module):
            return self.override_manager.get_override(token, module=module)

        return self.resolver.resolve(token, module=module, request=request)

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

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider."""
        self.override_manager.clear_override(token, module=module)

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        return self.override_manager.has_override(token, module=module)

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        return self.override_manager.get_override(token, module=module)


def build_container(module_graph: ModuleGraph) -> Container:
    """Build the runtime container for a validated module graph."""
    return Container(module_graph)
