"""The HTTP surface for tasks."""

from __future__ import annotations

from dataclasses import asdict

from bustan import Auth, Controller, Get, HttpResponse, Post, Roles
from bustan.errors import NotFoundException

from .models import CreateTaskPayload
from .tasks_service import TasksService


@Controller("/tasks")
@Auth("bearer")
class TasksController:
    """Translates HTTP into calls on the service, and answers with the right status.

    Reading is open to any authenticated caller; writing needs the ``author`` role.
    """

    def __init__(self, tasks: TasksService) -> None:
        self._tasks = tasks

    @Get("/")
    def list_tasks(self) -> list[dict[str, object]]:
        return [asdict(task) for task in self._tasks.list_tasks()]

    @Get("/{task_id}")
    def read_task(self, task_id: int) -> dict[str, object]:
        task = self._tasks.read_task(task_id)
        if task is None:
            # Returning None here would answer 204, which says "nothing to send" rather
            # than "no such task". Raise instead, and the error contract answers 404.
            raise NotFoundException(f"no task with id {task_id}")
        return asdict(task)

    @Post("/")
    @Roles("author")
    def create_task(self, payload: CreateTaskPayload) -> HttpResponse:
        task = self._tasks.create_task(payload)
        # 201 and a Location header are the contract for a created resource; returning
        # the dataclass alone would answer 200.
        return HttpResponse.json(
            asdict(task), status_code=201, headers={"location": f"/tasks/{task.id}"}
        )
