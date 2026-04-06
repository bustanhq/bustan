"""Shared type definitions and protocols for the framework."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar
from dataclasses import dataclass

T = TypeVar("T")
ClassT = TypeVar("ClassT", bound=type[object])
DecoratedT = TypeVar("DecoratedT", bound=object)


class ProviderScope(StrEnum):
    """Supported provider lifetimes."""

    SINGLETON = "singleton"
    TRANSIENT = "transient"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class ControllerMetadata:
    """Static metadata captured from a @Controller declaration."""

    prefix: str = ""


@dataclass(frozen=True, slots=True)
class RouteMetadata:
    """Static metadata captured from an HTTP method decorator."""

    method: str
    path: str
    name: str
