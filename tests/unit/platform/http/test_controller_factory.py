"""Unit tests for controller instantiation scopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from bustan import Controller, Get, Guard, Injectable, Module, Scope
from bustan.core.errors import InvalidControllerError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.controller_factory import ControllerFactory

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


def test_controller_factory_reuses_singleton_controllers_by_default(
    build_request: RequestFactory,
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
        factory.instantiate(
            UsersController, module=AppModule, request=build_request(path="/users")
        ),
    )
    second = cast(
        Any,
        factory.instantiate(
            UsersController, module=AppModule, request=build_request(path="/users")
        ),
    )

    assert first is second
    assert first.user_service is second.user_service


def test_controller_factory_reuses_request_scoped_controllers_per_request(
    build_request: RequestFactory,
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
    first_request = build_request(path="/users")
    second_request = build_request(path="/users")

    first = factory.instantiate(UsersController, module=AppModule, request=first_request)
    second = factory.instantiate(UsersController, module=AppModule, request=first_request)
    third = factory.instantiate(UsersController, module=AppModule, request=second_request)

    assert first is second
    assert first is not third


def test_controller_factory_creates_transient_controllers_each_time(
    build_request: RequestFactory,
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
    request = build_request(path="/users")

    first = factory.instantiate(UsersController, module=AppModule, request=request)
    second = factory.instantiate(UsersController, module=AppModule, request=request)

    assert first is not second


@pytest.mark.parametrize("scope", list(Scope))
def test_controller_factory_only_serves_the_lifetimes_a_controller_can_have(
    scope: Scope,
    build_request: RequestFactory,
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
    request = build_request(path="/users")

    if scope in {Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT}:
        assert isinstance(
            factory.instantiate(UsersController, module=AppModule, request=request),
            UsersController,
        )
        return

    with pytest.raises(InvalidControllerError):
        factory.instantiate(UsersController, module=AppModule, request=request)


def test_controller_factory_never_caches_a_durable_controller_as_a_singleton(
    build_request: RequestFactory,
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
        factory.instantiate(
            TenantsController, module=AppModule, request=build_request(path="/tenants")
        )

    assert container.scope_manager.controller_singletons == {}


def test_pipeline_components_are_constructed_directly_unless_they_declare_provider_metadata(
    build_request: RequestFactory,
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
    request = build_request(path="/users")

    (decorated,) = factory.resolve_components(
        (DecoratedGuard,), Guard, module=AppModule, request=request, kind="guard"
    )
    (inheriting,) = factory.resolve_components(
        (InheritingGuard,), Guard, module=AppModule, request=request, kind="guard"
    )

    assert decorated is container.resolve(DecoratedGuard, module=AppModule, request=request)
    assert isinstance(inheriting, InheritingGuard)
    assert inheriting is not container.resolve(DecoratedGuard, module=AppModule, request=request)
