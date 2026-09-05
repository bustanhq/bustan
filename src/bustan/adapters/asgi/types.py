"""The ASGI vocabulary this package is written against.

ASGI defines a connection as three objects - a scope describing it, a callable that
yields the messages arriving on it, and a callable that writes messages back - so these
aliases are the whole of what the transport hands over. The message and scope values are
heterogeneous by specification: a key's type depends on the message type it appears in,
so ``Any`` is the honest declaration here rather than a narrowing that every reader
would have to undo with a cast.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

# One ASGI message: the ``type`` key names it and the rest depends on that name.
Message = MutableMapping[str, Any]

# What the server knows about one connection before the first message arrives.
Scope = MutableMapping[str, Any]

# Awaits the next message the client sent on this connection.
Receive = Callable[[], Awaitable[Message]]

# Writes one message back to the client.
Send = Callable[[Message], Awaitable[None]]

# A whole ASGI application: everything this adapter builds and wraps is one of these.
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]

__all__ = (
    "AsgiApp",
    "Message",
    "Receive",
    "Scope",
    "Send",
)
