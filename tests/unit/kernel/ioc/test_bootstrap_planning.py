"""What the container settles while it is being built, and what it refuses outright.

Every class the module graph can build is planned once here, so a dependency that
cannot be found is a startup failure rather than a five hundred on whichever request
first reaches it, and an author who has made several mistakes is told about all of
them at once.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, cast

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app, create_app_context
from bustan.common.decorators.injectable import Inject, OptionalDep
from bustan.errors import InvalidControllerError, ProviderResolutionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.ioc.planning.container_plan import controller_scope
from bustan.kernel.ioc.planning.plan import FixedValue, ProvidedToken
from bustan.kernel.ioc.tokens import APPLICATION, REQUEST, RESPONSE, InjectionToken
from bustan.kernel.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import RequestFactory

CONFIG = InjectionToken("CONFIG")
SNAPSHOT = InjectionToken("SNAPSHOT")


class DsnTokens(StrEnum):
    """A token declared as a string enum, which equals the bare string it is written as."""

    DB = "db"


class NotRegistered:
    """A class no module declares, used as a dependency that cannot be satisfied."""


def test_a_transient_provider_with_a_missing_dependency_is_refused_at_bootstrap() -> None:
    # The same mistake on a singleton was always caught at startup. Catching it on a
    # transient too is the point: one class of error, one moment it is reported.
    @Injectable(scope=Scope.TRANSIENT)
    class Broken:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Module(providers=[Broken])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="NotRegistered"):
        create_app_context(AppModule)


def test_a_controller_with_a_missing_dependency_is_refused_at_bootstrap() -> None:
    @Controller("/broken")
    class BrokenController:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

        @Get("/")
        def read(self) -> dict[str, str]:
            return {}

    @Module(controllers=[BrokenController])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="NotRegistered"):
        create_app(AppModule)


def test_every_failure_in_one_graph_is_reported_together() -> None:
    # Reporting one failure per attempt is how an author fixes five mistakes across
    # five deploys, so a refused graph names all of them the first time.
    @Injectable(scope=Scope.REQUEST)
    class RequestState:
        pass

    @Injectable(scope=Scope.TRANSIENT)
    class MissingOne:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Injectable
    class MissingTwo:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Injectable
    class OutlivesTheRequest:
        def __init__(self, state: RequestState) -> None:
            self.state = state

    @Controller("/probe")
    class ProbeController:
        def __init__(self, request: Request) -> None:
            self.request = request

        @Get("/")
        def read(self) -> dict[str, str]:
            return {}

    @Module(
        controllers=[ProbeController],
        providers=[RequestState, MissingOne, MissingTwo, OutlivesTheRequest],
    )
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError) as failure:
        create_app(AppModule)

    reported = str(failure.value)

    assert "4 problems were found" in reported
    assert reported.count("MissingOne") == 1
    assert reported.count("MissingTwo") == 1
    assert "OutlivesTheRequest" in reported
    assert "ProbeController" in reported


def test_a_single_failure_is_reported_on_its_own_without_a_preamble() -> None:
    @Injectable
    class Broken:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Module(providers=[Broken])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError) as failure:
        create_app_context(AppModule)

    assert "problems were found" not in str(failure.value)


def test_create_app_and_create_app_context_refuse_the_same_graph() -> None:
    @Injectable
    class Broken:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Module(providers=[Broken])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError) as from_app:
        create_app(AppModule)
    with pytest.raises(ProviderResolutionError) as from_context:
        create_app_context(AppModule)

    assert str(from_app.value) == str(from_context.value)


def test_a_parameter_with_a_default_is_left_to_it_rather_than_reported() -> None:
    @Injectable
    class UsesDefault:
        def __init__(self, retries: int = 3) -> None:
            self.retries = retries

    @Module(providers=[UsesDefault], exports=[UsesDefault])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    plan = container.plan.for_target(AppModule, UsesDefault)

    assert plan is not None
    assert plan.arguments == ()
    assert cast(Any, container.resolve(UsesDefault, module=AppModule)).retries == 3


def test_an_optional_dependency_nothing_supplies_is_settled_while_planning() -> None:
    @Injectable
    class UsesOptional:
        def __init__(self, maybe: Annotated[object | None, Inject(CONFIG), OptionalDep()]) -> None:
            self.maybe = maybe

    @Module(providers=[UsesOptional], exports=[UsesOptional])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    plan = container.plan.for_target(AppModule, UsesOptional)

    assert plan is not None
    assert plan.arguments[0].source == FixedValue(None)


def test_an_optional_dependency_something_supplies_is_resolved_not_substituted() -> None:
    @Injectable
    class UsesOptional:
        def __init__(self, maybe: Annotated[object | None, Inject(CONFIG), OptionalDep()]) -> None:
            self.maybe = maybe

    @Module(
        providers=[UsesOptional, {"provide": CONFIG, "use_value": "real"}],
        exports=[UsesOptional],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    plan = container.plan.for_target(AppModule, UsesOptional)

    assert plan is not None
    assert plan.arguments[0].source == ProvidedToken(CONFIG)
    assert cast(Any, container.resolve(UsesOptional, module=AppModule)).maybe == "real"


def test_every_class_the_graph_can_build_is_planned_before_anything_is_built() -> None:
    @Injectable
    class Service:
        pass

    @Controller("/things")
    class ThingController:
        def __init__(self, service: Service) -> None:
            self.service = service

        @Get("/")
        def read(self) -> dict[str, str]:
            return {}

    @Module(controllers=[ThingController], providers=[Service])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert set(container.plan.constructions) == {
        (AppModule, Service),
        (AppModule, ThingController),
    }


def test_a_class_the_graph_does_not_declare_is_planned_once_and_kept() -> None:
    # A test replacement or a module reference hands the container a class no module
    # declares. It cannot have been planned at bootstrap, so it is planned on first
    # use and the second build of it costs no more than the second build of a provider.
    @Injectable
    class Service:
        pass

    class Standalone:
        def __init__(self, service: Service) -> None:
            self.service = service

    @Module(providers=[Service], exports=[Service])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    first = cast(Any, container.instantiate_class(Standalone, module=AppModule))
    second = cast(Any, container.instantiate_class(Standalone, module=AppModule))

    assert first is not second
    assert first.service is second.service
    assert container.kernel._unplanned.keys() == {(AppModule, Standalone)}


def test_a_factory_may_inject_the_request_and_the_response(
    build_request: RequestFactory,
) -> None:
    # A request-aware factory provider could not be written at all: every inject entry
    # went through a visibility lookup, and no module declares these tokens.
    def describe(request: Request, response: object) -> dict[str, str]:
        return {
            "user": request.headers.get("x-user-id", "anonymous"),
            "response": type(response).__name__,
        }

    @Controller("/snapshots", scope=Scope.REQUEST)
    class SnapshotController:
        def __init__(self, snapshot: Annotated[Any, Inject(SNAPSHOT)]) -> None:
            self.snapshot = snapshot

        @Get("/")
        def read(self) -> dict[str, str]:
            return self.snapshot

    @Module(
        controllers=[SnapshotController],
        providers=[
            {
                "provide": SNAPSHOT,
                "use_factory": describe,
                "inject": [REQUEST, RESPONSE],
                "scope": "request",
            }
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        payload = client.get("/snapshots/", headers={"x-user-id": "alice"}).json()

    assert payload["user"] == "alice"
    assert payload["response"] != "NoneType"


def test_a_singleton_factory_may_not_inject_the_request() -> None:
    def describe(request: Request) -> str:
        return request.headers.get("x-user-id", "anonymous")

    @Module(providers=[{"provide": SNAPSHOT, "use_factory": describe, "inject": [REQUEST]}])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="REQUEST"):
        create_app_context(AppModule)


def test_a_factory_may_inject_the_application(build_request: RequestFactory) -> None:
    def describe(application: object) -> str:
        return type(application).__name__

    @Module(
        providers=[{"provide": SNAPSHOT, "use_factory": describe, "inject": [APPLICATION]}],
        exports=[SNAPSHOT],
    )
    class AppModule:
        pass

    context = create_app_context(AppModule)

    assert context.get(SNAPSHOT) == "ApplicationContext"


def test_a_class_bound_twice_in_one_module_is_planned_once() -> None:
    @Injectable
    class Service:
        pass

    @Module(
        providers=[
            {"provide": "first", "use_class": Service},
            {"provide": "second", "use_class": Service},
        ],
        exports=["first", "second"],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert set(container.plan.constructions) == {(AppModule, Service)}
    assert container.resolve("first", module=AppModule) is not container.resolve(
        "second", module=AppModule
    )


def test_a_class_handed_to_the_container_late_is_refused_the_same_way() -> None:
    class Standalone:
        def __init__(self, dependency: NotRegistered) -> None:
            self.dependency = dependency

    @Module()
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="NotRegistered"):
        container.instantiate_class(Standalone, module=AppModule)


def test_a_token_that_cannot_be_a_key_is_a_dependency_nothing_supplies() -> None:
    @Injectable
    class Broken:
        def __init__(self, dependency: Annotated[object, Inject(["not", "a", "key"])]) -> None:
            self.dependency = dependency

    @Module(providers=[Broken])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="cannot see"):
        create_app_context(AppModule)


def test_a_controller_with_no_declared_scope_is_cached_for_the_process() -> None:
    class Undecorated:
        pass

    assert controller_scope(Undecorated) is Scope.SINGLETON


@pytest.mark.parametrize("scope", [Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT])
def test_a_controller_is_planned_under_the_lifetime_it_declares(scope: Scope) -> None:
    @Controller("/tenants", scope=scope)
    class TenantsController:
        pass

    assert controller_scope(TenantsController) is scope


def test_a_durable_controller_is_never_planned_as_a_durable_owner() -> None:
    # A durable owner is judged by durable rules, and every one of them is about a
    # lifetime no controller can hold. Handing the scope table this declaration is
    # what once reported the defect against a constructor parameter instead of the
    # decorator that carries it.
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        pass

    with pytest.raises(InvalidControllerError, match="declares scope 'durable'"):
        controller_scope(TenantsController)


def test_a_keyword_only_dependency_is_passed_by_keyword() -> None:
    @Injectable
    class Service:
        pass

    @Injectable
    class Consumer:
        def __init__(self, *, service: Service) -> None:
            self.service = service

    @Module(providers=[Service, Consumer], exports=[Consumer])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    plan = container.plan.for_target(AppModule, Consumer)

    assert plan is not None
    assert plan.arguments[0].positional is False
    assert isinstance(cast(Any, container.resolve(Consumer, module=AppModule)).service, Service)


def test_a_factory_injecting_equal_tokens_of_different_types_is_given_both() -> None:
    # Planning reads the same visibility the resolver does, so a factory may inject a
    # string enum member and the bare string it equals and be handed both bindings.
    def combine(enum_dsn: str, string_dsn: str) -> str:
        return f"{enum_dsn}|{string_dsn}"

    @Module(providers=[{"provide": DsnTokens.DB, "use_value": "enum-db"}], exports=[DsnTokens.DB])
    class SharedModule:
        pass

    @Module(
        imports=[SharedModule],
        providers=[
            {"provide": "db", "use_value": "string-db"},
            {"provide": "dsn", "use_factory": combine, "inject": [DsnTokens.DB, "db"]},
        ],
    )
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))

    assert container.resolve("dsn", module=FeatureModule) == "enum-db|string-db"
