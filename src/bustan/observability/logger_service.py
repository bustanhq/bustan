"""Injectable logger service."""

from __future__ import annotations

from ..common.decorators.injectable import Injectable
from .logger import Logger


@Injectable
class LoggerService(Logger):
    """Injectable wrapper around the framework logger."""

    pass
