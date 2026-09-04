"""Base provider whose constructor uses names that only exist in this module."""

from __future__ import annotations

from typing import Annotated

from bustan import Inject, InjectionToken

SETTINGS = InjectionToken("SETTINGS")


class BaseRepository:
    def __init__(self, settings: Annotated[dict, Inject(SETTINGS)]) -> None:
        self.settings = settings
