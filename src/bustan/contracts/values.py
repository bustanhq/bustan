"""Neutral value types for the parts of a request that used to leak native objects.

``url`` and ``query_params`` are the two places where a transport's own datastructures
reached framework code, so the framework could not be exercised without that transport
installed. These types carry the same information as plain data and hold no reference
to whatever produced them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
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


__all__ = (
    "QueryParams",
    "Url",
)
