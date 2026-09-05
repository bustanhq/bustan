"""Guard base class and execution helpers."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable
from typing import Any, cast
from uuid import uuid4

from ..core.errors import GuardRejectedError, ProviderResolutionError
from ..core.utils import _qualname
from .auth import AUTHENTICATOR_REGISTRY, Principal
from .context import ExecutionContext

_LOGGER = logging.getLogger(__name__)

# The attribute a request keeps its correlation identifier on. The public helper that
# mints and reads it belongs to a package this one may not import, so the reserved name
# is restated here; both ends must name the same slot or a log line cannot be joined to
# the request it describes.
_REQUEST_CONTEXT_ID_ATTR = "bustan_request_context_id"


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
                raise _rejected(context, "Authentication required")
            request = context.request
            if request is None:
                raise _rejected(context, "Authentication required")
            request.state.principal = principal

        if getattr(policy_plan, "roles", ()):
            if principal is None:
                raise _rejected(context, "Authentication required")
            missing_roles = [
                role for role in policy_plan.roles if role not in getattr(principal, "roles", ())
            ]
            if missing_roles:
                raise _rejected(context, f"Policy denied: missing roles {tuple(missing_roles)}")

        if getattr(policy_plan, "permissions", ()):
            if principal is None:
                raise _rejected(context, "Authentication required")
            missing_permissions = [
                permission
                for permission in policy_plan.permissions
                if permission not in getattr(principal, "permissions", ())
            ]
            if missing_permissions:
                raise _rejected(
                    context, f"Policy denied: missing permissions {tuple(missing_permissions)}"
                )

        return True

    async def _authenticate(self, context: ExecutionContext, strategy: str) -> Principal | None:
        try:
            registry = context.container.resolve(
                AUTHENTICATOR_REGISTRY,
                module=context.module,
                request=context.request,
            )
        except ProviderResolutionError as exc:
            raise _rejected(
                context, f"Unknown authenticator registry for strategy {strategy!r}"
            ) from exc

        authenticator = getattr(registry, "get", lambda _key, _default=None: None)(strategy, None)
        if authenticator is None:
            raise _rejected(context, f"Unknown authenticator {strategy!r}")

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
            raise _rejected(context, f"Guard {_qualname(type(guard))} blocked the request")


def _rejected(context: ExecutionContext, reason: str) -> GuardRejectedError:
    """Record why a request is being refused and return the error that refuses it.

    A refused caller is told only that it was refused, because the reason names the
    guard's dotted class path, the authentication strategy the route expects, or the
    roles and permissions it lacks, and the caller that has just been refused is the one
    party that must not be handed them. This log line is therefore the only place the
    reason is written down, and it carries the request's correlation identifier so an
    operator can tell which guard refused which request.
    """

    _LOGGER.warning("Request rejected [correlation_id=%s]: %s", _correlation_id(context), reason)
    return GuardRejectedError(reason)


def _correlation_id(context: ExecutionContext) -> str:
    """Return the identifier that joins a log line to the request that produced it."""

    request = context.request
    if request is None:
        return "none"

    stored = getattr(request.state, _REQUEST_CONTEXT_ID_ATTR, None)
    if isinstance(stored, str):
        return stored

    # A rejection can be the first thing in a request to need the identifier. Minting it
    # into the slot the public helper reads, rather than into one of this module's own,
    # keeps a request to a single identifier: what an operator reads here is what the
    # application sees for the same request.
    minted = uuid4().hex
    setattr(request.state, _REQUEST_CONTEXT_ID_ATTR, minted)
    return minted


def _has_policy_requirements(policy_plan: object) -> bool:
    return any(
        (
            getattr(policy_plan, "auth", None) is not None,
            getattr(policy_plan, "public", False),
            bool(getattr(policy_plan, "roles", ())),
            bool(getattr(policy_plan, "permissions", ())),
        )
    )
