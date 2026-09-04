"""Unit tests for provider and controller resolution behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.requests import Request

from bustan import Controller, Get, Global, Injectable, Module
from bustan.core.errors import InvalidModuleError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import ModuleGraph, ModuleNode, build_module_graph
from bustan.core.module.metadata import ModuleMetadata

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


def test_container_resolves_singleton_providers_and_transient_controllers() -> None:
    @Injectable
    class UserService:
        pass

    @Controller("/users")
    class UserController:
        def __init__(self, user_service: UserService) -> None:
            self.user_service = user_service

        @Get("/")
        def list_users(self) -> list[dict[str, str]]:
            return [{"name": "Moses"}]

    @Module(
        controllers=[UserController],
        providers=[UserService],
        exports=[UserService],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    first_service = container.resolve(UserService, module=AppModule)
    second_service = container.resolve(UserService, module=AppModule)
    first_controller = cast(Any, container.instantiate_class(UserController, module=AppModule))
    second_controller = cast(Any, container.instantiate_class(UserController, module=AppModule))

    assert first_service is second_service
    assert first_controller is not second_controller
    assert first_controller.user_service is first_service
    assert second_controller.user_service is first_service


def test_container_resolves_exported_providers_from_imported_modules() -> None:
    @Injectable
    class UserService:
        pass

    @Injectable
    class HiddenService:
        pass

    @Module(
        providers=[UserService, HiddenService],
        exports=[UserService],
    )
    class UsersModule:
        pass

    @Module(imports=[UsersModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    assert isinstance(container.resolve(UserService, module=AppModule), UserService)

    with pytest.raises(ProviderResolutionError, match="HiddenService"):
        container.resolve(HiddenService, module=AppModule)


def test_container_resolves_controller_dependencies_from_imported_exports() -> None:
    @Injectable
    class UserService:
        pass

    @Module(providers=[UserService], exports=[UserService])
    class UsersModule:
        pass

    @Controller("/dashboard")
    class DashboardController:
        def __init__(self, user_service: UserService) -> None:
            self.user_service = user_service

        @Get("/")
        def show_dashboard(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        imports=[UsersModule],
        controllers=[DashboardController],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    controller_instance = cast(
        Any, container.instantiate_class(DashboardController, module=AppModule)
    )

    assert isinstance(controller_instance.user_service, UserService)


def test_container_resolves_request_scoped_providers_once_per_request(
    build_request: RequestFactory,
) -> None:
    @Injectable(scope="request")
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(providers=[RequestState], exports=[RequestState])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="requires an active request"):
        container.resolve(RequestState, module=AppModule)

    first_request = build_request(path="/requests/one")
    first_instance = cast(
        Any, container.resolve(RequestState, module=AppModule, request=first_request)
    )
    second_instance = container.resolve(RequestState, module=AppModule, request=first_request)
    third_request = build_request(path="/requests/one")
    third_instance = cast(
        Any, container.resolve(RequestState, module=AppModule, request=third_request)
    )

    assert first_instance is second_instance
    assert first_instance is not third_instance
    assert first_instance.request is first_request
    assert third_instance.request is third_request


def test_container_rejects_request_scoped_dependencies_from_singleton_providers(
    build_request: RequestFactory,
) -> None:
    @Injectable(scope="request")
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Injectable
    class SingletonService:
        def __init__(self, request_state: RequestState) -> None:
            self.request_state = request_state

    @Module(providers=[RequestState, SingletonService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        container.resolve(SingletonService, module=AppModule, request=build_request(path="/scope"))


def test_container_rejects_missing_constructor_annotations() -> None:
    @Injectable
    class BrokenService:
        def __init__(self, dependency) -> None:
            self.dependency = dependency

    @Module(providers=[BrokenService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="missing a type annotation"):
        container.resolve(BrokenService, module=AppModule)


def test_container_rejects_unresolved_provider_dependencies() -> None:
    @Injectable
    class MissingService:
        pass

    @Injectable
    class ConsumerService:
        def __init__(self, missing_service: MissingService) -> None:
            self.missing_service = missing_service

    @Module(providers=[ConsumerService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="MissingService"):
        container.resolve(ConsumerService, module=AppModule)


def test_container_rejects_circular_provider_dependencies() -> None:
    @Injectable
    class LeftService:
        def __init__(self, right_service: object) -> None:
            self.right_service = right_service

    @Injectable
    class RightService:
        def __init__(self, left_service: LeftService) -> None:
            self.left_service = left_service

    LeftService.__init__.__annotations__["right_service"] = RightService

    @Module(providers=[LeftService, RightService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(
        ProviderResolutionError,
        match="LeftService -> RightService -> LeftService",
    ):
        container.resolve(LeftService, module=AppModule)


def test_container_separates_framework_owned_injections_from_provider_di() -> None:
    @Injectable
    class RequestAwareService:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(providers=[RequestAwareService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        container.resolve(RequestAwareService, module=AppModule)


def test_container_resolves_value_provider_def() -> None:
    DATABASE_URL = "database_url"

    @Module(
        providers=[{"provide": DATABASE_URL, "use_value": "postgres://localhost/mydb"}],
        exports=[DATABASE_URL],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    first = container.resolve(DATABASE_URL, module=AppModule)
    second = container.resolve(DATABASE_URL, module=AppModule)

    assert first == "postgres://localhost/mydb"
    assert first is second


def test_container_resolves_factory_provider_def_with_inject() -> None:
    @Injectable
    class ConfigService:
        base_url = "https://api.example.com"

    def build_client(config: ConfigService) -> dict[str, str]:
        return {"base_url": config.base_url}

    @Module(
        providers=[
            ConfigService,
            {"provide": "http_client", "use_factory": build_client, "inject": [ConfigService]},
        ],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    first = container.resolve("http_client", module=AppModule)
    second = container.resolve("http_client", module=AppModule)

    assert isinstance(first, dict)
    first = cast(dict[str, Any], first)
    assert first["base_url"] == "https://api.example.com"
    assert first is second


def test_container_resolves_class_provider_def_with_interface_token() -> None:
    class IUserRepo:
        pass

    @Injectable
    class SqlUserRepo(IUserRepo):
        pass

    @Module(
        providers=[{"provide": IUserRepo, "use_class": SqlUserRepo}],
        exports=[IUserRepo],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    instance = container.resolve(IUserRepo, module=AppModule)

    assert isinstance(instance, SqlUserRepo)
    assert isinstance(instance, IUserRepo)


def test_container_resolves_existing_provider_def() -> None:
    @Injectable
    class UserService:
        pass

    @Module(
        providers=[
            UserService,
            {"provide": "user_service_alias", "use_existing": UserService},
        ],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    original = container.resolve(UserService, module=AppModule)
    alias = container.resolve("user_service_alias", module=AppModule)

    assert original is alias


def test_container_resolves_transient_factory_provider_def() -> None:
    call_count = 0

    def build_handler() -> dict[str, int]:
        nonlocal call_count
        call_count += 1
        return {"id": call_count}

    @Module(
        providers=[{"provide": "handler", "use_factory": build_handler, "scope": "transient"}],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    first = container.resolve("handler", module=AppModule)
    second = container.resolve("handler", module=AppModule)

    assert first is not second
    first = cast(dict[str, Any], first)
    second = cast(dict[str, Any], second)
    assert first["id"] == 1
    assert second["id"] == 2


def test_container_resolves_a_two_hop_re_export_through_the_importing_module() -> None:
    # The facade pattern: one module imports a feature module and re-exports its service
    # so consumers depend on a single name. Resolving the token is the only proof that
    # the re-export is backed by a binding; presence in a mapping is not.
    @Injectable
    class Repository:
        pass

    @Module(providers=[Repository], exports=[Repository])
    class DataModule:
        pass

    @Module(imports=[DataModule], exports=[Repository])
    class SharedModule:
        pass

    @Injectable
    class UserService:
        def __init__(self, repository: Repository) -> None:
            self.repository = repository

    @Module(imports=[SharedModule], providers=[UserService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert isinstance(container.resolve(Repository, module=AppModule), Repository)
    service = cast(Any, container.resolve(UserService, module=AppModule))
    assert isinstance(service.repository, Repository)


def test_container_resolves_a_global_facade_re_export() -> None:
    @Injectable
    class Repository:
        pass

    @Module(providers=[Repository], exports=[Repository])
    class DataModule:
        pass

    @Global()
    @Module(imports=[DataModule], exports=[Repository])
    class FacadeModule:
        pass

    @Module()
    class ConsumerModule:
        pass

    @Module(imports=[FacadeModule, ConsumerModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert isinstance(container.resolve(Repository, module=ConsumerModule), Repository)
    assert isinstance(container.resolve(Repository, module=AppModule), Repository)


def test_container_overrides_a_re_exported_provider_at_its_declaring_module() -> None:
    # Visibility names the declaring module, so an override needs no module argument and
    # reaches every module the token was passed on to.
    @Injectable
    class Clock:
        pass

    @Module(providers=[Clock], exports=[Clock])
    class TimeModule:
        pass

    @Module(imports=[TimeModule], exports=[Clock])
    class SharedModule:
        pass

    @Module(imports=[SharedModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    replacement = object()
    container.override(Clock, replacement)

    assert container.resolve(Clock, module=AppModule) is replacement


def test_container_visibility_is_the_graph_visibility_and_every_entry_has_a_binding() -> None:
    @Injectable
    class Repository:
        pass

    @Module(providers=[Repository], exports=[Repository])
    class DataModule:
        pass

    @Global()
    @Module(providers=[{"provide": "config", "use_value": "value"}], exports=["config"])
    class SettingsModule:
        pass

    @Module(imports=[DataModule], exports=[Repository])
    class SharedModule:
        pass

    @Module(imports=[SharedModule, SettingsModule])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    for node in graph.nodes:
        assert container.registry.module_visibility[node.key] == dict(node.visibility)
        assert set(node.available_providers) == set(node.visibility)
        for token, declaring_module in node.visibility.items():
            assert (declaring_module, token) in container.registry.bindings


def test_container_refuses_visibility_that_no_binding_backs() -> None:
    # A hand-built graph is the only way to reach the bootstrap check, because the graph
    # no longer produces visibility a binding does not back. The check exists so that a
    # future regression fails at build time rather than on the first request.
    @Module()
    class AppModule:
        pass

    node = ModuleNode(
        key=AppModule,
        module=AppModule,
        metadata=ModuleMetadata(),
        exported_providers=frozenset(),
        available_providers=frozenset({"config"}),
        bindings=(),
        imported_exports={},
        visibility={"config": AppModule},
    )
    graph = ModuleGraph(root_key=AppModule, nodes=(node,), _nodes_by_key={AppModule: node})

    with pytest.raises(InvalidModuleError, match="declares no provider for it"):
        build_container(graph)
