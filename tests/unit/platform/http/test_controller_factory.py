"""Unit tests for controller instantiation scopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from bustan import Controller, Get, Injectable, Module, Scope
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
