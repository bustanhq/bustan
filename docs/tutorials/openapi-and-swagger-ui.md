# OpenAPI And Swagger UI

**Where you are.** You finished [Before The Handler Runs](before-the-handler-runs.md). Requests
carry an id, and `/tasks/` refuses a caller with no token.

By the end of this the application will publish an OpenAPI document describing what it already
serves, and a browsable page for reading it.

Nothing about the routes changes here. The document is generated from the application the framework
already compiled, so it cannot describe a route that does not exist, and it cannot miss one that
does.

## Describe The Application

In `src/my_app/__init__.py`, build a document and hand it to `create_app`:

```python
from bustan import DocumentBuilder, SwaggerOptions, create_app

from .app_module import AppModule


def build_application() -> Application:
    document = (
        DocumentBuilder()
        .set_title("Tasks API")
        .set_description("The application the tutorial series builds.")
        .set_version("1.0.0")
        .add_bearer_auth()
    )
    return create_app(AppModule, swagger=SwaggerOptions(document_builder=document, path="/api"))
```

`SwaggerOptions` takes the builder, not a built document. It calls `build()` at the point the
application is compiled, which is what lets the document see every route.

`add_bearer_auth` declares that the API uses bearer tokens. It describes; it does not enforce. The
guard from the last tutorial is what enforces, and the two agreeing is your job.

## Read It

```bash
uv run dev
curl http://127.0.0.1:3000/api | python -m json.tool | head -20
```

The paths are already there:

```json
{"paths": {"/health/live": {...}, "/health/ready": {...},
           "/tasks": {...}, "/tasks/{task_id}": {...}}}
```

Note `/tasks`, without the trailing slash the route declares. That is the document's normalised form
and it is worth knowing before you assert on it in a test.

Open `http://127.0.0.1:3000/api/docs` in a browser for the same document as a page you can click
through.

## Say More Than The Signatures Do

The document so far is inferred: paths, methods, path parameters, and the shape of a Pydantic
payload. What it cannot infer is intent. Four decorators supply it.

In `tasks_controller.py`:

```python
from bustan import ApiBearerAuth, ApiOperation, ApiResponse, ApiTags


@Controller("/tasks")
@Auth("bearer")
@ApiTags("tasks")
@ApiBearerAuth()
class TasksController:

    @Get("/{task_id}")
    @ApiOperation(summary="Read one task by its id")
    @ApiResponse(status=404, description="No task with that id")
    def read_task(self, task_id: int) -> dict[str, object]:
        ...
```

`@ApiTags` groups the routes under a heading. `@ApiOperation` gives the human sentence a signature
cannot. `@ApiResponse` documents an outcome the framework cannot infer, because a `404` raised
inside a handler is invisible to a signature. `@ApiBearerAuth` marks the routes as needing the
scheme declared above.

Document the outcomes a caller has to handle, and stop. A response entry per status code you can
imagine is a document nobody reads.

## Test That It Is Served

```python
def test_the_openapi_document_is_served(client: AsgiTestClient) -> None:
    document = client.get("/api").json()
    assert document["info"]["title"] == "Tasks API"
    assert "/tasks" in document["paths"]
    assert "/tasks/{task_id}" in document["paths"]
```

Asserting the paths is worth more than it looks. It fails when a route is removed and the document
silently stops describing it, which is the failure nobody notices by reading.

## Where This Leaves You

You have an application that serves a validated resource with correct statuses, reads its settings
from the environment, keeps data in a store it opens and disposes cleanly, reports honestly on
whether it can serve, refuses callers it does not recognise, and describes itself.

The whole thing is in [`examples/tutorial_app`](../../examples/tutorial_app/), which runs in CI.

Where to go next depends on what you are doing:

- **Putting it in a container** - [Containerise An Application](../how-to/containerise-an-application.md).
- **Running it in production** - [Deploy An Application](../how-to/deploy.md), which covers draining,
  workers and proxies.
- **Watching it** - [Observe An Application](../how-to/observe-an-application.md) for metrics,
  tracing and correlation.
- **Locking it down** - [Harden An Application](../how-to/harden-security.md) for throttling, CORS
  and request limits.
- **Growing the suite** - [Test An Application](../how-to/test-an-application.md).
