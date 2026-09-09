"""Every statement that touches the store, in one place."""

from __future__ import annotations

import sqlite3

from bustan import Injectable

from ..link_store import LinkStore
from .models import Link


@Injectable()
class LinksRepository:
    """Reads and writes links. Knows about rows; knows nothing about HTTP."""

    def __init__(self, store: LinkStore) -> None:
        self._store = store

    def list_links(self, limit: int) -> list[Link]:
        rows = self._store.connection.execute(
            "SELECT code, url, visits FROM links ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Link(code=row[0], url=row[1], visits=row[2]) for row in rows]

    def read_link(self, code: str) -> Link | None:
        row = self._store.connection.execute(
            "SELECT code, url, visits FROM links WHERE code = ?", (code,)
        ).fetchone()
        return None if row is None else Link(code=row[0], url=row[1], visits=row[2])

    def create_link(self, code: str, url: str) -> Link | None:
        """Store one link, or answer None when the code is already taken."""
        connection = self._store.connection
        try:
            connection.execute(
                "INSERT INTO links (code, url, visits) VALUES (?, ?, 0)", (code, url)
            )
        except sqlite3.IntegrityError:
            return None
        connection.commit()
        return Link(code=code, url=url, visits=0)

    def count_visit(self, code: str) -> None:
        connection = self._store.connection
        connection.execute("UPDATE links SET visits = visits + 1 WHERE code = ?", (code,))
        connection.commit()
