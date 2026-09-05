"""Path templates, the routes built from them, and the router that matches them."""

from __future__ import annotations

import pytest

from bustan.adapters.asgi.routing import (
    AsgiRoute,
    AsgiRouter,
    Matched,
    MethodMismatch,
    Redirect,
    Unmatched,
    build_asgi_routes,
    compile_path,
)
from bustan.contracts import AdapterRoute, HttpRequest, HttpResponse


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
    # The port lets a plan carry a registration another transport already built instead
    # of a handler. Nothing in the framework builds one any more, but the port still
    # allows it, so this adapter still has to answer for one arriving.
    plan = AdapterRoute(path="/openapi.json", methods=("GET",), registration=object())

    with pytest.raises(ValueError, match="/openapi.json carries no handler"):
        build_asgi_routes([plan])
