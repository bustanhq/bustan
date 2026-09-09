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

One case narrows that comparison and it is the only one. A case may name body members it
does not compare *between* adapters, and it must then say which adapter answers what, so
that every adapter is still held to its own document member for member and only the
comparison of one adapter against another steps over the named member. That is for a
difference that is understood and written down rather than one nobody has looked at, and
a case declaring one says whether it is a property of the transports or a defect being
tracked. A body member nobody could name a reason for belongs in neither list: it belongs
in a failing case.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any, Protocol, cast

from .adapters.asgi import AsgiAdapter
from .app.bootstrap import create_app
from .common.decorators.controller import Controller
from .common.decorators.parameter import (
    Body,
    Cookies,
    Header,
    HostParam,
    Ip,
    Param,
    Query,
    UploadedFile,
    UploadedFiles,
    create_param_decorator,
)
from .common.decorators.route import Get, Post
from .contracts import HttpRequest, HttpResponse, NativeHttpRequest
from .kernel.module.decorators import Module
from .pipeline.context import ExecutionContext
from .pipeline.decorators import UseFilters
from .pipeline.filters import ExceptionFilter
from .pipeline.middleware import Middleware, MiddlewareConsumer
from .runtime.adapter import AbstractHttpAdapter, AdapterCapabilities, AdapterRuntime
from .runtime.execution import set_request_limits
from .runtime.params import DEFAULT_MAX_UPLOAD_BYTES, RequestLimits
from .runtime.versioning import VersioningOptions, VersioningType

# The header every case compares, whatever else it names: a response's media type is
# part of the framework's contract rather than one transport's default.
ALWAYS_COMPARED_HEADERS = ("content-type",)

# The logger every part of the framework writes under, whose level one case is run with
# raised; naming it here keeps the reason next to the constant.
PACKAGE_LOGGER = "bustan"

JSON_MEDIA_TYPE = "application/json"
PROBLEM_MEDIA_TYPE = "application/problem+json"

# What a body member two adapters are not compared on becomes, in the reduced observation
# the comparison between them is made over. It is a value rather than a deletion, so that
# a member one adapter stopped sending still reads as a difference from one that sends it,
# and so that a report of some other difference in the same body says on its face why this
# member is not the one being argued about.
UNCOMPARED_BODY_MEMBER = "<differs by adapter; each adapter is held to its own>"


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
    # A body sent as the chunks this returns, which is how a client sends one it has not
    # measured: the request declares no length and the adapter cannot judge the body
    # until it has read it. It is a callable rather than bytes because the one case that
    # needs it sends ten megabytes, and a case is built when this module is imported.
    body_chunks: Callable[[], Iterator[bytes]] | None = None
    follow_redirects: bool = False


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One request and the observation every conforming adapter must produce for it."""

    name: str
    dimension: str
    request: ConformanceRequest
    expected: ResponseObservation
    # What an adapter is held to where it legitimately answers differently, by name. An
    # adapter named here is held to its own document in full, member for member, and an
    # adapter not named is held to ``expected``. Naming one is a statement that the
    # difference is understood and written down, so a case that names any adapter says
    # where the difference comes from and whether it is a property or a tracked defect.
    expected_by_adapter: tuple[tuple[str, ResponseObservation], ...] = ()
    # JSON members of the body this case does not compare *between* adapters. It narrows
    # nothing about what either adapter answers on its own: every adapter is still held
    # to its whole document above, and the status, the headers and every other member
    # are still compared between adapters exactly.
    diverging_body_members: tuple[str, ...] = ()

    def expected_for(self, adapter: str) -> ResponseObservation:
        """Return what *adapter* is held to, which is ``expected`` unless the case names it."""

        return dict(self.expected_by_adapter).get(adapter, self.expected)


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    """The result of one case against one adapter."""

    name: str
    passed: bool
    detail: str
    dimension: str = ""
    observation: ResponseObservation | None = None
    # The same observation reduced to what the comparison between adapters is made over,
    # which is the whole of it for every case that names no diverging member. It is kept
    # beside the observation rather than in place of it, so a report still carries what
    # the adapter actually answered.
    cross_adapter_observation: ResponseObservation | None = None


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
        """Return each case's observation by case name, for comparison across adapters.

        What comes back is each observation reduced to what the comparison between
        adapters is defined over. For every case that names no diverging body member,
        which is all but one of them, that is the observation unchanged.

        A check carrying no reduced observation is compared on the whole of what it
        observed. That is the safe way round: a caller who built a check without one gets
        the comparison it would have had before reductions existed, and a reduction is
        only ever applied where a case asked for one.
        """

        return {
            check.name: (
                check.observation
                if check.cross_adapter_observation is None
                else check.cross_adapter_observation
            )
            for check in self.checks
        }

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
    limits: RequestLimits | None = None


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


def _expect_problem(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
) -> ResponseObservation:
    """The observation a problem-details refusal must produce."""

    return _expect_json(
        {
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": instance,
        },
        status_code=status_code,
        media_type=PROBLEM_MEDIA_TYPE,
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

    @Module(controllers=[_addressing_controller(), _payload_controller(), _upload_controller()])
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

        @Post("/native-request")
        async def read_native_request(self, request: NativeHttpRequest) -> dict[str, object]:
            """Read the body through whichever request object the transport built.

            This is the one spelling that names a transport's own request without naming
            a transport, so it is the one a case shared by every adapter can use: each
            adapter hands over the object it produces, and each is held to reading the
            same body out of it. An adapter whose request cannot stream a body fails the
            case rather than passing it by reading the body some other way.
            """

            return {"streamed": b"".join([chunk async for chunk in request.stream()]).decode()}

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


class ConformanceUpload(Protocol):
    """The part of one uploaded file the two form-body cases hold an adapter to.

    A form's values are typed ``object`` at the request contract, because the framework
    names no upload type of its own: what a handler receives is whatever the transport
    parsed the body into. This protocol is what the cases assert those objects have in
    common, so an adapter whose uploads carry a different name for the file name or the
    part's media type fails the case rather than passing it by returning ``None``.
    """

    filename: str | None
    content_type: str | None
    size: int | None

    async def read(self, size: int = -1) -> bytes:
        raise NotImplementedError


# The boundary and bodies the form-body cases post. They are written out rather than
# built by a client library because every adapter's own test client sends them: a body
# one client assembled would be certifying that client, not the adapter under it.
UPLOAD_BOUNDARY = "bustanconformanceboundary"
UPLOAD_MEDIA_TYPE = f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"

SINGLE_UPLOAD_BODY = (
    f"--{UPLOAD_BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="document"; filename="note.txt"\r\n'
    "Content-Type: text/plain\r\n"
    "\r\n"
    "conformance upload\r\n"
    f"--{UPLOAD_BOUNDARY}--\r\n"
).encode()

MULTIPLE_UPLOAD_BODY = (
    f"--{UPLOAD_BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="documents"; filename="first.txt"\r\n'
    "Content-Type: text/plain\r\n"
    "\r\n"
    "first upload\r\n"
    f"--{UPLOAD_BOUNDARY}\r\n"
    'Content-Disposition: form-data; name="documents"; filename="second.txt"\r\n'
    "Content-Type: text/plain\r\n"
    "\r\n"
    "second upload\r\n"
    f"--{UPLOAD_BOUNDARY}--\r\n"
).encode()


def _upload_controller() -> type[object]:
    """Routes for the two sources read from a parsed form body.

    These are the sources a transport is most likely to differ on, because parsing a
    form is work the framework hands to the adapter entirely: one adapter parses the
    body itself and another delegates to its server library, which may not be able to.
    The routes therefore report what the upload carries rather than only that one
    arrived, so a difference in the file name, the part's media type or its length is a
    failing case instead of an answer that happens to match.
    """

    @Controller("/parameters")
    class UploadController:
        @Post("/file")
        async def read_file(
            self, document: Annotated[ConformanceUpload, UploadedFile]
        ) -> dict[str, object]:
            return {
                "filename": document.filename,
                "content_type": document.content_type,
                "size": document.size,
                "content": (await document.read()).decode("utf-8"),
            }

        @Post("/files")
        async def read_files(
            self, documents: Annotated[list[ConformanceUpload], UploadedFiles]
        ) -> dict[str, object]:
            return {
                "filenames": [document.filename for document in documents],
                "contents": [(await document.read()).decode("utf-8") for document in documents],
            }

    return UploadController


# The parameter sources the suite does not certify, named here because a coverage gap
# nobody wrote down is indistinguishable from an oversight. It is empty, and the test
# that adds it to the certified dimensions and expects every ParameterSource back is
# what keeps it that way: a source dropped from the suite has to be admitted here
# before the coverage test will pass again.
UNCERTIFIED_PARAMETER_SOURCES: tuple[str, ...] = ()


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
        name="parameter_source_file",
        dimension="parameter source: file",
        request=ConformanceRequest(
            method="POST",
            path="/parameters/file",
            headers=(("content-type", UPLOAD_MEDIA_TYPE),),
            content=SINGLE_UPLOAD_BODY,
        ),
        expected=_expect_json(
            {
                "filename": "note.txt",
                "content_type": "text/plain",
                "size": 18,
                "content": "conformance upload",
            }
        ),
    ),
    ConformanceCase(
        name="parameter_source_files",
        dimension="parameter source: files",
        request=ConformanceRequest(
            method="POST",
            path="/parameters/files",
            headers=(("content-type", UPLOAD_MEDIA_TYPE),),
            content=MULTIPLE_UPLOAD_BODY,
        ),
        expected=_expect_json(
            {
                "filenames": ["first.txt", "second.txt"],
                "contents": ["first upload", "second upload"],
            }
        ),
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
        name="parameter_source_native_request",
        # The same source as the neutral spelling beside it: a parameter naming the
        # transport's own request is bound from the request, and what differs is only
        # which of the two objects standing for it the handler is handed.
        dimension="parameter source: request",
        request=ConformanceRequest(
            method="POST",
            path="/parameters/native-request",
            content=b"read from the transport's own request",
        ),
        expected=_expect_json({"streamed": "read from the transport's own request"}),
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


def _expect_not_found(instance: str) -> ResponseObservation:
    """The document a caller receives wherever the framework finds nothing to serve.

    One document rather than one per refusing part. A path nothing is registered at and
    a path whose versions the request does not name are the same answer to the caller,
    who cannot see which part of the framework looked and has nothing to do differently
    for either.
    """

    return _expect_json(
        {
            "type": "https://bustan.dev/problems/not-found",
            "title": "Not Found",
            "status": 404,
            "detail": "Not Found",
            "instance": instance,
            "code": "not-found",
        },
        status_code=404,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _build_refusal_module(_fixtures: Path) -> type[object]:
    """An application whose two routes leave every refusal reachable.

    Between them a request can be turned away three ways before a handler runs: no route
    answers the path, a route answers the path but not the method, and a route answers
    both but serves no version the request asked for.
    """

    @Controller("/orders")
    class OrdersController:
        @Get("/")
        def index(self) -> dict[str, object]:
            return {"orders": []}

    @Controller("/invoices", version="1")
    class InvoicesController:
        @Get("/")
        def index(self) -> dict[str, object]:
            return {"invoices": []}

    @Module(controllers=[OrdersController, InvoicesController])
    class RefusalModule:
        pass

    return RefusalModule


# The refusals a caller meets before any handler runs. Each is compared on the media
# type as well as the status, because a status alone cannot tell a problem document from
# a line of text: two transports answering 404 and 405 with the same numbers and
# different shapes agree on every figure this suite would otherwise read, and a caller
# written against the documented error model breaks on whichever shape it did not
# expect. These are the errors an API returns most often, so they are the ones that
# shape has to hold for.
REFUSAL_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="router_refuses_an_unmatched_route_with_problem_details",
        dimension="refusal before a handler",
        request=ConformanceRequest(path="/no-route-is-registered-here"),
        expected=_expect_not_found("/no-route-is-registered-here"),
    ),
    ConformanceCase(
        name="router_refuses_a_wrong_method_with_problem_details",
        dimension="refusal before a handler",
        request=ConformanceRequest(method="POST", path="/orders"),
        # ``allow`` is named because a 405 without it tells a client it guessed wrong
        # without telling it what to send instead, and because the two transports work
        # the header out separately: unnamed, it was free to differ between them and did.
        expected=_expect_json(
            {
                "type": "https://bustan.dev/problems/method-not-allowed",
                "title": "Method Not Allowed",
                "status": 405,
                "detail": "Method Not Allowed",
                "instance": "/orders",
                "code": "method-not-allowed",
            },
            status_code=405,
            media_type=PROBLEM_MEDIA_TYPE,
            headers={"allow": "GET, HEAD"},
        ),
    ),
    ConformanceCase(
        name="version_dispatcher_refuses_an_unknown_version_with_problem_details",
        dimension="refusal before a handler",
        request=ConformanceRequest(path="/invoices", headers=(("X-API-Version", "9"),)),
        expected=_expect_not_found("/invoices"),
    ),
)


# What the request-limit scenario's application accepts as a body, and a body two bytes
# past it. The limit is the largest body the framework's own limits accept anywhere under
# their defaults, so a body over it is past every bound those defaults set. That is what
# makes these cases worth comparing: a transport keeping a byte ceiling of its own below
# this answers them its own way, and the caller is told which of the two refused only by
# reading the status.
REQUEST_LIMIT_MAX_BODY_BYTES = DEFAULT_MAX_UPLOAD_BYTES
OVER_LIMIT_BODY_BYTES = REQUEST_LIMIT_MAX_BODY_BYTES + 2

# What the same application accepts as an upload, and a form two bytes past it. It is
# deliberately not the body figure: a form is read under the upload bound, so two figures
# that differ are what make a transport reading a form under the wrong one fail these
# cases rather than pass them by arithmetic. It is the higher of the two because a route
# that accepts uploads is expected to carry more than one that binds a JSON document, and
# it is only a megabyte higher so that a form past it is still inside any byte ceiling a
# transport keeps of its own, leaving the application's figure to answer the caller.
REQUEST_LIMIT_MAX_UPLOAD_BYTES = REQUEST_LIMIT_MAX_BODY_BYTES + 1024 * 1024
OVER_LIMIT_FORM_BYTES = REQUEST_LIMIT_MAX_UPLOAD_BYTES + 2

_OVER_LIMIT_BODY_PREFIX = b'{"title":"'
_OVER_LIMIT_BODY_SUFFIX = b'"}'


def _over_limit_body() -> Iterator[bytes]:
    """Yield a JSON body past the request limit, as one chunk of undeclared length.

    It is built when the case runs rather than held as a constant, because it is ten
    megabytes and one case needs it: importing this suite should not cost that to a
    caller who never sends it.
    """

    filler = OVER_LIMIT_BODY_BYTES - len(_OVER_LIMIT_BODY_PREFIX) - len(_OVER_LIMIT_BODY_SUFFIX)
    yield _OVER_LIMIT_BODY_PREFIX + b"x" * filler + _OVER_LIMIT_BODY_SUFFIX


def _over_limit_form() -> Iterator[bytes]:
    """Yield a multipart body past the upload limit, of undeclared length.

    It carries one file part, because that is the part a transport delegating to a
    parser of its own has no total bound on: such a parser bounds a part it holds in
    memory and spools a file part onto disk instead, so a form nobody set a bound on is
    a body of the caller's choosing written into the process. Like the body above it is
    built when the case runs rather than held as a constant.
    """

    head = (
        f"--{UPLOAD_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="document"; filename="over.bin"\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
    ).encode()
    tail = f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()
    yield head
    yield b"x" * (OVER_LIMIT_FORM_BYTES - len(head) - len(tail))
    yield tail


def _build_request_limit_module(_fixtures: Path) -> type[object]:
    """Routes that bind a body and an upload, run under the scenario's declared bounds."""

    @Controller("/limits")
    class RequestLimitController:
        @Post("/notes")
        def create_note(self, title: Annotated[str, Body("title")]) -> dict[str, object]:
            return {"length": len(title)}

        @Post("/uploads")
        async def receive_upload(
            self, document: Annotated[ConformanceUpload, UploadedFile]
        ) -> dict[str, object]:
            return {"filename": document.filename, "content": (await document.read()).decode()}

    @Module(controllers=[RequestLimitController])
    class RequestLimitModule:
        pass

    return RequestLimitModule


# The sentence every adapter gives when it refuses a body of undeclared length.
#
# A body that declares no length cannot be judged before it is read, so an adapter refuses
# it at the chunk that carries it past the limit the application declared. It never
# receives the rest, so it cannot say how many bytes were sent and does not claim to. That
# is why the sentence names the limit and not the body: an adapter that could report the
# body's size would be one that had read all of it, which is the memory the limit exists
# to refuse to spend.
STREAMED_OVER_LIMIT_DETAIL = (
    f"The request body exceeds the {REQUEST_LIMIT_MAX_BODY_BYTES} byte limit"
)

# The same sentence for a form, which names the upload bound because that is the figure
# a form is read under.
STREAMED_OVER_UPLOAD_LIMIT_DETAIL = (
    f"The request body exceeds the {REQUEST_LIMIT_MAX_UPLOAD_BYTES} byte limit"
)


REQUEST_LIMIT_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        name="request_limit_serves_a_body_within_the_limit",
        dimension="request limit: body",
        request=ConformanceRequest(
            method="POST", path="/limits/notes", json_body={"title": "conformance"}
        ),
        expected=_expect_json({"length": 11}),
    ),
    ConformanceCase(
        name="request_limit_refuses_a_declared_body_over_the_limit",
        dimension="request limit: declared body",
        request=ConformanceRequest(
            method="POST",
            path="/limits/notes",
            # The declared length is the whole of what this case is about, so the body
            # sent is two bytes: a refusal that arrives anyway is one made without
            # reading, which is what refusing on the declared length is worth.
            headers=(
                ("content-type", JSON_MEDIA_TYPE),
                ("content-length", str(OVER_LIMIT_BODY_BYTES)),
            ),
            content=b"{}",
        ),
        expected=_expect_problem(
            413,
            "Content Too Large",
            f"The request body declares {OVER_LIMIT_BODY_BYTES} bytes, "
            f"over the {REQUEST_LIMIT_MAX_BODY_BYTES} byte limit",
            "/limits/notes",
        ),
    ),
    ConformanceCase(
        name="request_limit_refuses_a_streamed_body_over_the_limit",
        dimension="request limit: streamed body",
        request=ConformanceRequest(
            method="POST",
            path="/limits/notes",
            headers=(("content-type", JSON_MEDIA_TYPE),),
            body_chunks=_over_limit_body,
        ),
        expected=_expect_problem(
            413, "Content Too Large", STREAMED_OVER_LIMIT_DETAIL, "/limits/notes"
        ),
    ),
    ConformanceCase(
        name="request_limit_serves_a_form_within_the_limit",
        dimension="request limit: form",
        request=ConformanceRequest(
            method="POST",
            path="/limits/uploads",
            headers=(("content-type", UPLOAD_MEDIA_TYPE),),
            content=SINGLE_UPLOAD_BODY,
        ),
        expected=_expect_json({"filename": "note.txt", "content": "conformance upload"}),
    ),
    ConformanceCase(
        name="request_limit_refuses_a_streamed_form_over_the_limit",
        dimension="request limit: streamed form",
        request=ConformanceRequest(
            method="POST",
            path="/limits/uploads",
            headers=(("content-type", UPLOAD_MEDIA_TYPE),),
            body_chunks=_over_limit_form,
        ),
        expected=_expect_problem(
            413, "Content Too Large", STREAMED_OVER_UPLOAD_LIMIT_DETAIL, "/limits/uploads"
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
# router answers it; under the other two strategies the route exists and the framework's
# own version dispatcher answers. Two parts of the framework, one document: which of
# them looked is the framework's business, and a caller that had to tell them apart
# would be handling two refusals for one condition. The path each names as the instance
# is what still separates them, and it is the path the caller asked for.
TRANSPORT_NOT_FOUND = _expect_not_found("/v3/reports")
DISPATCHER_NOT_FOUND = _expect_not_found("/reports")

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


@dataclass(slots=True)
class ModuleLifecycleRecord:
    """What the module graph's own lifecycle hooks have run, counted as they run.

    Nothing here is a lifespan. The record is written only by hooks the framework
    invokes through the lifespan it built and handed the adapter, so a count that has
    not moved means the module graph never started or never stopped, and no substitute
    the suite wrote can move it in the framework's place.
    """

    module_inits: int = 0
    application_shutdowns: int = 0

    def state(self) -> dict[str, object]:
        """What the module graph has done so far, as the cases compare it."""

        return {
            "module_inits": self.module_inits,
            "application_shutdowns": self.application_shutdowns,
        }


def _build_lifecycle_module(record: ModuleLifecycleRecord) -> type[object]:
    """An application whose module keeps lifecycle hooks and whose route reports them."""

    @Controller("/lifespan")
    class LifespanController:
        @Get("/")
        def read(self) -> dict[str, object]:
            return record.state()

    @Module(controllers=[LifespanController])
    class LifespanModule:
        def on_module_init(self) -> None:
            record.module_inits += 1

        def on_application_shutdown(self, _signal: str | None) -> None:
            record.application_shutdowns += 1

    return LifespanModule


class _LifespanAdapterFactory:
    """Build the adapter under test out of the runtime the framework hands a factory.

    A factory is how an adapter receives the lifespan the framework built, and the port
    declares no constructor, so asking for it is a request an adapter may refuse. The
    refusal is remembered because the framework, not the suite, calls the factory: the
    ``TypeError`` a refusal raises arrives at the caller from application assembly,
    where other causes raise the same type, and only a call that recorded a refusal here
    may be reported as an adapter failing the case.
    """

    def __init__(self, adapter_class: Callable[..., AbstractHttpAdapter]) -> None:
        self._adapter_class = adapter_class
        self.refusal: TypeError | None = None

    def __call__(self, runtime: AdapterRuntime) -> AbstractHttpAdapter:
        try:
            return self._adapter_class(lifespan=runtime.lifespan)
        except TypeError as error:
            self.refusal = error
            raise


LIFESPAN_STARTUP_CASE = ConformanceCase(
    name="lifespan_startup_runs_before_the_first_request",
    dimension="lifespan",
    request=ConformanceRequest(path="/lifespan"),
    expected=_expect_json({"module_inits": 1, "application_shutdowns": 0}),
)

LIFESPAN_SHUTDOWN_CASE = ConformanceCase(
    name="lifespan_shutdown_runs_after_the_last_request",
    dimension="lifespan",
    request=ConformanceRequest(path="/lifespan"),
    expected=_observation(
        None, {}, _canonical_json({"module_inits": 1, "application_shutdowns": 1})
    ),
)


SCENARIOS: tuple[ConformanceScenario, ...] = (
    ConformanceScenario("parameters", _build_parameter_module, PARAMETER_CASES),
    ConformanceScenario("responses", _build_response_module, RESPONSE_CASES),
    ConformanceScenario("middleware", _build_middleware_module, MIDDLEWARE_CASES),
    ConformanceScenario("exception filters", _build_filter_module, FILTER_CASES),
    ConformanceScenario(
        "refusals",
        _build_refusal_module,
        REFUSAL_CASES,
        VersioningOptions(type=VersioningType.HEADER),
    ),
    ConformanceScenario(
        "request limits",
        _build_request_limit_module,
        REQUEST_LIMIT_CASES,
        limits=RequestLimits(
            max_body_bytes=REQUEST_LIMIT_MAX_BODY_BYTES,
            max_upload_bytes=REQUEST_LIMIT_MAX_UPLOAD_BYTES,
        ),
    ),
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


def _build_adapter(prototype: AbstractHttpAdapter) -> AbstractHttpAdapter:
    """Return a new adapter of the prototype's class, built the way the port allows.

    The port says nothing about how an adapter is constructed, and the only thing it
    can be assumed to accept is nothing at all, which is what a scenario needing no
    lifespan asks for.
    """

    factory = cast("Callable[..., AbstractHttpAdapter]", type(prototype))
    return factory()


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
    # The application is kept only long enough to declare the scenario's limits on it:
    # building it is what registers the compiled routes on the adapter, and the adapter
    # is what the client below drives.
    application = create_app(
        scenario.build_module(fixtures), adapter=adapter, versioning=scenario.versioning
    )
    if scenario.limits is not None:
        set_request_limits(application, scenario.limits)
    with cast(Any, adapter.create_test_client()) as client:
        return tuple(_run_case(client, case, adapter=adapter.name) for case in scenario.cases)


def _run_lifespan_scenario(prototype: AbstractHttpAdapter) -> tuple[ConformanceCheck, ...]:
    """Certify that the adapter runs the lifespan the framework built for the module graph.

    The adapter is not built here and then handed over. It is built by the framework,
    from a factory, so the lifespan it receives is the one that starts and stops the
    module graph and no substitute stands in for it: what the cases read is the count
    the graph's own hooks kept. An adapter whose constructor will not take a lifespan
    fails the case with that as the reason rather than crashing the run.
    """

    record = ModuleLifecycleRecord()
    factory = _LifespanAdapterFactory(cast("Callable[..., AbstractHttpAdapter]", type(prototype)))
    try:
        application = create_app(_build_lifecycle_module(record), adapter=factory)
    except TypeError as error:
        # Assembly raises TypeError for its own reasons too, so only the refusal the
        # factory recorded is read as this adapter failing the case.
        if factory.refusal is None:
            raise
        return (_failed_check(LIFESPAN_STARTUP_CASE, f"no lifespan on construction: {error}"),)

    served = application.get_http_adapter()
    with cast(Any, served.create_test_client()) as client:
        startup = _run_case(client, LIFESPAN_STARTUP_CASE, adapter=served.name)

    shutdown = _compare(
        LIFESPAN_SHUTDOWN_CASE, _observation(None, {}, _canonical_json(record.state()))
    )
    return (startup, shutdown)


def _run_case(client: Any, case: ConformanceCase, *, adapter: str = "") -> ConformanceCheck:
    """Send one case's request and compare what came back with what it expects.

    *adapter* names which adapter is answering, because a case may hold one adapter to a
    different document from another where the two legitimately differ.
    """

    try:
        response = _send(client, case.request)
    except Exception as error:
        return _failed_check(case, f"{type(error).__name__}: {error}")

    return _compare(case, _observe(response, case.expected_for(adapter)), adapter=adapter)


def _send(client: Any, request: ConformanceRequest) -> Any:
    """Send one request through whichever test client the adapter handed over."""

    content = request.content if request.body_chunks is None else request.body_chunks()
    return client.request(
        request.method,
        request.path,
        headers=dict(request.headers) or None,
        content=content,
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


def _compare(
    case: ConformanceCase, observation: ResponseObservation, *, adapter: str = ""
) -> ConformanceCheck:
    """Judge one observation against the document *adapter* is held to for this case."""

    expected = case.expected_for(adapter)
    compared = _reduce_for_comparison(case, observation)
    if observation == expected:
        return ConformanceCheck(
            name=case.name,
            passed=True,
            detail=f"status={observation.status_code}",
            dimension=case.dimension,
            observation=observation,
            cross_adapter_observation=compared,
        )
    return ConformanceCheck(
        name=case.name,
        passed=False,
        detail="; ".join(describe_difference("expected", expected, "observed", observation)),
        dimension=case.dimension,
        observation=observation,
        cross_adapter_observation=compared,
    )


def _reduce_for_comparison(
    case: ConformanceCase, observation: ResponseObservation
) -> ResponseObservation:
    """Reduce one observation to what the comparison between adapters is made over.

    For a case that names no diverging member this is the observation itself, which is
    every case but the one whose adapters refuse at different layers and can therefore
    only report different detail. There, the members the case named are replaced on both
    sides and everything else in the document is still compared exactly, so a divergence
    anywhere but in the named member is still a failure rather than a silence.
    """

    if not case.diverging_body_members or not observation.body:
        return observation
    try:
        payload = json.loads(observation.body)
    except ValueError:
        return observation
    if not isinstance(payload, dict):
        return observation
    members = cast("dict[str, object]", payload)
    return ResponseObservation(
        status_code=observation.status_code,
        headers=observation.headers,
        body=_canonical_json(
            {
                name: (UNCOMPARED_BODY_MEMBER if name in case.diverging_body_members else value)
                for name, value in members.items()
            }
        ),
    )


def _failed_check(case: ConformanceCase, detail: str) -> ConformanceCheck:
    return ConformanceCheck(
        name=case.name,
        passed=False,
        detail=detail,
        dimension=case.dimension,
        observation=None,
        cross_adapter_observation=None,
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


_STARLETTE_EXTRA_MISSING = (
    "The starlette adapter needs the starlette extra, which is not installed.\n\n"
    "Install it with:\n\n"
    "    pip install 'bustan[starlette]'"
)


def load_adapter(name: str) -> AbstractHttpAdapter:
    """Return a new adapter by name, for a caller that has only the name.

    A name no adapter answers to is a ``ValueError``, and a named adapter whose optional
    dependency is absent is an ``ImportError`` saying what to install: the caller can
    tell a typo from an incomplete installation without reading a traceback. The import
    is deferred for that second reason as well as the first - importing this module must
    not require a web server, or the half of the suite that needs none could not be run
    without one installed.
    """

    if name == "starlette":
        try:
            from .adapters.starlette import StarletteAdapter
        except ModuleNotFoundError as error:
            # Only the absent extra becomes advice. Anything else missing underneath the
            # adapter is a real import failure, and an install instruction would send the
            # reader to fix the one thing that is not wrong.
            if error.name not in {"starlette", "uvicorn"}:
                raise
            raise ImportError(_STARLETTE_EXTRA_MISSING) from error
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
    "ConformanceUpload",
    "ResponseObservation",
    "SCENARIOS",
    "UNCOMPARED_BODY_MEMBER",
    "describe_difference",
    "evaluate_adapter_conformance",
    "load_adapter",
)
