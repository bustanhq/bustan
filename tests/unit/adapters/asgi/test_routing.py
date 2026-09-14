"""Path templates, the routes built from them, and the router that matches them."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from bustan.adapters.asgi.routing import (
    AsgiRoute,
    AsgiRouter,
    Matched,
    MethodMismatch,
    Redirect,
    Unmatched,
    alternate_path,
    build_asgi_routes,
    compile_path,
)
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse

if TYPE_CHECKING:
    import re

    from bustan.adapters.asgi.routing import Resolution


async def _handler(request: HttpRequest) -> HttpResponse:
    return HttpResponse.json({"path": request.path})


def _route(path: str, methods: tuple[str, ...] = ("GET",)) -> AsgiRoute:
    return AsgiRoute(path, methods, _handler, name="route")


def test_a_path_without_parameters_matches_only_itself() -> None:
    pattern = compile_path("/users.json")

    assert pattern.match("/users.json") is not None
    assert pattern.match("/usersXjson") is None


@pytest.mark.parametrize(
    ("template", "path", "expected"),
    [
        ("/users/{user_id}", "/users/7", {"user_id": "7"}),
        ("/users/{user_id:int}", "/users/7", {"user_id": "7"}),
        ("/users/{user_id:int}", "/users/seven", None),
        ("/prices/{amount:float}", "/prices/12.50", {"amount": "12.50"}),
        (
            "/things/{key:uuid}",
            "/things/6c84fb90-12c4-11e1-840d-7b25c5ee775a",
            {"key": "6c84fb90-12c4-11e1-840d-7b25c5ee775a"},
        ),
        ("/files/{rest:path}", "/files/a/b/c.txt", {"rest": "a/b/c.txt"}),
        ("/users/{user_id}", "/users/7/posts", None),
    ],
)
def test_a_converter_decides_what_one_captured_parameter_may_contain(
    template: str, path: str, expected: dict[str, str] | None
) -> None:
    matched = compile_path(template).match(path)

    assert (None if matched is None else matched.groupdict()) == expected


def test_an_unknown_converter_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError, match="Unknown path converter 'slug'"):
        compile_path("/users/{user_id:slug}")


def test_a_malformed_parameter_is_refused_rather_than_matched_literally() -> None:
    with pytest.raises(ValueError, match="Malformed path parameter"):
        compile_path("/users/{user_id")


def test_a_route_answers_head_wherever_it_answers_get() -> None:
    assert _route("/users").methods == frozenset({"GET", "HEAD"})
    assert _route("/users", ("POST",)).methods == frozenset({"POST"})


def test_a_route_reports_the_parameters_a_path_captured() -> None:
    assert _route("/users/{user_id}").match("/users/7") == {"user_id": "7"}
    assert _route("/users/{user_id}").match("/orders/7") is None


def test_a_route_repr_names_the_path_and_the_handler_it_was_compiled_for() -> None:
    assert repr(_route("/users")) == "AsgiRoute(path='/users', name='route')"


def test_the_router_returns_the_first_route_that_answers_the_request() -> None:
    router = AsgiRouter()
    first, second = _route("/users/{user_id}"), _route("/users/me")
    router.add([first, second])

    resolution = router.resolve("/users/me", "GET")

    assert isinstance(resolution, Matched)
    assert resolution.route is first
    assert resolution.path_params == {"user_id": "me"}


def test_the_router_reports_what_a_matching_path_does_answer_to() -> None:
    router = AsgiRouter()
    router.add([_route("/users", ("POST",)), _route("/users", ("DELETE",))])

    resolution = router.resolve("/users", "GET")

    assert resolution == MethodMismatch(("DELETE", "POST"))


def test_the_router_offers_the_path_with_its_trailing_slash_corrected() -> None:
    router = AsgiRouter()
    router.add([_route("/users")])

    assert router.resolve("/users/", "GET") == Redirect("/users")


def test_the_router_offers_the_path_with_a_trailing_slash_added() -> None:
    router = AsgiRouter()
    router.add([_route("/users/")])

    assert router.resolve("/users", "GET") == Redirect("/users/")


def test_a_path_no_route_answers_in_any_form_is_unmatched() -> None:
    router = AsgiRouter()
    router.add([_route("/users")])

    assert router.resolve("/orders", "GET") == Unmatched()


def test_a_parameterised_route_added_before_a_static_route_it_matches_still_answers_it() -> None:
    router = AsgiRouter()
    parameterised, static = _route("/users/{user_id}"), _route("/users/me")
    router.add([parameterised])
    router.add([static])

    assert router.resolve("/users/me", "GET") == Matched(parameterised, {"user_id": "me"})


def test_a_static_route_answers_ahead_of_a_parameterised_route_registered_after_it() -> None:
    router = AsgiRouter()
    static, parameterised = _route("/users/me"), _route("/users/{user_id}")
    router.add([static, parameterised])

    assert router.resolve("/users/me", "GET") == Matched(static, {})
    assert router.resolve("/users/7", "GET") == Matched(parameterised, {"user_id": "7"})


def test_a_later_route_answers_a_method_the_static_route_for_that_path_does_not() -> None:
    router = AsgiRouter()
    static, parameterised = _route("/users/me", ("POST",)), _route("/users/{user_id}")
    router.add([static, parameterised])

    assert router.resolve("/users/me", "GET") == Matched(parameterised, {"user_id": "me"})
    assert router.resolve("/users/me", "DELETE") == MethodMismatch(("GET", "HEAD", "POST"))


def test_a_static_route_registered_after_a_pattern_answering_its_path_waits_behind_it() -> None:
    router = AsgiRouter()
    first, pattern, last = _route("/x"), _route("/{name}", ("POST",)), _route("/x", ("POST",))
    router.add([first])
    router.add([pattern])
    router.add([last])

    assert router.resolve("/x", "GET") == Matched(first, {})
    assert router.resolve("/x", "POST") == Matched(pattern, {"name": "x"})


class _CountingPattern:
    """A compiled path pattern that records every path it is asked to match."""

    def __init__(self, pattern: re.Pattern[str], tried: list[str]) -> None:
        self._pattern = pattern
        self._tried = tried

    def match(self, path: str) -> re.Match[str] | None:
        self._tried.append(path)
        return self._pattern.match(path)


def test_the_last_of_two_hundred_static_routes_is_matched_as_cheaply_as_the_first() -> None:
    """Counted in patterns tried rather than timed, so that it holds on any machine.

    Answering by trying each earlier route's pattern costs one attempt for every route
    registered before the one that answers, so the two counts would differ.
    """

    tried: list[str] = []
    routes = [_route(f"/static/{index}") for index in range(200)]
    for route in routes:
        route.pattern = cast("re.Pattern[str]", _CountingPattern(route.pattern, tried))
    router = AsgiRouter()
    router.add(routes)

    assert router.resolve("/static/0", "GET") == Matched(routes[0], {})
    tried_for_first = len(tried)
    assert router.resolve("/static/199", "GET") == Matched(routes[-1], {})
    tried_for_last = len(tried) - tried_for_first

    assert tried_for_first == tried_for_last == 0
    # A path no route answers is still tried against every pattern, in both spellings,
    # which is what shows the count above was being taken.
    assert router.resolve("/absent", "GET") == Unmatched()
    assert len(tried) == 2 * len(routes)


def _in_registration_order(routes: list[AsgiRoute], path: str, method: str) -> Resolution:
    """Answer by trying every route's pattern in registration order, keeping nothing.

    This is the rule the router is specified by, so whatever the router keeps in order to
    answer sooner has to agree with it on every request.
    """

    allowed: set[str] = set()
    for route in routes:
        path_params = route.match(path)
        if path_params is None:
            continue
        if method in route.methods:
            return Matched(route, path_params)
        allowed |= route.methods
    if allowed:
        return MethodMismatch(tuple(sorted(allowed)))
    alternate = alternate_path(path)
    if alternate and any(route.match(alternate) is not None for route in routes):
        return Redirect(alternate)
    return Unmatched()


# Routes registered one ``add`` at a time, each a path and the methods it answers. Each
# arrangement registers routes that answer one path on both sides of another route.
_REGISTRATIONS: dict[str, list[list[tuple[str, tuple[str, ...]]]]] = {
    "static before a pattern that matches it": [
        [("/users/me", ("POST",)), ("/users/{user_id}", ("GET",))],
    ],
    "pattern before a static route it matches, added apart": [
        [("/users/{user_id}", ("GET",))],
        [("/users/me", ("GET", "POST"))],
    ],
    "two static routes for one path around a pattern": [
        [("/x", ("GET",))],
        [("/{name}", ("POST",))],
        [("/x", ("POST", "DELETE"))],
    ],
    "both spellings of a trailing slash": [
        [("/users/", ("GET",)), ("/users", ("POST",)), ("/users/{user_id:int}", ("GET",))],
    ],
    "a whole path pattern after static routes": [
        [("/", ("GET",)), ("/files/a", ("GET",))],
        [("/files/{rest:path}", ("DELETE",))],
    ],
    "a static path ending in a newline": [
        [("/a", ("GET",)), ("/a\n", ("GET", "POST"))],
    ],
}
_PATHS = (
    "/",
    "/x",
    "/x/",
    "/users",
    "/users/",
    "/users/me",
    "/users/me/",
    "/users/7",
    "/files/a",
    "/files/a/",
    "/files/a/b",
    "/a",
    "/a\n",
    "/absent",
)
_METHODS = ("GET", "HEAD", "POST", "DELETE")


@pytest.mark.parametrize("registrations", list(_REGISTRATIONS.values()), ids=list(_REGISTRATIONS))
def test_every_request_is_answered_the_way_registration_order_answers_it(
    registrations: list[list[tuple[str, tuple[str, ...]]]],
) -> None:
    router = AsgiRouter()
    registered: list[AsgiRoute] = []
    for batch in registrations:
        routes = [_route(path, methods) for path, methods in batch]
        router.add(routes)
        registered.extend(routes)

    disagreements = [
        (method, path)
        for path in _PATHS
        for method in _METHODS
        if router.resolve(path, method) != _in_registration_order(registered, path, method)
    ]

    assert disagreements == []


def test_a_compiled_plan_becomes_routes_carrying_what_the_framework_named_on_them() -> None:
    plan = AdapterRoute(
        path="/users/{user_id}",
        methods=("GET",),
        name="UsersController.read_user",
        handler=_handler,
        attributes=(("bustan_route_contract", "contract"),),
    )

    built = build_asgi_routes([plan])

    assert built[0].path == "/users/{user_id}"
    assert built[0].name == "UsersController.read_user"
    assert vars(built[0])["bustan_route_contract"] == "contract"


def test_a_route_carrying_no_handler_is_refused_by_name() -> None:
    # A handler is the whole of what the port hands an adapter, so a route without one
    # cannot serve a request and is refused rather than registered as a dead path.
    plan = AdapterRoute(path="/openapi.json", methods=("GET",))

    with pytest.raises(ValueError, match="/openapi.json carries no handler"):
        build_asgi_routes([plan])
