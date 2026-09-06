"""Dependency injection container assembly and runtime resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import InvalidModuleError, ProviderResolutionError
from ..utils import _display_name, _qualname
from .overrides import OverrideManager
from .planning.container_plan import plan_container
from .registry import Registry
from .runtime.kernel import ResolutionKernel
from .scopes import ScopeManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...contracts import HttpRequest
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
        self._shut_down = False

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

    def mark_startup_begun(self) -> None:
        """Report that a startup has begun, so providers may be resolved again.

        A startup resolves the providers it initializes, so the refusal a completed
        shutdown installed is lifted before the first startup stage runs rather than
        after the last one.
        """
        self._shut_down = False

    def mark_shut_down(self) -> None:
        """Report that a teardown has completed and every instance has been dropped.

        Resolution is refused from here until the next startup: the instances this
        container held have been destroyed, and building replacements for them outside
        a startup would hand back providers whose initialization hooks never ran.
        """
        self._shut_down = True

    @property
    def is_shut_down(self) -> bool:
        """Report whether a completed shutdown is still waiting for the next startup."""
        return self._shut_down

    def _refuse_while_shut_down(self, subject: object) -> None:
        """Refuse to build anything between a completed shutdown and the next startup.

        The rule is the same for every binding, including a transient one and a
        ``use_value`` one that carry no initialization hooks of their own. An exception
        for those two could not be held to: a transient provider reaches the destroyed
        singletons through its dependencies, and letting the transient through would
        rebuild them here, uninitialized, which is the whole of what this refusal
        exists to prevent. Which kind of binding declares a token is also the declaring
        module's business and changes without notice to the caller, so an exception
        would make resolvability after shutdown a detail of somebody else's module.
        """
        if not self._shut_down:
            return
        raise ProviderResolutionError(
            f"{_qualname(subject)} cannot be resolved because the application has been shut "
            "down and every instance it built has been destroyed. Start the application "
            "again to build a fresh set of instances, then resolve from that one"
        )

    def resolve(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Resolve a provider visible from the given module.

        Passing no request resolves as though none were in flight, so an imperative
        resolution never captures a request that merely happens to be active further
        out. Overrides are honoured against the token's declaring module, so
        overriding an exported provider also applies to importing modules.

        Between a completed shutdown and the next startup nothing resolves: the
        application has destroyed what it built, so the caller is told to start it
        again rather than handed a provider that was never initialized.
        """
        self._refuse_while_shut_down(token)
        return self.kernel.resolve(token, module=module, request=request)

    async def resolve_async(
        self,
        token: object,
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Resolve a provider, awaiting async factories when required."""

        self._refuse_while_shut_down(token)
        return await self.kernel.resolve_async(token, module=module, request=request)

    def instantiate_class(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Build one fresh instance of a class, such as a controller or a test double."""
        self._refuse_while_shut_down(cls)
        return self.kernel.instantiate_class(cls, module=module, request=request)

    async def instantiate_class_async(
        self,
        cls: type[object],
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Build one fresh instance of a class, awaiting async dependencies."""
        self._refuse_while_shut_down(cls)
        return await self.kernel.instantiate_class_async(cls, module=module, request=request)

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Resolve the tokens a factory declares and call it."""
        self._refuse_while_shut_down(factory)
        return self.kernel.call_factory(factory, inject, module=module, request=request)

    async def call_factory_async(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: HttpRequest | None = None,
    ) -> object:
        """Resolve the tokens a factory declares and call it, awaiting an async factory."""
        self._refuse_while_shut_down(factory)
        return await self.kernel.call_factory_async(factory, inject, module=module, request=request)

    def override(self, token: object, value: object, *, module: ModuleKey | None = None) -> None:
        """Register a replacement object for a provider, before the application starts.

        The replacement reaches every consumer of the token and not only the ones built
        after it: whatever was already built from the binding, or from a binding that
        transitively depends on it, is dropped and built again against the replacement.
        An override is refused once the application is running, because replacing a
        provider under a request that is holding it is not something it can survive.

        ``module`` names the module that declares the provider and is needed only when
        more than one declares the token. A module class names every dynamic
        registration of it, so a provider a dynamic module declares is targeted by
        writing the class.
        """
        self.override_manager.override(
            token, value, module=module, plan=self.plan, scopes=self.scope_manager
        )

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider, before the application starts.

        Everything built while the replacement stood is dropped with it, so a singleton
        first built against a replacement does not outlive the override that installed it.
        """
        self.override_manager.clear_override(
            token, module=module, plan=self.plan, scopes=self.scope_manager
        )

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        """Report whether a replacement object is registered for a provider.

        A token no module declares, or one several declare without ``module`` saying
        which, has no single binding to answer for and so reports no override.
        """
        return self.override_manager.has_override(token, module=module)

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        """Return the replacement object registered for a provider, if there is one."""
        return self.override_manager.get_override(token, module=module)

    def get_global_pipeline_providers(self, token: InjectionToken[object]) -> tuple[ModuleKey, ...]:
        """Return the modules declaring a global pipeline token, in registration order.

        What a global guard, pipe, interceptor or filter token means is not settled
        until a request runs it: the provider may be request-scoped, may be built by an
        async factory, and may have been replaced by an override registered after the
        application was built. So this names where each component comes from rather
        than building it, and the runtime resolves it once per request.
        """
        return tuple(
            node.key
            for node in self.module_graph.nodes
            if (node.key, token) in self.registry.bindings
        )


def build_container(module_graph: ModuleGraph) -> Container:
    """Build the runtime container for a validated module graph."""
    return Container(module_graph)
