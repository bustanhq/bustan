"""Integration conformance checks for HTTP adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, cast

from bustan import Controller, Get, Module, Post, create_app
from bustan import conformance as conformance_module
from bustan.adapters.starlette import StarletteAdapter
from bustan.conformance import (
    ADAPTER_NAMES,
    UNCOMPARED_BODY_MEMBER,
    ConformanceCase,
    ResponseObservation,
    describe_difference,
)
from bustan.runtime.adapter import AbstractHttpAdapter, AdapterCapabilities
from bustan.testing import AsgiTestClient

_STREAMED_BODY_CASE = "request_limit_refuses_a_streamed_body_over_the_limit"


@dataclass(frozen=True, slots=True)
class Payload:
    name: str


def test_starlette_adapter_conforms_to_the_shared_http_adapter_suite() -> None:
    _assert_http_adapter_conformance(StarletteAdapter())


def _assert_http_adapter_conformance(adapter: AbstractHttpAdapter) -> None:
    @Controller("/health")
    class HealthController:
        @Get("/")
        def read_health(self) -> dict[str, str]:
            return {"status": "ok"}

    @Controller("/payloads")
    class PayloadController:
        @Post("/")
        def create_payload(self, payload: Payload) -> dict[str, str]:
            return {"name": payload.name}

    @Module(controllers=[HealthController, PayloadController])
    class AppModule:
        pass

    assert adapter.name == "starlette"
    assert adapter.capabilities == AdapterCapabilities(
        supports_host_routing=False,
        supports_raw_body=True,
        supports_streaming_responses=True,
        supports_websocket_upgrade=False,
    )

    application = create_app(AppModule, adapter=adapter)
    with AsgiTestClient(cast(Any, application)) as client:
        health_response = client.get("/health")
        payload_response = client.post("/payloads", json={"name": "Ada"})

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert payload_response.status_code == 200
    assert payload_response.json() == {"name": "Ada"}


def _case(name: str) -> ConformanceCase:
    for scenario in conformance_module.SCENARIOS:
        for case in scenario.cases:
            if case.name == name:
                return case
    raise AssertionError(f"no conformance case named {name!r}")


def test_no_case_narrows_what_is_compared_between_adapters() -> None:
    """A narrowed comparison is a debt, so the suite has to say how much of it there is.

    None, today: every case is compared whole, member for member, across every adapter,
    and no case holds one adapter to a document another is not held to. A case appearing
    that does either without this test being changed is the thing worth catching, because
    the facility that allows it is general and reaching for it is cheap.
    """

    narrowed = [
        case.name
        for scenario in conformance_module.SCENARIOS
        for case in scenario.cases
        if case.diverging_body_members
    ]
    held_apart = [
        case.name
        for scenario in conformance_module.SCENARIOS
        for case in scenario.cases
        if case.expected_by_adapter
    ]

    assert narrowed == []
    assert held_apart == []


def test_the_streamed_body_case_holds_every_adapter_to_one_document() -> None:
    """The case that once needed two answers is the one worth naming here.

    Both adapters refuse a body of undeclared length at the chunk that carries it past
    the limit, so neither has read enough of it to say how large it was and both name the
    limit instead. An adapter that went back to reporting the size would be one that had
    buffered the whole body first, and the day that happens is a day this case fails.
    """

    case = _case(_STREAMED_BODY_CASE)

    assert case.expected_by_adapter == ()
    assert case.diverging_body_members == ()
    assert _detail(case.expected) == "The request body exceeds the 10485760 byte limit"
    for adapter in ADAPTER_NAMES:
        assert case.expected_for(adapter) is case.expected


def _narrowing_case() -> ConformanceCase:
    """A case that names one diverging member, built here rather than found in the suite.

    The suite narrows nothing, and the facility still has to work for the case that one
    day needs it. A test that reached into the suite for an example would have stopped
    testing the facility the moment the last such case was removed, which is exactly when
    the facility became untested rather than unused.
    """

    return ConformanceCase(
        name="narrowing_case",
        dimension="narrowing",
        request=conformance_module.ConformanceRequest(method="POST", path="/limits/notes"),
        expected=_problem(UNCOMPARED_BODY_MEMBER),
        expected_by_adapter=(
            ("starlette", _problem("refused while reading")),
            ("asgi", _problem("refused after reading 10485762 bytes")),
        ),
        diverging_body_members=("detail",),
    )


def _problem(detail: str) -> ResponseObservation:
    """The observation the constructed case's adapters are held to, detail apart."""

    return ResponseObservation(
        413,
        (("content-type", "application/problem+json"),),
        json.dumps(
            {
                "type": "about:blank",
                "title": "Content Too Large",
                "status": 413,
                "detail": detail,
                "instance": "/limits/notes",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def test_a_case_that_names_a_diverging_member_has_it_reduced_on_both_sides() -> None:
    """Two documents that differ only in the named member compare as agreeing."""

    case = _narrowing_case()
    starlette, asgi = (
        conformance_module._reduce_for_comparison(case, dict(case.expected_by_adapter)[name])
        for name in ("starlette", "asgi")
    )

    assert _detail(starlette) == UNCOMPARED_BODY_MEMBER
    assert _detail(asgi) == UNCOMPARED_BODY_MEMBER
    assert describe_difference("starlette", starlette, "asgi", asgi) == ()


def test_a_narrowed_comparison_still_reports_every_other_part_of_the_answer() -> None:
    """Narrowed to one member means narrowed to one member, not to nothing."""

    case = _narrowing_case()
    starlette = conformance_module._reduce_for_comparison(
        case, dict(case.expected_by_adapter)["starlette"]
    )
    asgi = dict(case.expected_by_adapter)["asgi"]

    for altered in (
        replace(asgi, status_code=500),
        replace(asgi, body=asgi.body.replace('"/limits/notes"', '"/elsewhere"')),
        replace(asgi, body=asgi.body.replace('"Content Too Large"', '"Payload Too Large"')),
        replace(asgi, headers=(("content-type", "application/json"),)),
    ):
        reduced = conformance_module._reduce_for_comparison(case, altered)
        assert describe_difference("starlette", starlette, "asgi", reduced) != ()


def test_a_case_that_names_no_diverging_member_is_compared_whole() -> None:
    observation = ResponseObservation(200, (("content-type", "application/json"),), '{"a":1}')
    case = _case("request_limit_serves_a_body_within_the_limit")

    assert conformance_module._reduce_for_comparison(case, observation) is observation


def _detail(expected: ResponseObservation) -> str:
    return cast("dict[str, str]", json.loads(expected.body))["detail"]
