"""Integration tests for global pipeline provider tokens."""

from __future__ import annotations

from typing import Any, cast

from starlette.testclient import TestClient

from bustan import APP_GUARD, Controller, Get, Guard, Module, create_app
from bustan.pipeline.context import RequestContext


class RejectAllGuard(Guard):
    async def can_activate(self, context: RequestContext) -> bool:
        return False


def test_app_guard_provider_applies_to_all_routes() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_class": RejectAllGuard}],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users")

    assert response.status_code == 403
