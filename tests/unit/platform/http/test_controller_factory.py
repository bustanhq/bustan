"""Unit tests for controller instantiation scopes."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.requests import Request

from bustan import Controller, Get, Injectable, Module, Scope
from bustan.core.errors import InvalidControllerError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.platform.http.controller_factory import ControllerFactory


def test_controller_factory_reuses_singleton_controllers_by_default() -> None:
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
        factory.instantiate(UsersController, module=AppModule, request=_build_request("/users")),
    )
    second = cast(
        Any,
        factory.instantiate(UsersController, module=AppModule, request=_build_request("/users")),
    )

    assert first is second
    assert first.user_service is second.user_service


def test_controller_factory_reuses_request_scoped_controllers_per_request() -> None:
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
    first_request = _build_request("/users")
    second_request = _build_request("/users")

    first = factory.instantiate(UsersController, module=AppModule, request=first_request)
    second = factory.instantiate(UsersController, module=AppModule, request=first_request)
    third = factory.instantiate(UsersController, module=AppModule, request=second_request)

    assert first is second
    assert first is not third


def test_controller_factory_creates_transient_controllers_each_time() -> None:
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
    request = _build_request("/users")

    first = factory.instantiate(UsersController, module=AppModule, request=request)
    second = factory.instantiate(UsersController, module=AppModule, request=request)

    assert first is not second


def test_controller_factory_refuses_durable_controllers() -> None:
    @Controller("/tenant", scope=Scope.DURABLE)
    class TenantController:
        @Get("/")
        def read(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[TenantController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(InvalidControllerError, match="durable scope"):
        ControllerFactory(container)


def test_controller_factory_refuses_a_singleton_controller_holding_request_state() -> None:
    @Injectable(scope=Scope.REQUEST)
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Controller("/state")
    class StateController:
        def __init__(self, request_state: RequestState) -> None:
            self.request_state = request_state

        @Get("/")
        def read(self) -> list[str]:
            return ["Ada"]

    @Module(controllers=[StateController], providers=[RequestState])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        ControllerFactory(container)


def _build_request(path: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "path_params": {},
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)
