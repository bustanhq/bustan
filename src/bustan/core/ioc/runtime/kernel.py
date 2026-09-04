"""Find an instance in a cache, or build one from the plan the container computed."""

from __future__ import annotations

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ....common.types import ProviderScope
from ...errors import ProviderResolutionError
from ...utils import _display_name, _qualname
from ..planning.container_plan import plan_target
from ..planning.plan import (
    CONTAINER_TOKEN_SOURCES,
    ActiveApplication,
    ActiveRequest,
    ActiveResponse,
    ArgumentSource,
    ConstructionPlan,
    ContainerPlan,
    FixedValue,
    PlannedArgument,
    ProvidedToken,
    TargetKey,
)
from ..planning.scopes import entered_request_scope
from ..scopes import CACHE_MISS, DurableProvider, ScopeManager
from .steps import NO_CACHE, Guarded, InstanceCache, Invoke, Machine, Resolve, Site, Step

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from ...module.dynamic import ModuleKey
    from ..overrides import OverrideManager
    from ..registry import Binding, Registry

__all__ = ["ResolutionFrame", "ResolutionKernel"]


@dataclass(frozen=True, slots=True)
class ResolutionFrame:
    """One binding whose construction has started and not yet finished."""

    token: object
    module: ModuleKey


class ResolutionKernel:
    """Resolve tokens and build classes by executing plans, without reading a signature.

    The kernel holds no plan of its own: every class the module graph declares was
    planned while the container was built, and a class handed to it from outside the
    graph is planned once on first use.
    """

    def __init__(
        self,
        registry: Registry,
        scope_manager: ScopeManager,
        override_manager: OverrideManager,
        plan: ContainerPlan,
    ) -> None:
        self.registry = registry
        self.scope_manager = scope_manager
        self.override_manager = override_manager
        self.plan = plan
        self._unplanned: dict[TargetKey, ConstructionPlan] = {}
        self.resolution_stack: ContextVar[tuple[ResolutionFrame, ...]] = ContextVar(
            "bustan_resolution_stack", default=()
        )
        # Classes whose constructors are currently being built, outermost first.
        # INQUIRER reads the entry below the class being built.
        self.construction_stack: ContextVar[tuple[type[object], ...]] = ContextVar(
            "bustan_construction_stack", default=()
        )

    def resolve(
        self, token: object, *, module: ModuleKey, request: Request | None = None
    ) -> object:
        """Resolve a provider visible from the given module."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return self._run(self._resolve_steps(token, module))

    async def resolve_async(
        self, token: object, *, module: ModuleKey, request: Request | None = None
    ) -> object:
        """Resolve a provider, awaiting async factories when required."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return await self._run_async(self._resolve_steps(token, module))

    def instantiate_class(
        self, cls: type[object], *, module: ModuleKey, request: Request | None = None
    ) -> object:
        """Build one fresh instance of a class, resolving its constructor dependencies."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return self._run(self._build_steps(self._plan_for(cls, module)))

    async def instantiate_class_async(
        self, cls: type[object], *, module: ModuleKey, request: Request | None = None
    ) -> object:
        """Build one fresh instance of a class, awaiting async dependencies."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return await self._run_async(self._build_steps(self._plan_for(cls, module)))

    def call_factory(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a factory's declared tokens and call it."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return self._run(self._factory_steps(factory, inject, module))

    async def call_factory_async(
        self,
        factory: Callable[..., object],
        inject: tuple[object, ...],
        *,
        module: ModuleKey,
        request: Request | None = None,
    ) -> object:
        """Resolve a factory's declared tokens and call it, awaiting an async factory."""

        with entered_request_scope(self.scope_manager.active_request, request):
            return await self._run_async(self._factory_steps(factory, inject, module))

    def _run(self, machine: Machine) -> object:
        """Drive one construction to completion, taking every step synchronously."""

        try:
            sent: object = None
            while True:
                try:
                    step = machine.send(sent)
                except StopIteration as stop:
                    return cast(object, stop.value)
                sent = self._take(step)
        finally:
            # A machine abandoned mid-construction has to be closed here, where the
            # context that entered its scopes is still current. Left to the garbage
            # collector it would try to leave them from wherever collection happens.
            machine.close()

    async def _run_async(self, machine: Machine) -> object:
        """Drive one construction to completion, awaiting the steps that can be awaited."""

        try:
            sent: object = None
            while True:
                try:
                    step = machine.send(sent)
                except StopIteration as stop:
                    return cast(object, stop.value)
                sent = await self._take_async(step)
        finally:
            machine.close()

    def _take(self, step: Step) -> object:
        if isinstance(step, Resolve):
            try:
                return self._run(self._resolve_steps(step.token, step.module, step.site))
            except ProviderResolutionError as exc:
                raise self._dependency_failure(step, exc) from exc
        if isinstance(step, Guarded):
            with self.scope_manager.get_construction_lock(step.key):
                return self._run(step.machine)
        if inspect.iscoroutinefunction(step.factory):
            raise self._async_factory_refusal(step)
        result = step.factory(*step.arguments)
        if inspect.isawaitable(result):
            # Closing it first keeps a refused resolution from leaving an un-awaited
            # coroutine behind for the interpreter to complain about later.
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise self._async_factory_refusal(step)
        return result

    def _async_factory_refusal(self, step: Invoke) -> ProviderResolutionError:
        """Refuse an async factory reached by a caller that cannot await it."""

        return ProviderResolutionError(
            f"{step.label} is an async factory and cannot be called during synchronous "
            "resolution. Initialize the application before resolving what it provides"
        )

    async def _take_async(self, step: Step) -> object:
        if isinstance(step, Resolve):
            machine = self._resolve_steps(step.token, step.module, step.site)
            try:
                return await self._run_async(machine)
            except ProviderResolutionError as exc:
                raise self._dependency_failure(step, exc) from exc
        if isinstance(step, Guarded):
            async with self.scope_manager.get_async_construction_lock(step.key):
                return await self._run_async(step.machine)
        result = step.factory(*step.arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def _resolve_steps(self, token: object, module: ModuleKey, site: Site | None = None) -> Machine:
        """Answer a token from a cache, from an override, or by building it."""

        source = _container_source(token)
        if source is not None:
            return self._context_value(source, _asked_at(token, site))

        declaring_module = self._declaring_module(token, module)
        # Overrides are keyed by the declaring module, so overriding an exported
        # provider also takes effect when it is resolved through an importing module.
        if self.override_manager.has_override(token, module=declaring_module):
            return self.override_manager.get_override(token, module=declaring_module)

        key = (declaring_module, token)
        binding = self.registry.get_binding(key)
        if binding is None:
            raise ProviderResolutionError(f"Binding not found for {_qualname(token)}")

        cache = self._cache_for(binding, key)
        cached = cache.get()
        if cached is not CACHE_MISS:
            return cached

        self._check_for_cycle(token, declaring_module)
        if cache.shared:
            return (yield Guarded(cache.key, self._cached_construction(binding, key, cache)))
        return (yield from self._cached_construction(binding, key, cache))

    def _cached_construction(
        self, binding: Binding, key: tuple[ModuleKey, object], cache: InstanceCache
    ) -> Machine:
        """Build a binding's instance and keep it, re-reading a shared slot first.

        The second read matters only for a shared slot: the caller that waited on the
        lock must see what the caller that held it built, or the two would both build
        and one instance would be orphaned.
        """

        cached = cache.get()
        if cached is not CACHE_MISS:
            return cached
        instance = yield from self._construct_steps(binding, key)
        cache.set(instance)
        return instance

    def _construct_steps(self, binding: Binding, key: tuple[ModuleKey, object]) -> Machine:
        """Build one binding's instance according to the kind of binding it is."""

        module, token = key
        frame = self.resolution_stack.set(
            (*self.resolution_stack.get(), ResolutionFrame(token, module))
        )
        try:
            if binding.resolver_kind == "value":
                return binding.target
            if binding.resolver_kind == "existing":
                site = Site(_qualname(token), "alias target")
                return (yield Resolve(binding.target, module, site))
            if binding.resolver_kind == "class":
                target = cast(type[object], binding.target)
                return (yield from self._build_steps(self._plan_for(target, module)))
            if binding.resolver_kind == "factory":
                factory, inject = cast(
                    "tuple[Callable[..., object], tuple[object, ...]]", binding.target
                )
                return (yield from self._factory_steps(factory, inject, module))
            raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")
        finally:
            self.resolution_stack.reset(frame)

    def _factory_steps(
        self, factory: Callable[..., object], inject: tuple[object, ...], module: ModuleKey
    ) -> Machine:
        """Resolve every token a factory declares, then call it with them."""

        label = _factory_label(factory)
        owner = f"Factory {label}"
        arguments: list[object] = []
        for position, token in enumerate(inject):
            site = Site(owner, f"inject entry {position}")
            arguments.append((yield Resolve(token, module, site)))
        return (yield Invoke(factory, tuple(arguments), label))

    def _build_steps(self, plan: ConstructionPlan) -> Machine:
        """Fill in a planned constructor's arguments and call it."""

        owner = f"{_qualname(plan.target)}.__init__"
        stack = self.construction_stack.set((*self.construction_stack.get(), plan.target))
        try:
            positional: list[object] = []
            keyword: dict[str, object] = {}
            for argument in plan.arguments:
                value = yield from self._argument_steps(plan, argument, owner)
                if argument.positional:
                    positional.append(value)
                else:
                    keyword[argument.name] = value
            return plan.target(*positional, **keyword)
        finally:
            self.construction_stack.reset(stack)

    def _argument_steps(
        self, plan: ConstructionPlan, argument: PlannedArgument, owner: str
    ) -> Machine:
        """Produce the value for one planned constructor argument."""

        site = Site(owner, f"parameter {argument.name!r}")
        if isinstance(argument.source, ProvidedToken):
            return (yield Resolve(argument.source.token, plan.module, site))
        if isinstance(argument.source, FixedValue):
            return argument.source.value
        return self._context_value(argument.source, str(site))

    def _context_value(self, source: ArgumentSource, asked_at: str) -> object:
        """Return the state the container itself owns for the call currently in flight."""

        if isinstance(source, ActiveRequest):
            request = self.scope_manager.active_request.get()
            if request is not None:
                return request
            raise ProviderResolutionError(
                f"{asked_at} asks for the request being served, and no request is being served"
            )
        if isinstance(source, ActiveResponse):
            response = self.scope_manager.active_response.get()
            if response is not None:
                return response
            raise ProviderResolutionError(
                f"{asked_at} asks for the response being assembled, and none is being assembled"
            )
        if isinstance(source, ActiveApplication):
            return self._application(asked_at)
        return self._inquirer(asked_at)

    def _application(self, asked_at: str) -> object:
        application = self.scope_manager.active_application.get()
        if application is not None:
            return application
        request = self.scope_manager.active_request.get()
        if request is not None and hasattr(request, "app"):
            return request.app
        raise ProviderResolutionError(
            f"{asked_at} asks for the running application, which is only available once one is "
            "running"
        )

    def _inquirer(self, asked_at: str) -> object:
        stack = self.construction_stack.get()
        if len(stack) < 2:
            raise ProviderResolutionError(
                f"{asked_at} asks for INQUIRER, which names the class one provider is being "
                "built for and has no value outside a nested construction"
            )
        return stack[-2]

    def _cache_for(self, binding: Binding, key: tuple[ModuleKey, object]) -> InstanceCache:
        """Return the slot a binding's instance is kept in for its declared lifetime."""

        if binding.scope is ProviderScope.SINGLETON:
            return InstanceCache(self.scope_manager.singletons, key, shared=True)
        if binding.scope is ProviderScope.DURABLE:
            return InstanceCache(
                self.scope_manager.durable_instances, self._durable_key(binding, key), shared=True
            )
        if binding.scope is ProviderScope.REQUEST:
            request = self.scope_manager.active_request.get()
            if request is None:
                raise ProviderResolutionError(
                    f"Request-scoped provider {_qualname(key[1])} requires an active request"
                )
            return InstanceCache(self.scope_manager.get_request_cache(request), key, shared=False)
        return NO_CACHE

    def _durable_key(self, binding: Binding, key: tuple[ModuleKey, object]) -> object:
        """Return the cache key partitioning a durable provider across requests."""

        target = binding.target
        if isinstance(target, type) and isinstance(target, DurableProvider):
            request = self.scope_manager.active_request.get()
            return (key[0], key[1], target.get_durable_context_key(request))
        # A durable cache must never be keyed on id(request): CPython reuses object
        # ids, which hands one request's instance to a later, unrelated request.
        raise ProviderResolutionError(
            f"Durable provider {_qualname(key[1])} must implement the DurableProvider protocol "
            "with a 'get_durable_context_key' classmethod so durable instances can be "
            "partitioned across requests"
        )

    def _plan_for(self, target: type[object], module: ModuleKey) -> ConstructionPlan:
        """Return the plan for a class, planning a class the graph does not declare."""

        planned = self.plan.for_target(module, target)
        if planned is not None:
            return planned
        unplanned = self._unplanned.get((module, target))
        if unplanned is None:
            visible = self.registry.module_visibility.get(module, {})
            unplanned = plan_target(target, module, visible)
            self._unplanned[(module, target)] = unplanned
        return unplanned

    def _declaring_module(self, token: object, module: ModuleKey) -> ModuleKey:
        visibility = self.registry.module_visibility.get(module)
        if visibility is None:
            raise ProviderResolutionError(
                f"{_display_name(module)} is not part of the application container"
            )

        declaring_module = visibility.get(token)
        if declaring_module is None:
            raise ProviderResolutionError(
                f"{_qualname(token)} is not available to {_display_name(module)}. "
                "Dependencies must come from the same module or an imported module export"
            )
        return declaring_module

    def _check_for_cycle(self, token: object, declaring_module: ModuleKey) -> None:
        # A cycle exists only when the same binding identity repeats; the same token
        # name declared by two different modules is legitimate.
        current = self.resolution_stack.get()
        if not any(frame.token == token and frame.module == declaring_module for frame in current):
            return
        path = " -> ".join(
            _display_name(frame.token)
            for frame in (*current, ResolutionFrame(token, declaring_module))
        )
        raise ProviderResolutionError(f"Circular provider dependencies detected: {path}")

    def _dependency_failure(
        self, step: Resolve, exc: ProviderResolutionError
    ) -> ProviderResolutionError:
        """Name the owner and the path when a dependency several levels down fails."""

        return ProviderResolutionError(
            f"{step.site} in {_display_name(step.module)} failed to resolve "
            f"{_qualname(step.token)} (dependency path: {self._dependency_path(step.token)}): {exc}"
        )

    def _dependency_path(self, next_token: object) -> str:
        tokens = [frame.token for frame in self.resolution_stack.get()] + [next_token]
        return " -> ".join(_display_name(token) for token in tokens)


def _container_source(token: object) -> ArgumentSource | None:
    """Return the state a container token names, or ``None`` for an ordinary token."""

    for candidate, source in CONTAINER_TOKEN_SOURCES:
        if token is candidate:
            return source
    return None


def _asked_at(token: object, site: Site | None) -> str:
    """Name the place a token was asked for, falling back to naming the token."""

    return str(site) if site is not None else _display_name(token)


def _factory_label(factory: object) -> str:
    """Return a stable name for a factory to use in a diagnostic."""

    qualname = getattr(factory, "__qualname__", None)
    if qualname is None:
        return _qualname(factory)
    module = getattr(factory, "__module__", None)
    return f"{module}.{qualname}" if module else str(qualname)
