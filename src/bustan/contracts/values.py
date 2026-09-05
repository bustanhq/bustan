"""Neutral value types for the parts of a request that used to leak native objects.

``url``, ``query_params``, ``headers`` and ``state`` are the places where a transport's
own datastructures reached framework code, so the framework could not be exercised
without that transport installed. These types carry the same information as plain data
and hold no reference to whatever produced them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


@dataclass(frozen=True, slots=True)
class Url:
    """The parts of a request URL the framework reads, as plain data.

    ``query_string`` is the raw, still-encoded text after ``?`` with no leading ``?``;
    decoding it is :class:`QueryParams`' job. ``port`` is ``None`` when the request did
    not carry one, rather than being filled in from the scheme, because the framework
    reports what arrived instead of guessing.
    """

    scheme: str = ""
    host: str = ""
    port: int | None = None
    path: str = "/"
    query_string: str = ""
    fragment: str = ""

    @property
    def netloc(self) -> str:
        """Host and, when one was supplied, port, joined the way a URL writes them."""

        if self.port is None:
            return self.host
        return f"{self.host}:{self.port}"

    def __str__(self) -> str:
        scheme = f"{self.scheme}:" if self.scheme else ""
        authority = f"//{self.netloc}" if self.host else ""
        query = f"?{self.query_string}" if self.query_string else ""
        fragment = f"#{self.fragment}" if self.fragment else ""
        return f"{scheme}{authority}{self.path}{query}{fragment}"


class QueryParams:
    """Immutable multi-value view of a decoded query string.

    A query string may repeat a key, so every key maps to an ordered tuple of the
    values as they arrived. Subscripting returns the *last* value for a key, matching
    what HTTP servers do with a repeated parameter; :meth:`getlist` returns all of
    them. Construction is the only way to put values in, which is what makes an
    instance safe to hand to application code.
    """

    __slots__ = ("_values",)

    def __init__(self, items: Iterable[tuple[str, str]] = ()) -> None:
        grouped: dict[str, list[str]] = {}
        for key, value in items:
            grouped.setdefault(key, []).append(value)
        self._values: dict[str, tuple[str, ...]] = {
            key: tuple(values) for key, values in grouped.items()
        }

    @classmethod
    def from_query_string(cls, query_string: str) -> QueryParams:
        """Build parameters from raw query text, with or without a leading ``?``."""

        return cls(parse_qsl(query_string.removeprefix("?"), keep_blank_values=True))

    def getlist(self, key: str) -> list[str]:
        """Return every value supplied for ``key``, in arrival order."""

        return list(self._values.get(key, ()))

    def get(self, key: str, default: str | None = None) -> str | None:
        """Return the last value for ``key``, or ``default`` when it is absent."""

        values = self._values.get(key)
        return default if values is None else values[-1]

    def keys(self) -> tuple[str, ...]:
        """Return each key once, in the order it first appeared."""

        return tuple(self._values)

    def multi_items(self) -> tuple[tuple[str, str], ...]:
        """Return every key and value pair, repeated keys included."""

        return tuple((key, value) for key, values in self._values.items() for value in values)

    def __getitem__(self, key: str) -> str:
        return self._values[key][-1]

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QueryParams):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:
        return hash(tuple(self._values.items()))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.multi_items())!r})"


class Headers(Mapping[str, str]):
    """Immutable, case-insensitive view of the headers one request arrived with.

    HTTP header names are case-insensitive, so lookups are folded to lower case while
    iteration reports the names as they arrived. A name may be sent more than once;
    subscripting joins the repeats with ``, `` the way HTTP defines it, and
    :meth:`getlist` returns them separately.
    """

    __slots__ = ("_order", "_values")

    def __init__(self, items: Iterable[tuple[str, str]] = ()) -> None:
        grouped: dict[str, list[str]] = {}
        order: dict[str, str] = {}
        for name, value in items:
            folded = name.lower()
            grouped.setdefault(folded, []).append(value)
            order.setdefault(folded, name)
        self._values: dict[str, tuple[str, ...]] = {
            name: tuple(values) for name, values in grouped.items()
        }
        self._order: dict[str, str] = order

    def getlist(self, key: str) -> list[str]:
        """Return every value sent under *key*, in arrival order."""

        return list(self._values.get(key.lower(), ()))

    def __getitem__(self, key: str) -> str:
        return ", ".join(self._values[key.lower()])

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._order.values())

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Headers):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:
        return hash(tuple(self._values.items()))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.items())!r})"


class RequestState:
    """Mutable attribute namespace that lives exactly as long as one request.

    Attributes are read and written as ordinary attributes and kept in a mapping the
    caller may supply, so a transport that already owns per-request storage hands that
    mapping over and the two views stay the same data rather than two copies that
    drift. Reading an attribute that was never written raises ``AttributeError``, which
    is what lets ``getattr(state, name, default)`` tell "not set yet" apart from "set
    to ``None``".
    """

    __slots__ = ("_values",)

    def __init__(self, values: MutableMapping[str, Any] | None = None) -> None:
        object.__setattr__(self, "_values", {} if values is None else values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: object) -> None:
        self._values[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({sorted(self._values)!r})"


__all__ = (
    "Headers",
    "QueryParams",
    "RequestState",
    "Url",
)
