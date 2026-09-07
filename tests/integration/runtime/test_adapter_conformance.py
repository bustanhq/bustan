"""Integration conformance checks for HTTP adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, cast

from bustan import Controller, Get, Module, Post, create_app
from bustan.adapters.starlette import StarletteAdapter
from bustan.runtime import conformance as conformance_module
from bustan.runtime.adapter import AbstractHttpAdapter, AdapterCapabilities
from bustan.runtime.conformance import (
    ADAPTER_NAMES,
    UNCOMPARED_BODY_MEMBER,
    ConformanceCase,
    ResponseObservation,
    describe_difference,
)
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


def test_only_the_streamed_body_case_narrows_what_is_compared_between_adapters() -> None:
    """A narrowed comparison is a debt, so the suite has to say how much of it there is.

    One case narrows the comparison, by one body member, because the two adapters refuse
    an undeclared over-limit body at different layers and each reports what its layer
    knows. Everything else in the suite is compared whole. A second narrowed case
    appearing without this test being changed is the thing worth catching.
    """

    narrowed = {
        case.name: case.diverging_body_members
        for scenario in conformance_module.SCENARIOS
        for case in scenario.cases
        if case.diverging_body_members
    }

    assert narrowed == {_STREAMED_BODY_CASE: ("detail",)}


def test_the_streamed_body_case_holds_every_adapter_to_a_document_of_its_own() -> None:
    """Narrowing the comparison is only defensible while each adapter is still pinned.

    The member the two adapters differ on is asserted per adapter rather than left
    unasserted, so the day either sentence changes is a day this case fails.
    """

    case = _case(_STREAMED_BODY_CASE)
    named = dict(case.expected_by_adapter)

    assert set(named) == set(ADAPTER_NAMES)
    details = {adapter: _detail(expected) for adapter, expected in named.items()}
    assert details["starlette"] == "The request body exceeds the 10485760 byte limit"
    assert details["asgi"] == (
        "The request body carries 10485762 bytes, over the 10485760 byte limit"
    )
    # The document no adapter is held to marks the member rather than picking one side.
    assert _detail(case.expected) == UNCOMPARED_BODY_MEMBER


def test_the_narrowed_comparison_still_reports_every_other_part_of_the_answer() -> None:
    """Narrowed to one member means narrowed to one member, not to nothing."""

    case = _case(_STREAMED_BODY_CASE)
    starlette, asgi = (
        conformance_module._reduce_for_comparison(case, dict(case.expected_by_adapter)[name])
        for name in ("starlette", "asgi")
    )

    assert describe_difference("starlette", starlette, "asgi", asgi) == ()

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
