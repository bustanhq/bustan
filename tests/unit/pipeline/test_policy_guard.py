"""Unit tests for the default compiled policy guard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, UseGuards, create_app, request_context_id
from bustan.kernel.errors import (
    AuthenticationRequiredError,
    AuthenticatorRegistryError,
    GuardRejectedError,
    InvalidPipelineError,
    ProviderResolutionError,
)
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.pipeline.guards import Guard, PolicyGuard, run_guards
from bustan.pipeline.metadata import AuthPolicy
from bustan.runtime.compiler import PolicyPlan
from bustan.runtime.controller_factory import ControllerFactory
from bustan.security import AUTHENTICATOR_REGISTRY, Auth, Public

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


@dataclass(frozen=True, slots=True)
class PrincipalStub:
    id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()


class AuthenticatorStub:
    def __init__(self, principal: PrincipalStub | None) -> None:
        self.principal = principal

    async def authenticate(self, context) -> PrincipalStub | None:
        return self.principal


class ContainerStub:
    def __init__(
        self,
        registry: dict[str, AuthenticatorStub] | None = None,
        *,
        should_raise: bool = False,
    ) -> None:
        self.registry = registry or {}
        self.should_raise = should_raise

    def resolve(self, token, *, module, request=None):
        assert token is AUTHENTICATOR_REGISTRY
        if self.should_raise:
            raise ProviderResolutionError("registry missing")
        return self.registry


def _context(
    *,
    policy_plan: PolicyPlan,
    registry: dict[str, AuthenticatorStub] | None = None,
    should_raise: bool = False,
):
    request = SimpleNamespace(state=SimpleNamespace(), native_request=None)
    return SimpleNamespace(
        container=ContainerStub(registry, should_raise=should_raise),
        module=object(),
        request=request,
        get_policy_plan=lambda: policy_plan,
        get_principal=lambda: getattr(request.state, "principal", None),
    )


@pytest.mark.anyio
async def test_policy_guard_consumes_compiled_plans_only() -> None:
    context = _context(policy_plan=PolicyPlan())

    assert await PolicyGuard().can_activate(context) is True


@pytest.mark.anyio
async def test_policy_guard_binds_authenticated_principal_to_request_state() -> None:
    principal = PrincipalStub(id="user-1", roles=("admin",), permissions=("users:read",))
    context = _context(
        policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt"), roles=("admin",)),
        registry={"jwt": AuthenticatorStub(principal)},
    )

    assert await PolicyGuard().can_activate(context) is True
    assert context.request.state.principal is principal


@pytest.mark.anyio
async def test_policy_guard_raises_deterministic_errors_for_denied_roles() -> None:
    principal = PrincipalStub(id="user-1", roles=("user",), permissions=("users:read",))
    context = _context(
        policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt"), roles=("admin",)),
        registry={"jwt": AuthenticatorStub(principal)},
    )

    with pytest.raises(GuardRejectedError, match="missing roles"):
        await PolicyGuard().can_activate(context)


@pytest.mark.anyio
async def test_policy_guard_allows_public_routes_and_rejects_missing_authentication() -> None:
    assert await PolicyGuard().can_activate(_context(policy_plan=PolicyPlan(public=True))) is True

    # The refusal is the one it always was, and is still a guard rejection. Its own class
    # is what lets the answer say the caller lacks an identity rather than a permission.
    with pytest.raises(AuthenticationRequiredError, match="Authentication required"):
        await PolicyGuard().can_activate(
            _context(
                policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt")),
                registry={"jwt": AuthenticatorStub(None)},
            )
        )


@pytest.mark.anyio
async def test_a_route_missing_its_roles_is_refused_as_a_caller_that_is_merely_unpermitted() -> (
    None
):
    principal = PrincipalStub(id="user-1", roles=("user",))
    context = _context(
        policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt"), roles=("admin",)),
        registry={"jwt": AuthenticatorStub(principal)},
    )

    with pytest.raises(GuardRejectedError) as rejection:
        await PolicyGuard().can_activate(context)

    assert not isinstance(rejection.value, AuthenticationRequiredError)


@pytest.mark.anyio
async def test_policy_guard_reports_missing_registry_authenticator_and_permissions() -> None:
    # Unusable wiring is not a caller being refused, so it is not reported as one: every
    # caller of the route would meet it, however good the credentials it sent.
    with pytest.raises(AuthenticatorRegistryError, match="Unknown authenticator registry"):
        await PolicyGuard().can_activate(
            _context(
                policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt")),
                should_raise=True,
            )
        )

    with pytest.raises(AuthenticatorRegistryError, match="Unknown authenticator 'jwt'"):
        await PolicyGuard().can_activate(
            _context(policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt")))
        )

    principal = PrincipalStub(id="user-1", roles=("admin",), permissions=("users:read",))
    with pytest.raises(GuardRejectedError, match="missing permissions"):
        await PolicyGuard().can_activate(
            _context(
                policy_plan=PolicyPlan(
                    auth=AuthPolicy(strategy="jwt"),
                    permissions=("users:write",),
                ),
                registry={"jwt": AuthenticatorStub(principal)},
            )
        )


@pytest.mark.anyio
async def test_run_guards_supports_async_and_sync_guards_and_rejections() -> None:
    events: list[str] = []

    class AsyncAllowGuard(Guard):
        async def can_activate(self, context) -> bool:
            events.append("async")
            return True

    class SyncBlockGuard(Guard):
        def can_activate(self, context) -> bool:
            events.append("sync")
            return False

    context = _context(policy_plan=PolicyPlan())

    with pytest.raises(GuardRejectedError, match="SyncBlockGuard"):
        await run_guards(context, (AsyncAllowGuard(), SyncBlockGuard()))

    assert events == ["async", "sync"]


@pytest.mark.anyio
async def test_a_blocking_guard_is_named_in_the_log_under_the_request_correlation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class DenyGuard(Guard):
        def can_activate(self, context) -> bool:
            return False

    context = _context(policy_plan=PolicyPlan())

    with (
        caplog.at_level(logging.WARNING, logger="bustan.pipeline.guards"),
        pytest.raises(GuardRejectedError),
    ):
        await run_guards(context, (DenyGuard(),))

    (record,) = caplog.records
    message = record.getMessage()
    assert f"{DenyGuard.__module__}.{DenyGuard.__qualname__}" in message
    assert request_context_id(cast(Any, context.request)).value in message


@pytest.mark.anyio
async def test_an_unresolvable_strategy_is_named_in_the_log_under_the_same_identifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _context(
        policy_plan=PolicyPlan(auth=AuthPolicy(strategy="acme-hmac-v2")),
        should_raise=True,
    )

    with (
        caplog.at_level(logging.WARNING, logger="bustan.pipeline.guards"),
        pytest.raises(AuthenticatorRegistryError),
    ):
        await PolicyGuard().can_activate(context)

    (record,) = caplog.records
    message = record.getMessage()
    assert "acme-hmac-v2" in message
    assert request_context_id(cast(Any, context.request)).value in message


def test_undecorated_subclass_of_an_injectable_guard_is_constructed_and_serves_the_request() -> (
    None
):
    @Injectable()
    class BaseGuard(Guard):
        def can_activate(self, context) -> bool:
            return True

    class StrictGuard(BaseGuard):
        pass

    @Controller("/reports")
    class ReportsController:
        @Get("/")
        @UseGuards(StrictGuard)
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/reports/")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_a_decorated_guard_is_still_resolved_through_the_container(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable()
    class DependencyService:
        pass

    @Injectable()
    class DecoratedGuard(Guard):
        def __init__(self, dependency: DependencyService) -> None:
            self.dependency = dependency

        def can_activate(self, context) -> bool:
            return True

    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[ReportsController], providers=[DecoratedGuard, DependencyService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)
    request = build_http_request(path="/reports")

    (resolved,) = factory.resolve_components(
        (DecoratedGuard,), Guard, module=AppModule, request=request, kind="guard"
    )

    assert resolved is container.resolve(DecoratedGuard, module=AppModule, request=request)


def test_an_undeclared_guard_that_needs_arguments_is_still_refused(
    build_http_request: HttpRequestFactory,
) -> None:
    class NeedsArgumentsGuard(Guard):
        def __init__(self, dependency: object) -> None:
            self.dependency = dependency

        def can_activate(self, context) -> bool:
            return True

    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    factory = ControllerFactory(container)

    with pytest.raises(InvalidPipelineError):
        factory.resolve_components(
            (NeedsArgumentsGuard,),
            Guard,
            module=AppModule,
            request=build_http_request(path="/reports"),
            kind="guard",
        )


def test_an_auth_route_without_a_visible_registry_is_refused_while_the_app_is_built() -> None:
    # The mistake is in the wiring rather than in any request, so it is answered where
    # it was made. Left to the request, every caller of this route meets a refusal it
    # cannot tell from the one a wrong credential earns.
    @Auth("jwt")
    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with pytest.raises(AuthenticatorRegistryError) as refusal:
        create_app(AppModule)

    assert "AUTHENTICATOR_REGISTRY" in str(refusal.value)
    assert "ReportsController.read_report" in str(refusal.value)
    # Distinct from an authentication failure, which is the whole point of raising it.
    assert not isinstance(refusal.value, GuardRejectedError)


def test_a_registry_only_an_async_factory_can_build_is_refused_the_same_way() -> None:
    # The guard resolves the registry in the middle of a request and cannot await it, so
    # a registry behind an async factory authenticates nobody however well it is written.
    async def build_registry() -> dict[str, AuthenticatorStub]:
        return {"jwt": AuthenticatorStub(PrincipalStub(id="user-1"))}

    @Auth("jwt")
    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(
        controllers=[ReportsController],
        providers=[{"provide": AUTHENTICATOR_REGISTRY, "use_factory": build_registry}],
    )
    class AppModule:
        pass

    with pytest.raises(AuthenticatorRegistryError, match="async factory"):
        create_app(AppModule)


def test_a_public_route_carrying_an_auth_policy_needs_no_registry_to_build() -> None:
    # A public route never reaches the registry, so requiring one of it would refuse an
    # application that is correct.
    @Auth("jwt")
    @Controller("/reports")
    class ReportsController:
        @Public()
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/reports/")

    assert response.status_code == 200


def test_a_route_whose_module_imports_the_registry_builds_and_serves() -> None:
    @Auth("jwt")
    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def read_report(self) -> dict[str, bool]:
            return {"ok": True}

    @Module(
        providers=[
            {
                "provide": AUTHENTICATOR_REGISTRY,
                "use_value": {"jwt": AuthenticatorStub(PrincipalStub(id="user-1"))},
            }
        ],
        exports=[AUTHENTICATOR_REGISTRY],
    )
    class SecurityModule:
        pass

    @Module(controllers=[ReportsController], imports=[SecurityModule])
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/reports/")

    assert response.status_code == 200
