"""Versioning helpers for HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .abstractions import HttpRequest, as_http_request


class VersioningType(StrEnum):
    URI = "uri"
    HEADER = "header"
    MEDIA_TYPE = "media_type"


VERSION_NEUTRAL = "__VERSION_NEUTRAL__"


@dataclass(frozen=True, slots=True)
class VersioningOptions:
    type: VersioningType
    prefix: str = "v"
    header: str = "X-API-Version"
    default_version: str | None = None


def normalize_versions(version: str | list[str] | None) -> tuple[str, ...]:
    """Normalize a version declaration into a tuple."""
    if version is None:
        return ()
    if isinstance(version, list):
        return tuple(version)
    return (version,)


def extract_request_version(request: HttpRequest | object, options: VersioningOptions) -> str | None:
    """Extract a request version according to the configured strategy."""
    http_request = as_http_request(request)
    if options.type is VersioningType.HEADER:
        return http_request.headers.get(options.header) or options.default_version

    if options.type is VersioningType.MEDIA_TYPE:
        accept = http_request.headers.get("accept", "")
        for part in accept.split(";"):
            part = part.strip()
            if part.startswith("version="):
                return part.partition("=")[2]
        return options.default_version

    return options.default_version
