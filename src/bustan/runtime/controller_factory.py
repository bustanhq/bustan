"""Factory for controller instantiation and pipeline component resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from ..common.decorators.injectable import get_provider_metadata
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
from .metadata import get_controller_metadata

ComponentT = TypeVar("ComponentT")

# What a resolved component is filed under: the module it is resolved through, the
# token's own type-aware identity, the contract its slot requires it to implement, and
# whether it came from a global token, which is the one case where a single token may
# stand for several components.
type _ComponentKey = tuple[ModuleKey, TokenKey, type[object], bool]


class PipelineMemo:
    """The pipeline components one route may hand to every request it serves.

    A component is kept here only when resolving it again could not answer with
    anything else. That is settled by the rule that an override replaces a provider for
    the whole application and may only be registered before that application starts:
    once it is running, a singleton and a fixed value are what they will be for the
    rest of the run. Every other lifetime is partitioned by something a request
    carries, so none of them is kept and each request resolves its own.

    The instances belong to one container's set. A shutdown destroys that set and the
    next startup builds another from the same graph, so what is kept is remembered
    alongside the container and the generation it came out of, and is dropped rather
    than served once either has moved on.
    """

    __slots__ = ("_container", "_entries", "_generation")

    def __init__(self) -> None:
        self._entries: dict[_ComponentKey, tuple[object, ...]] = {}
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

    def _follow(self, container: Container) -> None:
        """Empty the memo when it is holding instances a container no longer has."""

        generation = container.instance_generation
        if container is self._container and generation == self._generation:
            return
        self._entries.clear()
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
        scope = self._controller_scope(controller_cls)
        controller_key = (module, controller_cls)

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

        instance = self.container.scope_manager.get_controller_singleton(controller_key)
        if instance is not None:
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

        ``memo`` is where a route keeps the components that cannot come out differently
        for the next request, so a route whose pipeline is entirely settled resolves
        nothing from the container after the first request that reaches it. Passing
        none resolves everything afresh, which is what an unsettled pipeline does
        anyway; the answer is the same either way.
        """
        metadata = self._overridden(metadata)
        return ResolvedPipeline(
            guards=await self.resolve_components_async(
                metadata.guards, Guard, module=module, request=request, kind="guard", memo=memo
            ),
            pipes=await self.resolve_components_async(
                metadata.pipes, Pipe, module=module, request=request, kind="pipe", memo=memo
            ),
            interceptors=await self.resolve_components_async(
                metadata.interceptors,
                Interceptor,
                module=module,
                request=request,
                kind="interceptor",
                memo=memo,
            ),
            filters=await self.resolve_components_async(
                metadata.filters,
                ExceptionFilter,
                module=module,
                request=request,
                kind="filter",
                memo=memo,
            ),
        )

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

    async def resolve_components_async(
        self,
        components: tuple[object, ...],
        expected_type: type[ComponentT],
        *,
        module: ModuleKey,
        request: HttpRequest,
        kind: str,
        memo: PipelineMemo | None = None,
    ) -> tuple[ComponentT, ...]:
        """Resolve pipeline components for one request, awaiting asynchronous factories."""
        resolved: list[ComponentT] = []
        for component in components:
            source = self._container_source(component, module)
            if source is None:
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
            resolved.extend(instances)
        return tuple(resolved)

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
        visibility = container.registry.module_visibility.get(owner)
        if visibility is None:
            return False
        declaring_module = visibility.get(token)
        if declaring_module is None:
            return False
        binding = container.registry.get_binding((declaring_module, token))
        if binding is None:
            return False
        return binding.scope is ProviderScope.SINGLETON or binding.resolver_kind == "value"

    def _overridden(self, metadata: PipelineMetadata) -> PipelineMetadata:
        if self.pipeline_override_registry is None:
            return metadata
        return self.pipeline_override_registry.apply_to_metadata(metadata)

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

        return component in self.container.registry.module_visibility.get(module, {})

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
