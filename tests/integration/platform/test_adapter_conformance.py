"""Integration conformance checks for HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, Get, Module, Post, create_app
from bustan.platform.http.adapter import AdapterCapabilities, AbstractHttpAdapter
from bustan.platform.http.adapters.starlette_adapter import StarletteAdapter


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
    with TestClient(cast(Any, application)) as client:
        health_response = client.get("/health")
        payload_response = client.post("/payloads", json={"name": "Ada"})

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert payload_response.status_code == 200
    assert payload_response.json() == {"name": "Ada"}