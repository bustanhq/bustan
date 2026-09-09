"""Integration tests for installing a response serializer the way an application must.

Every name this file takes from the framework comes from ``bustan`` or
``bustan.testing``, and what it asserts is what a request produces on the wire rather
than that a setter ran: a serializer that is installed but never consulted would satisfy
the second and fail every test here.

The runtime writes a response at three places, and a serializer that reaches only one of
them leaves the rest of the defect in place, so each has a test naming the path it
serves: the value a handler returned, the failure a handler raised, and the failure a
middleware raised before the route was ever entered.
"""

from __future__ import annotations

from typing import Any, cast

from bustan import (
    BadRequestException,
    Controller,
    DefaultResponseSerializer,
    Get,
    HttpRequest,
    HttpResponse,
    Middleware,
    Module,
    create_app,
)
from bustan.pipeline.middleware import MiddlewareConsumer
from bustan.testing import AsgiTestClient

_ENVELOPE_HEADER = "x-envelope"


class EnvelopeSerializer:
    """Serialize what a handler returns into one application's envelope.

    A value the envelope does not describe - a response the framework built for itself,
    which is what a rendered failure hands over - is given to the default serializer
    instead. That delegation is what the exported default exists for, so an application
    only has to describe the values it actually owns.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._default = DefaultResponseSerializer()
        self.serialized: list[object] = []

    def serialize(self, value: object) -> HttpResponse:
        self.serialized.append(value)
        if isinstance(value, dict):
            response = HttpResponse.json({"envelope": self._name, "data": value})
        else:
            response = cast(HttpResponse, self._default.serialize(value))
        response.headers[_ENVELOPE_HEADER] = self._name
        return response


class RefusingMiddleware(Middleware):
    """Refuse the request before the route it fronts is entered."""

    async def use(self, request: HttpRequest, call_next: Any) -> Any:
        raise BadRequestException("the middleware refused the request")


def _notes_module(*, constructed: list[str] | None = None) -> type[object]:
    """Return a module whose one route returns a value the serializer will see."""

    @Controller("/notes")
    class NotesController:
        def __init__(self) -> None:
            if constructed is not None:
                constructed.append("NotesController")

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"title": "a note"}

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    return AppModule


def test_a_serializer_given_to_create_app_changes_what_a_returned_value_becomes() -> None:
    """The success path: what ``execute_http_route`` writes when a handler returns."""

    serializer = EnvelopeSerializer("orders")

    with AsgiTestClient(cast(Any, create_app(_notes_module()))) as client:
        default = client.get("/notes")

    configured = create_app(_notes_module(), response_serializer=serializer)
    with AsgiTestClient(cast(Any, configured)) as client:
        enveloped = client.get("/notes")

    assert default.status_code == 200
    assert default.json() == {"title": "a note"}
    assert _ENVELOPE_HEADER not in default.headers

    assert enveloped.status_code == 200
    assert enveloped.json() == {"envelope": "orders", "data": {"title": "a note"}}
    assert enveloped.headers[_ENVELOPE_HEADER] == "orders"
    assert serializer.serialized == [{"title": "a note"}]


def test_a_serializer_given_to_create_app_reaches_the_failure_a_handler_raised() -> None:
    """The route's own error path: what ``_render_failure`` writes.

    The controller is constructed and the handler runs, so the response cannot have come
    from the path that answers a request the route was never entered for.
    """

    serializer = EnvelopeSerializer("orders")
    constructed: list[str] = []

    @Controller("/notes")
    class NotesController:
        def __init__(self) -> None:
            constructed.append("NotesController")

        @Get("/")
        def read(self) -> dict[str, str]:
            raise BadRequestException("the handler refused the request")

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    application = create_app(AppModule, response_serializer=serializer)
    with AsgiTestClient(cast(Any, application)) as client:
        refused = client.get("/notes")

    assert constructed == ["NotesController"]
    assert refused.status_code == 400
    assert refused.headers[_ENVELOPE_HEADER] == "orders"
    assert [type(value) for value in serializer.serialized] == [HttpResponse]


def test_a_serializer_given_to_create_app_reaches_the_failure_a_middleware_raised() -> None:
    """The middleware error path: what ``execute_http_exception`` writes.

    The middleware refuses before ``call_next``, so the controller is never constructed
    and the route is never entered. Any response therefore came from the path that
    renders an exception for a route that never ran.
    """

    serializer = EnvelopeSerializer("orders")
    constructed: list[str] = []
    notes_module = _notes_module(constructed=constructed)

    @Module(imports=[notes_module])
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(RefusingMiddleware).for_routes("/notes*")

    application = create_app(AppModule, response_serializer=serializer)
    with AsgiTestClient(cast(Any, application)) as client:
        refused = client.get("/notes")

    assert constructed == []
    assert refused.status_code == 400
    assert refused.headers[_ENVELOPE_HEADER] == "orders"
    assert [type(value) for value in serializer.serialized] == [HttpResponse]


def test_two_applications_in_one_process_serialize_through_their_own_serializers() -> None:
    """The serializer belongs to an application, not to the process it happens to share."""

    orders = create_app(_notes_module(), response_serializer=EnvelopeSerializer("orders"))
    invoices = create_app(_notes_module(), response_serializer=EnvelopeSerializer("invoices"))
    plain = create_app(_notes_module())

    with (
        AsgiTestClient(cast(Any, orders)) as orders_client,
        AsgiTestClient(cast(Any, invoices)) as invoices_client,
        AsgiTestClient(cast(Any, plain)) as plain_client,
    ):
        from_orders = orders_client.get("/notes")
        from_invoices = invoices_client.get("/notes")
        from_plain = plain_client.get("/notes")
        # Read the first application again while the other two are alive, because a
        # serializer that had been process-wide would have been replaced by the assembly
        # of the second rather than kept by the first.
        from_orders_again = orders_client.get("/notes")

    assert from_orders.json() == {"envelope": "orders", "data": {"title": "a note"}}
    assert from_orders_again.json() == from_orders.json()
    assert from_invoices.json() == {"envelope": "invoices", "data": {"title": "a note"}}
    assert from_plain.json() == {"title": "a note"}
    assert _ENVELOPE_HEADER not in from_plain.headers


def test_a_route_that_returns_its_own_response_is_not_serialized() -> None:
    """A handler that builds the response itself declares what goes on the wire."""

    serializer = EnvelopeSerializer("orders")

    @Controller("/notes")
    class NotesController:
        @Get("/raw")
        def raw(self) -> HttpResponse:
            return HttpResponse.json({"title": "a note"})

    @Module(controllers=[NotesController])
    class AppModule:
        pass

    application = create_app(AppModule, response_serializer=serializer)
    with AsgiTestClient(cast(Any, application)) as client:
        response = client.get("/notes/raw")

    assert response.status_code == 200
    assert response.json() == {"title": "a note"}
    assert _ENVELOPE_HEADER not in response.headers
    assert serializer.serialized == []
