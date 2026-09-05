"""How the framework recognises a parameter that named its transport's own request.

The framework holds one request type, ``HttpRequest``, and imports no transport. An
application may still write the request type its transport defines, so that spelling
has to be recognised by shape rather than by name: a class carrying the whole of
``NativeHttpRequest`` is the transport's request, anything else is not.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import Response

from bustan.adapters.starlette.requests import StarletteHttpRequest
from bustan.contracts import HttpRequest, HttpResponse, NativeHttpRequest, names_native_request


def test_the_transport_s_own_request_is_recognised() -> None:
    assert names_native_request(Request)
    assert issubclass(Request, NativeHttpRequest)


def test_no_neutral_type_is_mistaken_for_the_transport_s_request() -> None:
    # The neutral contract and the wrapper written against it both reach a body, and
    # neither streams one, which is what keeps them out of this rule.
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
