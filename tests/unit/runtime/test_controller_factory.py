"""Unit tests for controller instantiation scopes."""

from __future__ import annotations

import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, cast

import anyio
import pytest

from bustan import (
    APP_FILTER,
    APP_GUARD,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    FactoryProvider,
    Get,
    Guard,
    Inject,
    Injectable,
    Module,
    Pipe,
    Scope,
    UseGuards,
    ValueProvider,
    create_app,
)
from bustan.kernel.errors import InvalidControllerError, InvalidPipelineError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.pipeline.metadata import PipelineMetadata
from bustan.runtime import controller_factory
from bustan.runtime.compiler import GlobalPipelineProvider
from bustan.runtime.controller_factory import ControllerFactory, PipelineMemo, ResolvedPipeline
from bustan.testing import PipelineOverrideRegistry, create_testing_module

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bustan.app.application import Application
    from bustan.kernel.ioc.container import Container
    from tests.conftest import HttpRequestFactory

# Declared at module level because a constructor annotation naming it is read back as
# a string, and a name local to a test function is not in scope by then.
SESSION = object()

# The lifetimes a controller can be served under. Every other member of the enum
# partitions instances by a key a controller does not carry.
SERVABLE_CONTROLLER_SCOPES = frozenset({Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT})


@Module()
class EmptyModule:
    """A module declaring nothing, for a controller no module graph would accept."""


def _module_declaring(controller_cls: type[object], scope: Scope) -> type[object]:
    """Return the module a controller of this lifetime can be reached through.

    The module graph refuses a lifetime no controller can be served under, so such a
    declaration cannot be reached through a module that declares it. The factory is
    handed the class directly instead, because its own refusal is what keeps a
    lifetime the graph has not learned to refuse from falling through to the
    singleton cache.
    """

    if scope not in SERVABLE_CONTROLLER_SCOPES:
        return EmptyModule

    @Module(controllers=[controller_cls])
    class DeclaringModule:
        pass

    return DeclaringModule


@asynccontextmanager
async def _running(root_module: type[object]) -> AsyncIterator[Application]:
    """Start an application through its own lifecycle, and stop it afterwards.

    Nothing is settled before startup, because until then an override may still replace
    any provider, so a pipeline can only be kept by an application that has started.
    """

    application = create_app(root_module)
    await application.init()
    try:
        yield application
    finally:
        await application.close()


def _count_resolutions(container: Container, monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record every token the container is asked to resolve, and answer as before."""

    resolutions: list[object] = []
    resolve_async = container.resolve_async

    async def counted(token: object, *, module: Any, request: Any = None) -> object:
        resolutions.append(token)
        return await resolve_async(token, module=module, request=request)

    monkeypatch.setattr(container, "resolve_async", counted)
    return resolutions


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _WatchedPlan(PipelineMetadata):
    """A plan a test can hold weakly, to see whether anything else still holds it."""


@pytest.mark.anyio
async def test_controller_factory_reuses_singleton_controllers_by_default(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable
    class UserService:
        pass

    @Controller("/users")
    class UsersController:
        def __init__(self, user_service: UserService) -> None:
            self.user_service = user_service

        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController], providers=[UserService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    first = cast(
        Any,
        await factory.instantiate_async(
            UsersController, module=AppModule, request=build_http_request(path="/users")
        ),
    )
    second = cast(
        Any,
        await factory.instantiate_async(
            UsersController, module=AppModule, request=build_http_request(path="/users")
        ),
    )

    assert first is second
    assert first.user_service is second.user_service


@pytest.mark.anyio
async def test_controller_factory_reuses_request_scoped_controllers_per_request(
    build_http_request: HttpRequestFactory,
) -> None:
    @Controller("/users", scope=Scope.REQUEST)
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    first_request = build_http_request(path="/users")
    second_request = build_http_request(path="/users")

    first = await factory.instantiate_async(
        UsersController, module=AppModule, request=first_request
    )
    second = await factory.instantiate_async(
        UsersController, module=AppModule, request=first_request
    )
    third = await factory.instantiate_async(
        UsersController, module=AppModule, request=second_request
    )

    assert first is second
    assert first is not third


@pytest.mark.anyio
async def test_controller_factory_creates_transient_controllers_each_time(
    build_http_request: HttpRequestFactory,
) -> None:
    @Controller("/users", scope=Scope.TRANSIENT)
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    first = await factory.instantiate_async(UsersController, module=AppModule, request=request)
    second = await factory.instantiate_async(UsersController, module=AppModule, request=request)

    assert first is not second


@pytest.mark.parametrize("scope", list(Scope))
@pytest.mark.anyio
async def test_controller_factory_only_serves_the_lifetimes_a_controller_can_have(
    scope: Scope,
    build_http_request: HttpRequestFactory,
) -> None:
    @Controller("/users", scope=scope)
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    module = _module_declaring(UsersController, scope)
    container = build_container(build_module_graph(module))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    if scope in SERVABLE_CONTROLLER_SCOPES:
        assert isinstance(
            await factory.instantiate_async(UsersController, module=module, request=request),
            UsersController,
        )
        return

    with pytest.raises(InvalidControllerError):
        await factory.instantiate_async(UsersController, module=module, request=request)


@pytest.mark.anyio
async def test_controller_factory_never_caches_a_durable_controller_as_a_singleton(
    build_http_request: HttpRequestFactory,
) -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    module = _module_declaring(TenantsController, Scope.DURABLE)
    container = build_container(build_module_graph(module))
    factory = ControllerFactory(container)

    with pytest.raises(InvalidControllerError):
        await factory.instantiate_async(
            TenantsController, module=module, request=build_http_request(path="/tenants")
        )

    assert container.controller_instance_view == {}


@pytest.mark.anyio
async def test_concurrent_first_requests_still_build_a_singleton_controller_once(
    build_http_request: HttpRequestFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructions: list[object] = []

    async def open_session() -> dict[str, str]:
        # Yielding while the controller's dependency is built lets every other first
        # request reach the controller before this one has finished building it.
        await anyio.sleep(0)
        return {"kind": "async"}

    @Controller("/users")
    class UsersController:
        def __init__(self, session: Annotated[object, Inject(SESSION)]) -> None:
            constructions.append(self)

        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(
        controllers=[UsersController],
        providers=[FactoryProvider(provide=SESSION, use_factory=open_session)],
    )
    class AppModule:
        pass

    factory = ControllerFactory(build_container(build_module_graph(AppModule)))
    served: list[object] = []

    async def serve() -> None:
        request = build_http_request(path="/users")
        served.append(
            await factory.instantiate_async(UsersController, module=AppModule, request=request)
        )

    async with anyio.create_task_group() as tasks:
        for _ in range(4):
            tasks.start_soon(serve)

    locked: list[object] = []
    shared_construction = controller_factory.shared_construction

    def counting_locks(scopes: Any, key: object) -> Any:
        locked.append(key)
        return shared_construction(scopes, key)

    monkeypatch.setattr(controller_factory, "shared_construction", counting_locks)
    again = await factory.instantiate_async(
        UsersController, module=AppModule, request=build_http_request(path="/users")
    )

    assert len(constructions) == 1
    assert served == constructions * 4
    # A controller already built is served without queuing for its construction lock.
    assert again is constructions[0]
    assert locked == []


def test_pipeline_components_are_constructed_directly_unless_they_declare_provider_metadata(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable()
    class DecoratedGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    class InheritingGuard(DecoratedGuard):
        pass

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController], providers=[DecoratedGuard])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    (decorated,) = factory.resolve_components(
        (DecoratedGuard,), Guard, module=AppModule, request=request, kind="guard"
    )
    (inheriting,) = factory.resolve_components(
        (InheritingGuard,), Guard, module=AppModule, request=request, kind="guard"
    )

    assert decorated is container.resolve(DecoratedGuard, module=AppModule, request=request)
    assert isinstance(inheriting, InheritingGuard)
    assert inheriting is not container.resolve(DecoratedGuard, module=AppModule, request=request)


def test_a_registered_pipeline_class_is_built_by_the_container_even_undecorated(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable()
    class Policy:
        allowed = True

    class RegisteredGuard(Guard):
        def __init__(self, policy: Policy) -> None:
            self.policy = policy

        def can_activate(self, context: object) -> bool:
            return self.policy.allowed

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController], providers=[Policy, RegisteredGuard])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    (resolved,) = factory.resolve_components(
        (RegisteredGuard,), Guard, module=AppModule, request=request, kind="guard"
    )

    assert isinstance(cast(Any, resolved).policy, Policy)


def test_an_unregistered_pipeline_class_that_needs_arguments_is_refused(
    build_http_request: HttpRequestFactory,
) -> None:
    class NeedsArguments(Guard):
        def __init__(self, dependency: object) -> None:
            self.dependency = dependency

        def can_activate(self, context: object) -> bool:
            return True

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    with pytest.raises(InvalidPipelineError, match="must be an instance"):
        factory.resolve_components(
            (NeedsArguments,),
            Guard,
            module=AppModule,
            request=build_http_request(path="/users"),
            kind="guard",
        )


def test_a_global_token_bound_to_a_list_resolves_to_every_component_it_names(
    build_http_request: HttpRequestFactory,
) -> None:
    class FirstGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    class SecondGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    first, second = FirstGuard(), SecondGuard()

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(
        controllers=[UsersController],
        providers=[ValueProvider(provide=APP_GUARD, use_value=[first, second])],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    resolved = factory.resolve_components(
        (GlobalPipelineProvider(APP_GUARD, AppModule, [first, second]),),
        Guard,
        module=AppModule,
        request=build_http_request(path="/users"),
        kind="guard",
    )

    assert resolved == (first, second)


@pytest.mark.anyio
async def test_the_awaited_driver_builds_a_controller_whose_dependency_is_awaited(
    build_http_request: HttpRequestFactory,
) -> None:
    async def build_session() -> dict[str, str]:
        return {"kind": "async"}

    @Controller("/users", scope=Scope.REQUEST)
    class UsersController:
        def __init__(self, session: Annotated[object, Inject(SESSION)]) -> None:
            self.session = session

        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(
        controllers=[UsersController],
        providers=[
            FactoryProvider(provide=SESSION, use_factory=build_session, scope=Scope.REQUEST)
        ],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    instance = await factory.instantiate_async(UsersController, module=AppModule, request=request)
    again = await factory.instantiate_async(UsersController, module=AppModule, request=request)

    assert cast(Any, instance).session == {"kind": "async"}
    assert instance is again


def test_a_component_that_does_not_implement_its_slot_is_refused(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable()
    class NotAGuard:
        pass

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController], providers=[NotAGuard])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    with pytest.raises(InvalidPipelineError, match="must inherit from Guard"):
        factory.resolve_components(
            (NotAGuard,),
            Guard,
            module=AppModule,
            request=build_http_request(path="/users"),
            kind="guard",
        )


@pytest.mark.anyio
async def test_a_pipeline_override_replaces_the_component_a_route_declared(
    build_http_request: HttpRequestFactory,
) -> None:
    """A registry of replacements is honoured before anything is resolved.

    The declaration a route compiled from is not edited: the substitution happens as
    the pipeline is resolved for a request, so the replacement is what runs and the
    route still carries the component its controller declared.
    """

    class DeclaredGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return False

    class ReplacementGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    replacement = ReplacementGuard()
    overrides = PipelineOverrideRegistry()
    overrides.guards[DeclaredGuard] = replacement

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container, pipeline_override_registry=overrides)

    resolved = await factory.resolve_pipeline_async(
        PipelineMetadata(guards=(DeclaredGuard,)),
        module=AppModule,
        request=build_http_request(path="/users"),
    )

    assert resolved.guards == (replacement,)


@pytest.mark.anyio
async def test_a_pipeline_with_no_override_registered_resolves_what_it_declared(
    build_http_request: HttpRequestFactory,
) -> None:
    """A registry holding no replacement for a component leaves it alone."""

    class DeclaredGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container, pipeline_override_registry=PipelineOverrideRegistry())

    resolved = await factory.resolve_pipeline_async(
        PipelineMetadata(guards=(DeclaredGuard,)),
        module=AppModule,
        request=build_http_request(path="/users"),
    )

    (guard,) = resolved.guards
    assert isinstance(guard, DeclaredGuard)


@pytest.mark.anyio
async def test_a_settled_pipeline_resolves_nothing_after_its_first_request(
    build_http_request: HttpRequestFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @Injectable
    class SessionGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    class TrimPipe(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            return value

    class NeverCatches(ExceptionFilter):
        exception_types = (RuntimeError,)

        async def catch(self, exc: Exception, context: ExecutionContext) -> None:
            return None

    written_out = TrimPipe()
    fixed = NeverCatches()

    @Module(providers=[SessionGuard, ValueProvider(provide=APP_FILTER, use_value=fixed)])
    class AppModule:
        pass

    # A singleton, an instance the author wrote out, and a fixed value under a global
    # token: the three ways a component is settled.
    plan = PipelineMetadata(
        guards=(SessionGuard,),
        pipes=(written_out,),
        filters=(GlobalPipelineProvider(APP_FILTER, AppModule, fixed),),
    )

    async with _running(AppModule) as application:
        factory = ControllerFactory(application.container)
        memo = PipelineMemo()
        resolutions = _count_resolutions(application.container, monkeypatch)

        first = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )
        first_resolutions = list(resolutions)
        resolutions.clear()
        second = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )
        later_resolutions = list(resolutions)
        # Without a memo every component is resolved afresh, which is how a request
        # resolved its pipeline before any was kept.
        fresh = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request()
        )

    assert first_resolutions == [SessionGuard, APP_FILTER]
    assert later_resolutions == []
    assert second is first
    assert second == fresh
    assert second.pipes == (written_out,)
    assert second.filters == (fixed,)


@pytest.mark.anyio
async def test_a_pipeline_kept_from_one_run_is_dropped_when_the_application_starts_again(
    build_http_request: HttpRequestFactory,
) -> None:
    # A shutdown destroys the guard the first run was handed and the next startup builds
    # another. A pipeline kept around the destroyed guard is not served to the second run.
    @Injectable
    class SessionGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    @Module(providers=[SessionGuard])
    class AppModule:
        pass

    application = create_app(AppModule)
    factory = ControllerFactory(application.container)
    memo = PipelineMemo()
    plan = PipelineMetadata(guards=(SessionGuard,))

    await application.init()
    try:
        first_run = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )
    finally:
        await application.close()

    await application.init()
    try:
        second_run = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )
        current = await application.container.resolve_async(SessionGuard, module=AppModule)
    finally:
        await application.close()

    assert second_run.guards == (current,)
    assert first_run.guards != second_run.guards


# Each lifetime is tried alone beside a settled guard: any one of them leaves the whole
# pipeline unsettled, and would hide whether another was still being honoured.
@pytest.mark.parametrize("lifetime", ["request", "transient", "unregistered"])
@pytest.mark.anyio
async def test_a_request_scoped_or_transient_component_is_still_resolved_per_request(
    lifetime: str,
    build_http_request: HttpRequestFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @Injectable
    class SessionGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    @Injectable(scope=Scope.REQUEST)
    class TenantGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    @Injectable(scope=Scope.TRANSIENT)
    class TimingGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    # Nothing registers this one, so it is built for each resolution, as a transient is.
    class ThrottleGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    unsettled = {"request": TenantGuard, "transient": TimingGuard, "unregistered": ThrottleGuard}

    @Module(providers=[SessionGuard, TenantGuard, TimingGuard])
    class AppModule:
        pass

    plan = PipelineMetadata(guards=(SessionGuard, unsettled[lifetime]))

    async with _running(AppModule) as application:
        factory = ControllerFactory(application.container)
        memo = PipelineMemo()
        first = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )
        resolutions = _count_resolutions(application.container, monkeypatch)
        second = await factory.resolve_pipeline_async(
            plan, module=AppModule, request=build_http_request(), memo=memo
        )

    (settled_first, unsettled_first), (settled_second, unsettled_second) = (
        first.guards,
        second.guards,
    )
    assert unsettled_second is not unsettled_first
    # The singleton beside it is still the one kept from the first request.
    assert settled_second is settled_first
    assert SessionGuard not in resolutions


@pytest.mark.anyio
async def test_a_pipeline_override_registered_after_compile_still_applies() -> None:
    """The registry is test support's, which may still write to it once compiled.

    The route is warm by the time the replacement is written, and the guard it declared
    is a settled singleton, so the pipeline in front of it is exactly one that would be
    kept whole; the replacement must still be what runs on the next request.
    """

    @Injectable
    class RefusingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            return False

    class AdmittingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            return True

    @UseGuards(RefusingGuard)
    @Controller("/users")
    class UsersController:
        @Get("/")
        async def list_users(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[UsersController], providers=[RefusingGuard])
    class AppModule:
        pass

    builder = create_testing_module(AppModule)
    compiled = await builder.compile()
    try:
        with compiled.create_client() as client:
            refused = [client.get("/users").status_code for _ in range(2)]
            builder.override_guard(RefusingGuard).use_value(AdmittingGuard())
            admitted = client.get("/users").status_code
    finally:
        await compiled.close()

    assert refused == [403, 403]
    assert admitted == 200


@pytest.mark.anyio
async def test_a_plan_that_declares_nothing_resolves_to_one_shared_empty_pipeline(
    build_http_request: HttpRequestFactory,
) -> None:
    container = build_container(build_module_graph(EmptyModule))
    plain = ControllerFactory(container)
    overridden = ControllerFactory(container, pipeline_override_registry=PipelineOverrideRegistry())

    first = await plain.resolve_pipeline_async(
        PipelineMetadata(), module=EmptyModule, request=build_http_request()
    )
    second = await overridden.resolve_pipeline_async(
        PipelineMetadata(), module=EmptyModule, request=build_http_request(), memo=PipelineMemo()
    )

    assert first is second
    assert first == ResolvedPipeline(guards=(), pipes=(), interceptors=(), filters=())


@pytest.mark.anyio
async def test_a_plan_built_for_one_call_is_not_kept_for_the_life_of_the_route(
    build_http_request: HttpRequestFactory,
) -> None:
    # An error path builds a plan for the one call that needs it. The pipeline resolved
    # for it can be settled and so kept, but nothing asks for that plan again, and were
    # each one kept, every such request would leave one behind for the life of the route.
    class AdmittingGuard(Guard):
        def can_activate(self, context: object) -> bool:
            return True

    written_out = AdmittingGuard()
    factory = ControllerFactory(build_container(build_module_graph(EmptyModule)))
    memo = PipelineMemo()

    plan = _WatchedPlan(guards=(written_out,))
    watched = weakref.ref(plan)
    await factory.resolve_pipeline_async(
        plan, module=EmptyModule, request=build_http_request(), memo=memo
    )
    del plan
    for _ in range(100):
        await factory.resolve_pipeline_async(
            _WatchedPlan(guards=(written_out,)),
            module=EmptyModule,
            request=build_http_request(),
            memo=memo,
        )

    assert watched() is None
