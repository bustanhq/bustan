"""Path templates, the routes built from them, and the router that matches them.

Route paths are written once and served by whichever adapter an application chose, so
the template syntax here is the one the framework's routes are already written in:
``{name}`` captures one path segment and ``{name:converter}`` narrows what that segment
may contain. A converter constrains matching only; the captured value is handed on as
text, because coercing it to the type a handler declared is the framework's work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ...contracts import AdapterRoute, RouteHandler

# What each converter allows one captured parameter to contain. ``path`` is the only one
# that may span a ``/``, which is what lets a route capture a whole trailing path.
CONVERTERS: dict[str, str] = {
    "str": r"[^/]+",
    "int": r"[0-9]+",
    "float": r"[0-9]+(?:\.[0-9]+)?",
    "uuid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "path": r".*",
}

_PARAMETER = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?}")


def compile_path(path: str) -> re.Pattern[str]:
    """Compile one path template into the expression that matches a request path.

    Everything outside a ``{...}`` parameter is matched literally, so a path containing
    a character that means something to a regular expression still matches only itself.
    """

    pattern = ""
    position = 0
    for parameter in _PARAMETER.finditer(path):
        name, converter = parameter.group(1), parameter.group(2) or "str"
        if converter not in CONVERTERS:
            raise ValueError(
                f"Unknown path converter {converter!r} in {path!r}; "
                f"expected one of {', '.join(sorted(CONVERTERS))}"
            )
        pattern += re.escape(path[position : parameter.start()])
        pattern += f"(?P<{name}>{CONVERTERS[converter]})"
        position = parameter.end()
    unparsed = path[position:]
    if "{" in unparsed or "}" in unparsed:
        raise ValueError(f"Malformed path parameter in {path!r}")
    return re.compile(f"^{pattern}{re.escape(unparsed)}$")


class AsgiRoute:
    """One route this adapter serves, with the pattern that recognises its path.

    Attributes the framework named on the route plan are set on the instance, so tooling
    that reads a running server's routes back finds what compiled each one. That is why
    this is an ordinary object rather than a closed value type: the set of attributes is
    the framework's to choose, not this adapter's.
    """

    def __init__(
        self,
        path: str,
        methods: Iterable[str],
        handler: RouteHandler,
        name: str | None = None,
    ) -> None:
        self.path = path
        self.handler = handler
        self.name = name
        self.pattern = compile_path(path)
        declared = {method.upper() for method in methods}
        # A server answers HEAD wherever it answers GET, so the router matches it here
        # and the response writer is what drops the body.
        if "GET" in declared:
            declared.add("HEAD")
        self.methods = frozenset(declared)

    def match(self, path: str) -> dict[str, str] | None:
        """Return the parameters *path* captures, or ``None`` when it does not match."""

        matched = self.pattern.match(path)
        return None if matched is None else matched.groupdict()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(path={self.path!r}, name={self.name!r})"


@dataclass(frozen=True, slots=True)
class Matched:
    """A route answers this path and this method."""

    route: AsgiRoute
    path_params: dict[str, str]


@dataclass(frozen=True, slots=True)
class MethodMismatch:
    """A route answers this path, but not this method."""

    allowed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Redirect:
    """No route answers this path, but one answers it with the trailing slash fixed."""

    path: str


@dataclass(frozen=True, slots=True)
class Unmatched:
    """No route answers this path in any form."""


# What asking the router about one request can conclude.
Resolution = Matched | MethodMismatch | Redirect | Unmatched


class AsgiRouter:
    """The routes registered on one application, matched in registration order."""

    def __init__(self) -> None:
        self.routes: list[AsgiRoute] = []

    def add(self, routes: Iterable[AsgiRoute]) -> None:
        """Append routes, which are matched after every route already registered."""

        self.routes.extend(routes)

    def resolve(self, path: str, method: str) -> Resolution:
        """Decide which route, if any, serves one request.

        A path that matches no route is tried once more with its trailing slash added or
        removed, because a route written one way and a client that asked the other way
        are the same request; the caller redirects rather than guessing on the client's
        behalf.
        """

        allowed: set[str] = set()
        for route in self.routes:
            path_params = route.match(path)
            if path_params is None:
                continue
            if method in route.methods:
                return Matched(route, path_params)
            allowed |= route.methods
        if allowed:
            return MethodMismatch(tuple(sorted(allowed)))
        alternate = path.removesuffix("/") if path.endswith("/") else f"{path}/"
        if alternate and any(route.match(alternate) is not None for route in self.routes):
            return Redirect(alternate)
        return Unmatched()


def build_asgi_routes(routes: Sequence[AdapterRoute]) -> list[AsgiRoute]:
    """Turn neutral adapter routes into the routes this adapter serves.

    Every route must carry a handler. A plan may instead carry a registration another
    transport already built, and one of those cannot be served here because reading it
    would mean importing that transport; such a route is refused by name rather than
    dropped silently.
    """

    built: list[AsgiRoute] = []
    for route in routes:
        if route.handler is None:
            raise ValueError(
                f"Route {route.path} carries no handler; the ASGI adapter can only register "
                "a route written against the port, not one built in another transport's terms"
            )
        built_route = AsgiRoute(route.path, route.methods, route.handler, route.name)
        for attribute, value in route.attributes:
            setattr(built_route, attribute, value)
        built.append(built_route)
    return built


__all__ = (
    "CONVERTERS",
    "AsgiRoute",
    "AsgiRouter",
    "Matched",
    "MethodMismatch",
    "Redirect",
    "Resolution",
    "Unmatched",
    "build_asgi_routes",
    "compile_path",
)
