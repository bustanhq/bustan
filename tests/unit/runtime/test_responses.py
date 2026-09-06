"""Unit tests for handler response coercion."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from starlette.responses import PlainTextResponse

from bustan.contracts import HttpResponse
from bustan.runtime.responses import coerce_response


def test_coerce_response_passes_a_transport_built_response_through_untouched() -> None:
    response = PlainTextResponse("ok", status_code=201)

    assert coerce_response(response) is response


def test_coerce_response_serializes_dict_and_list_values() -> None:
    dict_response = coerce_response({"status": "ok"})
    list_response = coerce_response(["bustan", "lette"])

    assert isinstance(dict_response, HttpResponse)
    assert isinstance(list_response, HttpResponse)
    assert dict_response.body == b'{"status":"ok"}'
    assert list_response.body == b'["bustan","lette"]'


def test_coerce_response_serializes_dataclass_instances() -> None:
    @dataclass(frozen=True, slots=True)
    class Payload:
        status: str
        count: int

    response = coerce_response(Payload(status="ok", count=2))

    assert isinstance(response, HttpResponse)
    assert response.body == b'{"status":"ok","count":2}'


def test_coerce_response_converts_none_to_no_content() -> None:
    response = coerce_response(None)

    assert isinstance(response, HttpResponse)
    assert response.status_code == 204
    assert response.body == b""


def test_coerce_response_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError, match="Unsupported handler return type"):
        coerce_response("ok")
