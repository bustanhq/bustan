"""Unit tests for structured error payload helpers and the bodies callers receive."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest

from bustan import Controller, Get, Module, create_app
from bustan.common.types import RouteMetadata
from bustan.contracts import HttpResponse
from bustan.kernel.errors import (
    BadGatewayException,
    BadRequestException,
    HttpException,
    NotFoundException,
    ParameterBindingError,
)
from bustan.kernel.module.dynamic import ModuleInstanceKey
from bustan.pipeline.context import RequestContext
from bustan.pipeline.filters import handle_exception
from bustan.runtime.metadata import ControllerRouteDefinition
from bustan.security import AUTHENTICATOR_REGISTRY, Auth, Permissions, Roles
from bustan.testing import AsgiTestClient
from tests.unit.kernel.test_errors import STATUS_CONTRACT

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory

# The vocabulary the application uses internally, chosen so that a leak of any of it
# into a response body is unmistakable rather than a substring of something ordinary.
_STRATEGY = "acme-hmac-v2"
_ROLE = "warehouse-supervisor"
_PERMISSION = "invoices:void"


def test_parameter_binding_error_to_payload_includes_optional_fields_when_present() -> None:
    error = ParameterBindingError(
        "invalid binding",
        field="user_id",
        source="path",
        reason="integer expected",
    )

    assert error.to_payload() == {
        "detail": "invalid binding",
        "field": "user_id",
        "source": "path",
        "reason": "integer expected",
    }


def test_bad_request_exception_to_payload_omits_missing_optional_fields() -> None:
    error = BadRequestException("invalid request")

    assert error.to_payload() == {"detail": "invalid request"}


@pytest.mark.anyio
@pytest.mark.parametrize(("exception_type", "status", "problem_type", "code"), STATUS_CONTRACT)
async def test_each_status_is_answered_with_its_own_status_type_and_code(
    build_http_request: HttpRequestFactory,
    exception_type: type[HttpException],
    status: int,
    problem_type: str,
    code: str,
) -> None:
    result = await handle_exception(
        _context(build_http_request, "/orders/17"),
        exception_type("Raised by the application"),
        (),
    )

    assert isinstance(result, HttpResponse)
    assert result.status_code == status
    assert result.media_type == "application/problem+json"
    payload = json.loads(result.body)
    assert payload["status"] == status
    assert payload["type"] == problem_type
    assert payload["code"] == code
    assert payload["instance"] == "/orders/17"


@pytest.mark.anyio
async def test_a_status_the_application_chose_carries_the_message_it_wrote(
    build_http_request: HttpRequestFactory,
) -> None:
    result = await handle_exception(
        _context(build_http_request, "/orders/17"),
        NotFoundException("No order with that number"),
        (),
    )

    assert isinstance(result, HttpResponse)
    assert json.loads(result.body)["detail"] == "No order with that number"


@pytest.mark.anyio
async def test_a_server_fault_message_is_kept_out_of_the_body_whoever_raised_it(
    build_http_request: HttpRequestFactory,
) -> None:
    # A 5xx names the thing that broke, and what broke is never the caller's business.
    result = await handle_exception(
        _context(build_http_request, "/orders/17"),
        BadGatewayException("ledger-service returned 500 for tenant 41"),
        (),
    )

    assert isinstance(result, HttpResponse)
    assert result.status_code == 502
    assert "ledger-service" not in result.body.decode("utf-8")
    assert json.loads(result.body)["detail"] == "Internal server error"


def test_a_caller_without_credentials_is_told_to_authenticate_and_nothing_else() -> None:
    with AsgiTestClient(cast(Any, create_app(_secured_module(None)))) as client:
        response = client.get("/invoices/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    _assert_names_nothing_internal(response.text)
    assert response.json()["code"] == "unauthorized"


def test_a_caller_holding_an_identity_that_is_not_enough_learns_nothing_more() -> None:
    # The principal authenticates and then fails both the role and the permission the
    # route requires, which is the path whose message used to enumerate what it lacked.
    identified = _PrincipalStub(id="user-1", roles=("clerk",), permissions=("invoices:read",))

    with AsgiTestClient(cast(Any, create_app(_secured_module(identified)))) as client:
        response = client.get("/invoices/")

    assert response.status_code == 403
    assert "www-authenticate" not in response.headers
    _assert_names_nothing_internal(response.text)
    assert response.json()["code"] == "forbidden"


def _assert_names_nothing_internal(body: str) -> None:
    """Assert a refusal body names no role, permission or strategy of the application."""

    for internal_name in (_ROLE, _PERMISSION, _STRATEGY):
        assert internal_name not in body
    for fragment in ("Policy denied", "missing roles", "missing permissions", "PolicyGuard"):
        assert fragment not in body
    # No dotted path into the framework or the application either: a caller that learns
    # which module refused it learns the layout of a process it cannot reach.
    assert "bustan.pipeline" not in body
    assert "bustan.security" not in body


@dataclass(frozen=True, slots=True)
class _PrincipalStub:
    id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()


class _AuthenticatorStub:
    def __init__(self, principal: _PrincipalStub | None) -> None:
        self._principal = principal

    async def authenticate(self, context: object) -> _PrincipalStub | None:
        return self._principal


def _secured_module(principal: _PrincipalStub | None) -> type[object]:
    """Build a module whose one route requires an identity, a role and a permission."""

    @Auth(_STRATEGY)
    @Roles(_ROLE)
    @Permissions(_PERMISSION)
    @Controller("/invoices")
    class InvoicesController:
        @Get("/")
        def void_invoice(self) -> dict[str, str]:
            return {"status": "never reached"}

    @Module(
        controllers=[InvoicesController],
        providers=[
            {
                "provide": AUTHENTICATOR_REGISTRY,
                "use_value": {_STRATEGY: _AuthenticatorStub(principal)},
            }
        ],
    )
    class SecuredModule:
        pass

    return SecuredModule


def _context(build_http_request: HttpRequestFactory, path: str) -> RequestContext:
    """Build the execution context a filter reads the request path out of."""

    return RequestContext(
        request=build_http_request(path=path),
        module=ModuleInstanceKey(module=object, instance_id="test"),
        controller_type=object,
        controller=object(),
        route=ControllerRouteDefinition(
            handler_name="test",
            handler=_handler,
            route=RouteMetadata(method="GET", path=path, name="test"),
        ),
        container=cast(Any, object()),
    )


def _handler() -> None:
    return None
