"""How the framework recognises a parameter that named its transport's own request.

The framework holds one request type, ``HttpRequest``, and imports no transport. An
application may still write the request type its transport defines, and that spelling is
read in two steps. Shape says a parameter asked for *a* transport's request: a class
carrying the whole of ``NativeHttpRequest`` did, anything else did not. Identity says
*which*: every transport's request has the same shape, so only the adapter can say
whether the object it produces is the one the parameter asked for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response

from bustan.adapters.asgi.requests import AsgiHttpRequest
from bustan.adapters.starlette.requests import StarletteHttpRequest
from bustan.contracts import HttpRequest, HttpResponse, NativeHttpRequest, names_native_request
from bustan.contracts.requests import produces_native_request


def test_the_transport_s_own_request_is_recognised() -> None:
    assert names_native_request(Request)
    assert issubclass(Request, NativeHttpRequest)


def test_the_raw_asgi_request_is_recognised_as_its_own_transport_s_request() -> None:
    """Raw ASGI defines no request object, so the adapter's wrapper is the one it builds.

    It is what ``native_request`` returns under that adapter, so a handler that names it
    is naming the object it will be handed, and the rule has to see that.
    """

    assert names_native_request(AsgiHttpRequest)
    assert issubclass(AsgiHttpRequest, NativeHttpRequest)


def test_no_neutral_type_is_mistaken_for_the_transport_s_request() -> None:
    # The neutral contract and the Starlette wrapper written against it both reach a
    # body and neither streams one, which is what keeps them out of this rule.
    for neutral in (HttpRequest, StarletteHttpRequest, HttpResponse, Response):
        assert not names_native_request(neutral)


def test_nothing_that_is_not_a_class_is_a_request() -> None:
    for annotation in (None, "Request", 42, object()):
        assert not names_native_request(annotation)


def test_an_application_class_that_happens_to_read_a_body_is_still_recognised() -> None:
    """The rule is about shape, so a second transport's request needs no registration."""

    class OtherTransportRequest:
        def stream(self) -> AsyncIterator[bytes]:
            raise NotImplementedError

        async def body(self) -> bytes:
            return b""

        async def json(self) -> object:
            return None

    assert names_native_request(OtherTransportRequest)


def test_a_class_missing_one_member_is_not_a_request() -> None:
    class HalfARequest:
        async def body(self) -> bytes:
            return b""

        async def json(self) -> object:
            return None

    assert not names_native_request(HalfARequest)


def test_an_adapter_satisfies_only_the_annotations_its_own_request_answers_to() -> None:
    """Which transport an annotation named is settled by what the adapter produces."""

    assert produces_native_request(AsgiHttpRequest, AsgiHttpRequest)
    assert produces_native_request(Request, Request)
    assert not produces_native_request(AsgiHttpRequest, Request)
    assert not produces_native_request(Request, AsgiHttpRequest)


def test_the_neutral_spelling_of_a_transport_request_is_satisfied_by_every_adapter() -> None:
    """``NativeHttpRequest`` names a transport's request without naming a transport."""

    assert produces_native_request(AsgiHttpRequest, NativeHttpRequest)
    assert produces_native_request(Request, NativeHttpRequest)


def test_an_annotation_naming_a_base_of_the_produced_request_is_satisfied() -> None:
    """The object handed over is an instance of it, so the annotation stays true."""

    class TransportRequest:
        pass

    class DerivedTransportRequest(TransportRequest):
        pass

    assert produces_native_request(DerivedTransportRequest, TransportRequest)


def test_an_adapter_declaring_no_request_type_of_its_own_satisfies_nothing() -> None:
    assert not produces_native_request(None, Request)
    assert not produces_native_request(None, NativeHttpRequest)


def test_an_annotation_that_cannot_be_tested_is_refused_rather_than_assumed() -> None:
    """A parameter whose truth cannot be established must not be quietly satisfied."""

    class NotRuntimeCheckable(Protocol):
        def stream(self) -> AsyncIterator[bytes]: ...

    assert not produces_native_request(Request, NotRuntimeCheckable)
    assert not produces_native_request(Request, "Request")
