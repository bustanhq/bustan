"""Unit tests for provider and controller resolution behavior."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest
from starlette.requests import Request

from bustan import (
    Controller,
    DynamicModule,
    Get,
    Global,
    Injectable,
    InjectionToken,
    Module,
    Scope,
)
from bustan.core.errors import InvalidModuleError, ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.lifecycle.manager import LifecycleManager
from bustan.core.module.graph import ModuleGraph, ModuleNode, build_module_graph
from bustan.core.module.metadata import ModuleMetadata

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


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
    build_http_request: HttpRequestFactory,
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

    first_request = build_http_request(path="/requests/one")
    first_instance = cast(
        Any, container.resolve(RequestState, module=AppModule, request=first_request)
    )
    second_instance = container.resolve(RequestState, module=AppModule, request=first_request)
    third_request = build_http_request(path="/requests/one")
    third_instance = cast(
        Any, container.resolve(RequestState, module=AppModule, request=third_request)
    )

    assert first_instance is second_instance
    assert first_instance is not third_instance
    # The parameter named the transport's own request type, so that is what it holds.
    assert first_instance.request is first_request.native_request
    assert third_instance.request is third_request.native_request


def test_container_rejects_request_scoped_dependencies_from_singleton_providers() -> None:
    # A singleton is built once and kept for the process, so a request-scoped
    # dependency inside it pins the first caller's state and answers it to everyone
    # after. The composition is refused while the graph is planned, before any
    # request exists to observe it.
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

    with pytest.raises(ProviderResolutionError, match="request-scoped provider"):
        build_container(build_module_graph(AppModule))


def test_container_rejects_missing_constructor_annotations() -> None:
    @Injectable
    class BrokenService:
        def __init__(self, dependency) -> None:
            self.dependency = dependency

    @Module(providers=[BrokenService])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="has no type annotation"):
        build_container(build_module_graph(AppModule))


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

    with pytest.raises(ProviderResolutionError, match="MissingService"):
        build_container(build_module_graph(AppModule))


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

    with pytest.raises(ProviderResolutionError, match="the transport's own request object"):
        build_container(build_module_graph(AppModule))


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
        assert container.registry.module_visibility[node.key] == node.visibility
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


def test_a_local_binding_and_an_imported_export_of_an_equal_token_resolve_apart() -> None:
    # A string enum member equals the bare string it is written as. The local string
    # binding used to answer for both, so the imported enum export became unreachable
    # in the module that imported it and nothing said so.
    class Tokens(StrEnum):
        DB = "db"

    @Module(providers=[{"provide": Tokens.DB, "use_value": "enum-db"}], exports=[Tokens.DB])
    class SharedModule:
        pass

    @Module(
        imports=[SharedModule],
        providers=[{"provide": "db", "use_value": "string-db"}],
    )
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))

    assert container.resolve(Tokens.DB, module=FeatureModule) == "enum-db"
    assert container.resolve("db", module=FeatureModule) == "string-db"


def test_a_token_equal_to_a_visible_one_but_of_another_type_resolves_to_nothing() -> None:
    class Tokens(StrEnum):
        DB = "db"

    @Module(providers=[{"provide": Tokens.DB, "use_value": "enum-db"}], exports=[Tokens.DB])
    class SharedModule:
        pass

    @Module(imports=[SharedModule])
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))

    with pytest.raises(ProviderResolutionError, match="is not available to FeatureModule"):
        container.resolve("db", module=FeatureModule)


def test_an_override_replaces_the_token_it_names_and_not_an_equal_one() -> None:
    class Tokens(StrEnum):
        DB = "db"

    @Module(providers=[{"provide": Tokens.DB, "use_value": "enum-db"}], exports=[Tokens.DB])
    class SharedModule:
        pass

    @Module(
        imports=[SharedModule],
        providers=[{"provide": "db", "use_value": "string-db"}],
    )
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))
    container.override(Tokens.DB, "fake-enum-db")

    assert container.resolve(Tokens.DB, module=FeatureModule) == "fake-enum-db"
    assert container.resolve("db", module=FeatureModule) == "string-db"
    assert container.has_override("db") is False


def test_a_true_token_and_a_one_token_are_two_providers() -> None:
    @Module(providers=[{"provide": 1, "use_value": "int-one"}], exports=[1])
    class IntModule:
        pass

    @Module(imports=[IntModule], providers=[{"provide": True, "use_value": "bool-true"}])
    class BoolModule:
        pass

    container = build_container(build_module_graph(BoolModule))

    assert container.resolve(1, module=BoolModule) == "int-one"
    assert container.resolve(True, module=BoolModule) == "bool-true"


def test_an_override_reaches_a_singleton_that_holds_the_token_two_hops_away() -> None:
    # The whole point of the rule: a test that swaps a database must not leave every
    # singleton built on top of it still holding the real one.
    @Injectable
    class Clock:
        def now(self) -> str:
            return "real"

    @Injectable
    class Stamper:
        def __init__(self, clock: Clock) -> None:
            self.clock = clock

    @Injectable
    class ReportService:
        def __init__(self, stamper: Stamper) -> None:
            self.stamper = stamper

    @Module(providers=[Clock, Stamper, ReportService])
    class AppModule:
        pass

    class FakeClock:
        def now(self) -> str:
            return "fake"

    container = build_container(build_module_graph(AppModule))

    def stamped() -> str:
        report = cast(ReportService, container.resolve(ReportService, module=AppModule))
        return report.stamper.clock.now()

    # Built first, so the singletons hold the real clock before the override exists.
    assert stamped() == "real"

    container.override(Clock, FakeClock())
    assert stamped() == "fake"

    container.clear_override(Clock)
    assert stamped() == "real"


def test_a_singleton_first_built_during_an_override_does_not_outlive_it() -> None:
    @Injectable
    class Clock:
        def now(self) -> str:
            return "real"

    @Injectable
    class ReportService:
        def __init__(self, clock: Clock) -> None:
            self.clock = clock

    @Module(providers=[Clock, ReportService])
    class AppModule:
        pass

    class FakeClock:
        def now(self) -> str:
            return "fake"

    container = build_container(build_module_graph(AppModule))

    def stamped() -> str:
        report = cast(ReportService, container.resolve(ReportService, module=AppModule))
        return report.clock.now()

    container.override(Clock, FakeClock())
    assert stamped() == "fake"

    container.clear_override(Clock)

    assert stamped() == "real"


def test_an_override_of_a_factory_binding_reaches_what_the_factory_injects() -> None:
    # A factory names its dependencies in an inject list rather than a constructor, so
    # the reach of an override has to be read from the binding as well as from the plan.
    @Module(
        providers=[
            {"provide": "dsn", "use_value": "postgres://real"},
            {
                "provide": "connection",
                "use_factory": lambda dsn: f"connected:{dsn}",
                "inject": ["dsn"],
            },
        ]
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    assert container.resolve("connection", module=AppModule) == "connected:postgres://real"

    container.override("dsn", "sqlite://fake")

    assert container.resolve("connection", module=AppModule) == "connected:sqlite://fake"


def test_an_override_of_a_singleton_is_the_instance_the_lifecycle_initializes() -> None:
    events: list[str] = []

    @Injectable
    class Database:
        def on_module_init(self) -> None:
            events.append("real:init")

    class FakeDatabase:
        def on_module_init(self) -> None:
            events.append("fake:init")

        def on_module_destroy(self) -> None:
            events.append("fake:destroy")

    @Module(providers=[Database])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    lifecycle = LifecycleManager(graph, container)
    container.override(Database, FakeDatabase())

    anyio.run(lifecycle.startup)
    anyio.run(lifecycle.shutdown)

    assert events == ["fake:init", "fake:destroy"]


def test_an_override_registered_after_startup_is_refused_by_name() -> None:
    @Injectable
    class Clock:
        pass

    @Module(providers=[Clock])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    container.override_manager.mark_started()

    with pytest.raises(ProviderResolutionError) as raised:
        container.override(Clock, object())

    message = str(raised.value)
    assert "Clock" in message
    assert "before startup" in message


def test_a_provider_a_dynamic_module_declares_is_overridden_through_its_class() -> None:
    # A dynamic registration is keyed by an instance key no caller outside the container
    # holds, so writing the module class has to reach it.
    CONFIG = InjectionToken("CONFIG")

    @Module()
    class ConfigModule:
        pass

    @Module(
        imports=[
            DynamicModule(
                module=ConfigModule,
                providers=({"provide": CONFIG, "use_value": "prod"},),
                exports=(CONFIG,),
            )
        ]
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    container.override(CONFIG, "fake", module=ConfigModule)

    assert container.has_override(CONFIG, module=ConfigModule) is True
    assert container.resolve(CONFIG, module=AppModule) == "fake"


def test_an_override_of_a_request_scoped_provider_serves_one_object_to_every_request(
    build_http_request: HttpRequestFactory,
) -> None:
    # An override is one object, whatever lifetime the provider it replaces declared, so
    # a replaced request-scoped provider stops being per-request. It also stops needing
    # a request at all, because there is no longer anything to build.
    @Injectable(scope=Scope.REQUEST)
    class RequestContext:
        pass

    @Module(providers=[RequestContext])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    replacement = object()
    container.override(RequestContext, replacement)

    assert container.resolve(RequestContext, module=AppModule) is replacement
    assert (
        container.resolve(RequestContext, module=AppModule, request=build_http_request())
        is replacement
    )
    assert (
        container.resolve(RequestContext, module=AppModule, request=build_http_request())
        is replacement
    )


def test_an_override_reaches_a_dependent_that_holds_the_token_through_an_alias() -> None:
    # An alias keeps nothing of its own, so what has to be evicted is whatever was
    # built through it, which is only visible by following the alias to its target.
    @Injectable
    class Clock:
        def now(self) -> str:
            return "real"

    class FakeClock:
        def now(self) -> str:
            return "fake"

    @Module(
        providers=[
            Clock,
            {"provide": "clock-alias", "use_existing": Clock},
            {
                "provide": "stamp",
                "use_factory": lambda clock: clock.now(),
                "inject": ["clock-alias"],
            },
        ]
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    assert container.resolve("stamp", module=AppModule) == "real"

    container.override(Clock, FakeClock())

    assert container.resolve("stamp", module=AppModule) == "fake"


def test_an_override_survives_a_graph_naming_a_token_nothing_can_hash() -> None:
    # A factory may name anything in its inject list, and a token nothing can hash is
    # refused when it is resolved. Reading the graph to evict must not be what turns
    # that mistake into a failure in an unrelated place.
    @Module(
        providers=[
            {"provide": "config", "use_value": "real"},
            {"provide": "broken", "use_factory": lambda value: value, "inject": [["unhashable"]]},
        ]
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    container.override("config", "fake")

    assert container.resolve("config", module=AppModule) == "fake"
