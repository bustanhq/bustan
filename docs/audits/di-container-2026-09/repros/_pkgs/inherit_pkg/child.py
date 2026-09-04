"""Subclass that inherits __init__ without importing Inject or SETTINGS."""

from __future__ import annotations

from bustan import Injectable

from .base import BaseRepository


@Injectable()
class UserRepository(BaseRepository):
    pass
