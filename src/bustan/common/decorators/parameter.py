"""Parameter binding markers for explicit request source annotation.

Use these with ``typing.Annotated`` to override the default source inference::

    from typing import Annotated
    from bustan import Body, Query, Header, Param

    @Get("/{item_id}")
    def get_item(
        self,
        item_id: Annotated[int, Param],          # forced from URL path
        search: Annotated[str, Query],            # forced from query string
        payload: Annotated[CreateItem, Body],     # forced from request body
        x_token: Annotated[str, Header("x-api-token")],  # named header
    ) -> dict: ...
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _BodyMarker:
    """Marker: bind this parameter from the JSON request body."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "Body" if self.alias is None else f"Body({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _QueryMarker:
    """Marker: bind this parameter from the query string."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "Query" if self.alias is None else f"Query({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _ParamMarker:
    """Marker: bind this parameter from the URL path."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "Param" if self.alias is None else f"Param({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _HeaderMarker:
    """Marker: bind this parameter from a request header."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "Header" if self.alias is None else f"Header({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _CookiesMarker:
    """Marker: bind this parameter from request cookies."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "Cookies" if self.alias is None else f"Cookies({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _IpMarker:
    """Marker: bind the client IP address.

    The IP is always sourced from the connection (``request.client.host``);
    no alias is supported.
    """

    def __repr__(self) -> str:
        return "Ip"


@dataclass(frozen=True, slots=True)
class _HostParamMarker:
    """Marker: bind a request header that carries the host name.

    By default the standard ``Host`` header is used.  Pass an alias to read a
    different header instead, e.g. ``HostParam("x-forwarded-host")``.
    """

    alias: str | None = None

    def __repr__(self) -> str:
        return "HostParam" if self.alias is None else f"HostParam({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _UploadedFileMarker:
    """Marker: bind a single uploaded file from multipart form data."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "UploadedFile" if self.alias is None else f"UploadedFile({self.alias!r})"


@dataclass(frozen=True, slots=True)
class _UploadedFilesMarker:
    """Marker: bind multiple uploaded files from multipart form data."""

    alias: str | None = None

    def __repr__(self) -> str:
        return "UploadedFiles" if self.alias is None else f"UploadedFiles({self.alias!r})"


class _MarkerCallable:
    """Makes a marker usable both bare (``Annotated[str, Body]``)
    and as a call (``Annotated[str, Body("field")]``)."""

    def __init__(self, marker_cls: type) -> None:
        self._cls = marker_cls
        self._default = marker_cls()

    def __call__(self, alias: str) -> object:
        return self._cls(alias=alias)

    def __repr__(self) -> str:
        return self._cls.__name__.lstrip("_").replace("Marker", "")

    # Allow use as bare annotation marker (not called)
    @property
    def alias(self) -> str | None:
        return None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _MarkerCallable):
            return self._cls is other._cls
        return isinstance(other, self._cls)

    def __hash__(self) -> int:
        return hash(self._cls)


Body: _MarkerCallable = _MarkerCallable(_BodyMarker)
Query: _MarkerCallable = _MarkerCallable(_QueryMarker)
Param: _MarkerCallable = _MarkerCallable(_ParamMarker)
Header: _MarkerCallable = _MarkerCallable(_HeaderMarker)
Cookies: _MarkerCallable = _MarkerCallable(_CookiesMarker)
Ip: _MarkerCallable = _MarkerCallable(_IpMarker)
HostParam: _MarkerCallable = _MarkerCallable(_HostParamMarker)
UploadedFile: _MarkerCallable = _MarkerCallable(_UploadedFileMarker)
UploadedFiles: _MarkerCallable = _MarkerCallable(_UploadedFilesMarker)
