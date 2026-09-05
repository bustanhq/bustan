"""Form bodies, parsed without a form library.

Two encodings reach a handler: ``application/x-www-form-urlencoded``, which is a query
string in the body, and ``multipart/form-data``, which is how a browser uploads a file.
Both are parsed here into one :class:`FormData`, so a handler binding a form field or an
uploaded file reads the same shape whichever encoding it arrived in.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl

if TYPE_CHECKING:
    from collections.abc import Mapping

# The largest header block one multipart part may carry before the body is judged
# malformed rather than merely long, so a crafted body cannot be scanned indefinitely.
_MAX_PART_HEADER_BYTES = 16 * 1024


class UploadFile:
    """One file a multipart request uploaded, held in memory.

    The whole part is read before a handler sees it, because the body it came from has
    already been read; a deployment expecting uploads larger than memory sets a smaller
    body limit on the adapter and refuses them at the boundary instead.
    """

    __slots__ = ("_file", "content_type", "filename", "size")

    def __init__(self, filename: str | None, content_type: str | None, content: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = len(content)
        self._file = io.BytesIO(content)

    @property
    def file(self) -> io.BytesIO:
        """The uploaded bytes, as a file object positioned wherever reads left it."""

        return self._file

    async def read(self, size: int = -1) -> bytes:
        """Read *size* bytes from the upload, or the rest of it when *size* is -1."""

        return self._file.read(size)

    async def seek(self, offset: int) -> None:
        """Move the read position to *offset* bytes from the start."""

        self._file.seek(offset)

    async def close(self) -> None:
        """Release the upload. Reading afterwards raises ``ValueError``."""

        self._file.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(filename={self.filename!r}, size={self.size})"


class FormData:
    """Immutable multi-value view of one parsed form body.

    A form may repeat a field name, so every name maps to the values in arrival order.
    :meth:`get` returns the last one, matching what a server does with a repeated field,
    and :meth:`getlist` returns all of them.
    """

    __slots__ = ("_values",)

    def __init__(self, items: Iterable[tuple[str, str | UploadFile]] = ()) -> None:
        grouped: dict[str, list[str | UploadFile]] = {}
        for name, value in items:
            grouped.setdefault(name, []).append(value)
        self._values: dict[str, tuple[str | UploadFile, ...]] = {
            name: tuple(values) for name, values in grouped.items()
        }

    def get(self, key: str, default: object | None = None) -> object | None:
        """Return the last value sent for *key*, or *default* when it is absent."""

        values = self._values.get(key)
        return default if values is None else values[-1]

    def getlist(self, key: str) -> list[object]:
        """Return every value sent for *key*, in arrival order."""

        return list(self._values.get(key, ()))

    def multi_items(self) -> tuple[tuple[str, str | UploadFile], ...]:
        """Return every name and value pair, repeated names included."""

        return tuple((name, value) for name, values in self._values.items() for value in values)

    def __getitem__(self, key: str) -> str | UploadFile:
        return self._values[key][-1]

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.multi_items())!r})"


def parse_form_body(body: bytes, content_type: str | None) -> FormData:
    """Parse a request body as form data, according to what its content type says.

    A body with no form content type parses as empty rather than raising, because a
    handler asking for a form field on a request that carried none should see the field
    missing, which is the framework's error to report, not the transport's.
    """

    media_type, parameters = _parse_content_type(content_type)
    if media_type == "multipart/form-data":
        boundary = parameters.get("boundary")
        if boundary is None:
            raise ValueError("A multipart/form-data body must declare a boundary")
        return FormData(_parse_multipart(body, boundary.encode("latin-1")))
    if media_type == "application/x-www-form-urlencoded":
        charset = parameters.get("charset", "utf-8")
        return FormData(parse_qsl(body.decode(charset), keep_blank_values=True, encoding=charset))
    return FormData()


def _parse_content_type(content_type: str | None) -> tuple[str, dict[str, str]]:
    if not content_type:
        return "", {}
    media_type, _, remainder = content_type.partition(";")
    parameters: dict[str, str] = {}
    for parameter in remainder.split(";"):
        name, _, value = parameter.partition("=")
        if name.strip():
            parameters[name.strip().lower()] = value.strip().strip('"')
    return media_type.strip().lower(), parameters


def _parse_multipart(body: bytes, boundary: bytes) -> Iterator[tuple[str, str | UploadFile]]:
    delimiter = b"--" + boundary
    for raw_part in body.split(delimiter)[1:]:
        if raw_part.startswith(b"--"):
            break
        part = raw_part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        header_block, separator, content = part.partition(b"\r\n\r\n")
        if not separator or len(header_block) > _MAX_PART_HEADER_BYTES:
            raise ValueError("Malformed multipart/form-data part")
        headers = _parse_part_headers(header_block)
        name, filename = _parse_disposition(headers.get("content-disposition", ""))
        if name is None:
            continue
        if filename is None:
            yield name, content.decode("utf-8")
        else:
            yield name, UploadFile(filename, headers.get("content-type"), content)


def _parse_part_headers(header_block: bytes) -> Mapping[str, str]:
    headers: dict[str, str] = {}
    for line in header_block.split(b"\r\n"):
        name, separator, value = line.decode("latin-1").partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


def _parse_disposition(disposition: str) -> tuple[str | None, str | None]:
    _media_type, parameters = _parse_content_type(f"x;{disposition.partition(';')[2]}")
    return parameters.get("name"), parameters.get("filename")


__all__ = (
    "FormData",
    "UploadFile",
    "parse_form_body",
)
