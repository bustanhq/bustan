"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from ..common.decorators.injectable import get_provider_metadata
from ..common.metadata import get_controller_metadata
from ..common.types import PipelineOverrides, ProviderScope
from ..contracts import HttpRequest
from ..kernel.errors import InvalidControllerError, InvalidPipelineError
from ..kernel.ioc.container import Container
from ..kernel.ioc.registry import TokenKey, token_identity
from ..kernel.ioc.runtime.locks import shared_construction
from ..kernel.module.dynamic import ModuleKey
from ..kernel.utils import _qualname
from ..pipeline.filters import ExceptionFilter
from ..pipeline.guards import Guard
from ..pipeline.interceptors import Interceptor
from ..pipeline.metadata import PipelineMetadata
from ..pipeline.pipes import Pipe
from .compiler import GlobalPipelineProvider

ComponentT = TypeVar("ComponentT")

# What a resolved component is filed under: the module it is resolved through, the
# token's own type-aware identity, the contract its slot requires it to implement, and
# whether it came from a global token, which is the one case where a single token may
# stand for several components.
type _ComponentKey = tuple[ModuleKey, TokenKey, type[object], bool]

# How many whole pipelines one route keeps. A route resolves its pipeline in a few slices,
# each compiled once onto its plan, and this holds all of them with room to spare. A plan
# built for a single call, as an error path builds one, is never asked for again, so the
# table is emptied when it fills rather than growing by one entry for every such call.
_KEPT_PIPELINE_LIMIT = 8


class PipelineMemo:
    """The pipeline components one route may hand to every request it serves.

    A component is kept here only when resolving it again could not answer with
    anything else. That is settled by the rule that an override replaces a provider for
    the whole application and may only be registered before that application starts:
    once it is running, a singleton and a fixed value are what they will be for the
    rest of the run. Every other lifetime is partitioned by something a request
    carries, so none of them is kept and each request resolves its own.

    A pipeline built from nothing but settled components is kept whole as well, under
    the plan it was resolved for, so a later request resolving that plan builds nothing.

    The instances belong to one container's set. A shutdown destroys that set and the
    next startup builds another from the same graph, so what is kept is remembered
    alongside the container and the generation it came out of, and is dropped rather
    than served once either has moved on.
    """

    __slots__ = ("_container", "_entries", "_generation", "_pipelines")

    def __init__(self) -> None:
        self._entries: dict[_ComponentKey, tuple[object, ...]] = {}
        # Filed under the identity of the plan, and holding the plan itself, so no other
        # plan can be given that identity for as long as the entry exists.
        self._pipelines: dict[int, tuple[PipelineMetadata, ResolvedPipeline]] = {}
        self._container: Container | None = None
        self._generation = -1

    def get(self, container: Container, key: _ComponentKey) -> tuple[object, ...] | None:
        """Return the instances kept under a key, or ``None`` when none are."""

        self._follow(container)
        return self._entries.get(key)

    def keep(self, container: Container, key: _ComponentKey, instances: tuple[object, ...]) -> None:
        """Keep the instances a key resolved to for every request that follows."""

        self._follow(container)
        self._entries[key] = instances

    def get_pipeline(self, container: Container, plan: PipelineMetadata) -> ResolvedPipeline | None:
        """Return the pipeline kept for a plan, or ``None`` when none is."""

        self._follow(container)
        kept = self._pipelines.get(id(plan))
        return None if kept is None else kept[1]

    def keep_pipeline(
        self, container: Container, plan: PipelineMetadata, pipeline: ResolvedPipeline
    ) -> None:
        """Keep the pipeline a plan resolved to for every request that follows."""

        self._follow(container)
        if len(self._pipelines) >= _KEPT_PIPELINE_LIMIT:
            self._pipelines.clear()
        self._pipelines[id(plan)] = (plan, pipeline)

    def _follow(self, container: Container) -> None:
        """Empty the memo when it is holding instances a container no longer has."""

        generation = container.instance_generation
        if container is self._container and generation == self._generation:
            return
        self._entries.clear()
        self._pipelines.clear()
        self._container = container
        self._generation = generation


class ControllerFactory:
    """Manages the creation and DI-resolution of controllers and their pipelines."""

    def __init__(
        self,
        container: Container,
        *,
        pipeline_override_registry: PipelineOverrides[PipelineMetadata] | None = None,
    ) -> None:
        self.container = container
        self.pipeline_override_registry = pipeline_override_registry

    async def instantiate_async(
        self,
        controller_cls: type[object],
        *,
        module: ModuleKey,
        request: HttpRequest,
    ) -> object:
        """Instantiate a controller for a request, awaiting asynchronous dependencies.

        This is the driver the HTTP runtime uses, and the only one a request goes
        through, so a controller may depend on a provider only an awaited factory can
        build whatever lifetime that provider declares.
        """
        controller_key = (module, controller_cls)
        # Nothing but a controller declared a singleton is ever kept under this key, so
        # one already built is served before its declaration is read again, and without
        # queuing for the lock that guards its construction.
        instance = self.container.scope_manager.get_controller_singleton(controller_key)
        if instance is not None:
            return instance

        scope = self._controller_scope(controller_cls)
        if scope is ProviderScope.TRANSIENT:
            return await self.container.instantiate_class_async(
                controller_cls, module=module, request=request
            )

        if scope is ProviderScope.REQUEST:
            request_cache = self.container.scope_manager.get_request_controller_cache(request)
            instance = request_cache.get(controller_key)
            if instance is None:
                instance = await self.container.instantiate_class_async(
                    controller_cls, module=module, request=request
                )
                # A check and set, because two stages of one request can build at the
                # same time and the request is promised one controller, not two.
                instance = request_cache.setdefault(controller_key, instance)
            return instance

        # The lock a synchronous construction would take, taken here without stalling
        # the loop, so one controller cannot be built twice by two different drivers.
        async with shared_construction(self.container.scope_manager, controller_key):
            instance = self.container.scope_manager.get_controller_singleton(controller_key)
            if instance is None:
                instance = await self.container.instantiate_class_async(
                    controller_cls, module=module, request=request
                )
                self.container.scope_manager.set_controller_singleton(controller_key, instance)
        assert instance is not None
        return instance

    def _controller_scope(self, controller_cls: type[object]) -> ProviderScope:
        """Return the lifetime a controller declared, refusing one it cannot have."""

        metadata = get_controller_metadata(controller_cls)
        scope = metadata.scope if metadata is not None else ProviderScope.SINGLETON
        if scope in {ProviderScope.TRANSIENT, ProviderScope.REQUEST, ProviderScope.SINGLETON}:
            return scope

        # Every remaining lifetime partitions instances by a key a controller does not
        # carry, so serving one would mean handing one caller's instance to the next.
        # The compiler refuses such a declaration while the application is built; this
        # guard keeps the fall-through from quietly reappearing behind a new scope.
        raise InvalidControllerError(
            f"{_qualname(controller_cls)} declares scope {scope.value!r}, which a "
            "controller cannot have; declare a singleton, request or transient controller"
        )

    async def resolve_pipeline_async(
        self,
        metadata: PipelineMetadata,
        *,
        module: ModuleKey,
        request: HttpRequest,
        memo: PipelineMemo | None = None,
    ) -> ResolvedPipeline:
        """Resolve a route's pipeline for one request, awaiting asynchronous factories.

        ``memo`` is where a route keeps what cannot come out differently for the next
        request: each settled component, and each pipeline built from nothing else. A
        route whose pipeline is entirely settled therefore resolves nothing from the
        container and builds nothing after the first request that reaches it. Passing
        none resolves everything afresh, which is what an unsettled pipeline does
        anyway; the answer is the same either way.

        A pipeline resolved through an override registry is never kept whole: test
        support can still write a replacement into the registry once the application is
        compiled, and a kept pipeline would go on serving the component it replaced. A
        plan that declares nothing needs no keeping, and resolves to one shared pipeline.
        """
        registry = self.pipeline_override_registry
        if registry is not None:
            metadata = registry.apply_to_metadata(metadata)
        if not (metadata.guards or metadata.pipes or metadata.interceptors or metadata.filters):
            return _EMPTY_PIPELINE
        keeper = memo if registry is None else None
        if keeper is not None:
            kept = keeper.get_pipeline(self.container, metadata)
            if kept is not None:
                return kept

        guards, guards_settled = await self._resolve_components_async(
            metadata.guards, Guard, module=module, request=request, kind="guard", memo=memo
        )
        pipes, pipes_settled = await self._resolve_components_async(
            metadata.pipes, Pipe, module=module, request=request, kind="pipe", memo=memo
        )
        interceptors, interceptors_settled = await self._resolve_components_async(
            metadata.interceptors,
            Interceptor,
            module=module,
            request=request,
            kind="interceptor",
            memo=memo,
        )
        filters, filters_settled = await self._resolve_components_async(
            metadata.filters,
            ExceptionFilter,
            module=module,
            request=request,
            kind="filter",
            memo=memo,
        )
        pipeline = ResolvedPipeline(
            guards=guards, pipes=pipes, interceptors=interceptors, filters=filters
        )
        if keeper is not None and (
            guards_settled and pipes_settled and interceptors_settled and filters_settled
        ):
            keeper.keep_pipeline(self.container, metadata, pipeline)
        return pipeline

    def resolve_components(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: HttpRequest,
        kind: str,
    ) -> tuple[ComponentT, ...]:
        """Resolve individual components (instances or classes) into instances."""
        resolved: list[ComponentT] = []
        for component in components:
            source = self._container_source(component, module)
            if source is None:
                instances: tuple[object, ...] = (self._build_unmanaged(component, kind),)
            else:
                token, owner = source
                instances = self._expanded(
                    component, self.container.resolve(token, module=owner, request=request)
                )
            resolved.extend(self._verified(instance, expected_type, kind) for instance in instances)
        return tuple(resolved)

    async def _resolve_components_async(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: HttpRequest,
        kind: str,
        memo: PipelineMemo | None,
    ) -> tuple[tuple[ComponentT, ...], bool]:
        """Resolve pipeline components for one request, awaiting asynchronous factories.

        Returned beside them is whether the next request would be handed these same
        instances: it would when each one was kept in ``memo`` or is an instance the
        author wrote out. A class built here is a new instance every time, and nothing
        is kept without a memo to keep it in.
        """
        resolved: list[ComponentT] = []
        settled = True
        for component in components:
            source = self._container_source(component, module)
            if source is None:
                if isinstance(component, type):
                    settled = False
                unmanaged = self._build_unmanaged(component, kind)
                resolved.append(self._verified(unmanaged, expected_type, kind))
                continue

            token, owner = source
            key: _ComponentKey = (
                owner,
                token_identity(token),
                expected_type,
                isinstance(component, GlobalPipelineProvider),
            )
            kept = memo.get(self.container, key) if memo is not None else None
            if kept is not None:
                resolved.extend(cast("tuple[ComponentT, ...]", kept))
                continue

            instances = tuple(
                self._verified(instance, expected_type, kind)
                for instance in self._expanded(
                    component,
                    await self.container.resolve_async(token, module=owner, request=request),
                )
            )
            if memo is not None and self._settled(token, owner):
                memo.keep(self.container, key, instances)
            else:
                settled = False
            resolved.extend(instances)
        return tuple(resolved), settled

    def _settled(self, token: object, owner: ModuleKey) -> bool:
        """Report whether resolving a token again would answer with the same object.

        An override replaces a provider for the whole application, and registering one
        is refused once that application has started, so a running application's
        singletons and its fixed values are what they will be until it stops. Anything
        built for a shorter lifetime is partitioned by something a request carries -
        the request itself, the partition a durable provider derives from it, or
        nothing at all for a transient - so it is a different object each time and is
        never treated as settled.
        """

        container = self.container
        if not container.override_manager.started:
            return False
        visibility = container.registry.visibility_view.get(owner)
        if visibility is None:
            return False
        declaring_module = visibility.get(token)
        if declaring_module is None:
            return False
        binding = container.registry.get_binding((declaring_module, token))
        if binding is None:
            return False
        return binding.scope is ProviderScope.SINGLETON or binding.resolver_kind == "value"

    def _container_source(
        self, component: object, module: ModuleKey
    ) -> tuple[object, ModuleKey] | None:
        """Return the token and module a component is built from, or ``None``.

        A component the container knows about is built by the container, so it receives
        its dependencies and its declared lifetime. Anything else is a plain class or an
        instance the author wrote out, and is built here.
        """

        if isinstance(component, GlobalPipelineProvider):
            return component.token, component.module
        if not isinstance(component, type):
            return None
        if get_provider_metadata(component) is not None or self._is_registered(component, module):
            return component, module
        return None

    def _expanded(self, component: object, resolved: object) -> tuple[object, ...]:
        """Expand a global token bound to a list into the components it names.

        One global token may stand for several components, so a module registers more
        than one global guard, pipe, interceptor or filter by binding a list under the
        token. They run in the order the list was written.
        """

        if isinstance(component, GlobalPipelineProvider) and isinstance(resolved, (list, tuple)):
            return tuple(resolved)
        return (resolved,)

    def _is_registered(self, component: type[object], module: ModuleKey) -> bool:
        """Return whether a module can see a provider registered under this class."""

        return component in self.container.registry.visibility_view.get(module, {})

    def _build_unmanaged(self, component: object, kind: str) -> object:
        """Build a component the container does not know about, or refuse it."""

        if not isinstance(component, type):
            return component
        try:
            return component()
        except TypeError as exc:
            raise InvalidPipelineError(
                f"{kind.capitalize()} {_qualname(component)} must be an instance, "
                "a no-argument class, or an @Injectable provider"
            ) from exc

    def _verified(self, instance: object, expected_type: type[ComponentT], kind: str) -> ComponentT:
        """Return an instance that implements the contract its slot requires."""

        if not isinstance(instance, expected_type):
            raise InvalidPipelineError(
                f"Resolved {kind} {_qualname(type(instance))} must inherit from "
                f"{expected_type.__name__}"
            )
        return instance


@dataclass(frozen=True, slots=True)
class ResolvedPipeline:
    """Container for instantiated pipeline components."""

    guards: tuple[Guard, ...]
    pipes: tuple[Pipe, ...]
    interceptors: tuple[Interceptor, ...]
    filters: tuple[ExceptionFilter, ...]


# What every plan declaring nothing resolves to. It holds no instance, so one pipeline
# serves each such plan whatever container, run or request it is resolved for.
_EMPTY_PIPELINE = ResolvedPipeline(guards=(), pipes=(), interceptors=(), filters=())
