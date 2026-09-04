"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import InvalidModuleError
from ..utils import _display_name, _qualname
from .overrides import OverrideManager
from .planning.container_plan import plan_container
from .registry import Registry
from .runtime.kernel import ResolutionKernel
from .scopes import ScopeManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from ..module.dynamic import ModuleKey
    from ..module.graph import ModuleGraph
    from .tokens import InjectionToken


class Container:
    """Resolve providers and controllers against a validated module graph.

    Building one is the whole of the framework's bootstrap-time reasoning about
    dependencies: every class the graph can build is planned here, and a graph whose
    plan cannot be completed is refused now, naming every reason at once, rather than
    on whichever request first happens to touch the mistake.
    """

    def __init__(self, module_graph: ModuleGraph) -> None:
        self.module_graph = module_graph
        self.registry = Registry()
        self.scope_manager = ScopeManager()
        self.override_manager = OverrideManager(self.registry)

        self._build_bindings()
        self.plan = plan_container(
            bindings=self.registry.bindings,
            visibility=self.registry.module_visibility,
            controllers=self.registry.controller_modules,
        )
        self.kernel = ResolutionKernel(
            self.registry, self.scope_manager, self.override_manager, self.plan
        )

    def _build_bindings(self) -> None:
        """Populate the registry and visibility rules from the module graph."""
        for node in self.module_graph.nodes:
            for binding in node.bindings:
                self.registry.register_binding((node.key, binding.token), binding)

            # Visibility is computed once, by the graph. Copying it here rather than
            # recomputing the rule is what keeps the documented graph view and the
            # resolvable set the same set.
            self.registry.set_visibility(node.key, node.visibility)

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

        Passing no request resolves as though none were in flight, so an imperative
        resolution never captures a request that merely happens to be active further
        out. Overrides are honoured against the token's declaring module, so
        overriding an exported provider also applies to importing modules.
        """
        return self.kernel.resolve(token, module=module, request=request)

    async def resolve_async(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a provider, awaiting async factories when required."""

        return await self.kernel.resolve_async(token, module=module, request=request)

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Build one fresh instance of a class, such as a controller or a test double."""
        return self.kernel.instantiate_class(cls, module=module, request=request)

    async def instantiate_class_async(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Build one fresh instance of a class, awaiting async dependencies."""
        return await self.kernel.instantiate_class_async(cls, module=module, request=request)

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve the tokens a factory declares and call it."""
        return self.kernel.call_factory(factory, inject, module=module, request=request)

    async def call_factory_async(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve the tokens a factory declares and call it, awaiting an async factory."""
        return await self.kernel.call_factory_async(factory, inject, module=module, request=request)

    def override(self, token: object, value: object, *, module: ModuleKey | None = None) -> None:
        """Register a replacement object for a provider."""
        self.override_manager.override(token, value, module=module)
        self.scope_manager.clear_controller_singletons()

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider."""
        self.override_manager.clear_override(token, module=module)
        self.scope_manager.clear_controller_singletons()

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        """Report whether a replacement object is registered for a provider."""
        return self.override_manager.has_override(token, module=module)

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        """Return the replacement object registered for a provider, if there is one."""
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
