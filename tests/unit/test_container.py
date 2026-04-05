"""Unit tests for provider and controller resolution behavior."""

import pytest
from starlette.requests import Request

from bustan import Controller, Get, Injectable, Module
from bustan.container import build_container
from bustan.errors import ProviderResolutionError
from bustan.module_graph import build_module_graph


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

    first_service = container.resolve_provider(UserService, AppModule)
    second_service = container.resolve_provider(UserService, AppModule)
    first_controller = container.resolve_controller(UserController)
    second_controller = container.resolve_controller(UserController)

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
    module_registry = container.get_module_registry(AppModule)

    assert module_registry.declaring_module_for(UserService) is UsersModule
    assert isinstance(container.resolve_provider(UserService, AppModule), UserService)

    with pytest.raises(ProviderResolutionError, match="HiddenService"):
        container.resolve_provider(HiddenService, AppModule)


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
    controller_instance = container.resolve_controller(DashboardController)

    assert isinstance(controller_instance.user_service, UserService)


def test_container_resolves_request_scoped_providers_once_per_request() -> None:
    @Injectable(scope="request")
    class RequestState:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(providers=[RequestState], exports=[RequestState])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="requires an active request"):
        container.resolve_provider(RequestState, AppModule)

    first_request = _build_request("/requests/one")
    first_instance = container.resolve_provider(RequestState, AppModule, request=first_request)
    second_instance = container.resolve_provider(RequestState, AppModule, request=first_request)
    third_request = _build_request("/requests/two")
    third_instance = container.resolve_provider(RequestState, AppModule, request=third_request)

    assert first_instance is second_instance
    assert first_instance is not third_instance
    assert first_instance.request is first_request
    assert third_instance.request is third_request


def test_container_rejects_request_scoped_dependencies_from_singleton_providers() -> None:
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
        container.resolve_provider(SingletonService, AppModule, request=_build_request("/scope"))


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
        container.resolve_provider(BrokenService, AppModule)


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
        container.resolve_provider(ConsumerService, AppModule)


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
        container.resolve_provider(LeftService, AppModule)


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
        container.resolve_provider(RequestAwareService, AppModule)


def test_container_resolves_value_provider_def() -> None:
    DATABASE_URL = "database_url"

    @Module(
        providers=[{"provide": DATABASE_URL, "use_value": "postgres://localhost/mydb"}],
        exports=[DATABASE_URL],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    first = container.resolve_provider(DATABASE_URL, AppModule)
    second = container.resolve_provider(DATABASE_URL, AppModule)

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

    first = container.resolve_provider("http_client", AppModule)
    second = container.resolve_provider("http_client", AppModule)

    assert isinstance(first, dict)
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

    instance = container.resolve_provider(IUserRepo, AppModule)

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

    original = container.resolve_provider(UserService, AppModule)
    alias = container.resolve_provider("user_service_alias", AppModule)

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

    first = container.resolve_provider("handler", AppModule)
    second = container.resolve_provider("handler", AppModule)

    assert first is not second
    assert first["id"] == 1
    assert second["id"] == 2


def _build_request(path: str) -> Request:
    """Construct a minimal Request object for container tests."""

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