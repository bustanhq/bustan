"""Unit tests for route compilation edge cases."""

import pytest

from bustan import Controller, Get, Module, VersioningOptions, VersioningType
from bustan.errors import ParameterBindingError, RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.runtime.routing import compile_routes


def test_compile_routes_rejects_duplicate_application_routes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Controller("/users")
    class ProfilesController:
        @Get("/")
        def list_profiles(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @Module(controllers=[UsersController, ProfilesController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="Duplicate application route GET /users"):
        compile_routes(module_graph, container)


def test_compile_routes_rejects_variadic_handler_parameters() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, *user_ids: str) -> dict[str, str]:
            return {"ids": ",".join(user_ids)}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(ParameterBindingError, match="unsupported variadic parameter"):
        compile_routes(module_graph, container)


def test_the_plan_records_host_routing_and_leaves_the_verdict_to_the_adapter() -> None:
    @Controller("/users", host="api.example.test")
    class UsersController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    # Whether a host route can be served is a property of the chosen adapter, so the
    # plan records what the route needs and the capability check refuses it once.
    routes = compile_routes(module_graph, container)

    assert routes[0].hosts == ("api.example.test",)


def test_two_versions_of_one_path_collide_when_no_versioning_is_configured() -> None:
    @Controller("/users", version="1")
    class V1Controller:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Controller("/users", version="2")
    class V2Controller:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Grace"}]

    @Module(controllers=[V1Controller, V2Controller])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="Duplicate application route GET /users"):
        compile_routes(module_graph, container)


def test_uri_versioning_refuses_two_handlers_that_expand_to_the_same_path() -> None:
    @Controller("/users", version="1")
    class FirstController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Ada"}]

    @Controller("/users", version="1")
    class SecondController:
        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Grace"}]

    @Module(controllers=[FirstController, SecondController])
    class AppModule:
        pass

    module_graph = build_module_graph(AppModule)
    container = build_container(module_graph)

    with pytest.raises(RouteDefinitionError, match="Duplicate application route GET /v1/users"):
        compile_routes(
            module_graph,
            container,
            versioning=VersioningOptions(type=VersioningType.URI),
        )
