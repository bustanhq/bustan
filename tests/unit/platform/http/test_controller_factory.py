"""Unit tests for controller instantiation scopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast

import pytest

from bustan import APP_GUARD, Controller, Get, Guard, Inject, Injectable, Module, Scope
from bustan.core.errors import InvalidControllerError, InvalidPipelineError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.compiler import GlobalPipelineProvider
from bustan.platform.http.controller_factory import ControllerFactory

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory

# Declared at module level because a constructor annotation naming it is read back as
# a string, and a name local to a test function is not in scope by then.
SESSION = object()


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

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/users")

    if scope in {Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT}:
        assert isinstance(
            await factory.instantiate_async(UsersController, module=AppModule, request=request),
            UsersController,
        )
        return

    with pytest.raises(InvalidControllerError):
        await factory.instantiate_async(UsersController, module=AppModule, request=request)


@pytest.mark.anyio
async def test_controller_factory_never_caches_a_durable_controller_as_a_singleton(
    build_http_request: HttpRequestFactory,
) -> None:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @Get("/")
        def list_tenants(self) -> list[str]:
            return ["acme"]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    with pytest.raises(InvalidControllerError):
        await factory.instantiate_async(
            TenantsController, module=AppModule, request=build_http_request(path="/tenants")
        )

    assert container.scope_manager.controller_singletons == {}


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
        providers=[{"provide": APP_GUARD, "use_value": [first, second]}],
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
        providers=[{"provide": SESSION, "use_factory": build_session, "scope": "request"}],
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
