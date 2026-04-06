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


class _MarkerCallable:
    """Makes a marker usable both bare (``Annotated[str, Body]``)
    and as a call (``Annotated[str, Body("field")]``)."""

    def __init__(self, marker_cls: type) -> None:
        self._cls = marker_cls
        self._default = marker_cls()

    def __call__(self, alias: str) -> object:
        return self._cls(alias=alias)

    def __repr__(self) -> str:
        return self._cls.__name__.lstrip("_")

    # Allow use as bare annotation marker (not called)
    @property
    def alias(self) -> str | None:
        return None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, (_MarkerCallable, self._cls))

    def __hash__(self) -> int:
        return hash(self._cls)


Body: _MarkerCallable = _MarkerCallable(_BodyMarker)
Query: _MarkerCallable = _MarkerCallable(_QueryMarker)
Param: _MarkerCallable = _MarkerCallable(_ParamMarker)
Header: _MarkerCallable = _MarkerCallable(_HeaderMarker)
