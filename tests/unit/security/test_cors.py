"""Unit tests for application CORS support.

CORS is enforced by the transport, so the interesting assertions are the ones made
against more than one of them: every case below runs through both shipped adapters and
compares them, because an application that changes transport must not change what a
browser sees. The refusal an adapter without the capability answers with is asserted
here too, since silently accepting the call is the failure this surface is guarding
against.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from bustan import Application, Controller, CorsOptions, Get, Module, create_app
from bustan.adapters.asgi import AsgiAdapter, AsgiCorsMiddleware
from bustan.adapters.starlette import StarletteAdapter
from bustan.contracts import AbstractHttpAdapter, AdapterCapabilities, AdapterRoute, HttpRequest
from bustan.contracts.cors import CorsOptions as ContractCorsOptions
from bustan.runtime.adapter import AdapterRuntime
from bustan.security.cors import CorsOptions as SecurityCorsOptions
from bustan.testing import AsgiTestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

# Every header the cross-origin protocol puts on an answer. A case compares all of them
# rather than the one it is about, so an adapter that sets an extra one is a difference
# rather than something the next case happens not to look at.
CORS_HEADERS = (
    "access-control-allow-credentials",
    "access-control-allow-headers",
    "access-control-allow-methods",
    "access-control-allow-origin",
    "access-control-allow-private-network",
    "access-control-expose-headers",
    "access-control-max-age",
    "vary",
)

ORIGIN = "https://console.example.com"
OTHER_ORIGIN = "https://attacker.example.com"

# Builds an application on the ASGI adapter, enables CORS on it, and answers one request
# in a fresh interpreter that cannot import Starlette however it is asked. The blocked
# import is what a plain ``pip install bustan`` has: this adapter is the one that install
# serves through, and enforcing a policy is the thing it used to be unable to do there.
_ENFORCE_WITHOUT_STARLETTE = """
import json
import sys


class RefuseStarlette:
    def find_spec(self, name, path=None, target=None):
        if name == "starlette" or name.startswith("starlette."):
            raise ModuleNotFoundError(f"No module named {name!r}", name="starlette")
        return None


sys.meta_path.insert(0, RefuseStarlette())

from bustan import Controller, CorsOptions, Get, Module, create_app
from bustan.adapters.asgi import AsgiAdapter
from bustan.testing import AsgiTestClient


@Controller("/")
class RootController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[RootController])
class AppModule:
    pass


app = create_app(AppModule, adapter=lambda runtime: AsgiAdapter(lifespan=runtime.lifespan))
app.enable_cors(CorsOptions(origins=["https://console.example.com"]))

with AsgiTestClient(app) as client:
    served = client.get("/", headers={"origin": "https://console.example.com"})
    preflight = client.options(
        "/",
        headers={
            "origin": "https://console.example.com",
            "access-control-request-method": "GET",
        },
    )

print(
    json.dumps(
        {
            "starlette_imported": any(n.split(".")[0] == "starlette" for n in sys.modules),
            "served_status": served.status_code,
            "served_allow_origin": served.headers.get("access-control-allow-origin"),
            "preflight_status": preflight.status_code,
            "preflight_allow_origin": preflight.headers.get("access-control-allow-origin"),
        }
    )
)
"""


@Controller("/")
class CorsController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[CorsController])
class CorsModule:
    pass


class UncorsedAdapter(AbstractHttpAdapter):
    """An adapter written against the port that says nothing about cross-origin policy."""

    name = "uncorsed"
    capabilities = AdapterCapabilities()

    def from_native_request(self, native_request: object) -> HttpRequest:
        return cast(HttpRequest, native_request)

    def to_native_response(self, response: object) -> object:
        return response

    def register_routes(self, routes: Sequence[AdapterRoute]) -> None:
        return None

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        return None

    async def stop(self) -> None:
        return None

    def create_test_client(self) -> object:
        return object()

    def get_instance(self) -> object:
        return self

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        return None


def _asgi(runtime: AdapterRuntime) -> AbstractHttpAdapter:
    return AsgiAdapter(lifespan=cast(Any, runtime.lifespan))


def _starlette(runtime: AdapterRuntime) -> AbstractHttpAdapter:
    return StarletteAdapter(debug=runtime.debug, lifespan=runtime.lifespan)


ADAPTERS: dict[str, Callable[[AdapterRuntime], AbstractHttpAdapter]] = {
    "asgi": _asgi,
    "starlette": _starlette,
}


def _application(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter], options: CorsOptions | None
) -> Application:
    application = create_app(CorsModule, adapter=adapter)
    application.enable_cors(options)
    return application


def _answer(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
    options: CorsOptions | None = None,
    *,
    method: str = "GET",
    headers: Mapping[str, str],
) -> tuple[int, str, dict[str, str | None]]:
    """Serve one request and return everything the cross-origin protocol decides."""

    with AsgiTestClient(cast(Any, _application(adapter, options))) as client:
        response = client.request(method, "/", headers=dict(headers))
    return (
        response.status_code,
        response.text,
        {name: response.headers.get(name) for name in CORS_HEADERS},
    )


@pytest.fixture(params=sorted(ADAPTERS))
def adapter_name(request: pytest.FixtureRequest) -> str:
    return cast(str, request.param)


@pytest.fixture
def adapter(adapter_name: str) -> Callable[[AdapterRuntime], AbstractHttpAdapter]:
    return ADAPTERS[adapter_name]


def test_a_named_origin_is_allowed_to_read_the_response(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, _body, headers = _answer(
        adapter, CorsOptions(origins=[ORIGIN]), headers={"origin": ORIGIN}
    )

    assert status == 200
    assert headers["access-control-allow-origin"] == ORIGIN
    assert headers["vary"] == "Origin"


def test_an_origin_the_policy_did_not_name_is_not_allowed_to_read_the_response(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, _body, headers = _answer(
        adapter, CorsOptions(origins=[ORIGIN]), headers={"origin": OTHER_ORIGIN}
    )

    assert status == 200
    assert headers["access-control-allow-origin"] is None


def test_the_default_policy_allows_every_origin(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    """``enable_cors()`` with no arguments is documented as allowing every origin."""

    status, _body, headers = _answer(adapter, None, headers={"origin": OTHER_ORIGIN})

    assert status == 200
    assert headers["access-control-allow-origin"] == "*"


def test_a_request_carrying_no_origin_is_served_untouched(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, body, headers = _answer(adapter, CorsOptions(origins=[ORIGIN]), headers={})

    assert status == 200
    assert json.loads(body) == {"status": "ok"}
    assert headers["access-control-allow-origin"] is None


def test_a_credentialed_policy_names_the_origin_rather_than_starring_it(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    """A browser refuses ``*`` on a request that carries credentials."""

    _status, _body, headers = _answer(
        adapter, CorsOptions(credentials=True), headers={"origin": ORIGIN}
    )

    assert headers["access-control-allow-origin"] == ORIGIN
    assert headers["access-control-allow-credentials"] == "true"
    assert headers["vary"] == "Origin"


def test_exposed_headers_reach_the_response(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    _status, _body, headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN], exposed_headers=["x-total-count"]),
        headers={"origin": ORIGIN},
    )

    assert headers["access-control-expose-headers"] == "x-total-count"


def test_a_preflight_is_answered_by_the_transport_and_never_reaches_a_route(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, body, headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN], max_age=120),
        method="OPTIONS",
        headers={"origin": ORIGIN, "access-control-request-method": "GET"},
    )

    assert status == 200
    assert body == "OK"
    assert headers["access-control-allow-origin"] == ORIGIN
    assert headers["access-control-allow-methods"] == "GET, HEAD, PUT, PATCH, POST, DELETE"
    assert headers["access-control-max-age"] == "120"


def test_a_preflight_from_an_origin_the_policy_refuses_says_what_it_refused(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, body, headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN]),
        method="OPTIONS",
        headers={"origin": OTHER_ORIGIN, "access-control-request-method": "GET"},
    )

    assert status == 400
    assert body == "Disallowed CORS origin"
    assert headers["access-control-allow-origin"] is None


def test_a_preflight_for_a_method_the_policy_refuses_says_so(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, body, _headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN], methods=["GET"]),
        method="OPTIONS",
        headers={"origin": ORIGIN, "access-control-request-method": "DELETE"},
    )

    assert status == 400
    assert body == "Disallowed CORS method"


def test_a_preflight_for_a_header_the_policy_did_not_name_is_refused(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, body, _headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN], allowed_headers=["authorization"]),
        method="OPTIONS",
        headers={
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-headers": "x-trace-id",
        },
    )

    assert status == 400
    assert body == "Disallowed CORS headers"


def test_a_policy_allowing_every_header_mirrors_back_the_ones_asked_for(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, _body, headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN]),
        method="OPTIONS",
        headers={
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization, x-trace-id",
        },
    )

    assert status == 200
    assert headers["access-control-allow-headers"] == "authorization, x-trace-id"


def test_a_policy_naming_its_methods_with_a_star_allows_all_of_them(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    status, _body, headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN], methods=["*"]),
        method="OPTIONS",
        headers={"origin": ORIGIN, "access-control-request-method": "DELETE"},
    )

    assert status == 200
    assert headers["access-control-allow-methods"] == (
        "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
    )


def test_a_preflight_asking_to_reach_a_private_network_is_refused(
    adapter: Callable[[AdapterRuntime], AbstractHttpAdapter],
) -> None:
    """No option declares a private network reachable, so the answer is always no."""

    status, body, _headers = _answer(
        adapter,
        CorsOptions(origins=[ORIGIN]),
        method="OPTIONS",
        headers={
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-private-network": "true",
        },
    )

    assert status == 400
    assert body == "Disallowed CORS private-network"


# Every case above, as (options, method, request headers), run through both adapters and
# compared. Each assertion above holds one adapter to the protocol; this holds the two of
# them to each other, which is the claim that makes the transport replaceable.
PARITY_CASES: tuple[tuple[str, CorsOptions | None, str, dict[str, str]], ...] = (
    ("named origin", CorsOptions(origins=[ORIGIN]), "GET", {"origin": ORIGIN}),
    ("unnamed origin", CorsOptions(origins=[ORIGIN]), "GET", {"origin": OTHER_ORIGIN}),
    ("default policy", None, "GET", {"origin": ORIGIN}),
    ("no origin", CorsOptions(origins=[ORIGIN]), "GET", {}),
    ("credentialed", CorsOptions(credentials=True), "GET", {"origin": ORIGIN}),
    (
        "exposed headers",
        CorsOptions(origins=[ORIGIN], exposed_headers=["x-total-count", "x-page"]),
        "GET",
        {"origin": ORIGIN},
    ),
    (
        "preflight allowed",
        CorsOptions(origins=[ORIGIN], max_age=120),
        "OPTIONS",
        {"origin": ORIGIN, "access-control-request-method": "GET"},
    ),
    (
        "preflight wildcard origin",
        None,
        "OPTIONS",
        {"origin": ORIGIN, "access-control-request-method": "GET"},
    ),
    (
        "preflight credentialed",
        CorsOptions(credentials=True),
        "OPTIONS",
        {"origin": ORIGIN, "access-control-request-method": "GET"},
    ),
    (
        "preflight refused origin",
        CorsOptions(origins=[ORIGIN]),
        "OPTIONS",
        {"origin": OTHER_ORIGIN, "access-control-request-method": "GET"},
    ),
    (
        "preflight refused method",
        CorsOptions(origins=[ORIGIN], methods=["GET"]),
        "OPTIONS",
        {"origin": ORIGIN, "access-control-request-method": "DELETE"},
    ),
    (
        "preflight named headers",
        CorsOptions(origins=[ORIGIN], allowed_headers=["authorization"]),
        "OPTIONS",
        {
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-headers": "Authorization, content-type",
        },
    ),
    (
        "preflight refused headers",
        CorsOptions(origins=[ORIGIN], allowed_headers=["authorization"]),
        "OPTIONS",
        {
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-headers": "x-trace-id",
        },
    ),
    (
        "preflight private network",
        CorsOptions(origins=[ORIGIN]),
        "OPTIONS",
        {
            "origin": ORIGIN,
            "access-control-request-method": "GET",
            "access-control-request-private-network": "true",
        },
    ),
)


@pytest.mark.parametrize(
    ("options", "method", "headers"),
    [case[1:] for case in PARITY_CASES],
    ids=[case[0] for case in PARITY_CASES],
)
def test_both_adapters_answer_a_cross_origin_request_identically(
    options: CorsOptions | None, method: str, headers: dict[str, str]
) -> None:
    answers = {
        name: _answer(factory, options, method=method, headers=headers)
        for name, factory in ADAPTERS.items()
    }

    assert answers["asgi"] == answers["starlette"]


def test_an_adapter_without_the_capability_refuses_and_names_itself() -> None:
    """Silence would be worse than a refusal: it reads as a policy that is being enforced."""

    application = create_app(CorsModule, adapter=UncorsedAdapter())

    with pytest.raises(NotImplementedError) as refusal:
        application.enable_cors(CorsOptions(origins=[ORIGIN]))

    assert "UncorsedAdapter" in str(refusal.value)
    assert "CORS" in str(refusal.value)


def test_the_asgi_adapter_enforces_a_policy_with_no_web_framework_installed() -> None:
    """The install this adapter exists for is the one that has no Starlette to reach for.

    Before the policy became the adapter's own work, the application wrapper imported
    Starlette's middleware to enforce it, so this call raised ``ModuleNotFoundError`` on
    a plain install and the operator was told to fix a package they never asked for.
    """

    completed = subprocess.run(
        [sys.executable, "-c", _ENFORCE_WITHOUT_STARLETTE],
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    answered = json.loads(completed.stdout)

    assert answered == {
        "starlette_imported": False,
        "served_status": 200,
        "served_allow_origin": ORIGIN,
        "preflight_status": 200,
        "preflight_allow_origin": ORIGIN,
    }


@pytest.mark.anyio
async def test_a_connection_that_is_not_a_request_passes_through_untouched() -> None:
    """A cross-origin policy is about requests, so the middleware reads nothing else."""

    seen: list[str] = []

    async def application(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    async def receive() -> MutableMapping[str, Any]:
        return {"type": "lifespan.startup"}

    async def send(message: MutableMapping[str, Any]) -> None:
        raise AssertionError(f"nothing should be written: {message}")

    middleware = AsgiCorsMiddleware(application, options=CorsOptions(origins=[ORIGIN]))
    await middleware({"type": "lifespan"}, receive, send)

    assert seen == ["lifespan"]


def test_the_exported_options_type_is_the_one_both_layers_name() -> None:
    """The policy crosses the adapter port, so the contracts declare it; the export is the same."""

    assert CorsOptions is ContractCorsOptions
    assert CorsOptions is SecurityCorsOptions


def test_the_options_type_still_means_what_it_meant() -> None:
    options = CorsOptions()

    assert options.origins == "*"
    assert options.methods == ["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"]
    assert options.allowed_headers == ["*"]
    assert options.exposed_headers == []
    assert options.credentials is False
    assert options.max_age == 600
