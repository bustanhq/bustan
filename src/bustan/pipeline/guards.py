"""Guard base class and execution helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Any, cast

from ..core.errors import GuardRejectedError, ProviderResolutionError
from .auth import AUTHENTICATOR_REGISTRY, Principal
from .context import ExecutionContext
from ..core.utils import _qualname


class Guard:
    """Base class for authorization and policy gates."""

    def can_activate(self, context: ExecutionContext) -> bool | Awaitable[bool]:
        """Return True to allow request execution to continue."""

        return True


class PolicyGuard(Guard):
    """Default guard that executes compiled route policy plans."""

    async def can_activate(self, context: ExecutionContext) -> bool:
        raw_policy_plan = context.get_policy_plan()
        if raw_policy_plan is None or not _has_policy_requirements(raw_policy_plan):
            return True
        policy_plan = cast(Any, raw_policy_plan)

        if getattr(policy_plan, "public", False):
            return True

        principal = context.get_principal()
        auth_policy = getattr(policy_plan, "auth", None)
        if auth_policy is not None:
            principal = await self._authenticate(context, auth_policy.strategy)
            if principal is None:
                raise GuardRejectedError("Authentication required")
            request = context.request
            if request is None:
                raise GuardRejectedError("Authentication required")
            setattr(request.state, "principal", principal)

        if getattr(policy_plan, "roles", ()):
            if principal is None:
                raise GuardRejectedError("Authentication required")
            missing_roles = [
                role
                for role in policy_plan.roles
                if role not in getattr(principal, "roles", ())
            ]
            if missing_roles:
                raise GuardRejectedError(
                    f"Policy denied: missing roles {tuple(missing_roles)}"
                )

        if getattr(policy_plan, "permissions", ()):
            if principal is None:
                raise GuardRejectedError("Authentication required")
            missing_permissions = [
                permission
                for permission in policy_plan.permissions
                if permission not in getattr(principal, "permissions", ())
            ]
            if missing_permissions:
                raise GuardRejectedError(
                    f"Policy denied: missing permissions {tuple(missing_permissions)}"
                )

        return True

    async def _authenticate(self, context: ExecutionContext, strategy: str) -> Principal | None:
        request = getattr(context.request, "native_request", None)
        try:
            registry = context.container.resolve(
                AUTHENTICATOR_REGISTRY,
                module=context.module,
                request=request if request is not None else None,
            )
        except ProviderResolutionError as exc:
            raise GuardRejectedError(f"Unknown authenticator registry for strategy {strategy!r}") from exc

        authenticator = getattr(registry, "get", lambda _key, _default=None: None)(strategy, None)
        if authenticator is None:
            raise GuardRejectedError(f"Unknown authenticator {strategy!r}")

        result = authenticator.authenticate(context)
        if inspect.isawaitable(result):
            return await result
        return result


async def run_guards(context: ExecutionContext, guards: tuple[Guard, ...]) -> None:
    """Execute guards in declaration order until one rejects the request."""

    for guard in guards:
        result = guard.can_activate(context)
        if inspect.isawaitable(result):
            result = await result

        if not bool(result):
            raise GuardRejectedError(f"Guard {_qualname(type(guard))} blocked the request")


def _has_policy_requirements(policy_plan: object) -> bool:
    return any(
        (
            getattr(policy_plan, "auth", None) is not None,
            getattr(policy_plan, "public", False),
            bool(getattr(policy_plan, "roles", ())),
            bool(getattr(policy_plan, "permissions", ())),
        )
    )
