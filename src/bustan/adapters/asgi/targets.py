"""How a request target becomes the path, raw path and query string of a scope.

One parser, called by everything in this package that builds a connection scope. There
are two such places - the server that reads a request off a socket and the client that
drives an application without one - and two spellings of one reading drift apart at the
first fix that reaches only one of them.

What arrives is the target the caller wrote, which is not yet the path a router matches.
It carries a query string, and it carries percent escapes: ``/users/John%20Doe`` is how a
caller addresses ``/users/John Doe``, because the second cannot be sent. A router handed
the target as it arrived answers a literal route only when the caller happened to spell it
the way the route was written, hands a handler text nobody sent, and can never match a
converter that constrains what a segment may contain.

The decoding is done one segment at a time, and that is what keeps a caller from choosing
which route answers. An escaped separator is a character written inside a segment;
decoding the target whole turns it into a boundary and moves the request to a path with
one more segment than the caller addressed, which is a different route. Splitting on the
separator first makes that impossible: an escape can only ever produce a character inside
the segment it was written in. Where that character is itself a separator it is written
back as an escape, because a scope carries the path as one string and a bare separator in
it is the boundary that was just refused. ``raw_path`` carries the target as it arrived,
for anything that needs what the caller wrote rather than what it means.

Nothing is normalised. A dot segment is a name here rather than a navigation, because no
server this framework runs on collapses one either, and a transport that quietly resolved
one would answer a different route from the transport beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import unquote

# What a separator produced by decoding is written back as, so that it stays inside the
# segment the caller wrote it in.
ENCODED_SEPARATOR = "%2F"


class HttpParseError(Exception):
    """Raised when a request cannot be read, carrying the status that answers it."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RequestTarget:
    """One request target, read into the three fields a connection scope carries.

    ``path`` is what a router matches, decoded. ``raw_path`` is the same part of the
    target exactly as the caller wrote it. ``query_string`` is everything after the first
    ``?``, undecoded, because what its escapes mean is decided by whoever parses it.
    """

    path: str
    raw_path: bytes
    query_string: bytes


def parse_request_target(target: bytes) -> RequestTarget:
    """Read one request target into the fields a connection scope carries.

    A target with a byte outside ASCII in it is refused rather than read: the characters
    outside ASCII a caller can address are the ones it percent-encodes, so a request
    carrying the bytes themselves has already been rewritten by something that did not
    know it was carrying a URL, and reading it means guessing which encoding that was.

    A segment whose escapes decode to bytes that are not UTF-8 is refused for the same
    reason: what the caller meant by them cannot be recovered, and a path assembled out of
    replacement characters is a path nobody addressed.
    """

    if not target.isascii():
        raise HttpParseError(HTTPStatus.BAD_REQUEST, "Non-ASCII byte in the request target")
    raw_path, _separator, query_string = target.partition(b"?")
    path = "/".join(_decoded_segment(segment) for segment in raw_path.split(b"/"))
    return RequestTarget(path=path, raw_path=raw_path, query_string=query_string)


def _decoded_segment(segment: bytes) -> str:
    """Decode one path segment, keeping any separator it decodes to inside the segment.

    A percent that begins no escape decodes to nothing and stays the character it is,
    which is what every server does with it: refusing it would answer a caller who sent a
    bare percent that its request was unreadable.
    """

    try:
        decoded = unquote(segment.decode("ascii"), errors="strict")
    except UnicodeDecodeError as error:
        raise HttpParseError(
            HTTPStatus.BAD_REQUEST, "Undecodable percent-encoding in the request target"
        ) from error
    return decoded.replace("/", ENCODED_SEPARATOR)


__all__ = (
    "ENCODED_SEPARATOR",
    "HttpParseError",
    "RequestTarget",
    "parse_request_target",
)
