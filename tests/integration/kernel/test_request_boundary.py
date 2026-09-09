"""What the container is handed when a request is in flight.

The container is the part of the framework furthest from a socket, so it is the part
that must not know what a socket is. One request type crosses into it - the neutral
``HttpRequest`` the adapter built at the edge - and everything cached, keyed or
injected for that request is derived from that one object. A parameter that named the
transport's own request type is still served, out of the escape hatch the contract
declares, so the two spellings name the same request rather than two of them.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import (
    Controller,
    Get,
    HttpRequest,
    Inject,
    Injectable,
    Module,
    Scope,
    create_app,
)
from bustan.adapters.asgi import AsgiAdapter, AsgiTestClient
from bustan.adapters.asgi.requests import AsgiHttpRequest
from bustan.adapters.starlette.requests import from_starlette_request
from bustan.errors import RouteDefinitionError
from bustan.kernel.ioc.tokens import APPLICATION, REQUEST

SEEN: dict[str, object] = {}


@Injectable(scope=Scope.REQUEST)
class HoldsTheContract:
    """A provider that asked for the request by the framework's own type for it."""

    def __init__(self, request: HttpRequest) -> None:
        self.request = request


@Injectable(scope=Scope.REQUEST)
class HoldsTheTransportRequest:
    """A provider that asked for the request by the type its transport defines."""

    def __init__(self, request: Request) -> None:
        self.request = request


@Injectable(scope=Scope.REQUEST)
class HoldsTheRequestToken:
    """A provider that asked for the request by token."""

    def __init__(self, request: Annotated[Any, Inject(REQUEST)]) -> None:
        self.request = request


@Injectable(scope=Scope.TRANSIENT)
class NeedsTheApplication:
    """A provider that asks for the application it is running inside."""

    def __init__(self, application: Annotated[Any, Inject(APPLICATION)]) -> None:
        self.application = application


@Controller("/boundary", scope=Scope.REQUEST)
class BoundaryController:
    def __init__(
        self,
        contract: HoldsTheContract,
        transport: HoldsTheTransportRequest,
        token: HoldsTheRequestToken,
    ) -> None:
        SEEN["contract"] = contract.request
        SEEN["transport"] = transport.request
        SEEN["token"] = token.request

    @Get("/")
    def read(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(
    controllers=[BoundaryController],
    providers=[
        HoldsTheContract,
        HoldsTheTransportRequest,
        HoldsTheRequestToken,
        NeedsTheApplication,
    ],
)
class AppModule:
    pass


def _serve() -> dict[str, object]:
    SEEN.clear()
    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/boundary/", headers={"x-user-id": "ada"}).status_code == 200
    return dict(SEEN)


def test_the_request_the_container_carries_is_the_contract() -> None:
    seen = _serve()

    assert isinstance(seen["contract"], HttpRequest)
    assert not isinstance(seen["contract"], Request)
    assert seen["token"] is seen["contract"]


def test_the_transport_spelling_is_handed_the_transport_object() -> None:
    seen = _serve()

    transport_request = seen["transport"]
    contract_request = seen["contract"]

    assert isinstance(transport_request, Request)
    # One request, reached two ways: what the transport spelling was handed is the
    # object the contract keeps reachable, not a second request built beside it.
    assert transport_request is cast(HttpRequest, contract_request).native_request


def test_the_request_scope_state_is_read_through_the_contract() -> None:
    """The per-request namespace the container keys on is one storage, not two."""

    seen = _serve()

    contract_request = cast(HttpRequest, seen["contract"])
    native_request = seen["transport"]

    assert isinstance(native_request, Request)
    # The two wrappers share one storage, so a write through the contract is visible
    # to anything reading the transport request directly.
    contract_request.state.probe = "written through the contract"
    assert native_request.state.probe == "written through the contract"


def test_the_application_is_reached_through_the_contract_when_none_was_pushed() -> None:
    """A request tells the container an application is running, not which one.

    A resolution entered with a request and nothing pushed still names the application
    the container belongs to, which is the object every other entry point answers with.
    The server the request arrived on is a transport detail and never the answer.
    """

    application = create_app(AppModule)
    request = from_starlette_request(
        build_starlette_request(application.get_http_server()),
    )

    resolved = application.container.resolve(NeedsTheApplication, module=AppModule, request=request)
    entered_directly = application.get(NeedsTheApplication)

    assert resolved.application is not application.get_http_server()
    assert resolved.application is entered_directly.application


def build_starlette_request(app: Starlette) -> Request:
    """Return a bare request carrying *app*, as a transport hands one over."""

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/boundary/",
            "headers": [],
            "app": app,
        }
    )


ASGI_SEEN: dict[str, object] = {}


@Injectable(scope=Scope.REQUEST)
class HoldsTheRawAsgiRequest:
    """A provider that asked for the request by the type raw ASGI's adapter defines."""

    def __init__(self, request: AsgiHttpRequest) -> None:
        self.request = request


@Controller("/raw", scope=Scope.REQUEST)
class RawAsgiController:
    def __init__(self, contract: HoldsTheContract, transport: HoldsTheRawAsgiRequest) -> None:
        ASGI_SEEN["contract"] = contract.request
        ASGI_SEEN["transport"] = transport.request

    @Get("/")
    def read(self, request: AsgiHttpRequest) -> dict[str, str]:
        ASGI_SEEN["parameter"] = request
        return {"status": "ok"}


@Module(controllers=[RawAsgiController], providers=[HoldsTheContract, HoldsTheRawAsgiRequest])
class RawAsgiModule:
    pass


def test_a_handler_naming_the_serving_adapter_s_own_request_type_is_served_it() -> None:
    """Raw ASGI's request type is its adapter's own, and naming it must be served.

    The framework built this class, so a handler that writes it is naming the object the
    serving adapter hands over. It is bound as the request rather than looked for in the
    query string, and both the parameter and a provider constructor see the same object.
    """

    ASGI_SEEN.clear()
    application = create_app(
        RawAsgiModule, adapter=lambda runtime: AsgiAdapter(lifespan=runtime.lifespan)
    )

    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/raw/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    parameter_request = ASGI_SEEN["parameter"]
    contract_request = cast(HttpRequest, ASGI_SEEN["contract"])

    assert isinstance(parameter_request, AsgiHttpRequest)
    assert parameter_request is contract_request.native_request
    assert ASGI_SEEN["transport"] is parameter_request


@Injectable(scope=Scope.REQUEST)
class HoldsAForeignTransportRequest:
    """A provider that asked for the request by a type its transport will not build."""

    def __init__(self, request: Request) -> None:
        self.request = request


@Controller("/foreign", scope=Scope.REQUEST)
class ForeignRequestController:
    def __init__(self, holder: HoldsAForeignTransportRequest) -> None:
        self.holder = holder

    @Get("/")
    def read(self) -> dict[str, str]:
        return {"handed": type(self.holder.request).__name__}


@Module(controllers=[ForeignRequestController], providers=[HoldsAForeignTransportRequest])
class ForeignRequestModule:
    pass


def test_a_provider_naming_a_request_type_the_serving_adapter_will_not_build_is_refused() -> None:
    """The constructor spelling is held to the adapter exactly as the handler one is.

    Served through raw ASGI, this provider used to be handed an ``AsgiHttpRequest`` under
    an annotation promising a Starlette one, and told nothing: the two overlap widely
    enough that such a provider passes its own tests while holding the wrong object. The
    application is refused while it is assembled instead, before a server starts.
    """

    with pytest.raises(RouteDefinitionError) as info:
        create_app(
            ForeignRequestModule,
            adapter=lambda runtime: AsgiAdapter(lifespan=runtime.lifespan),
        )

    message = str(info.value)
    assert "HoldsAForeignTransportRequest.__init__ parameter 'request'" in message
    assert "starlette.requests.Request" in message
    assert "AsgiAdapter does not produce" in message
    assert "bustan.adapters.asgi.requests.AsgiHttpRequest" in message


def test_the_same_provider_serves_under_the_adapter_that_does_build_that_type() -> None:
    """The refusal is about the wiring, not about the spelling.

    The same provider, unchanged, is served the object it named as soon as the
    application is served through the transport that builds it.
    """

    with TestClient(cast(Any, create_app(ForeignRequestModule))) as client:
        response = client.get("/foreign/")

    assert response.status_code == 200
    assert response.json() == {"handed": "Request"}
