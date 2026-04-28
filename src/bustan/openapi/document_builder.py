"""OpenAPI document configuration builder."""

from __future__ import annotations


class DocumentBuilder:
    """Fluent builder for the base OpenAPI document."""

    def __init__(self) -> None:
        self._title = "API"
        self._version = "1.0"
        self._description = ""
        self._security_schemes: dict[str, dict[str, object]] = {}

    def set_title(self, title: str) -> "DocumentBuilder":
        self._title = title
        return self

    def set_version(self, version: str) -> "DocumentBuilder":
        self._version = version
        return self

    def set_description(self, description: str) -> "DocumentBuilder":
        self._description = description
        return self

    def add_bearer_auth(self, name: str = "bearer") -> "DocumentBuilder":
        self._security_schemes[name] = {"type": "http", "scheme": "bearer"}
        return self

    def build(self) -> dict[str, object]:
        return {
            "openapi": "3.1.0",
            "info": {
                "title": self._title,
                "version": self._version,
                "description": self._description,
            },
            "components": {"securitySchemes": dict(self._security_schemes)},
            "paths": {},
        }
