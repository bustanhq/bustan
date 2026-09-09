"""The settings this application refuses to start without."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Every value the application reads, validated once while it is built.

    A schema turns a missing or malformed setting into a refusal at startup, where one
    person reads it, instead of an AttributeError on the first request that needed it.
    """

    model_config = {"extra": "ignore"}

    DATABASE_PATH: str = Field(min_length=1)
    API_TOKEN: str = Field(min_length=8)
    PAGE_SIZE: int = Field(default=20, ge=1, le=100)
