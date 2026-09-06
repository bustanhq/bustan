"""The suite every transport adapter has to answer, and answer the same way.

An adapter is certified by driving it through **its own** test client: the suite asks
the adapter for the client its users would drive and sends requests through that, so
nothing here is written in one transport's terms and an adapter that binds no web
framework at all can be put through exactly the same cases.

Each case records an :class:`ResponseObservation`, and that record is the definition
of "identical" two adapters are held to:

* the **status code**;
* the **body**, canonicalised - a JSON body compared as parsed JSON with its keys
  sorted, so that key order and whitespace are not mistaken for a difference, and any
  other body compared as its exact text;
* the **headers the case names**, and no others. The media type is named by every
  case because it is part of what the framework promises; a case about a redirect
  names ``location``, a case about middleware names the header the middleware set.

Everything else a response carries is deliberately outside the comparison, because it
is the transport's to decide and no contract names it: header order, the framework's
absent defaults, ``date``, ``server``, ``content-length``, ``etag`` and the transfer
encoding a streaming response is written with. A matrix that compared those would
report a difference on the day a server library changed its defaults, and a matrix
that reports differences nobody can act on is a matrix that gets switched off.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Annotated, Any, cast

from ...adapters.asgi import AsgiAdapter
from ...adapters.starlette import StarletteAdapter
from ...app.bootstrap import create_app
from ...common.decorators.controller import Controller
from ...common.decorators.parameter import (
    Body,
    Cookies,
    Header,
    HostParam,
    Ip,
    Param,
    Query,
    create_param_decorator,
)
from ...common.decorators.route import Get, Post
from ...contracts import HttpRequest, HttpResponse
from ...core.module.decorators import Module
from ...pipeline.context import ExecutionContext
from ...pipeline.decorators import UseFilters
from ...pipeline.filters import ExceptionFilter
from ...pipeline.middleware import Middleware, MiddlewareConsumer
from .adapter import AbstractHttpAdapter, AdapterCapabilities
from .versioning import VersioningOptions, VersioningType

if TYPE_CHECKING:
    from collections.abc import AsyncIterator as AsyncIteratorType

# The header every case compares, whatever else it names: a response's media type is
# part of the framework's contract rather than one transport's default.
ALWAYS_COMPARED_HEADERS = ("content-type",)

# The logger every part of the framework writes under, whose level one case is run with
# raised; naming it here keeps the reason next to the constant.
PACKAGE_LOGGER = "bustan"

JSON_MEDIA_TYPE = "application/json"
PROBLEM_MEDIA_TYPE = "application/problem+json"


@dataclass(frozen=True, slots=True)
class ResponseObservation:
    """What one case saw, reduced to the part two adapters must agree on.

    ``status_code`` is ``None`` for a case that observed the application itself rather
    than a response - the lifespan shutdown case is the only one, because shutdown has
    by definition finished after the last request.
    """

    status_code: int | None
    headers: tuple[tuple[str, str], ...]
    body: str


@dataclass(frozen=True, slots=True)
class ConformanceRequest:
    """One request, in terms every adapter's own test client understands."""

    method: str = "GET"
    path: str = "/"
    headers: tuple[tuple[str, str], ...] = ()
    json_body: object | None = None
    content: bytes | None = None
    follow_redirects: bool = False


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One request and the observation every conforming adapter must produce for it."""

    name: str
    dimension: str
    request: ConformanceRequest
    expected: ResponseObservation


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    """The result of one case against one adapter."""

    name: str
    passed: bool
    detail: str
    dimension: str = ""
    observation: ResponseObservation | None = None


@dataclass(frozen=True, slots=True)
class AdapterConformanceResult:
    """Every case's result for one adapter, and what that adapter says it can do."""

    adapter: str
    capabilities: AdapterCapabilities
    checks: tuple[ConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def observations(self) -> dict[str, ResponseObservation | None]:
        """Return each case's observation by case name, for comparison across adapters."""

        return {check.name: check.observation for check in self.checks}

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "passed": self.passed,
            "capabilities": asdict(self.capabilities),
            "checks": tuple(asdict(check) for check in self.checks),
        }


@dataclass(frozen=True, slots=True)
class Payload:
    """The body model the body-binding cases post."""

    name: str


@dataclass(frozen=True, slots=True)
class ConformanceScenario:
    """One application the suite builds, and the cases it answers.

    A scenario is a whole application because some of what is being certified is
    chosen when the application is built - the versioning strategy is an argument to
    ``create_app``, and an adapter is handed its lifespan before any route exists - so
    the cases that need a different application get a different scenario.
    """

    name: str
    build_module: Callable[[Path], type[object]]
    cases: tuple[ConformanceCase, ...]
    versioning: VersioningOptions | None = None


def _observation(
    status_code: int | None,
    headers: Mapping[str, str],
    body: str,
) -> ResponseObservation:
    """Build an observation with its headers folded and ordered the way a case is read."""

    return ResponseObservation(
        status_code=status_code,
        headers=tuple(sorted((name.lower(), value) for name, value in headers.items())),
        body=body,
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _expect_json(
    payload: object,
    *,
    status_code: int = 200,
    media_type: str = JSON_MEDIA_TYPE,
    headers: Mapping[str, str] | None = None,
) -> ResponseObservation:
    """The observation a JSON answer must produce."""

    return _observation(
        status_code,
        {"content-type": media_type, **dict(headers or {})},
        _canonical_json(payload),
    )


def _expect_text(
    body: str,
    *,
    status_code: int = 200,
    media_type: str = "",
    headers: Mapping[str, str] | None = None,
) -> ResponseObservation:
    """The observation a non-JSON answer must produce."""

    return _observation(status_code, {"content-type": media_type, **dict(headers or {})}, body)


CurrentRequestPath = create_param_decorator(
    lambda _data, context: context.switch_to_http().get_request().path,
    name="CurrentRequestPath",
)


def _build_parameter_module(_fixtures: Path) -> type[object]:
    """An application with one route per parameter source the binder compiles."""

    @Module(controllers=[_addressing_controller(), _payload_controller()])
    class ParameterModule:
        pass

    return ParameterModule


def _addressing_controller() -> type[object]:
    """Routes for the sources read from where a request was addressed and by whom."""

    @Controller("/parameters")
    class AddressingController:
        @Get("/path/{user_id}")
        def read_path(self, user_id: Annotated[int, Param]) -> dict[str, object]:
            return {"user_id": user_id}

        @Get("/query")
        def read_query(
            self, term: Annotated[str, Query], tags: Annotated[list[str], Query("tag")]
        ) -> dict[str, object]:
            return {"term": term, "tags": tags}

        @Get("/header")
        def read_header(self, token: Annotated[str, Header("X-Api-Token")]) -> dict[str, object]:
            return {"token": token}

        @Get("/cookie")
        def read_cookie(
            self, session: Annotated[str | None, Cookies("session")]
        ) -> dict[str, object]:
            return {"session": session}

        @Get("/ip")
        def read_ip(self, client: Annotated[str | None, Ip]) -> dict[str, object]:
            return {"client": client}

        @Get("/host")
        def read_host(self, host: Annotated[str | None, HostParam]) -> dict[str, object]:
            return {"host": host}

    return AddressingController


def _payload_controller() -> type[object]:
    """Routes for the sources read from the request itself, and for inference.

    The two inferred routes are what certifies inference rather than the enum member
    named for it: a parameter with no marker is bound from the query string on a safe
    method and from the body on an unsafe one, and no binding is ever labelled inferred
    by the time a request is served.
    """

    @Controller("/parameters")
    class PayloadController:
        @Post("/body")
        def read_body(self, payload: Payload) -> dict[str, object]:
            return {"name": payload.name}

        @Post("/body-field")
        def read_body_field(self, name: Annotated[str, Body("name")]) -> dict[str, object]:
            return {"name": name}

        @Get("/request")
        def read_request(self, request: HttpRequest) -> dict[str, object]:
            return {"method": request.method, "path": request.path}

        @Get("/custom")
        def read_custom(self, path: Annotated[str, CurrentRequestPath]) -> dict[str, object]:
            return {"path": path}

        @Get("/inferred")
        def read_inferred(self, term: str) -> dict[str, object]:
            return {"term": term}

        @Post("/inferred")
        def write_inferred(self, name: str) -> dict[str, object]:
            return {"name": name}

    return PayloadController


# The two parameter sources the suite does not certify, named here because a coverage
# gap nobody wrote down is indistinguishable from an oversight. Both read the form body
# the adapter parsed, and the two adapters do not answer the same request the same way:
# one parses a form from the standard library alone, the other delegates to a server
# library that refuses every form body, urlencoded included, unless an optional package
# this project does not depend on is installed. Certifying them would make the matrix
# red for a difference no change to this file can close.
UNCERTIFIED_PARAMETER_SOURCES = ("file", "files")


PARAMETER_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="parameter_source_path",
        dimension="parameter source: path",
        request=ConformanceRequest(path="/parameters/path/42"),
        expected=_expect_json({"user_id": 42}),
    ),
    ConformanceCase(
        name="parameter_source_query",
        dimension="parameter source: query",
        request=ConformanceRequest(path="/parameters/query?term=alpha&tag=a&tag=b"),
        expected=_expect_json({"term": "alpha", "tags": ["a", "b"]}),
    ),
    ConformanceCase(
        name="parameter_source_body_model",
        dimension="parameter source: body",
        request=ConformanceRequest(
            method="POST", path="/parameters/body", json_body={"name": "Ada"}
        ),
        expected=_expect_json({"name": "Ada"}),
    ),
    ConformanceCase(
        name="parameter_source_body_field",
        dimension="parameter source: body",
        request=ConformanceRequest(
            method="POST", path="/parameters/body-field", json_body={"name": "Grace"}
        ),
        expected=_expect_json({"name": "Grace"}),
    ),
    ConformanceCase(
        name="parameter_source_header",
        dimension="parameter source: header",
        request=ConformanceRequest(path="/parameters/header", headers=(("X-Api-Token", "secret"),)),
        expected=_expect_json({"token": "secret"}),
    ),
    ConformanceCase(
        name="parameter_source_cookie",
        dimension="parameter source: cookie",
        request=ConformanceRequest(path="/parameters/cookie", headers=(("cookie", "session=abc"),)),
        expected=_expect_json({"session": "abc"}),
    ),
    ConformanceCase(
        name="parameter_source_ip",
        dimension="parameter source: ip",
        request=ConformanceRequest(path="/parameters/ip"),
        expected=_expect_json({"client": "testclient"}),
    ),
    ConformanceCase(
        name="parameter_source_host",
        dimension="parameter source: host",
        request=ConformanceRequest(path="/parameters/host"),
        expected=_expect_json({"host": "testserver"}),
    ),
    ConformanceCase(
        name="parameter_source_request",
        dimension="parameter source: request",
        request=ConformanceRequest(path="/parameters/request"),
        expected=_expect_json({"method": "GET", "path": "/parameters/request"}),
    ),
    ConformanceCase(
        name="parameter_source_custom",
        dimension="parameter source: custom",
        request=ConformanceRequest(path="/parameters/custom"),
        expected=_expect_json({"path": "/parameters/custom"}),
    ),
    ConformanceCase(
        name="parameter_source_inferred_query",
        dimension="parameter source: inferred",
        request=ConformanceRequest(path="/parameters/inferred?term=beta"),
        expected=_expect_json({"term": "beta"}),
    ),
    ConformanceCase(
        name="parameter_source_inferred_body",
        dimension="parameter source: inferred",
        request=ConformanceRequest(
            method="POST", path="/parameters/inferred", json_body={"name": "Hedy"}
        ),
        expected=_expect_json({"name": "Hedy"}),
    ),
)


# What the file-response case serves, written into the scenario's fixture directory so
# that both adapters read the same bytes from the same name.
FIXTURE_FILE_NAME = "conformance.txt"
FIXTURE_FILE_TEXT = "conformance fixture\n"


def _build_response_module(fixtures: Path) -> type[object]:
    """An application with one route per response strategy the compiler recognises."""

    @Module(controllers=[_serialised_controller(), _written_controller(fixtures)])
    class ResponseModule:
        pass

    return ResponseModule


def _serialised_controller() -> type[object]:
    """Routes whose results the framework serialises: the standard strategy."""

    @Controller("/responses")
    class SerialisedController:
        @Get("/standard")
        def standard(self) -> dict[str, object]:
            return {"strategy": "standard"}

        @Get("/standard-list")
        def standard_list(self) -> list[str]:
            return ["one", "two"]

        @Get("/standard-empty")
        def standard_empty(self) -> None:
            return None

    return SerialisedController


def _written_controller(fixtures: Path) -> type[object]:
    """Routes that hand the transport a response to write: raw, stream and file."""

    fixture_path = fixtures / FIXTURE_FILE_NAME

    @Controller("/responses")
    class WrittenController:
        @Get("/raw")
        def raw(self) -> HttpResponse:
            return HttpResponse(
                status_code=201,
                headers={"x-raw-response": "yes"},
                body=b'{"strategy":"raw"}',
                media_type=JSON_MEDIA_TYPE,
            )

        @Get("/raw-redirect")
        def raw_redirect(self) -> HttpResponse:
            return HttpResponse(
                status_code=307,
                headers={"location": "/responses/standard"},
                body=b"",
            )

        @Get("/stream")
        def stream(self) -> Iterator[bytes]:
            yield b"first "
            yield b"second"

        @Get("/stream-async")
        async def stream_async(self) -> AsyncIterator[bytes]:
            yield b"async "
            yield b"chunks"

        @Get("/file")
        def file(self) -> Path:
            return fixture_path

    return WrittenController


RESPONSE_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="response_strategy_standard_mapping",
        dimension="response strategy: standard",
        request=ConformanceRequest(path="/responses/standard"),
        expected=_expect_json({"strategy": "standard"}),
    ),
    ConformanceCase(
        name="response_strategy_standard_sequence",
        dimension="response strategy: standard",
        request=ConformanceRequest(path="/responses/standard-list"),
        expected=_expect_json(["one", "two"]),
    ),
    ConformanceCase(
        name="response_strategy_standard_no_content",
        dimension="response strategy: standard",
        request=ConformanceRequest(path="/responses/standard-empty"),
        expected=_expect_text("", status_code=204),
    ),
    ConformanceCase(
        name="response_strategy_raw",
        dimension="response strategy: raw",
        request=ConformanceRequest(path="/responses/raw"),
        expected=_expect_json(
            {"strategy": "raw"}, status_code=201, headers={"x-raw-response": "yes"}
        ),
    ),
    ConformanceCase(
        name="response_strategy_raw_redirect",
        dimension="response strategy: raw",
        request=ConformanceRequest(path="/responses/raw-redirect"),
        expected=_expect_text("", status_code=307, headers={"location": "/responses/standard"}),
    ),
    ConformanceCase(
        name="response_strategy_stream",
        dimension="response strategy: stream",
        request=ConformanceRequest(path="/responses/stream"),
        expected=_expect_text("first second"),
    ),
    ConformanceCase(
        name="response_strategy_stream_async",
        dimension="response strategy: stream",
        request=ConformanceRequest(path="/responses/stream-async"),
        expected=_expect_text("async chunks"),
    ),
    ConformanceCase(
        name="response_strategy_file",
        dimension="response strategy: file",
        request=ConformanceRequest(path="/responses/file"),
        expected=_expect_text(FIXTURE_FILE_TEXT, media_type="text/plain; charset=utf-8"),
    ),
)


class ConformanceMiddleware(Middleware):
    """Marks every response it sees, so a case can tell where the chain reached."""

    async def use(self, request: HttpRequest, call_next: Any) -> object:
        response = await call_next(request)
        response.headers["x-middleware"] = "applied"
        return response


def _build_middleware_module(_fixtures: Path) -> type[object]:
    """An application whose module configuration binds middleware to some routes only."""

    @Controller("/middleware")
    class MiddlewareController:
        @Get("/covered")
        def covered(self) -> dict[str, object]:
            return {"route": "covered"}

    @Controller("/plain")
    class PlainController:
        @Get("/uncovered")
        def uncovered(self) -> dict[str, object]:
            return {"route": "uncovered"}

    @Module(controllers=[MiddlewareController, PlainController])
    class MiddlewareModule:
        def configure(self, consumer: MiddlewareConsumer) -> None:
            consumer.apply(ConformanceMiddleware).for_routes("/middleware*")

    return MiddlewareModule


MIDDLEWARE_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="middleware_applies_to_matching_routes",
        dimension="middleware",
        request=ConformanceRequest(path="/middleware/covered"),
        expected=_expect_json({"route": "covered"}, headers={"x-middleware": "applied"}),
    ),
    ConformanceCase(
        name="middleware_leaves_other_routes_alone",
        dimension="middleware",
        request=ConformanceRequest(path="/plain/uncovered"),
        expected=_expect_json({"route": "uncovered"}, headers={"x-middleware": ""}),
    ),
)


class ConformanceFilter(ExceptionFilter):
    """Answers the one failure it declares, leaving every other failure alone."""

    exception_types = (ValueError,)

    async def catch(self, exc: Exception, context: ExecutionContext) -> object:
        return {"handled": "filter", "detail": str(exc)}


def _build_filter_module(_fixtures: Path) -> type[object]:
    """An application with a filtered failure and an unfiltered one."""

    @Controller("/failures")
    class FailureController:
        @UseFilters(ConformanceFilter())
        @Get("/filtered")
        def filtered(self) -> dict[str, object]:
            raise ValueError("filtered failure")

        @Get("/unfiltered")
        def unfiltered(self) -> dict[str, object]:
            raise RuntimeError("unfiltered failure")

    @Module(controllers=[FailureController])
    class FilterModule:
        pass

    return FilterModule


FILTER_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="exception_filter_answers_its_own_exception",
        dimension="exception filter",
        request=ConformanceRequest(path="/failures/filtered"),
        expected=_expect_json({"handled": "filter", "detail": "filtered failure"}),
    ),
    ConformanceCase(
        name="exception_filter_leaves_other_failures_to_the_error_model",
        dimension="exception filter",
        request=ConformanceRequest(path="/failures/unfiltered"),
        expected=_expect_json(
            {
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Internal server error",
                "instance": "/failures/unfiltered",
            },
            status_code=500,
            media_type=PROBLEM_MEDIA_TYPE,
        ),
    ),
)


def _build_versioning_module(_fixtures: Path) -> type[object]:
    """Two versions of one route, dispatched by whichever strategy the scenario sets."""

    @Controller("/reports", version="1")
    class ReportsV1Controller:
        @Get("/")
        def index(self) -> dict[str, object]:
            return {"version": "1"}

    @Controller("/reports", version="2")
    class ReportsV2Controller:
        @Get("/")
        def index(self) -> dict[str, object]:
            return {"version": "2"}

    @Module(controllers=[ReportsV1Controller, ReportsV2Controller])
    class VersioningModule:
        pass

    return VersioningModule


# A version the URI strategy does not know is a path no route was registered at, so the
# transport answers it; under the other two strategies the route exists and the
# framework's own version dispatcher answers. The two answers differ by design, and a
# matrix that did not distinguish them would be asserting one of them was wrong.
TRANSPORT_NOT_FOUND = _expect_text(
    "Not Found", status_code=404, media_type="text/plain; charset=utf-8"
)
DISPATCHER_NOT_FOUND = _expect_json({"detail": "Not Found"}, status_code=404)

URI_VERSIONING_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="versioning_uri_first_version",
        dimension="versioning strategy: uri",
        request=ConformanceRequest(path="/v1/reports"),
        expected=_expect_json({"version": "1"}),
    ),
    ConformanceCase(
        name="versioning_uri_second_version",
        dimension="versioning strategy: uri",
        request=ConformanceRequest(path="/v2/reports"),
        expected=_expect_json({"version": "2"}),
    ),
    ConformanceCase(
        name="versioning_uri_unknown_version",
        dimension="versioning strategy: uri",
        request=ConformanceRequest(path="/v3/reports"),
        expected=TRANSPORT_NOT_FOUND,
    ),
)

HEADER_VERSIONING_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="versioning_header_first_version",
        dimension="versioning strategy: header",
        request=ConformanceRequest(path="/reports", headers=(("X-API-Version", "1"),)),
        expected=_expect_json({"version": "1"}),
    ),
    ConformanceCase(
        name="versioning_header_second_version",
        dimension="versioning strategy: header",
        request=ConformanceRequest(path="/reports", headers=(("X-API-Version", "2"),)),
        expected=_expect_json({"version": "2"}),
    ),
    ConformanceCase(
        name="versioning_header_unknown_version",
        dimension="versioning strategy: header",
        request=ConformanceRequest(path="/reports", headers=(("X-API-Version", "3"),)),
        expected=DISPATCHER_NOT_FOUND,
    ),
)

MEDIA_TYPE_VERSIONING_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="versioning_media_type_first_version",
        dimension="versioning strategy: media_type",
        request=ConformanceRequest(
            path="/reports", headers=(("accept", "application/json; version=1"),)
        ),
        expected=_expect_json({"version": "1"}),
    ),
    ConformanceCase(
        name="versioning_media_type_second_version",
        dimension="versioning strategy: media_type",
        request=ConformanceRequest(
            path="/reports", headers=(("accept", "application/json; version=2"),)
        ),
        expected=_expect_json({"version": "2"}),
    ),
    ConformanceCase(
        name="versioning_media_type_unknown_version",
        dimension="versioning strategy: media_type",
        request=ConformanceRequest(
            path="/reports", headers=(("accept", "application/json; version=3"),)
        ),
        expected=DISPATCHER_NOT_FOUND,
    ),
)


class LifespanRecorder:
    """A lifespan that records having been run, for the case that asks whether it was.

    The suite hands this to the adapter as the application's lifespan, so what is being
    certified is the adapter's own obligation: run the lifespan it was constructed with,
    startup before the first request reaches a handler and shutdown after the last one.
    """

    def __init__(self) -> None:
        self.startups = 0
        self.shutdowns = 0

    @asynccontextmanager
    async def __call__(self, _application: object) -> AsyncIteratorType[None]:
        self.startups += 1
        try:
            yield
        finally:
            self.shutdowns += 1

    def state(self) -> dict[str, object]:
        """What the lifespan has done so far, as the cases compare it."""

        return {"startups": self.startups, "shutdowns": self.shutdowns}


def _build_lifespan_module(recorder: LifespanRecorder) -> type[object]:
    """An application whose one route reports what its lifespan has done so far."""

    @Controller("/lifespan")
    class LifespanController:
        @Get("/")
        def read(self) -> dict[str, object]:
            return recorder.state()

    @Module(controllers=[LifespanController])
    class LifespanModule:
        pass

    return LifespanModule


LIFESPAN_STARTUP_CASE = ConformanceCase(
    name="lifespan_startup_runs_before_the_first_request",
    dimension="lifespan",
    request=ConformanceRequest(path="/lifespan"),
    expected=_expect_json({"startups": 1, "shutdowns": 0}),
)

LIFESPAN_SHUTDOWN_CASE = ConformanceCase(
    name="lifespan_shutdown_runs_after_the_last_request",
    dimension="lifespan",
    request=ConformanceRequest(path="/lifespan"),
    expected=_observation(None, {}, _canonical_json({"startups": 1, "shutdowns": 1})),
)

SCENARIOS: tuple[ConformanceScenario, ...] = (
    ConformanceScenario("parameters", _build_parameter_module, PARAMETER_CASES),
    ConformanceScenario("responses", _build_response_module, RESPONSE_CASES),
    ConformanceScenario("middleware", _build_middleware_module, MIDDLEWARE_CASES),
    ConformanceScenario("exception filters", _build_filter_module, FILTER_CASES),
    ConformanceScenario(
        "uri versioning",
        _build_versioning_module,
        URI_VERSIONING_CASES,
        VersioningOptions(type=VersioningType.URI),
    ),
    ConformanceScenario(
        "header versioning",
        _build_versioning_module,
        HEADER_VERSIONING_CASES,
        VersioningOptions(type=VersioningType.HEADER),
    ),
    ConformanceScenario(
        "media type versioning",
        _build_versioning_module,
        MEDIA_TYPE_VERSIONING_CASES,
        VersioningOptions(type=VersioningType.MEDIA_TYPE),
    ),
)


def evaluate_adapter_conformance(adapter: AbstractHttpAdapter) -> AdapterConformanceResult:
    """Run every conformance case against *adapter* and report what it answered.

    The adapter given is the prototype rather than the application's server: each
    scenario builds a fresh instance of its class, because an adapter carries the routes
    registered on it and a scenario that inherited another's routes would be certifying
    something nobody asked for.
    """

    with TemporaryDirectory(prefix="bustan-conformance-") as directory, _muted_framework_logging():
        fixtures = Path(directory)
        (fixtures / FIXTURE_FILE_NAME).write_text(FIXTURE_FILE_TEXT, encoding="utf-8")
        checks = tuple(
            check for scenario in SCENARIOS for check in _run_scenario(adapter, scenario, fixtures)
        )
        checks += _run_lifespan_scenario(adapter)

    return AdapterConformanceResult(
        adapter=adapter.name,
        capabilities=adapter.capabilities,
        checks=checks,
    )


def _build_adapter(prototype: AbstractHttpAdapter, **options: object) -> AbstractHttpAdapter:
    """Return a new adapter of the prototype's class, built with ``options``.

    The call is dynamic because the port says nothing about how an adapter is
    constructed: what a constructor accepts is the adapter's own business today, so a
    scenario that needs something at construction asks for it and reports a refusal
    rather than assuming every adapter takes it.
    """

    factory = cast("Callable[..., AbstractHttpAdapter]", type(prototype))
    return factory(**options)


@contextmanager
def _muted_framework_logging() -> Iterator[None]:
    """Silence, for one run, the report the framework makes of a failure a case provokes.

    One case makes a handler raise so that the error model can be certified, and the
    framework logs that at exception level, which is right in an application and
    misleading here: a traceback printed by a passing conformance run reads as the run
    having gone wrong. The previous level is restored, so a caller that configured
    logging keeps what it configured.
    """

    logger = logging.getLogger(PACKAGE_LOGGER)
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(previous_level)


def _run_scenario(
    prototype: AbstractHttpAdapter,
    scenario: ConformanceScenario,
    fixtures: Path,
) -> tuple[ConformanceCheck, ...]:
    """Build one scenario's application on a fresh adapter and answer its cases."""

    adapter = _build_adapter(prototype)
    # The application is not held onto: building it is what registers the compiled routes
    # on the adapter, and the adapter is what the client below drives.
    create_app(scenario.build_module(fixtures), adapter=adapter, versioning=scenario.versioning)
    with cast(Any, adapter.create_test_client()) as client:
        return tuple(_run_case(client, case) for case in scenario.cases)


def _run_lifespan_scenario(prototype: AbstractHttpAdapter) -> tuple[ConformanceCheck, ...]:
    """Certify that the adapter runs the lifespan it was constructed with.

    An adapter is handed its lifespan when it is built rather than when routes are
    registered, so this scenario constructs its own; an adapter whose constructor does
    not accept one fails the case with that as the reason rather than crashing the run.
    """

    recorder = LifespanRecorder()
    try:
        adapter = _build_adapter(prototype, lifespan=recorder)
    except TypeError as error:
        return (_failed_check(LIFESPAN_STARTUP_CASE, f"no lifespan on construction: {error}"),)

    create_app(_build_lifespan_module(recorder), adapter=adapter)
    with cast(Any, adapter.create_test_client()) as client:
        startup = _run_case(client, LIFESPAN_STARTUP_CASE)

    shutdown = _compare(
        LIFESPAN_SHUTDOWN_CASE, _observation(None, {}, _canonical_json(recorder.state()))
    )
    return (startup, shutdown)


def _run_case(client: Any, case: ConformanceCase) -> ConformanceCheck:
    """Send one case's request and compare what came back with what it expects."""

    try:
        response = _send(client, case.request)
    except Exception as error:
        return _failed_check(case, f"{type(error).__name__}: {error}")

    return _compare(case, _observe(response, case.expected))


def _send(client: Any, request: ConformanceRequest) -> Any:
    """Send one request through whichever test client the adapter handed over."""

    return client.request(
        request.method,
        request.path,
        headers=dict(request.headers) or None,
        content=request.content,
        json=request.json_body,
        follow_redirects=request.follow_redirects,
    )


def _observe(response: Any, expected: ResponseObservation) -> ResponseObservation:
    """Reduce one response to the part the comparison is defined over."""

    names = {name for name, _ in expected.headers} | set(ALWAYS_COMPARED_HEADERS)
    headers = {name: (response.headers.get(name) or "").strip() for name in names}
    return _observation(
        response.status_code,
        headers,
        _canonical_body(headers.get("content-type", ""), response.content),
    )


def _canonical_body(content_type: str, content: bytes) -> str:
    """Return the body in the form the comparison is made on."""

    if not content:
        return ""
    if "json" in content_type:
        return _canonical_json(json.loads(content))
    return content.decode("utf-8", errors="replace")


def _compare(case: ConformanceCase, observation: ResponseObservation) -> ConformanceCheck:
    """Judge one observation against the case that produced it."""

    if observation == case.expected:
        return ConformanceCheck(
            name=case.name,
            passed=True,
            detail=f"status={observation.status_code}",
            dimension=case.dimension,
            observation=observation,
        )
    return ConformanceCheck(
        name=case.name,
        passed=False,
        detail="; ".join(describe_difference("expected", case.expected, "observed", observation)),
        dimension=case.dimension,
        observation=observation,
    )


def _failed_check(case: ConformanceCase, detail: str) -> ConformanceCheck:
    return ConformanceCheck(
        name=case.name,
        passed=False,
        detail=detail,
        dimension=case.dimension,
        observation=None,
    )


def describe_difference(
    left_label: str,
    left: ResponseObservation | None,
    right_label: str,
    right: ResponseObservation | None,
) -> tuple[str, ...]:
    """Name every way two observations differ, field by field.

    The report is written for whoever has to act on it, so it names the field, both
    values and which side each came from, rather than printing two records to be
    compared by eye.
    """

    if left == right:
        return ()
    if left is None or right is None:
        return (f"{left_label}={left!r}, {right_label}={right!r}",)

    differences: list[str] = []
    if left.status_code != right.status_code:
        differences.append(
            f"status: {left_label}={left.status_code}, {right_label}={right.status_code}"
        )
    for name in sorted({name for name, _ in left.headers} | {name for name, _ in right.headers}):
        left_value = dict(left.headers).get(name, "")
        right_value = dict(right.headers).get(name, "")
        if left_value != right_value:
            differences.append(
                f"header {name}: {left_label}={left_value!r}, {right_label}={right_value!r}"
            )
    if left.body != right.body:
        differences.append(f"body: {left_label}={left.body!r}, {right_label}={right.body!r}")
    return tuple(differences)


def load_adapter(name: str) -> AbstractHttpAdapter:
    """Return a new adapter by name, for a caller that has only the name."""

    if name == "starlette":
        return StarletteAdapter()
    if name == "asgi":
        return AsgiAdapter()
    raise ValueError(f"Unsupported adapter {name!r}")


ADAPTER_NAMES: tuple[str, ...] = ("starlette", "asgi")

__all__ = (
    "ADAPTER_NAMES",
    "AdapterConformanceResult",
    "ConformanceCase",
    "ConformanceCheck",
    "ConformanceRequest",
    "ConformanceScenario",
    "ResponseObservation",
    "SCENARIOS",
    "describe_difference",
    "evaluate_adapter_conformance",
    "load_adapter",
)
