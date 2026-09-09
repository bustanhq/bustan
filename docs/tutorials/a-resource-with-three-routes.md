# A Resource With Three Routes

**Where you are.** You finished [Your First App](first-app.md), and `curl http://127.0.0.1:3000/`
answers `{"message":"Hello from My App"}`.

By the end of this you will have a `tasks` resource that lists, reads and creates, answering `200`,
`404` and `201` as each case deserves, and refusing a malformed body with a problem document that
names the field.

The finished code for the whole series lives in
[`examples/tutorial_app`](../../examples/tutorial_app/). It runs in CI, so where it and this page
disagree, it is right. Its package is `tutorial_app` and yours is `my_app`; that is the only
difference.

## Add The Dependency Validation Needs

Automatic validation is built on Pydantic, which the `starlette` extra does not bring:

```bash
uv add pydantic
```

## Describe What A Task Is

Two shapes, and the distinction matters. `CreateTaskPayload` is what a caller sends, so it is a
Pydantic model and gets validated. `Task` is what you store and return, so it is a plain frozen
dataclass with no validation to do.

Create `src/my_app/tasks/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class CreateTaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    done: bool = False


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    title: str
    done: bool
```

## Hold The Tasks

For now they live in a list. [A Datastore And A Readiness Probe](a-datastore-and-a-readiness-probe.md)
replaces this with a real store, and nothing above it changes, which is the point of keeping storage
behind its own class.

Create `src/my_app/tasks/tasks_service.py`:

```python
from __future__ import annotations

from bustan import Injectable

from .models import CreateTaskPayload, Task


@Injectable()
class TasksService:
    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._next_id = 1

    def list_tasks(self) -> list[Task]:
        return list(self._tasks)

    def read_task(self, task_id: int) -> Task | None:
        return next((task for task in self._tasks if task.id == task_id), None)

    def create_task(self, payload: CreateTaskPayload) -> Task:
        task = Task(id=self._next_id, title=payload.title, done=payload.done)
        self._tasks.append(task)
        self._next_id += 1
        return task
```

`read_task` returns `None` for a task that is not there. Deciding what that means over HTTP is the
controller's job, not this one's.

## Serve The Three Routes

Create `src/my_app/tasks/tasks_controller.py`:

```python
from __future__ import annotations

from dataclasses import asdict

from bustan import Controller, Get, HttpResponse, Post
from bustan.errors import NotFoundException

from .models import CreateTaskPayload
from .tasks_service import TasksService


@Controller("/tasks")
class TasksController:
    def __init__(self, tasks: TasksService) -> None:
        self._tasks = tasks

    @Get("/")
    def list_tasks(self) -> list[dict[str, object]]:
        return [asdict(task) for task in self._tasks.list_tasks()]

    @Get("/{task_id}")
    def read_task(self, task_id: int) -> dict[str, object]:
        task = self._tasks.read_task(task_id)
        if task is None:
            raise NotFoundException(f"no task with id {task_id}")
        return asdict(task)

    @Post("/")
    def create_task(self, payload: CreateTaskPayload) -> HttpResponse:
        task = self._tasks.create_task(payload)
        return HttpResponse.json(
            asdict(task), status_code=201, headers={"location": f"/tasks/{task.id}"}
        )
```

Three things there are worth stopping on.

**`task_id: int` is bound from the path and converted.** The route declares `{task_id}` and the
parameter is annotated `int`, so a request to `/tasks/abc` is refused before your code runs. The full
set of binding rules is in [the routing reference](../reference/routing.md).

**Raising is how you answer 404.** Returning `None` would answer `204`, which tells a caller there is
nothing to send rather than that there is no such task. That distinction is easy to get wrong and
easy to miss, because both look fine until somebody writes a client.

**Returning a response object is how you answer 201.** Returning the dataclass would answer `200`.
A created resource deserves `201` and a `Location` header pointing at it.

## Make It A Module

A feature is a module. Create `src/my_app/tasks/tasks_module.py`:

```python
from __future__ import annotations

from bustan import Module

from .tasks_controller import TasksController
from .tasks_service import TasksService


@Module(controllers=[TasksController], providers=[TasksService], exports=[TasksService])
class TasksModule:
    pass
```

`exports` is the module's public surface. Another module that imports `TasksModule` can inject
`TasksService`; nothing else inside it is reachable. That is what makes a module a boundary rather
than a folder.

Add an empty `src/my_app/tasks/__init__.py`, then import the module in `src/my_app/app_module.py`:

```python
from bustan import Module

from .app_controller import AppController
from .app_service import AppService
from .tasks.tasks_module import TasksModule


@Module(imports=[TasksModule], controllers=[AppController], providers=[AppService])
class AppModule:
    pass
```

## Drive It

```bash
uv run dev
```

Create one:

```bash
curl -i -X POST http://127.0.0.1:3000/tasks/ \
  -H 'content-type: application/json' \
  -d '{"title": "Read the tutorial"}'
```

```text
HTTP/1.1 201 Created
location: /tasks/1

{"id":1,"title":"Read the tutorial","done":false}
```

Read one that is not there:

```bash
curl -i http://127.0.0.1:3000/tasks/999
```

```text
HTTP/1.1 404 Not Found
content-type: application/problem+json

{"type":"https://bustan.dev/problems/not-found","title":"Not Found","status":404,
 "detail":"no task with id 999","instance":"/tasks/999","code":"not-found"}
```

Send a title that is empty:

```bash
curl -i -X POST http://127.0.0.1:3000/tasks/ \
  -H 'content-type: application/json' -d '{"title": ""}'
```

```text
HTTP/1.1 400 Bad Request
content-type: application/problem+json
```

The body carries an `errors` array, and each entry names the `field` that failed and the `source` it
came from. That shape is the same for every refusal the framework makes, which is what lets a client
handle all of them once. The catalogue of what each error means is
[the error reference](../reference/errors.md).

## Test The Three Promises

Add to `tests/my_app/test_tasks.py`:

```python
from bustan.testing import AsgiTestClient
from my_app import build_application


def test_create_returns_201() -> None:
    with AsgiTestClient(build_application()) as client:
        response = client.post("/tasks/", json={"title": "Write the tutorial"})

    assert response.status_code == 201
    assert response.headers["location"] == f"/tasks/{response.json()['id']}"


def test_missing_task_returns_404() -> None:
    with AsgiTestClient(build_application()) as client:
        response = client.get("/tasks/999")

    assert response.status_code == 404
    assert response.json()["code"] == "not-found"


def test_invalid_payload_returns_problem_details() -> None:
    with AsgiTestClient(build_application()) as client:
        response = client.post("/tasks/", json={"title": ""})

    assert response.status_code == 400
    assert response.json()["errors"][0]["source"] == "body"
```

```bash
uv run pytest
```

Three tests, three sentences. Each one is a promise this page made, which is the only kind worth
writing first.

Notice there is no fixture yet. Building the application inline three times is repetitive but not
yet wrong; [A Datastore And A Readiness Probe](a-datastore-and-a-readiness-probe.md) introduces a
`conftest.py` at the point shared setup becomes real.

## Next

The service holds a hard-coded page of tasks and nothing is configurable. Next:
[Configuration End To End](configuration-end-to-end.md).
