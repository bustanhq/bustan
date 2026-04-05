"""Guard base class and execution helpers."""

from __future__ import annotations

import inspect

from ..errors import GuardRejectedError
from .context import RequestContext


class Guard:
    """Base class for authorization and policy gates."""

    async def can_activate(self, context: RequestContext) -> bool:
        """Return True to allow request execution to continue."""

        return True


async def run_guards(context: RequestContext, guards: tuple[Guard, ...]) -> None:
    """Execute guards in declaration order until one rejects the request."""

    for guard in guards:
        result = guard.can_activate(context)
        if inspect.isawaitable(result):
            result = await result

        if not bool(result):
            raise GuardRejectedError(f"Guard {_qualname(type(guard))} blocked the request")


def _qualname(target: object) -> str:
    if isinstance(target, type):
        return f"{target.__module__}.{target.__qualname__}"
    return repr(target)