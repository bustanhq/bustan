"""Unit tests for the default compiled policy guard."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bustan.core.errors import GuardRejectedError, ProviderResolutionError
from bustan.pipeline.guards import Guard, PolicyGuard, run_guards
from bustan.platform.http.compiler import PolicyPlan
from bustan.pipeline.metadata import AuthPolicy
from bustan.security import AUTHENTICATOR_REGISTRY


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

    with pytest.raises(GuardRejectedError, match="Authentication required"):
        await PolicyGuard().can_activate(
            _context(
                policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt")),
                registry={"jwt": AuthenticatorStub(None)},
            )
        )


@pytest.mark.anyio
async def test_policy_guard_reports_missing_registry_authenticator_and_permissions() -> None:
    with pytest.raises(GuardRejectedError, match="Unknown authenticator registry"):
        await PolicyGuard().can_activate(
            _context(
                policy_plan=PolicyPlan(auth=AuthPolicy(strategy="jwt")),
                should_raise=True,
            )
        )

    with pytest.raises(GuardRejectedError, match="Unknown authenticator 'jwt'"):
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