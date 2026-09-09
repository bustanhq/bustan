"""Request parameter analysis and runtime binding helpers.

This module also declares :class:`RequestLimits`, the bounds one application puts on a
single request. They live here because binding is where a request body is first read
and is therefore where the body and upload limits are enforced; the timeout and the
thread ceiling in the same value type are read by the execution engine, which already
depends on this module and so can hold the whole set as one object.
"""

from __future__ import annotations

import collections.abc
import inspect
import sys
from dataclasses import InitVar, dataclass, is_dataclass
from enum import StrEnum
from types import NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from ..common.decorators.parameter import (
    _BodyMarker,
    _CookiesMarker,
    _CustomParameterDecorator,
    _CustomParameterMarker,
    _HeaderMarker,
    _HostParamMarker,
    _IpMarker,
    _MarkerCallable,
    _ParamMarker,
    _QueryMarker,
    _UploadedFileMarker,
    _UploadedFilesMarker,
)
from ..common.metadata import ControllerRouteDefinition, get_controller_metadata
from ..contracts import HttpRequest, as_http_request, names_native_request
from ..contracts.requests import produces_native_request
from ..kernel.errors import BustanError, ParameterBindingError, RouteDefinitionError
from ..kernel.utils import _qualname

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ..contracts import AbstractHttpAdapter, AdapterRoute
    from ..kernel.ioc.planning.container_plan import NativeRequestDependency
    from ..pipeline.context import ExecutionContext
    from .execution import ExecutionPlan

_MISSING = object()
_NO_BODY = object()
_UNSET_BODY = object()

# The bounds an application that configures nothing still runs under. Each is finite,
# because the alternative is not "no limit" but "the limit the caller picks": a body
# size, a number of uploaded parts and a running time are all chosen by whoever sent
# the request, and all three are paid for in this process's memory and threads.
DEFAULT_MAX_BODY_BYTES = 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_UPLOAD_FILES = 20
DEFAULT_TIMEOUT_SECONDS = 30.0
# anyio offloads a synchronous handler onto its own default limiter, which allows this
# many threads. Matching it means an application that configures nothing keeps exactly
# the concurrency it had, and one that configures anything no longer has to reach into
# anyio to say so.
DEFAULT_SYNC_HANDLER_THREADS = 40


class RequestBodyTooLargeError(BustanError):
    """Raised when a request carries more body bytes or parts than the limit allows."""


@dataclass(frozen=True, slots=True)
class RequestLimits:
    """What one application will spend on a single request.

    ``max_body_bytes`` bounds the body read to bind ordinary parameters and
    ``max_upload_bytes`` the body read to parse a multipart form; they are separate
    because a route that accepts uploads is expected to carry more than a JSON
    document, and giving both the larger bound would raise the ceiling on every route.
    ``max_upload_files`` bounds how many parts of a form may bind to one parameter.
    ``timeout_seconds`` is the wall clock one request may take before it is abandoned
    and answered through the route's exception filters. ``sync_handler_threads`` is how
    many synchronous handlers may run at once.

    Every bound has a finite default. ``None`` removes one for a deployment that has
    measured that it needs to, and is never what an application gets by not choosing.

    A synchronous handler runs on a thread and Python cannot interrupt one, so
    ``timeout_seconds`` is enforced for such a handler only once it returns; what bounds
    a synchronous handler that never returns is ``sync_handler_threads``, which caps how
    many of them can be occupying threads at the same time.
    """

    max_body_bytes: int | None = DEFAULT_MAX_BODY_BYTES
    max_upload_bytes: int | None = DEFAULT_MAX_UPLOAD_BYTES
    max_upload_files: int | None = DEFAULT_MAX_UPLOAD_FILES
    timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS
    sync_handler_threads: int = DEFAULT_SYNC_HANDLER_THREADS

    def __post_init__(self) -> None:
        # A limit of zero or less refuses every request rather than bounding it, so it
        # is a configuration mistake worth naming where it is written rather than once
        # per request in a log nobody reads.
        for field_name in (
            "max_body_bytes",
            "max_upload_bytes",
            "max_upload_files",
            "timeout_seconds",
            "sync_handler_threads",
        ):
            value = cast(float | None, getattr(self, field_name))
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be greater than zero, got {value!r}")


class ParameterSource(StrEnum):
    """Supported sources for handler parameters."""

    REQUEST = "request"
    CUSTOM = "custom"
    PATH = "path"
    QUERY = "query"
    BODY = "body"
    HEADER = "header"
    COOKIE = "cookie"
    IP = "ip"
    HOST = "host"
    FILE = "file"
    FILES = "files"
    INFERRED = "inferred"


class ParameterBindingMode(StrEnum):
    """Supported parameter binding policies."""

    INFER = "infer"
    EXPLICIT = "explicit"
    STRICT = "strict"


class ValidationMode(StrEnum):
    """Supported validation policies compiled onto a handler plan."""

    AUTO = "auto"
    EXPLICIT = "explicit"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class ParameterBinding:
    """Compiled binding rule for one handler parameter."""

    name: str
    kind: inspect._ParameterKind
    source: ParameterSource
    annotation: object
    has_default: bool
    default: object = None
    alias: str | None = None  # Explicit name override (e.g. Header("x-api-token"))
    pipes: tuple[object, ...] = ()
    custom_resolver: object | None = None
    custom_data: object = None


@dataclass(frozen=True, slots=True)
class HandlerBindingPlan:
    """Compiled binding plan for a controller handler."""

    controller: type[object]
    handler_name: str
    parameters: tuple[ParameterBinding, ...]
    inferred_parameter_names: tuple[str, ...]
    mode: ParameterBindingMode = ParameterBindingMode.INFER
    body_model: type[object] | None = None
    validation_mode: ValidationMode = ValidationMode.AUTO
    validate_custom_decorators: bool = False


@dataclass(frozen=True, slots=True)
class BoundParameter:
    """Concrete bound value paired with its binding metadata."""

    binding: ParameterBinding
    value: object


def compile_parameter_bindings(
    controller_cls: type[object],
    route_definition: ControllerRouteDefinition,
) -> HandlerBindingPlan:
    """Compile a handler signature into a reusable binding plan."""

    controller_metadata = get_controller_metadata(controller_cls, inherit=True)
    binding_mode = _resolve_binding_mode(
        controller_metadata.binding_mode if controller_metadata else "infer"
    )
    validation_mode = _resolve_validation_mode(
        controller_metadata.validation_mode if controller_metadata else "auto"
    )
    validate_custom_decorators = (
        controller_metadata.validate_custom_decorators if controller_metadata else False
    )
    signature = inspect.signature(route_definition.handler)
    type_hints = _resolve_handler_parameter_annotations(controller_cls, route_definition)
    path_parameter_names = _extract_path_parameter_names(route_definition.route.path)
    parameters = [
        parameter for parameter in signature.parameters.values() if parameter.name != "self"
    ]
    unresolved_parameter_count = sum(
        1
        for parameter in parameters
        if not _has_explicit_source(
            parameter=parameter,
            annotation=type_hints.get(parameter.name, parameter.annotation),
            path_parameter_names=path_parameter_names,
        )
    )

    bindings: list[ParameterBinding] = []
    inferred_parameter_names: list[str] = []

    for parameter in parameters:
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise ParameterBindingError(
                f"{_qualname(controller_cls)}.{route_definition.handler_name} uses unsupported "
                f"variadic parameter {parameter.name!r}"
            )

        # Strip Annotated wrapper and check for explicit marker
        annotation = type_hints.get(parameter.name, parameter.annotation)
        real_annotation, marker = _extract_marker(annotation)

        source, inferred_from_body = _compile_parameter_source(
            controller_cls=controller_cls,
            handler_name=route_definition.handler_name,
            parameter=parameter,
            annotation=real_annotation,
            marker=marker,
            path_parameter_names=path_parameter_names,
            method=route_definition.route.method,
            binding_mode=binding_mode,
            unresolved_parameter_count=unresolved_parameter_count,
        )
        if inferred_from_body:
            inferred_parameter_names.append(parameter.name)

        alias: str | None = None
        if marker is not None and hasattr(marker, "alias") and isinstance(marker.alias, str):
            alias = marker.alias
        annotation = real_annotation
        custom_resolver, custom_data = _custom_parameter_resolver(marker)

        bindings.append(
            ParameterBinding(
                name=parameter.name,
                kind=parameter.kind,
                source=source,
                annotation=annotation,
                has_default=parameter.default is not inspect.Signature.empty,
                default=None if parameter.default is inspect.Signature.empty else parameter.default,
                alias=alias,
                custom_resolver=custom_resolver,
                custom_data=custom_data,
            )
        )

    return HandlerBindingPlan(
        controller=controller_cls,
        handler_name=route_definition.handler_name,
        parameters=tuple(bindings),
        inferred_parameter_names=tuple(inferred_parameter_names),
        mode=binding_mode,
        body_model=_infer_body_model(tuple(bindings), tuple(inferred_parameter_names)),
        validation_mode=validation_mode,
        validate_custom_decorators=validate_custom_decorators,
    )


def refuse_foreign_native_requests(
    adapter: AbstractHttpAdapter,
    routes: Iterable[AdapterRoute],
    *,
    constructor_dependencies: Iterable[NativeRequestDependency] = (),
) -> None:
    """Refuse any parameter naming a request type *adapter* does not produce.

    A parameter that names a transport's own request type is handed
    :attr:`HttpRequest.native_request`, so the annotation is true only where the adapter
    serving the application is the one that builds that type. Every transport's request
    has the same shape, so the annotation cannot say on its own which transport it named;
    the adapter declares the type it produces, and the two are compared by identity.

    Two surfaces can name one, and both are judged here under the same rule. A handler
    parameter is named by ``routes``, the compiled plan the adapter will be asked to
    register. A constructor parameter of a provider or a controller is named by
    ``constructor_dependencies``, which the container plan reports because it settled
    those parameters to the same object without yet knowing which transport would build
    it. Passing neither judges nothing, which is what a caller holding no such plan
    should get.

    This is a property of how an application was wired rather than of any one request,
    so it is answered where an adapter and the plans it will serve first meet, before any
    server starts. Left to the request, the same mistake is answered on every call -
    with another transport's object, or with a query parameter nobody wrote - and reads
    as a fault in the application rather than in how it was wired.

    Raises ``RouteDefinitionError`` naming the parameter, what it asked for and what the
    adapter produces.
    """

    for site, annotation in _native_request_parameters(routes, constructor_dependencies):
        if produces_native_request(adapter.native_request_type, annotation):
            continue
        raise RouteDefinitionError(_foreign_native_request_message(adapter, site, annotation))


def _native_request_parameters(
    routes: Iterable[AdapterRoute],
    constructor_dependencies: Iterable[NativeRequestDependency],
) -> Iterator[tuple[str, object]]:
    """Yield every parameter naming a transport's request, with where it was written.

    The site is the phrase an error names the parameter by, and it is built here rather
    than by the caller so that a handler parameter and a constructor parameter are
    refused in one wording. Handlers are yielded first because a route is the surface an
    author reads a refusal against most readily.
    """

    for route in routes:
        for binding_plan in _handler_binding_plans(route):
            for binding in binding_plan.parameters:
                if binding.source is not ParameterSource.REQUEST:
                    continue
                if not names_native_request(binding.annotation):
                    continue
                handler = f"{_qualname(binding_plan.controller)}.{binding_plan.handler_name}"
                yield f"{handler} parameter {binding.name!r}", binding.annotation

    for dependency in constructor_dependencies:
        owner = f"{_qualname(dependency.target)}.__init__"
        yield f"{owner} parameter {dependency.parameter!r}", dependency.annotation


def _handler_binding_plans(route: AdapterRoute) -> tuple[HandlerBindingPlan, ...]:
    """Return the binding plans of every handler one compiled route serves.

    A route the framework compiled carries the execution plans it was compiled from. One
    built by hand - by a test, or by an adapter registering a route of its own - carries
    none, and so names no handler parameter for anything to check.
    """

    plans = cast("tuple[ExecutionPlan, ...]", getattr(route, "execution_plans", ()))
    return tuple(plan.binding_plan for plan in plans)


def _foreign_native_request_message(
    adapter: AbstractHttpAdapter,
    site: str,
    annotation: object,
) -> str:
    """Return the refusal for a parameter the serving adapter cannot satisfy.

    *site* names where the parameter was written, and is the only part that differs
    between the two surfaces: the mistake and the way out of it are the same one.
    """

    produced = adapter.native_request_type
    produces = (
        f"produces {_qualname(produced)}"
        if produced is not None
        else "produces no request type of its own"
    )
    return (
        f"{site} names {_qualname(annotation)}, which "
        f"{type(adapter).__name__} does not produce: it {produces}. Annotate HttpRequest and "
        "reach for request.native_request, or serve this application through the adapter "
        "whose request type the parameter names."
    )


async def bind_handler_arguments(
    request: HttpRequest | object,
    binding_plan: HandlerBindingPlan,
    context: ExecutionContext | None = None,
    limits: RequestLimits | None = None,
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Bind handler parameters and split them into args/kwargs."""

    return separate_bound_parameters(
        await bind_handler_parameters(request, binding_plan, context, limits)
    )


async def bind_handler_parameters(
    request: HttpRequest | object,
    binding_plan: HandlerBindingPlan,
    context: ExecutionContext | None = None,
    limits: RequestLimits | None = None,
) -> tuple[BoundParameter, ...]:
    """Bind every parameter in a compiled handler plan.

    ``limits`` are the bounds the request is read under; leaving them out applies the
    defaults rather than none, so a caller that has no application to ask is still not
    a way to read an unbounded body.
    """

    http_request = as_http_request(request)
    effective_limits = limits if limits is not None else RequestLimits()
    bound_parameters: list[BoundParameter] = []
    request_body: object = _UNSET_BODY

    for binding in binding_plan.parameters:
        value, request_body = await _bind_parameter(
            http_request,
            binding_plan,
            binding,
            request_body,
            context,
            limits=effective_limits,
        )
        bound_parameters.append(BoundParameter(binding=binding, value=value))

    return tuple(bound_parameters)


def separate_bound_parameters(
    bound_parameters: tuple[BoundParameter, ...],
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Split bound parameter values into positional and keyword groups."""

    positional_arguments: list[object] = []
    keyword_arguments: dict[str, object] = {}

    for bound_parameter in bound_parameters:
        binding = bound_parameter.binding
        if binding.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional_arguments.append(bound_parameter.value)
        else:
            keyword_arguments[binding.name] = bound_parameter.value

    return tuple(positional_arguments), keyword_arguments


async def _bind_parameter(
    request: HttpRequest,
    binding_plan: HandlerBindingPlan,
    binding: ParameterBinding,
    request_body: object,
    context: ExecutionContext | None = None,
    *,
    limits: RequestLimits | None = None,
) -> tuple[object, object]:
    effective_limits = limits if limits is not None else RequestLimits()
    if binding.source is ParameterSource.REQUEST:
        if names_native_request(binding.annotation):
            # The parameter named the transport's own request type, so it is handed
            # that object rather than the contract wrapped around it.
            return request.native_request, request_body
        return request, request_body

    if binding.source is ParameterSource.CUSTOM:
        if context is None:
            raise _parameter_error(
                f"Custom parameter decorator {binding.name!r} requires an active execution context",
                field=binding.name,
                source="custom parameter decorator",
                reason="execution context required",
            )
        if not callable(binding.custom_resolver):
            raise _parameter_error(
                f"Custom parameter decorator {binding.name!r} is missing a resolver",
                field=binding.name,
                source="custom parameter decorator",
                reason="resolver missing",
            )

        parameter_context = context.with_parameter(
            name=binding.name,
            source=ParameterSource.CUSTOM.value,
            annotation=binding.annotation,
            value=None,
            validation_mode=binding_plan.validation_mode.value,
            validate_custom_decorators=binding_plan.validate_custom_decorators,
        )
        custom_resolver = cast(
            collections.abc.Callable[[object | None, object], object],
            binding.custom_resolver,
        )
        resolved_value = custom_resolver(binding.custom_data, parameter_context)
        if inspect.isawaitable(resolved_value):
            resolved_value = await resolved_value

        if resolved_value is _MISSING:
            if binding.has_default:
                return binding.default, request_body
            raise _parameter_error(
                f"Missing required custom parameter {binding.name!r}",
                field=binding.name,
                source="custom parameter decorator",
                reason="missing",
            )

        return (
            _coerce_value(
                resolved_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="custom parameter decorator",
            ),
            request_body,
        )

    if binding.source is ParameterSource.PATH:
        raw_value = request.path_params.get(binding.name, _MISSING)
        if raw_value is _MISSING:
            raise _parameter_error(
                f"Missing required path parameter {binding.name!r}",
                field=binding.name,
                source="path parameter",
                reason="missing",
            )
        return (
            _coerce_value(
                raw_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="path parameter",
            ),
            request_body,
        )

    if binding.source is ParameterSource.COOKIE:
        lookup_name = binding.alias or binding.name
        if binding.alias is None:
            _origin = get_origin(binding.annotation)
            _actual = _origin if _origin is not None else binding.annotation
            if isinstance(_actual, type) and issubclass(_actual, collections.abc.Mapping):
                return dict(request.cookies), request_body
        cookie_value = request.cookies.get(lookup_name)
        if cookie_value is not None:
            return (
                _coerce_value(
                    cookie_value,
                    annotation=binding.annotation,
                    parameter_name=binding.name,
                    source_description="cookie",
                ),
                request_body,
            )
        if binding.has_default:
            return binding.default, request_body
        return None, request_body

    if binding.source is ParameterSource.IP:
        host = request.client.host if request.client is not None else None
        if host is not None:
            return host, request_body
        if binding.has_default:
            return binding.default, request_body
        return None, request_body

    if binding.source is ParameterSource.HOST:
        host_header = request.headers.get(binding.alias or "host")
        if host_header is not None:
            return host_header, request_body
        if binding.has_default:
            return binding.default, request_body
        return None, request_body

    if binding.source in (ParameterSource.FILE, ParameterSource.FILES):
        _refuse_declared_body(request, effective_limits.max_upload_bytes, source="upload")
        form = await request.form()
        lookup_name = binding.alias or binding.name
        if binding.source is ParameterSource.FILE:
            file_value = form.get(lookup_name)
            if file_value is not None:
                return file_value, request_body
            if binding.has_default:
                return binding.default, request_body
            return None, request_body

        files_value = form.getlist(lookup_name)
        _refuse_excess_uploads(
            len(files_value), effective_limits.max_upload_files, field=binding.name
        )
        if files_value:
            return files_value, request_body
        if binding.has_default:
            return binding.default, request_body
        return [], request_body

    if binding.source is ParameterSource.QUERY:
        lookup_name = binding.alias or binding.name
        annotation_origin = get_origin(binding.annotation)
        if annotation_origin is list:
            values = request.query_params.getlist(lookup_name)
            if values:
                return (
                    _coerce_value(
                        values,
                        annotation=binding.annotation,
                        parameter_name=binding.name,
                        source_description="query parameter",
                    ),
                    request_body,
                )
        elif lookup_name in request.query_params:
            return (
                _coerce_value(
                    request.query_params[lookup_name],
                    annotation=binding.annotation,
                    parameter_name=binding.name,
                    source_description="query parameter",
                ),
                request_body,
            )
        if binding.has_default:
            return binding.default, request_body
        raise _parameter_error(
            f"Missing required query parameter {binding.name!r}",
            field=binding.name,
            source="query parameter",
            reason="missing",
        )

    if binding.source is ParameterSource.BODY:
        request_body = await _load_request_body(request, request_body, effective_limits)
        lookup_name = binding.alias or binding.name
        if request_body is _NO_BODY:
            if binding.has_default:
                return binding.default, request_body
            raise _parameter_error(
                f"Missing required body parameter {binding.name!r}",
                field=binding.name,
                source="request body",
                reason="missing",
            )
        if isinstance(request_body, dict):
            body_map = cast(dict[str, object], request_body)
            if lookup_name in body_map:
                return (
                    _bind_body_value(
                        body_map[lookup_name],
                        annotation=binding.annotation,
                        parameter_name=binding.name,
                        source_description="request body",
                    ),
                    request_body,
                )
            if binding.name in binding_plan.inferred_parameter_names:
                return (
                    _bind_body_value(
                        _extract_body_value(binding_plan, binding, request_body),
                        annotation=binding.annotation,
                        parameter_name=binding.name,
                        source_description="request body",
                    ),
                    request_body,
                )
            return (
                _bind_body_value(
                    request_body,
                    annotation=binding.annotation,
                    parameter_name=binding.name,
                    source_description="request body",
                ),
                request_body,
            )
        body_value = request_body
        if binding.name in binding_plan.inferred_parameter_names:
            body_value = _extract_body_value(binding_plan, binding, request_body)
        return (
            _bind_body_value(
                body_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="request body",
            ),
            request_body,
        )

    # Header-bound parameters must never fall through to the query string or
    # request body: those are client-controlled alternates that would allow
    # spoofing header-sourced values such as auth or trust headers.
    if binding.source is ParameterSource.HEADER:
        lookup_name = binding.alias or binding.name.replace("_", "-")
        header_value = request.headers.get(lookup_name)
        if header_value is None:
            if binding.has_default:
                return binding.default, request_body
            raise _parameter_error(
                f"Missing required header {lookup_name!r}",
                field=binding.name,
                source="header",
                reason="missing",
            )
        return (
            _coerce_value(
                header_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="header",
            ),
            request_body,
        )

    # Query values take precedence for inferred parameters so callers can
    # override scalars without reshaping the JSON body.
    query_value = _query_value(request, binding)
    if query_value is not _MISSING:
        return (
            _coerce_value(
                query_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="query parameter",
            ),
            request_body,
        )

    request_body = await _load_request_body(request, request_body, effective_limits)
    body_value = _extract_body_value(binding_plan, binding, request_body)
    if body_value is not _MISSING:
        return (
            _coerce_value(
                body_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="request body",
            ),
            request_body,
        )

    if binding.has_default:
        return binding.default, request_body

    raise _parameter_error(
        f"Missing required parameter {binding.name!r} in the query string or request body",
        field=binding.name,
        source="request parameter",
        reason="missing",
    )


def _query_value(request: HttpRequest, binding: ParameterBinding) -> object:
    annotation_origin = get_origin(binding.annotation)
    if annotation_origin is list:
        query_values = request.query_params.getlist(binding.name)
        return query_values if query_values else _MISSING

    if binding.name in request.query_params:
        return request.query_params[binding.name]

    return _MISSING


async def _load_request_body(
    request: HttpRequest,
    request_body: object,
    limits: RequestLimits,
) -> object:
    if request_body is not _UNSET_BODY:
        return request_body

    _refuse_declared_body(request, limits.max_body_bytes, source="request body")

    # The request body stream can only be consumed once, so cache the parsed
    # JSON document for all subsequent parameter bindings.
    body_bytes = await request.body()
    _refuse_received_body(len(body_bytes), limits.max_body_bytes, source="request body")
    if not body_bytes:
        return _NO_BODY

    try:
        return await request.json()
    except ValueError as exc:
        raise _parameter_error(
            "Request body must contain valid JSON",
            source="request body",
            reason=str(exc),
        ) from exc


def _refuse_declared_body(request: HttpRequest, limit: int | None, *, source: str) -> None:
    """Refuse a request that announces more body bytes than the limit allows.

    This reads the declared length and nothing else, so a caller announcing a body far
    larger than the application accepts is answered before that body is pulled into
    this process: the point of the limit is that the memory is never spent, and a check
    made after the read would have spent it already.

    A request that declares no length, or declares one that is not a number, is left to
    the check made once its body has arrived, which refuses it only after reading it.
    """

    if limit is None:
        return

    declared = request.headers.get("content-length")
    if declared is None:
        return

    try:
        declared_bytes = int(declared)
    except ValueError:
        return

    if declared_bytes > limit:
        raise RequestBodyTooLargeError(
            f"The {source} declares {declared_bytes} bytes, over the {limit} byte limit"
        )


def _refuse_received_body(received_bytes: int, limit: int | None, *, source: str) -> None:
    """Refuse a body that arrived larger than the limit despite declaring nothing.

    A body sent without a declared length cannot be judged before it is read, so the
    request is refused only once the whole of it is already in this process. That is a
    limitation and not a second line of defence: this check decides what the application
    is handed, never what reading the request cost.

    What it cost is whatever the serving adapter bounds a body at on its own, and only
    one of them bounds anything. The raw ASGI adapter refuses a body past ten megabytes
    as it reads it. The Starlette adapter, which is what an application gets when it
    names no adapter, has no bound of any kind, so an undeclared body of any size is
    read in full before this refuses it.
    """

    if limit is not None and received_bytes > limit:
        raise RequestBodyTooLargeError(
            f"The {source} carries {received_bytes} bytes, over the {limit} byte limit"
        )


def _refuse_excess_uploads(uploaded_count: int, limit: int | None, *, field: str) -> None:
    """Refuse a form that bound more parts to one parameter than the limit allows.

    Parts can only be counted once the form has been parsed, so what bounds the cost of
    reaching this point is the byte limit checked before the parse; this bounds what a
    handler is then handed, which is a list the caller decides the length of.
    """

    if limit is not None and uploaded_count > limit:
        raise RequestBodyTooLargeError(
            f"The request uploads {uploaded_count} files for {field!r}, over the {limit} file limit"
        )


def _extract_body_value(
    binding_plan: HandlerBindingPlan,
    binding: ParameterBinding,
    request_body: object,
) -> object:
    if request_body is _NO_BODY:
        return _MISSING

    if isinstance(request_body, dict):
        request_body_mapping = cast(dict[str, object], request_body)
        if binding.name in request_body:
            return request_body_mapping[binding.name]
        if len(binding_plan.inferred_parameter_names) == 1:
            return request_body_mapping
        return _MISSING

    if len(binding_plan.inferred_parameter_names) == 1:
        return request_body

    raise _parameter_error(
        f"{_qualname(binding_plan.controller)}.{binding_plan.handler_name} requires a JSON object "
        "to bind multiple request body parameters",
        field=binding.name,
        source="request body",
        reason="json object required",
    )


def _extract_marker(annotation: object) -> tuple[object, object]:
    """Unwrap ``Annotated[T, Marker]`` into ``(T, marker)`` or ``(annotation, None)``."""
    from typing import Annotated, get_args, get_origin

    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        inner = args[0]
        for meta in args[1:]:
            if isinstance(
                meta,
                (
                    _BodyMarker,
                    _CookiesMarker,
                    _CustomParameterDecorator,
                    _CustomParameterMarker,
                    _HeaderMarker,
                    _HostParamMarker,
                    _IpMarker,
                    _ParamMarker,
                    _QueryMarker,
                    _UploadedFileMarker,
                    _UploadedFilesMarker,
                    _MarkerCallable,
                ),
            ) or (hasattr(meta, "_cls") and meta.__class__.__name__ == "_MarkerCallable"):
                return inner, meta
        return inner, None
    return annotation, None


def _custom_parameter_resolver(marker: object) -> tuple[object | None, object]:
    if isinstance(marker, _CustomParameterMarker):
        return marker.factory, marker.data
    if isinstance(marker, _CustomParameterDecorator):
        return marker.factory, None
    return None, None


def _has_explicit_source(
    *,
    parameter: inspect.Parameter,
    annotation: object,
    path_parameter_names: frozenset[str],
) -> bool:
    real_annotation, marker = _extract_marker(annotation)
    return (
        marker is not None
        or real_annotation is HttpRequest
        or names_native_request(real_annotation)
        or parameter.name in path_parameter_names
    )


def _compile_parameter_source(
    *,
    controller_cls: type[object],
    handler_name: str,
    parameter: inspect.Parameter,
    annotation: object,
    marker: object,
    path_parameter_names: frozenset[str],
    method: str,
    binding_mode: ParameterBindingMode,
    unresolved_parameter_count: int,
) -> tuple[ParameterSource, bool]:
    explicit_source = _source_from_marker(marker)
    if explicit_source is not None:
        return explicit_source, False

    if annotation is HttpRequest or names_native_request(annotation):
        return ParameterSource.REQUEST, False
    if parameter.name in path_parameter_names:
        return ParameterSource.PATH, False

    if binding_mode is ParameterBindingMode.STRICT:
        raise ParameterBindingError(
            f"{_qualname(controller_cls)}.{handler_name} parameter {parameter.name!r} requires "
            "an explicit binding marker in strict mode"
        )

    if binding_mode is ParameterBindingMode.EXPLICIT:
        if method in _SAFE_METHODS:
            return ParameterSource.QUERY, False
        if unresolved_parameter_count == 1:
            return ParameterSource.BODY, True
        raise ParameterBindingError(
            f"{_qualname(controller_cls)}.{handler_name} parameter {parameter.name!r} is "
            "ambiguous in explicit mode"
        )

    if method in _SAFE_METHODS:
        return ParameterSource.QUERY, False
    return ParameterSource.BODY, True


def _source_from_marker(marker: object) -> ParameterSource | None:
    if marker is None:
        return None

    marker_cls_name = getattr(marker, "_cls", marker.__class__).__name__
    if marker_cls_name in {"_CustomParameterDecorator", "_CustomParameterMarker"}:
        return ParameterSource.CUSTOM
    if marker_cls_name == "_BodyMarker":
        return ParameterSource.BODY
    if marker_cls_name == "_QueryMarker":
        return ParameterSource.QUERY
    if marker_cls_name == "_ParamMarker":
        return ParameterSource.PATH
    if marker_cls_name == "_HeaderMarker":
        return ParameterSource.HEADER
    if marker_cls_name == "_CookiesMarker":
        return ParameterSource.COOKIE
    if marker_cls_name == "_IpMarker":
        return ParameterSource.IP
    if marker_cls_name == "_HostParamMarker":
        return ParameterSource.HOST
    if marker_cls_name == "_UploadedFileMarker":
        return ParameterSource.FILE
    if marker_cls_name == "_UploadedFilesMarker":
        return ParameterSource.FILES
    return ParameterSource.INFERRED


def _resolve_binding_mode(value: str) -> ParameterBindingMode:
    try:
        return ParameterBindingMode(value)
    except ValueError as exc:
        raise ParameterBindingError(f"Unsupported parameter binding mode: {value!r}") from exc


def _resolve_validation_mode(value: str) -> ValidationMode:
    try:
        return ValidationMode(value)
    except ValueError as exc:
        raise ParameterBindingError(f"Unsupported validation mode: {value!r}") from exc


def _infer_body_model(
    bindings: tuple[ParameterBinding, ...],
    inferred_parameter_names: tuple[str, ...],
) -> type[object] | None:
    body_bindings = [binding for binding in bindings if binding.source is ParameterSource.BODY]
    if len(body_bindings) != 1:
        return None

    binding = body_bindings[0]
    if binding.alias is not None and binding.name not in inferred_parameter_names:
        return None
    if not isinstance(binding.annotation, type):
        return None
    if binding.annotation in {str, int, float, bool, bytes, dict, list, tuple, set}:
        return None
    return binding.annotation


def _parameter_error(
    message: str,
    *,
    field: str | None = None,
    source: str | None = None,
    reason: str | None = None,
) -> ParameterBindingError:
    return ParameterBindingError(
        message,
        field=field,
        source=source,
        reason=reason,
    )


def _is_pydantic_model_type(annotation: object) -> bool:
    if not isinstance(annotation, type):
        return False

    try:
        from pydantic import BaseModel
    except ImportError:
        return False

    return issubclass(annotation, BaseModel)


@dataclass(frozen=True, slots=True)
class _FieldTypeMismatch:
    """One place inside a body whose value is not of the type declared for it.

    ``path`` locates the value within the body the caller sent: a bare name for a
    field of the body itself, a dotted name for one inside a nested object, and an
    index for an element of an array. ``wanted`` is the declared type as it reads.
    """

    path: str
    wanted: str


@dataclass(frozen=True, slots=True)
class _BodyShapeMismatch:
    """Every way one body fails the target it is being bound to.

    The three sets are the three kinds of problem a single body can have at the same
    time: the keyword names it omits, the ones the target does not declare, and the
    values whose type is not the declared one. They are carried together because a
    caller who has all three should learn all three from one answer.
    """

    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    mistyped: tuple[_FieldTypeMismatch, ...] = ()

    @property
    def found(self) -> bool:
        """Whether any set holds an entry, so a composed message is owed."""
        return bool(self.missing or self.unexpected or self.mistyped)

    def merged_with(self, other: _BodyShapeMismatch) -> _BodyShapeMismatch:
        """Fold a mismatch found elsewhere in the same body into this one."""
        return _BodyShapeMismatch(
            missing=self.missing + other.missing,
            unexpected=self.unexpected + other.unexpected,
            mistyped=self.mistyped + other.mistyped,
        )


_NO_MISMATCH = _BodyShapeMismatch(missing=(), unexpected=())


def _child_path(path: str, name: str) -> str:
    """Name a field of a nested object relative to the body the caller sent."""

    return f"{path}.{name}" if path else name


def _mistyped(path: str, wanted: str) -> _BodyShapeMismatch:
    """Report one value that is not of its declared type."""

    return _BodyShapeMismatch(
        missing=(), unexpected=(), mistyped=(_FieldTypeMismatch(path=path, wanted=wanted),)
    )


def _body_shape_mismatch(
    annotation: type[object], raw_value_mapping: dict[str, object], *, path: str = ""
) -> _BodyShapeMismatch:
    """Compare a mapping's keys against the keyword parameters a target declares.

    The constructor signature is the source of truth rather than the field list,
    because a pseudo-field that only ``__post_init__`` consumes is accepted by the
    constructor and absent from the field list; diffing against the field list would
    report such a key as one the target does not declare and refuse a body the target
    accepts. A parameter carrying any default is not required, which covers a default
    computed per instance, since the constructor supplies its own sentinel there.

    A target whose constructor collects surplus keywords declares no key unexpected.
    """

    try:
        parameters = inspect.signature(annotation).parameters
    except (TypeError, ValueError):
        return _NO_MISMATCH

    keyword_parameters = {
        name: parameter
        for name, parameter in parameters.items()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    collects_surplus = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    return _BodyShapeMismatch(
        missing=tuple(
            _child_path(path, name)
            for name, parameter in keyword_parameters.items()
            if parameter.default is inspect.Parameter.empty and name not in raw_value_mapping
        ),
        unexpected=(
            ()
            if collects_surplus
            else tuple(
                _child_path(path, key) for key in raw_value_mapping if key not in keyword_parameters
            )
        ),
    )


def _mismatch_clauses(
    mismatch: _BodyShapeMismatch, *, quoted: bool
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Label each kind of problem the body has and render the names it applies to.

    ``quoted`` picks the rendering: the prose message quotes each name, while the
    machine-readable reason leaves it bare so a caller can split the string.
    """

    def render(name: str) -> str:
        return repr(name) if quoted else name

    def wrong_type(entry: _FieldTypeMismatch) -> str:
        if quoted:
            return f"{render(entry.path)} (wanted {entry.wanted})"
        return f"{entry.path} wanted {entry.wanted}"

    clauses: list[tuple[str, tuple[str, ...]]] = []
    if mismatch.missing:
        clauses.append(
            (
                _plural("missing required field", "missing required fields", mismatch.missing),
                tuple(render(name) for name in mismatch.missing),
            )
        )
    if mismatch.unexpected:
        clauses.append(
            (
                _plural("unexpected field", "unexpected fields", mismatch.unexpected),
                tuple(render(name) for name in mismatch.unexpected),
            )
        )
    if mismatch.mistyped:
        clauses.append(
            (
                _plural("field of the wrong type", "fields of the wrong type", mismatch.mistyped),
                tuple(wrong_type(entry) for entry in mismatch.mistyped),
            )
        )
    return tuple(clauses)


def _plural(singular: str, plural: str, entries: tuple[object, ...]) -> str:
    """Pick the label that agrees with how many entries the clause names."""

    return singular if len(entries) == 1 else plural


def _describe_mismatch(mismatch: _BodyShapeMismatch) -> str:
    """Render every set as one sentence, so a caller repairs the body in one attempt."""

    clauses = tuple(
        f"{label} {', '.join(names)}" for label, names in _mismatch_clauses(mismatch, quoted=True)
    )
    if len(clauses) < 3:
        return " and ".join(clauses)
    return f"{', '.join(clauses[:-1])} and {clauses[-1]}"


def _mismatch_reason(mismatch: _BodyShapeMismatch) -> str:
    """Render every set for the machine-readable field, kept parseable.

    Names within one set are separated by a comma and the sets by a semicolon, so the
    two levels stay distinguishable to a caller that splits the string.
    """

    return "; ".join(
        f"{label}: {', '.join(names)}" for label, names in _mismatch_clauses(mismatch, quoted=False)
    )


def _mismatch_error(
    mismatch: _BodyShapeMismatch,
    *,
    annotation: object,
    parameter_name: str,
    source_description: str,
) -> ParameterBindingError:
    """Compose one refusal naming every problem the body has."""

    return _parameter_error(
        f"Could not bind {source_description} {parameter_name!r} to "
        f"{_display_annotation(annotation)}: {_describe_mismatch(mismatch)}",
        field=parameter_name,
        source=source_description,
        reason=_mismatch_reason(mismatch),
    )


# The types a JSON document carries itself. A value declared as one of these arrived
# with a representation of its own, so one of another type is the caller's mistake and
# is refused rather than converted; every other declared type is still built from what
# arrived, because there a string or a number is the only representation the caller had.
_JSON_SCALARS = (bool, int, float, str)


@dataclass(frozen=True, slots=True)
class _BodyPosition:
    """Where a value sits in a request body, and which parameter that body is bound to.

    It travels with the value into whatever the body nests, so one refusal can name
    both the parameter being bound and the part of the document that did not fit.
    """

    parameter_name: str
    source_description: str
    path: str = ""

    def field(self, name: str) -> _BodyPosition:
        """Where a named field of the object at this position sits."""
        return self._at(_child_path(self.path, name))

    def item(self, index: int) -> _BodyPosition:
        """Where one element of the array at this position sits."""
        return self._at(f"{self.path}[{index}]")

    def entry(self, key: str) -> _BodyPosition:
        """Where one value of the mapping at this position sits."""
        return self._at(f"{self.path}[{key!r}]")

    def _at(self, path: str) -> _BodyPosition:
        return _BodyPosition(
            parameter_name=self.parameter_name,
            source_description=self.source_description,
            path=path,
        )


def _fits_json_scalar(raw_value: object, annotation: object) -> bool:
    """Whether a decoded JSON value already is what a scalar declaration names.

    ``bool`` is a subclass of ``int`` in Python and is excluded from both number
    checks: a document that carried ``true`` did not carry a number, and a handler
    annotated ``int`` that is handed ``True`` is the confusion this check exists to
    stop. An ``int`` is accepted where ``float`` is declared, because a JSON document
    has one number literal and common encoders write a whole float without its
    fraction; it is passed on as it arrived rather than widened, since an integer
    outside the range a float holds exactly would lose digits on the way through.
    """

    if annotation is bool:
        return isinstance(raw_value, bool)
    if annotation is int:
        return isinstance(raw_value, int) and not isinstance(raw_value, bool)
    if annotation is float:
        return isinstance(raw_value, (float, int)) and not isinstance(raw_value, bool)
    return isinstance(raw_value, str)


def _bind_body_value(
    raw_value: object,
    *,
    annotation: object,
    parameter_name: str,
    source_description: str,
) -> object:
    """Bind a request body to the type the handler declared for it, or refuse it.

    A body is the one parameter source that arrives already typed, so a value of the
    wrong type is answered rather than reinterpreted. The refusal names every problem
    the same body has at once, so that a caller repairs it in one attempt.
    """

    at = _BodyPosition(parameter_name=parameter_name, source_description=source_description)
    bound_value, mismatch = _bind_body_field(raw_value, annotation=annotation, at=at)
    if not mismatch.found:
        return bound_value

    root = _root_mismatch(mismatch)
    if root is not None:
        # Nothing inside the body was reached, so there is no field name to compose
        # with and the refusal reads as it does for every other parameter source.
        raise _parameter_error(
            f"Could not bind {source_description} {parameter_name!r} to {root.wanted}",
            field=parameter_name,
            source=source_description,
            reason=f"{root.wanted} expected",
        )
    raise _mismatch_error(
        mismatch,
        annotation=annotation,
        parameter_name=parameter_name,
        source_description=source_description,
    )


def _root_mismatch(mismatch: _BodyShapeMismatch) -> _FieldTypeMismatch | None:
    """The whole body being of the wrong type, when that is the only problem found."""

    if mismatch.missing or mismatch.unexpected or len(mismatch.mistyped) != 1:
        return None
    entry = mismatch.mistyped[0]
    return entry if entry.path == "" else None


def _bind_body_field(
    raw_value: object, *, annotation: object, at: _BodyPosition
) -> tuple[object, _BodyShapeMismatch]:
    """Bind one decoded body value to its declared type, collecting what does not fit.

    Every problem is returned rather than raised, so that the problems of one body are
    answered together. A declared type JSON cannot carry is the exception: it is built
    by the conversion every other parameter source uses, which refuses in its own words.
    """

    if isinstance(annotation, InitVar):
        annotation = annotation.type
    if annotation in (inspect.Signature.empty, Any, object):
        return raw_value, _NO_MISMATCH

    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return _bind_body_union(raw_value, annotation=annotation, at=at)
    if annotation is NoneType:
        if raw_value is None:
            return None, _NO_MISMATCH
        return raw_value, _mistyped(at.path, "None")
    if annotation is list or origin is list:
        return _bind_body_list(raw_value, annotation=annotation, at=at)
    if annotation is dict or origin is dict:
        return _bind_body_dict(raw_value, annotation=annotation, at=at)
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _bind_body_dataclass(raw_value, annotation=annotation, at=at)
    if annotation in _JSON_SCALARS:
        if _fits_json_scalar(raw_value, annotation):
            return raw_value, _NO_MISMATCH
        return raw_value, _mistyped(at.path, _display_annotation(annotation))

    return (
        _coerce_value(
            raw_value,
            annotation=annotation,
            parameter_name=at.parameter_name,
            source_description=at.source_description,
        ),
        _NO_MISMATCH,
    )


def _bind_body_union(
    raw_value: object, *, annotation: object, at: _BodyPosition
) -> tuple[object, _BodyShapeMismatch]:
    """Take the first member of a union that the value already fits."""

    union_arguments = get_args(annotation)
    if raw_value is None:
        if NoneType in union_arguments:
            return None, _NO_MISMATCH
        return raw_value, _mistyped(at.path, _display_annotation(annotation))

    members = tuple(option for option in union_arguments if option is not NoneType)
    sole_member_mismatch: _BodyShapeMismatch | None = None
    for option in members:
        try:
            bound_value, mismatch = _bind_body_field(raw_value, annotation=option, at=at)
        except ParameterBindingError:
            # One member refusing is not the union refusing, so the next is tried and
            # the union answers for itself once every member has failed.
            continue
        if not mismatch.found:
            return bound_value, _NO_MISMATCH
        if len(members) == 1:
            # With one member there is no ambiguity about which the caller meant, so
            # what that member found inside the value is more useful than the union.
            sole_member_mismatch = mismatch
    if sole_member_mismatch is not None:
        return raw_value, sole_member_mismatch
    return raw_value, _mistyped(at.path, _display_annotation(annotation))


def _bind_body_list(
    raw_value: object, *, annotation: object, at: _BodyPosition
) -> tuple[object, _BodyShapeMismatch]:
    """Bind every element of an array to the element type the declaration names."""

    if not isinstance(raw_value, list):
        return raw_value, _mistyped(at.path, _display_annotation(annotation))

    item_types = get_args(annotation)
    item_annotation = item_types[0] if item_types else object
    bound_items: list[object] = []
    mismatch = _NO_MISMATCH
    for index, item in enumerate(cast(list[object], raw_value)):
        bound_item, item_mismatch = _bind_body_field(
            item, annotation=item_annotation, at=at.item(index)
        )
        bound_items.append(bound_item)
        mismatch = mismatch.merged_with(item_mismatch)
    return bound_items, mismatch


def _bind_body_dict(
    raw_value: object, *, annotation: object, at: _BodyPosition
) -> tuple[object, _BodyShapeMismatch]:
    """Bind every value of an object to the value type the declaration names.

    The declared key type is not checked: the keys of a JSON object are strings and
    nothing else, so a declaration naming another key type describes a mapping the
    caller had no way to send, and checking it would refuse every body.
    """

    if not isinstance(raw_value, dict):
        return raw_value, _mistyped(at.path, _display_annotation(annotation))

    argument_types = get_args(annotation)
    value_annotation = argument_types[1] if len(argument_types) == 2 else object
    bound_entries: dict[str, object] = {}
    mismatch = _NO_MISMATCH
    for key, value in cast(dict[str, object], raw_value).items():
        bound_value, value_mismatch = _bind_body_field(
            value, annotation=value_annotation, at=at.entry(key)
        )
        bound_entries[key] = bound_value
        mismatch = mismatch.merged_with(value_mismatch)
    return bound_entries, mismatch


def _bind_body_dataclass(
    raw_value: object, *, annotation: type[object], at: _BodyPosition
) -> tuple[object, _BodyShapeMismatch]:
    """Build a declared object out of the JSON object the caller sent for it."""

    if isinstance(raw_value, annotation):
        return raw_value, _NO_MISMATCH
    if not isinstance(raw_value, dict):
        return raw_value, _mistyped(at.path, _display_annotation(annotation))
    return _bind_mapping_to_dataclass(
        annotation, cast(dict[str, object], raw_value), at=at, bind_field_types=True
    )


def _bind_declared_fields(
    annotation: type[object], raw_value_mapping: dict[str, object], *, at: _BodyPosition
) -> tuple[dict[str, object], _BodyShapeMismatch]:
    """Bind each value the target declares a type for, leaving the rest as it arrived.

    A target whose annotations cannot be resolved is bound as it was before any type
    was held to: refusing every body for a target nobody can describe would deny more
    than it protects, and the shape comparison still holds.
    """

    try:
        declared_types = get_type_hints(annotation)
    except (AttributeError, NameError, TypeError):
        return raw_value_mapping, _NO_MISMATCH

    bound_mapping = dict(raw_value_mapping)
    mismatch = _NO_MISMATCH
    for name, value in raw_value_mapping.items():
        declared = declared_types.get(name, _MISSING)
        if declared is _MISSING or get_origin(declared) is ClassVar:
            continue
        bound_value, field_mismatch = _bind_body_field(
            value, annotation=declared, at=at.field(name)
        )
        bound_mapping[name] = bound_value
        mismatch = mismatch.merged_with(field_mismatch)
    return bound_mapping, mismatch


def _bind_mapping_to_dataclass(
    annotation: type[object],
    raw_value_mapping: dict[str, object],
    *,
    at: _BodyPosition,
    bind_field_types: bool,
) -> tuple[object, _BodyShapeMismatch]:
    """Construct a target from a mapping, reporting every way the mapping does not fit.

    The returned value is meaningful only when no mismatch was found; a caller that
    finds one composes the refusal instead of using it.
    """

    mismatch = _body_shape_mismatch(annotation, raw_value_mapping, path=at.path)
    bound_mapping = raw_value_mapping
    if bind_field_types:
        bound_mapping, field_mismatch = _bind_declared_fields(annotation, raw_value_mapping, at=at)
        mismatch = mismatch.merged_with(field_mismatch)
    if mismatch.found:
        return _MISSING, mismatch

    try:
        return annotation(**bound_mapping), _NO_MISMATCH
    except TypeError as exc:
        # The mapping was compared with what the target declares and fits it, so a
        # TypeError here is the target objecting from inside its own construction and
        # saying why, rather than the call being shaped wrongly. The interpreter's own
        # wording for a mis-shaped call is never the caller's to see.
        raise _parameter_error(
            f"Could not bind {at.source_description} {at.parameter_name!r} to "
            f"{_display_annotation(annotation)}: {exc}",
            field=at.parameter_name,
            source=at.source_description,
            reason=str(exc),
        ) from exc


def _coerce_value(
    raw_value: object,
    *,
    annotation: object,
    parameter_name: str,
    source_description: str,
) -> object:
    if annotation in (inspect.Signature.empty, Any, object):
        return raw_value

    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return _coerce_union_value(
            raw_value,
            annotation=annotation,
            parameter_name=parameter_name,
            source_description=source_description,
        )

    if origin is list:
        item_types = get_args(annotation)
        item_annotation = item_types[0] if item_types else object
        if not isinstance(raw_value, list):
            raise ParameterBindingError(
                f"Could not bind {source_description} {parameter_name!r} to list"
            )
        return [
            _coerce_value(
                item,
                annotation=item_annotation,
                parameter_name=parameter_name,
                source_description=source_description,
            )
            for item in raw_value
        ]

    if isinstance(annotation, type) and is_dataclass(annotation):
        if isinstance(raw_value, annotation):
            return raw_value
        if not isinstance(raw_value, dict):
            raise _parameter_error(
                f"Could not bind {source_description} {parameter_name!r} to "
                f"{_display_annotation(annotation)}",
                field=parameter_name,
                source=source_description,
                reason=f"expected {_display_annotation(annotation)}",
            )
        bound_value, mismatch = _bind_mapping_to_dataclass(
            annotation,
            cast(dict[str, object], raw_value),
            at=_BodyPosition(parameter_name=parameter_name, source_description=source_description),
            bind_field_types=False,
        )
        if mismatch.found:
            raise _mismatch_error(
                mismatch,
                annotation=annotation,
                parameter_name=parameter_name,
                source_description=source_description,
            )
        return bound_value

    if _is_pydantic_model_type(annotation):
        return raw_value

    if annotation is bool:
        return _coerce_bool(
            raw_value, parameter_name=parameter_name, source_description=source_description
        )

    if annotation is int:
        return _coerce_number(
            int, raw_value, parameter_name=parameter_name, source_description=source_description
        )

    if annotation is float:
        return _coerce_number(
            float, raw_value, parameter_name=parameter_name, source_description=source_description
        )

    if annotation is str:
        if isinstance(raw_value, str):
            return raw_value
        return str(raw_value)

    if annotation is dict:
        if isinstance(raw_value, dict):
            return raw_value
        raise ParameterBindingError(
            f"Could not bind {source_description} {parameter_name!r} to dict"
        )

    if annotation is list:
        if isinstance(raw_value, list):
            return raw_value
        raise ParameterBindingError(
            f"Could not bind {source_description} {parameter_name!r} to list"
        )

    if isinstance(annotation, type):
        if isinstance(raw_value, annotation):
            return raw_value
        try:
            return annotation(raw_value)
        except (TypeError, ValueError) as exc:
            raise _parameter_error(
                f"Could not bind {source_description} {parameter_name!r} to "
                f"{_display_annotation(annotation)}: {exc}",
                field=parameter_name,
                source=source_description,
                reason=str(exc),
            ) from exc

    return raw_value


def _coerce_union_value(
    raw_value: object,
    *,
    annotation: object,
    parameter_name: str,
    source_description: str,
) -> object:
    union_arguments = get_args(annotation)
    if raw_value is None and NoneType in union_arguments:
        return None

    last_error: ParameterBindingError | None = None
    for option in union_arguments:
        if option is NoneType:
            continue
        try:
            return _coerce_value(
                raw_value,
                annotation=option,
                parameter_name=parameter_name,
                source_description=source_description,
            )
        except ParameterBindingError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise ParameterBindingError(
        f"Could not bind {source_description} {parameter_name!r} to "
        f"{_display_annotation(annotation)}"
    )


def _coerce_bool(
    raw_value: object,
    *,
    parameter_name: str,
    source_description: str,
) -> bool:
    if isinstance(raw_value, bool):
        return raw_value

    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False

    raise _parameter_error(
        f"Could not bind {source_description} {parameter_name!r} to bool",
        field=parameter_name,
        source=source_description,
        reason="boolean expected",
    )


def _coerce_number(
    number_type: type[int] | type[float],
    raw_value: object,
    *,
    parameter_name: str,
    source_description: str,
) -> int | float:
    if isinstance(raw_value, number_type) and not isinstance(raw_value, bool):
        return cast(int | float, raw_value)

    if isinstance(raw_value, bool):
        raise _parameter_error(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}",
            field=parameter_name,
            source=source_description,
            reason=f"{number_type.__name__} expected",
        )

    if isinstance(raw_value, (str, bytes, bytearray)):
        convertible_raw_value: str | bytes | bytearray | int | float = raw_value
    elif isinstance(raw_value, int | float):
        convertible_raw_value = raw_value
    else:
        raise _parameter_error(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}",
            field=parameter_name,
            source=source_description,
            reason=f"{number_type.__name__} expected",
        )

    try:
        if number_type is int:
            return int(convertible_raw_value)
        return float(convertible_raw_value)
    except (TypeError, ValueError) as exc:
        raise _parameter_error(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}: "
            f"{exc}",
            field=parameter_name,
            source=source_description,
            reason=str(exc),
        ) from exc


def _resolve_handler_parameter_annotations(
    controller_cls: type[object],
    route_definition: ControllerRouteDefinition,
) -> dict[str, object]:
    handler_globals = cast(
        dict[str, object],
        getattr(route_definition.handler, "__globals__", {}),
    )
    module_globals = getattr(
        sys.modules.get(controller_cls.__module__),
        "__dict__",
        handler_globals,
    )
    local_namespace = {
        controller_cls.__name__: controller_cls,
        HttpRequest.__name__: HttpRequest,
    }

    try:
        raw_annotations = inspect.get_annotations(route_definition.handler, eval_str=False)
    except (NameError, TypeError) as exc:
        raise ParameterBindingError(
            "Could not resolve type hints for "
            f"{_qualname(controller_cls)}.{route_definition.handler_name}: {exc}"
        ) from exc

    resolved_annotations: dict[str, object] = {}
    for parameter_name, annotation in raw_annotations.items():
        if parameter_name == "return":
            continue
        if not isinstance(annotation, str):
            resolved_annotations[parameter_name] = annotation
            continue

        try:
            resolved_annotations[parameter_name] = _resolve_annotation_string(
                annotation,
                globalns=module_globals,
                localns=local_namespace,
            )
        except (NameError, TypeError) as exc:
            raise ParameterBindingError(
                "Could not resolve type hints for "
                f"{_qualname(controller_cls)}.{route_definition.handler_name}: {exc}"
            ) from exc

    return resolved_annotations


def _resolve_annotation_string(
    annotation: str,
    *,
    globalns: collections.abc.Mapping[str, object],
    localns: collections.abc.Mapping[str, object],
) -> object:
    def _annotation_holder() -> None:
        return None

    _annotation_holder.__annotations__ = {"value": annotation}
    return get_type_hints(
        _annotation_holder,
        globalns=dict(globalns),
        localns=dict(localns),
        include_extras=True,
    )["value"]


def _extract_path_parameter_names(path: str) -> frozenset[str]:
    path_parameter_names: set[str] = set()
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            parameter_name = segment[1:-1].split(":", maxsplit=1)[0].strip()
            if parameter_name:
                path_parameter_names.add(parameter_name)
    return frozenset(path_parameter_names)


def _display_annotation(annotation: object) -> str:
    """Name a declared type the way the caller wrote it, without where it lives.

    A module path names the application's own layout and tells a caller nothing it
    can act on, so only the type's own name is served.
    """

    if annotation is NoneType:
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (Union, UnionType):
        return " | ".join(_display_annotation(argument) for argument in arguments)
    if origin is not None and arguments:
        rendered = ", ".join(_display_annotation(argument) for argument in arguments)
        return f"{_display_annotation(origin)}[{rendered}]"
    return repr(annotation)


_SAFE_METHODS = frozenset({"GET", "HEAD", "DELETE", "OPTIONS"})
