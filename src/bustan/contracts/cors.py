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
    """Which origins may read this application's responses, and on what terms.

    A policy names the origins it permits. Built with no arguments it names none, and
    the wildcard that permits every origin has to be written out as ``origins=["*"]``
    rather than arrived at by leaving a field alone, because an origin set nobody chose
    is one nobody reviewed.

    Every field's default:

    - ``origins``: no origins. One origin as a bare string, or a list of them. ``"*"``
      is every origin on the internet, which a browser refuses to combine with
      credentials.
    - ``methods``: ``GET``, ``HEAD``, ``PUT``, ``PATCH``, ``POST``, ``DELETE``. A list
      holding ``"*"`` is every method the protocol defines.
    - ``allowed_headers``: ``["*"]``, so a preflight is answered with whatever headers
      it asked to send. Naming headers instead allows those and the ones a browser may
      send without asking, and refuses the rest.
    - ``exposed_headers``: none, so a browser reads only the few response headers the
      protocol exposes without being told to.
    - ``credentials``: ``False``, so a browser attaches no cookie and no
      ``Authorization`` header to a cross-origin request.
    - ``max_age``: ``600`` seconds, how long a browser may reuse one preflight answer
      before asking again.
    """

    origins: str | list[str] = field(default_factory=list)
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
    would eventually forget and iterate a string one character at a time. An empty list
    back means the policy permits no origin at all.
    """

    if isinstance(options.origins, str):
        return [options.origins]
    return list(options.origins)


__all__ = (
    "CorsOptions",
    "allowed_origins",
)
