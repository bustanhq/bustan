"""Adapter conformance helpers for governance and release gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, cast

from starlette.testclient import TestClient

from ...app.bootstrap import create_app
from ...common.decorators.controller import Controller
from ...common.decorators.route import Get, Post
from ...core.module.decorators import Module
from .adapter import AdapterCapabilities, AbstractHttpAdapter
from .adapters.starlette_adapter import StarletteAdapter


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class AdapterConformanceResult:
    adapter: str
    capabilities: AdapterCapabilities
    checks: tuple[ConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "passed": self.passed,
            "capabilities": asdict(self.capabilities),
            "checks": tuple(asdict(check) for check in self.checks),
        }


@dataclass(frozen=True, slots=True)
class Payload:
    name: str


def load_adapter(name: str) -> AbstractHttpAdapter:
    if name == "starlette":
        return StarletteAdapter()
    raise ValueError(f"Unsupported adapter {name!r}")


def evaluate_adapter_conformance(adapter: AbstractHttpAdapter) -> AdapterConformanceResult:
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

    application = create_app(AppModule, adapter=adapter)
    with TestClient(cast(Any, application)) as client:
        health_response = client.get("/health")
        payload_response = client.post("/payloads", json={"name": "Ada"})

    checks = (
        ConformanceCheck(
            name="health_route",
            passed=health_response.status_code == 200 and health_response.json() == {"status": "ok"},
            detail=f"status={health_response.status_code}",
        ),
        ConformanceCheck(
            name="body_binding",
            passed=payload_response.status_code == 200 and payload_response.json() == {"name": "Ada"},
            detail=f"status={payload_response.status_code}",
        ),
    )
    return AdapterConformanceResult(
        adapter=adapter.name,
        capabilities=adapter.capabilities,
        checks=checks,
    )


__all__ = (
    "AdapterConformanceResult",
    "ConformanceCheck",
    "evaluate_adapter_conformance",
    "load_adapter",
)