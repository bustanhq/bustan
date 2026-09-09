"""The cross-origin policy an application hands its transport to enforce.

CORS is enforced in front of the routes rather than inside them: every request the
transport carries is measured against one policy, and the framework never sees the
preflight requests that policy answers. The policy therefore has to cross the adapter
port, which is why the value type declaring it lives here rather than beside the rest of
the security helpers - a transport adapter may read the contracts and nothing above
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CorsOptions:
    """Configuration for application-level CORS support."""

    origins: str | list[str] = "*"
    methods: list[str] = field(
        default_factory=lambda: ["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"]
    )
    allowed_headers: list[str] = field(default_factory=lambda: ["*"])
    exposed_headers: list[str] = field(default_factory=list)
    credentials: bool = False
    max_age: int = 600


def allowed_origins(options: CorsOptions) -> list[str]:
    """Return the origins *options* allows, as a list however it happened to name them.

    A single origin may be written as the bare string it is, so every adapter would
    otherwise repeat the same widening before it could read the field, and one of them
    would eventually forget and iterate a string one character at a time.
    """

    if isinstance(options.origins, str):
        return [options.origins]
    return list(options.origins)


__all__ = (
    "CorsOptions",
    "allowed_origins",
)
