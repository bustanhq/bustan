"""Request parameter analysis and runtime binding helpers."""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, is_dataclass
from enum import StrEnum
from types import NoneType, UnionType
from typing import Any, Union, cast, get_args, get_origin

from starlette.requests import Request

from ...core.errors import ParameterBindingError
from ...core.utils import _qualname

from ...common.decorators.parameter import (
    _BodyMarker,
    _CookiesMarker,
    _HeaderMarker,
    _HostParamMarker,
    _IpMarker,
    _MarkerCallable,
    _ParamMarker,
    _QueryMarker,
    _UploadedFileMarker,
    _UploadedFilesMarker,
)

from .metadata import ControllerRouteDefinition

_MISSING = object()
_NO_BODY = object()
_UNSET_BODY = object()


class ParameterSource(StrEnum):
    """Supported sources for handler parameters."""

    REQUEST = "request"
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


@dataclass(frozen=True, slots=True)
class HandlerBindingPlan:
    """Compiled binding plan for a controller handler."""

    controller: type[object]
    handler_name: str
    parameters: tuple[ParameterBinding, ...]
    inferred_parameter_names: tuple[str, ...]


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

    signature = inspect.signature(route_definition.handler)
    type_hints = _resolve_handler_parameter_annotations(controller_cls, route_definition)
    path_parameter_names = _extract_path_parameter_names(route_definition.route.path)

    bindings: list[ParameterBinding] = []
    inferred_parameter_names: list[str] = []

    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue

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

        if marker is not None:
            marker_cls_name = getattr(marker, "_cls", marker.__class__).__name__
            if marker_cls_name == "_BodyMarker":
                source = ParameterSource.BODY
            elif marker_cls_name == "_QueryMarker":
                source = ParameterSource.QUERY
            elif marker_cls_name == "_ParamMarker":
                source = ParameterSource.PATH
            elif marker_cls_name == "_HeaderMarker":
                source = ParameterSource.HEADER
            elif marker_cls_name == "_CookiesMarker":
                source = ParameterSource.COOKIE
            elif marker_cls_name == "_IpMarker":
                source = ParameterSource.IP
            elif marker_cls_name == "_HostParamMarker":
                source = ParameterSource.HOST
            elif marker_cls_name == "_UploadedFileMarker":
                source = ParameterSource.FILE
            elif marker_cls_name == "_UploadedFilesMarker":
                source = ParameterSource.FILES
            else:
                source = ParameterSource.INFERRED
                inferred_parameter_names.append(parameter.name)
        elif real_annotation is Request:
            source = ParameterSource.REQUEST
        elif parameter.name in path_parameter_names:
            source = ParameterSource.PATH
        else:
            source = ParameterSource.INFERRED
            inferred_parameter_names.append(parameter.name)

        alias: str | None = None
        if marker is not None and hasattr(marker, "alias") and isinstance(marker.alias, str):
            alias = marker.alias
        annotation = real_annotation

        bindings.append(
            ParameterBinding(
                name=parameter.name,
                kind=parameter.kind,
                source=source,
                annotation=annotation,
                has_default=parameter.default is not inspect.Signature.empty,
                default=None if parameter.default is inspect.Signature.empty else parameter.default,
                alias=alias,
            )
        )

    return HandlerBindingPlan(
        controller=controller_cls,
        handler_name=route_definition.handler_name,
        parameters=tuple(bindings),
        inferred_parameter_names=tuple(inferred_parameter_names),
    )


async def bind_handler_arguments(
    request: Request,
    binding_plan: HandlerBindingPlan,
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Bind handler parameters and split them into args/kwargs."""

    return separate_bound_parameters(await bind_handler_parameters(request, binding_plan))


async def bind_handler_parameters(
    request: Request,
    binding_plan: HandlerBindingPlan,
) -> tuple[BoundParameter, ...]:
    """Bind every parameter in a compiled handler plan."""

    bound_parameters: list[BoundParameter] = []
    request_body: object = _UNSET_BODY

    for binding in binding_plan.parameters:
        value, request_body = await _bind_parameter(
            request,
            binding_plan,
            binding,
            request_body,
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
    request: Request,
    binding_plan: HandlerBindingPlan,
    binding: ParameterBinding,
    request_body: object,
) -> tuple[object, object]:
    if binding.source is ParameterSource.REQUEST:
        return request, request_body

    if binding.source is ParameterSource.PATH:
        raw_value = request.path_params.get(binding.name, _MISSING)
        if raw_value is _MISSING:
            raise ParameterBindingError(f"Missing required path parameter {binding.name!r}")
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
        cookie_value = request.cookies.get(lookup_name) if binding.alias else request.cookies.get(binding.name)
        if binding.alias is None and binding.annotation is dict:
            return dict(request.cookies), request_body
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
        host_header = request.headers.get("host")
        if host_header is not None:
            return host_header, request_body
        if binding.has_default:
            return binding.default, request_body
        return None, request_body

    if binding.source in (ParameterSource.FILE, ParameterSource.FILES):
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
        if files_value:
            return files_value, request_body
        if binding.has_default:
            return binding.default, request_body
        return [], request_body

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

    request_body = await _load_request_body(request, request_body)
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
        raise ParameterBindingError(f"Missing required query parameter {binding.name!r}")

    if binding.source is ParameterSource.BODY:
        request_body = await _load_request_body(request, request_body)
        lookup_name = binding.alias or binding.name
        if request_body is _NO_BODY:
            if binding.has_default:
                return binding.default, request_body
            raise ParameterBindingError(f"Missing required body parameter {binding.name!r}")
        if isinstance(request_body, dict):
            body_map = cast(dict[str, object], request_body)
            if lookup_name in body_map:
                return (
                    _coerce_value(
                        body_map[lookup_name],
                        annotation=binding.annotation,
                        parameter_name=binding.name,
                        source_description="request body",
                    ),
                    request_body,
                )
            # whole-body binding
            return (
                _coerce_value(
                    request_body,
                    annotation=binding.annotation,
                    parameter_name=binding.name,
                    source_description="request body",
                ),
                request_body,
            )
        return (
            _coerce_value(
                request_body,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="request body",
            ),
            request_body,
        )

    if binding.source is ParameterSource.HEADER:
        lookup_name = binding.alias or binding.name.replace("_", "-")
        header_value = request.headers.get(lookup_name)
        if header_value is None:
            if binding.has_default:
                return binding.default, request_body
            raise ParameterBindingError(f"Missing required header {lookup_name!r}")
        return (
            _coerce_value(
                header_value,
                annotation=binding.annotation,
                parameter_name=binding.name,
                source_description="header",
            ),
            request_body,
        )

    if binding.has_default:
        return binding.default, request_body

    raise ParameterBindingError(
        f"Missing required parameter {binding.name!r} in the query string or request body"
    )


def _query_value(request: Request, binding: ParameterBinding) -> object:
    annotation_origin = get_origin(binding.annotation)
    if annotation_origin is list:
        query_values = request.query_params.getlist(binding.name)
        return query_values if query_values else _MISSING

    if binding.name in request.query_params:
        return request.query_params[binding.name]

    return _MISSING


async def _load_request_body(request: Request, request_body: object) -> object:
    if request_body is not _UNSET_BODY:
        return request_body

    # The request body stream can only be consumed once, so cache the parsed
    # JSON document for all subsequent parameter bindings.
    body_bytes = await request.body()
    if not body_bytes:
        return _NO_BODY

    try:
        return await request.json()
    except ValueError as exc:
        raise ParameterBindingError("Request body must contain valid JSON") from exc


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

    raise ParameterBindingError(
        f"{_qualname(binding_plan.controller)}.{binding_plan.handler_name} requires a JSON object "
        "to bind multiple request body parameters"
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
            raise ParameterBindingError(
                f"Could not bind {source_description} {parameter_name!r} to {_display_annotation(annotation)}"
            )
        raw_value_mapping = cast(dict[str, object], raw_value)
        try:
            return annotation(**raw_value_mapping)
        except TypeError as exc:
            raise ParameterBindingError(
                f"Could not bind {source_description} {parameter_name!r} to {_display_annotation(annotation)}: {exc}"
            ) from exc

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
            raise ParameterBindingError(
                f"Could not bind {source_description} {parameter_name!r} to {_display_annotation(annotation)}: {exc}"
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
        f"Could not bind {source_description} {parameter_name!r} to {_display_annotation(annotation)}"
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

    raise ParameterBindingError(f"Could not bind {source_description} {parameter_name!r} to bool")


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
        raise ParameterBindingError(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}"
        )

    if isinstance(raw_value, (str, bytes, bytearray)):
        convertible_raw_value: str | bytes | bytearray | int | float = raw_value
    elif isinstance(raw_value, int):
        convertible_raw_value = raw_value
    elif isinstance(raw_value, float):
        convertible_raw_value = raw_value
    else:
        raise ParameterBindingError(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}"
        )

    try:
        if number_type is int:
            return int(convertible_raw_value)
        return float(convertible_raw_value)
    except (TypeError, ValueError) as exc:
        raise ParameterBindingError(
            f"Could not bind {source_description} {parameter_name!r} to {number_type.__name__}: {exc}"
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
        Request.__name__: Request,
    }

    resolved_annotations: dict[str, object] = {}
    try:
        # Only parameter annotations matter for runtime binding. Return
        # annotations are ignored because they can legally reference local types
        # that do not need to be resolved during request handling.
        raw_annotations = inspect.get_annotations(route_definition.handler, eval_str=False)
    except (NameError, TypeError) as exc:
        raise ParameterBindingError(
            f"Could not resolve type hints for {_qualname(controller_cls)}.{route_definition.handler_name}: {exc}"
        ) from exc

    for parameter_name, annotation in raw_annotations.items():
        if parameter_name == "return":
            continue
        if isinstance(annotation, str):
            try:
                resolved_annotations[parameter_name] = eval(
                    annotation,
                    module_globals,
                    local_namespace,
                )
            except (NameError, TypeError) as exc:
                raise ParameterBindingError(
                    f"Could not resolve type hints for {_qualname(controller_cls)}.{route_definition.handler_name}: {exc}"
                ) from exc
        else:
            resolved_annotations[parameter_name] = annotation

    return resolved_annotations


def _extract_path_parameter_names(path: str) -> frozenset[str]:
    path_parameter_names: set[str] = set()
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            parameter_name = segment[1:-1].split(":", maxsplit=1)[0].strip()
            if parameter_name:
                path_parameter_names.add(parameter_name)
    return frozenset(path_parameter_names)


def _display_annotation(annotation: object) -> str:
    if isinstance(annotation, type):
        return annotation.__name__
    return repr(annotation)
