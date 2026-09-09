"""The shapes a link takes on the way in and on the way out."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field, HttpUrl


class CreateLinkPayload(BaseModel):
    """What a caller sends to shorten a URL.

    ``HttpUrl`` is what makes a malformed address a refusal before any code runs, rather
    than a redirect to nowhere discovered by whoever clicks it.
    """

    url: HttpUrl
    code: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class Link:
    """A shortened link as it is stored and returned."""

    code: str
    url: str
    visits: int
