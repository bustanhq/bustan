"""Black-box tests of the resolution kernel: INQUIRER, overrides, cycles and scopes.

Every test here drives a real module graph through the public container API, because
the defects these cover were all reachable through it and none of them were caught by
the private-seam tests this file replaces.
"""

from __future__ import annotations

import functools
import inspect
import threading
from typing import TYPE_CHECKING, Annotated, Any, cast
from unittest import mock

import anyio
import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope, create_app_context
from bustan.common.decorators.injectable import Inject
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.container import build_container
from bustan.core.ioc.planning.scopes import entered_request_scope
from bustan.core.ioc.registry import Binding
from bustan.core.ioc.tokens import APPLICATION, INQUIRER, RESPONSE
from bustan.core.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import AppFactory, RequestFactory


def test_inquirer_receives_the_dependent_class_during_nested_resolution() -> None:
    # INQUIRER names whoever asked, so only a provider built afresh for each consumer
    # can carry it; a cached one would report its first consumer forever.
    @Injectable(scope=Scope.TRANSIENT)
    class AuditTrail:
        def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
            self.inquirer = inquirer

    @Injectable
    class BillingService:
        def __init__(self, audit_trail: AuditTrail) -> None:
            self.audit_trail = audit_trail

    @Module(providers=[AuditTrail, BillingService], exports=[BillingService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    billing = cast(Any, container.resolve(BillingService, module=AppModule))

    assert billing.audit_trail.inquirer is BillingService


def test_inquirer_receives_the_class_passed_to_instantiate_class() -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class AuditTrail:
        def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
            self.inquirer = inquirer

    class StandaloneConsumer:
        def __init__(self, audit_trail: AuditTrail) -> None:
            self.audit_trail = audit_trail

    @Module(providers=[AuditTrail], exports=[AuditTrail])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    consumer = cast(Any, container.instantiate_class(StandaloneConsumer, module=AppModule))

    assert consumer.audit_trail.inquirer is StandaloneConsumer


def test_override_of_exported_provider_applies_through_importing_modules() -> None:
    @Injectable
    class UserService:
        pass

    @Module(providers=[UserService], exports=[UserService])
    class UsersModule:
        pass

    @Module(imports=[UsersModule])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    replacement = object()
    container.override(UserService, replacement)

    assert container.resolve(UserService, module=AppModule) is replacement
    assert container.resolve(UserService, module=UsersModule) is replacement


def test_same_token_name_in_two_modules_is_not_reported_as_a_cycle() -> None:
    @Injectable
    class Svc:
        def __init__(self, cfg: Annotated[object, Inject("cfg")]) -> None:
            self.cfg = cfg

    @Module(
        providers=[Svc, {"provide": "cfg", "use_value": "inner-config"}],
        exports=[Svc],
    )
    class InnerModule:
        pass

    @Injectable
    class CfgHolder:
        def __init__(self, svc: Svc) -> None:
            self.svc = svc

    @Module(
        imports=[InnerModule],
        providers=[{"provide": "cfg", "use_class": CfgHolder}],
        exports=["cfg"],
    )
    class OuterModule:
        pass

    container = build_container(build_module_graph(OuterModule))
    holder = cast(Any, container.resolve("cfg", module=OuterModule))

    assert isinstance(holder, CfgHolder)
    assert holder.svc.cfg == "inner-config"


def test_class_bound_in_two_modules_uses_the_scope_of_the_resolved_binding(
    build_request: RequestFactory,
) -> None:
    class Shared:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Module(
        providers=[{"provide": "req_scoped", "use_class": Shared, "scope": "request"}],
        exports=["req_scoped"],
    )
    class RequestModule:
        pass

    @Module(
        imports=[RequestModule],
        providers=[{"provide": "singleton_bound", "use_class": Shared, "scope": "singleton"}],
    )
    class AppModule:
        pass

    # Each binding of the class is judged on its own scope, so the singleton one is
    # refused while the graph is planned even though the request-scoped one is legal.
    with pytest.raises(ProviderResolutionError, match="framework-owned type Request"):
        build_container(build_module_graph(AppModule))

    container = build_container(build_module_graph(RequestModule))
    request = build_request(path="/shared")
    resolved = cast(
        Any,
        container.resolve("req_scoped", module=RequestModule, request=request),
    )

    assert resolved.request is request


def test_concurrent_resolution_constructs_a_singleton_exactly_once() -> None:
    constructions: list[int] = []
    release = threading.Event()

    @Injectable
    class SlowService:
        def __init__(self) -> None:
            constructions.append(1)
            release.wait(timeout=1)

    @Module(providers=[SlowService], exports=[SlowService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    resolved: list[object] = []
    threads = [
        threading.Thread(
            target=lambda: resolved.append(container.resolve(SlowService, module=AppModule))
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert len(constructions) == 1
    assert len(resolved) == 4
    assert all(instance is resolved[0] for instance in resolved)


def test_resolve_async_supports_class_providers_with_async_factory_dependencies() -> None:
    async def make_connection() -> str:
        return "connected"

    @Injectable
    class NeedsConnection:
        def __init__(self, conn: Annotated[str, Inject("conn")]) -> None:
            self.conn = conn

    @Module(
        providers=[
            NeedsConnection,
            {"provide": "conn", "use_factory": make_connection, "scope": "transient"},
        ],
        exports=[NeedsConnection],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    async def resolve() -> object:
        return await container.resolve_async(NeedsConnection, module=AppModule)

    instance = cast(Any, anyio.run(resolve))
    assert instance.conn == "connected"


def test_a_singleton_whose_value_is_none_is_built_once_and_kept() -> None:
    # A provider may legitimately produce None, so a cache probe cannot read the
    # absence of a value out of it. Reading it that way rebuilds the provider on every
    # resolution, and makes an async one fail at startup.
    calls: list[int] = []

    def build_client() -> None:
        calls.append(1)
        return None

    @Module(
        providers=[{"provide": "client", "use_factory": build_client}],
        exports=["client"],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    for _ in range(5):
        assert container.resolve("client", module=AppModule) is None

    assert len(calls) == 1


def test_an_async_singleton_factory_that_returns_none_starts_the_application() -> None:
    calls: list[int] = []

    async def build_client() -> None:
        calls.append(1)
        return None

    @Module(
        providers=[{"provide": "client", "use_factory": build_client}],
        exports=["client"],
    )
    class AppModule:
        pass

    async def start() -> object:
        context = await create_app_context(AppModule).init()
        return context.get("client")

    assert anyio.run(start) is None
    assert len(calls) == 1


def test_a_value_provider_of_none_is_served_rather_than_rebuilt() -> None:
    @Module(providers=[{"provide": "absent", "use_value": None}], exports=["absent"])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert container.resolve("absent", module=AppModule) is None


def test_building_an_instance_reads_no_signature_and_evaluates_no_annotation() -> None:
    # Every question about a constructor is answered once, while the application is
    # built. Asking again per instantiation is what made the cost of building anything
    # grow with the number of tokens the module could see.
    @Injectable
    class Dependency:
        pass

    @Injectable(scope=Scope.TRANSIENT)
    class Consumer:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

    @Module(providers=[Dependency, Consumer], exports=[Consumer])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    container.resolve(Consumer, module=AppModule)

    inspected: list[object] = []
    original_signature = inspect.signature

    def recording_signature(target: object, **kwargs: object) -> object:
        inspected.append(target)
        return original_signature(cast(Any, target), **cast(Any, kwargs))

    with mock.patch.object(inspect, "signature", recording_signature):
        for _ in range(10):
            container.resolve(Consumer, module=AppModule)

    assert inspected == []


def test_resolving_an_unknown_token_names_the_module_that_cannot_see_it() -> None:
    @Injectable
    class Service:
        pass

    @Module(providers=[Service])
    class AppModule:
        pass

    class OtherModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="not available to AppModule"):
        container.resolve("nothing", module=AppModule)

    with pytest.raises(ProviderResolutionError, match="not part of the application container"):
        container.resolve(Service, module=OtherModule)


def test_the_request_and_the_response_are_refused_when_none_is_in_flight() -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class NeedsRequest:
        def __init__(self, request: Request) -> None:
            self.request = request

    @Injectable(scope=Scope.TRANSIENT)
    class NeedsResponse:
        def __init__(self, response: Annotated[object, Inject(RESPONSE)]) -> None:
            self.response = response

    @Module(providers=[NeedsRequest, NeedsResponse], exports=[NeedsRequest, NeedsResponse])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="no request is being served"):
        container.resolve(NeedsRequest, module=AppModule)

    with pytest.raises(ProviderResolutionError, match="none is being assembled"):
        container.resolve(NeedsResponse, module=AppModule)


def test_the_application_is_refused_when_none_is_running() -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class NeedsApplication:
        def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
            self.application = application

    @Module(providers=[NeedsApplication], exports=[NeedsApplication])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="only available once one is running"):
        container.resolve(NeedsApplication, module=AppModule)


def test_the_application_is_read_off_the_request_when_one_is_in_flight(
    build_request: RequestFactory,
    build_app: AppFactory,
) -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class NeedsApplication:
        def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
            self.application = application

    @Module(providers=[NeedsApplication], exports=[NeedsApplication])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    application = build_app()
    request = build_request(path="/runtime", app=application)
    resolved = cast(Any, container.resolve(NeedsApplication, module=AppModule, request=request))

    assert resolved.application is application


def test_inquirer_is_refused_when_nothing_is_being_built_for_anyone() -> None:
    @Injectable(scope=Scope.TRANSIENT)
    class AuditTrail:
        def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
            self.inquirer = inquirer

    @Module(providers=[AuditTrail], exports=[AuditTrail])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="INQUIRER"):
        container.resolve(AuditTrail, module=AppModule)


def test_an_imperative_resolution_does_not_inherit_a_request_it_was_not_given(
    build_request: RequestFactory,
) -> None:
    # An entry point handed no request must resolve as though none were in flight.
    # Leaving the active request untouched lets a provider built this way capture a
    # caller's state and keep it for as long as it is cached.
    @Injectable(scope=Scope.REQUEST)
    class Identity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user-id", "anonymous")

    @Module(providers=[Identity], exports=[Identity])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_request(path="/me", headers=[(b"x-user-id", b"alice")])

    inherited: list[Exception] = []

    def resolve_without_a_request() -> None:
        try:
            container.resolve(Identity, module=AppModule)
        except ProviderResolutionError as exc:
            inherited.append(exc)

    with entered_request_scope(container.scope_manager.active_request, request):
        resolve_without_a_request()

    assert len(inherited) == 1
    assert "requires an active request" in str(inherited[0])


def test_an_async_factory_cannot_be_called_by_synchronous_resolution() -> None:
    async def build_connection() -> str:
        return "connected"

    @Module(
        providers=[{"provide": "conn", "use_factory": build_connection}],
        exports=["conn"],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="async factory"):
        container.resolve("conn", module=AppModule)


def test_an_alias_resolves_to_the_provider_it_points_at() -> None:
    @Injectable
    class Service:
        pass

    @Module(
        providers=[Service, {"provide": "alias", "use_existing": Service}],
        exports=["alias", Service],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    assert container.resolve("alias", module=AppModule) is container.resolve(
        Service, module=AppModule
    )


def test_a_binding_the_kernel_cannot_recognise_names_the_kind_it_found() -> None:
    # Guards the invariant that normalization produces one of four resolver kinds; a
    # fifth would otherwise be a silent None handed to a constructor.
    @Module()
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    container.registry.register_binding(
        (AppModule, "odd"),
        Binding(
            token="odd",
            declaring_module=AppModule,
            resolver_kind="telepathy",
            target=None,
            scope=Scope.TRANSIENT,
        ),
    )
    container.registry.module_visibility[AppModule]["odd"] = AppModule

    with pytest.raises(ProviderResolutionError, match="Unknown resolver kind: telepathy"):
        container.resolve("odd", module=AppModule)


def test_a_callable_object_that_returns_a_coroutine_is_refused_by_name() -> None:
    class OpenConnection:
        async def __call__(self) -> str:
            return "connected"

    @Module(
        providers=[{"provide": "conn", "use_factory": OpenConnection()}],
        exports=["conn"],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="async factory"):
        container.resolve("conn", module=AppModule)


def test_a_factory_without_a_qualified_name_is_still_named_in_a_diagnostic() -> None:
    open_connection = functools.partial(_never_called)

    @Module(providers=[{"provide": "conn", "use_factory": open_connection}], exports=["conn"])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    with pytest.raises(ProviderResolutionError, match="functools.partial"):
        container.resolve("conn", module=AppModule)


async def _never_called() -> str:
    return "connected"
