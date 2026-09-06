"""Unit tests for controller startup scanning."""

from __future__ import annotations

import pytest

from bustan import Controller, Get, Module
from bustan.kernel.errors import InvalidControllerError, RouteDefinitionError
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.scanner import FRAMEWORK_HOOK_NAMES, ControllerScanner


def test_controller_scanner_rejects_non_controller_classes() -> None:
    class PlainController:
        pass

    @Module()
    class AppModule:
        pass

    scanner = ControllerScanner(build_module_graph(AppModule))

    with pytest.raises(InvalidControllerError, match="not decorated with @Controller"):
        scanner.scan_controller(AppModule, PlainController)


def test_controller_scanner_rejects_public_handler_without_route_metadata() -> None:
    @Controller("/users")
    class UsersController:
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    scanner = ControllerScanner(build_module_graph(AppModule))

    with pytest.raises(
        RouteDefinitionError, match="UsersController.list_users.*missing an HTTP route decorator"
    ):
        scanner.scan()


def test_controller_scanner_preserves_module_ownership_and_deterministic_order() -> None:
    @Controller("/admin")
    class AdminController:
        @Get("/health")
        def health(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

        @Get("/{user_id}")
        def read_user(self, user_id: str) -> dict[str, str]:
            return {"id": user_id}

    @Module(controllers=[UsersController])
    class UsersModule:
        pass

    @Module(controllers=[AdminController], imports=[UsersModule])
    class AppModule:
        pass

    scanner = ControllerScanner(build_module_graph(AppModule))
    scan_result = scanner.scan()

    assert [controller.module_key for controller in scan_result.controllers] == [
        AppModule,
        UsersModule,
    ]
    assert [
        (
            handler.module_key,
            handler.controller_cls.__name__,
            handler.handler_name,
            handler.full_path,
        )
        for handler in scan_result.handlers
    ] == [
        (AppModule, "AdminController", "health", "/admin/health"),
        (UsersModule, "UsersController", "list_users", "/users"),
        (UsersModule, "UsersController", "read_user", "/users/{user_id}"),
    ]


@pytest.mark.parametrize("hook_name", sorted(FRAMEWORK_HOOK_NAMES))
def test_controller_scanner_skips_every_framework_hook_name(hook_name: str) -> None:
    @Controller("/tenants")
    class TenantsController:
        @Get("/health")
        def health(self) -> dict[str, str]:
            return {"status": "ok"}

    def hook(self: object, *arguments: object) -> str:
        return "tenant"

    setattr(TenantsController, hook_name, hook)

    @Module()
    class AppModule:
        pass

    scanner = ControllerScanner(build_module_graph(AppModule))
    scanned = scanner.scan_controller(AppModule, TenantsController)

    assert [route.handler_name for route in scanned.routes] == ["health"]


def test_controller_scanner_still_rejects_an_undecorated_method_beside_a_hook() -> None:
    @Controller("/tenants")
    class TenantsController:
        def on_module_init(self) -> None:
            return None

        def list_tenants(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    scanner = ControllerScanner(build_module_graph(AppModule))

    with pytest.raises(
        RouteDefinitionError,
        match="TenantsController.list_tenants.*missing an HTTP route decorator",
    ):
        scanner.scan()
