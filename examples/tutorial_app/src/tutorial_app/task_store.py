"""The connection the application opens once and disposes once."""

from __future__ import annotations

import sqlite3

from bustan import ConfigService, Injectable


@Injectable()
class TaskStore:
    """Owns the database handle for the life of the application.

    Opened in ``on_application_bootstrap`` rather than in ``__init__`` because a
    constructor cannot await and a failure there is harder to attribute; disposed in
    ``on_module_destroy`` so a restart does not leak the handle. A real deployment swaps
    sqlite3 for a pool such as asyncpg and the wiring above and below is unchanged.
    """

    def __init__(self, config: ConfigService) -> None:
        self._path = str(config.get_or_throw("DATABASE_PATH"))
        self._connection: sqlite3.Connection | None = None

    async def on_application_bootstrap(self) -> None:
        # check_same_thread=False because a synchronous handler runs in a worker thread
        # while the event loop that opened this connection runs in another.
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, done INTEGER NOT NULL)"
        )
        self._connection.commit()

    async def on_module_destroy(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        """The open handle, or a refusal naming why there is none."""
        if self._connection is None:
            raise RuntimeError("the task store is not open; the application has not started")
        return self._connection

    def is_answering(self) -> bool:
        """Whether the store can still serve a query, which is what readiness asks."""
        if self._connection is None:
            return False
        try:
            self._connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True
