"""A middleware runs inside the request it is serving, on both sides of ``call_next``."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import (
    Controller,
    DiscoveryModule,
    Get,
    Injectable,
    Middleware,
    Module,
    ModuleRef,
    Scope,
    create_app,
)
from bustan.pipeline.middleware import MiddlewareConsumer


@Injectable(scope=Scope.REQUEST)
class RequestSerial:
    """A request-scoped provider that can say which construction produced it."""

    constructed = 0

    def __init__(self) -> None:
        RequestSerial.constructed += 1
        self.serial = RequestSerial.constructed


@Injectable(scope=Scope.REQUEST)
class ScopeProbeMiddleware(Middleware):
    def __init__(self, module_ref: ModuleRef) -> None:
        self._module_ref = module_ref

    async def use(self, request, call_next):
        before = cast(RequestSerial, self._module_ref.get(RequestSerial))
        response = await call_next(request)
        after = cast(RequestSerial, self._module_ref.get(RequestSerial))
        response.headers["x-serial-before"] = str(before.serial)
        response.headers["x-serial-after"] = str(after.serial)
        return response


def test_a_middleware_resolving_after_call_next_gets_the_instance_the_handler_got() -> None:
    RequestSerial.constructed = 0

    @Controller("/probe", scope=Scope.REQUEST)
    class ProbeController:
        def __init__(self, request_serial: RequestSerial) -> None:
            self.request_serial = request_serial

        @Get("/")
        def index(self) -> dict[str, int]:
            return {"serial": self.request_serial.serial}

    @Module(
        imports=[DiscoveryModule],
        controllers=[ProbeController],
        providers=[RequestSerial, ScopeProbeMiddleware],
        exports=[RequestSerial],
    )
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(ScopeProbeMiddleware).for_routes("/probe*")

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/probe")

    handler_serial = response.json()["serial"]

    assert response.status_code == 200
    assert response.headers["x-serial-before"] == str(handler_serial)
    assert response.headers["x-serial-after"] == str(handler_serial)
    assert RequestSerial.constructed == 1


def test_a_second_request_gets_its_own_request_scoped_instance() -> None:
    RequestSerial.constructed = 0

    @Controller("/probe", scope=Scope.REQUEST)
    class ProbeController:
        def __init__(self, request_serial: RequestSerial) -> None:
            self.request_serial = request_serial

        @Get("/")
        def index(self) -> dict[str, int]:
            return {"serial": self.request_serial.serial}

    @Module(
        imports=[DiscoveryModule],
        controllers=[ProbeController],
        providers=[RequestSerial, ScopeProbeMiddleware],
        exports=[RequestSerial],
    )
    class AppModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(ScopeProbeMiddleware).for_routes("/probe*")

    with TestClient(cast(Any, create_app(AppModule))) as client:
        first = client.get("/probe")
        second = client.get("/probe")

    assert first.json()["serial"] != second.json()["serial"]
    assert first.headers["x-serial-after"] == str(first.json()["serial"])
    assert second.headers["x-serial-after"] == str(second.json()["serial"])
