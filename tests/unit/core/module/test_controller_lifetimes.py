"""The verdict a controller's declared lifetime gets, from every way of starting up.

Every test here asserts two entry points against each other rather than one in
isolation, because a check that lived on one path is what let a context accept a
declaration a served application refused. A single-path assertion cannot see that.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from bustan import (
    Controller,
    Get,
    Injectable,
    Module,
    Scope,
    create_app,
    create_app_context,
)
from bustan.core.errors import InvalidControllerError
from bustan.core.module.graph import build_module_graph
from bustan.testing import create_testing_module


@Injectable(scope=Scope.REQUEST)
class Identity:
    """A provider built for one request, from that request."""

    def __init__(self, request: Request) -> None:
        self.tenant = request.headers.get("x-tenant-id", "public")


def _verdict(start: Any, root_module: type[object]) -> str:
    """Return what one entry point answers for a module graph, as a comparable string."""

    try:
        start(root_module)
    except Exception as refusal:  # noqa: BLE001 - the verdict under test is the type and message
        return f"{type(refusal).__name__}: {refusal}"
    return "accepted"


def _durable_controller_module() -> type[object]:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"tenant": "acme"}

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    return AppModule


def _context_key_hook_controller_module() -> type[object]:
    @Controller("/tenants")
    class TenantsController:
        @classmethod
        def get_durable_context_key(cls, request: Request | None) -> str:
            return request.headers.get("x-tenant-id", "public") if request is not None else "public"

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"tenant": "acme"}

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    return AppModule


def _durable_controller_holding_request_state_module() -> type[object]:
    @Controller("/tenants", scope=Scope.DURABLE)
    class TenantsController:
        def __init__(self, identity: Identity) -> None:
            self.identity = identity

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"tenant": self.identity.tenant}

    @Module(controllers=[TenantsController], providers=[Identity])
    class AppModule:
        pass

    return AppModule


@pytest.mark.parametrize(
    "build_module",
    [_durable_controller_module, _context_key_hook_controller_module],
    ids=["declares a durable scope", "declares a context key hook"],
)
def test_both_entry_points_refuse_a_lifetime_no_controller_can_have(
    build_module: Any,
) -> None:
    context_verdict = _verdict(create_app_context, build_module())
    application_verdict = _verdict(create_app, build_module())

    assert context_verdict == application_verdict
    assert context_verdict.startswith("InvalidControllerError:")


def test_a_durable_controller_is_refused_for_its_declaration_on_both_entry_points() -> None:
    # The refusal an author reads has to name the decorator, because the constructor
    # parameter it used to name is one line below the defect and no edit to it helps.
    build_module = _durable_controller_holding_request_state_module
    context_verdict = _verdict(create_app_context, build_module())
    application_verdict = _verdict(create_app, build_module())

    assert context_verdict == application_verdict
    assert "declares scope 'durable', which a controller cannot have" in context_verdict
    assert "parameter 'identity'" not in context_verdict


@pytest.mark.parametrize("scope", [Scope.SINGLETON, Scope.REQUEST, Scope.TRANSIENT])
def test_both_entry_points_accept_every_lifetime_a_controller_can_have(scope: Scope) -> None:
    @Controller("/tenants", scope=scope)
    class TenantsController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"tenant": "acme"}

    @Module(controllers=[TenantsController])
    class AppModule:
        pass

    assert _verdict(create_app_context, AppModule) == "accepted"
    assert _verdict(create_app, AppModule) == "accepted"


@pytest.mark.parametrize(
    "build_module",
    [_durable_controller_module, _context_key_hook_controller_module],
    ids=["declares a durable scope", "declares a context key hook"],
)
def test_the_module_graph_is_where_the_refusal_happens(build_module: Any) -> None:
    # Both entry points build the graph before anything else, so a graph that refuses
    # is what makes them agree; a check on either path alone would not.
    with pytest.raises(InvalidControllerError):
        build_module_graph(build_module())


@pytest.mark.anyio
async def test_a_testing_module_refuses_the_same_graph_with_the_same_message() -> None:
    graph_verdict = _verdict(build_module_graph, _durable_controller_module())

    with pytest.raises(InvalidControllerError) as refusal:
        await create_testing_module(_durable_controller_module()).compile()

    assert f"InvalidControllerError: {refusal.value}" == graph_verdict
