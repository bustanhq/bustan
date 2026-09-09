"""Every statement that touches the store, in one place."""

from __future__ import annotations

from bustan import Injectable

from ..task_store import TaskStore
from .models import Task


@Injectable()
class TasksRepository:
    """Reads and writes tasks. Knows about rows; knows nothing about HTTP."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    def list_tasks(self, limit: int) -> list[Task]:
        rows = self._store.connection.execute(
            "SELECT id, title, done FROM tasks ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        return [Task(id=row[0], title=row[1], done=bool(row[2])) for row in rows]

    def read_task(self, task_id: int) -> Task | None:
        row = self._store.connection.execute(
            "SELECT id, title, done FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return None if row is None else Task(id=row[0], title=row[1], done=bool(row[2]))

    def create_task(self, title: str, done: bool) -> Task:
        connection = self._store.connection
        cursor = connection.execute(
            "INSERT INTO tasks (title, done) VALUES (?, ?)", (title, int(done))
        )
        connection.commit()
        return Task(id=int(cursor.lastrowid or 0), title=title, done=done)
