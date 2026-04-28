"""CORS configuration types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CorsOptions:
    """Configuration for application-level CORS support."""

    origins: str | list[str] = "*"
    methods: list[str] = field(
        default_factory=lambda: ["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"]
    )
    allowed_headers: list[str] = field(default_factory=lambda: ["*"])
    exposed_headers: list[str] = field(default_factory=list)
    credentials: bool = False
    max_age: int = 600
