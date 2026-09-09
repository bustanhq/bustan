"""What the application does with tasks, apart from how they are stored or served."""

from __future__ import annotations

from bustan import ConfigService, Injectable

from .models import CreateTaskPayload, Task
from .tasks_repository import TasksRepository


@Injectable()
class TasksService:
    """Holds the rules. The controller translates HTTP; this decides."""

    def __init__(self, repository: TasksRepository, config: ConfigService) -> None:
        self._repository = repository
        self._page_size = int(config.get("PAGE_SIZE", 20))

    def list_tasks(self) -> list[Task]:
        return self._repository.list_tasks(self._page_size)

    def read_task(self, task_id: int) -> Task | None:
        return self._repository.read_task(task_id)

    def create_task(self, payload: CreateTaskPayload) -> Task:
        return self._repository.create_task(payload.title, payload.done)
