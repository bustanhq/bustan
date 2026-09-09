# Before The Handler Runs

**Where you are.** You finished
[A Datastore And A Readiness Probe](a-datastore-and-a-readiness-probe.md), tasks survive a restart,
and `/health/ready` reports the store.

By the end of this, every response will carry a request id, and creating a task will need a bearer
token and the right role. You will also cause the framework's sharpest startup refusal on purpose.

Two stages of the request pipeline do this work, and they are not interchangeable. Take them in the
order they run.

## Middleware: Everything, Before Anything Is Chosen

Middleware runs first, on every request, and knows nothing about which handler will be called. That
makes it right for work that is genuinely universal and wrong for anything that depends on the route.

Create `src/my_app/request_id_middleware.py`:

```python
from __future__ import annotations

from uuid import uuid4

from bustan import HttpRequest, Middleware


class RequestIdMiddleware(Middleware):
    async def use(self, request: HttpRequest, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
```

Register it from the root module by implementing `configure`:

```python
from bustan import MiddlewareConsumer


class AppModule:
    def configure(self, consumer: MiddlewareConsumer) -> None:
        consumer.apply(RequestIdMiddleware).exclude("/health/live", "/health/ready")
```

The probes are excluded because a load balancer calls them constantly and a correlation id on a
liveness check correlates nothing.

```bash
curl -i http://127.0.0.1:3000/tasks/ | grep x-request-id
```

## Identity: After Routing, Because It Depends On The Route

Whether a request may proceed depends on which handler it reached: some routes are public, some need
a role. That is a guard's question, not middleware's, and the framework has one built for policy
already. Which stage a piece of work belongs in is the whole subject of
[Choose A Pipeline Hook](../how-to/choose-a-pipeline-hook.md).

You supply the part only your application knows: who the caller is.

Create `src/my_app/bearer_authenticator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from bustan import ConfigService, ExecutionContext, Injectable


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


@Injectable()
class BearerAuthenticator:
    def __init__(self, config: ConfigService) -> None:
        self._token = str(config.get_or_throw("API_TOKEN"))

    def authenticate(self, context: ExecutionContext) -> TokenPrincipal | None:
        request = context.request
        header = "" if request is None else request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token != self._token:
            return None
        return TokenPrincipal(id="tutorial-user", roles=("author",), permissions=())
```

Returning `None` is the refusal. The guard turns it into a `401`, and you never write that status
yourself.

`TokenPrincipal` satisfies the framework's `Principal` protocol by having the three attributes it
names. Comparing one configured token is the tutorial's shortcut; a real authenticator verifies a
signature or asks an identity provider, and nothing around it changes.

## Tell The Framework Which Strategy Is Which

A route asks for a strategy by name. The registry maps that name to the thing that answers it.

Create `src/my_app/identity_module.py`:

```python
from __future__ import annotations

from bustan import AUTHENTICATOR_REGISTRY, Module

from .bearer_authenticator import BearerAuthenticator


def _registry(authenticator: BearerAuthenticator) -> dict[str, object]:
    return {"bearer": authenticator}


@Module(
    providers=[
        BearerAuthenticator,
        {
            "provide": AUTHENTICATOR_REGISTRY,
            "use_factory": _registry,
            "inject": (BearerAuthenticator,),
        },
    ],
    exports=[AUTHENTICATOR_REGISTRY],
)
class IdentityModule:
    pass
```

## Guard The Routes

In `tasks_controller.py`:

```python
from bustan import Auth, Roles


@Controller("/tasks")
@Auth("bearer")
class TasksController:
    ...

    @Post("/")
    @Roles("author")
    def create_task(self, payload: CreateTaskPayload) -> HttpResponse:
        ...
```

`@Auth` on the class covers every route in it. `@Roles` on the handler narrows one further.

## Cause The Refusal On Purpose

Start the application **without** importing `IdentityModule` into `TasksModule`. It refuses to
start:

```text
TasksController.list_tasks authenticates its callers, and no provider for
AUTHENTICATOR_REGISTRY is visible to TasksModule. Declare one in that module, or
import a module that exports it
```

This is the framework at its best. A route that asks for authentication it cannot get is a defect,
and it is caught while routes compile, naming the handler and the module, rather than becoming a
`500` on a caller's first request. The same shape as the store refusal in the last tutorial, and the
same fix: import the module that exports what you need.

Add the import:

```python
@Module(
    imports=[StoreModule, IdentityModule],
    ...
)
class TasksModule:
    pass
```

And import `IdentityModule` in the root module too.

## Drive It

```bash
curl -i http://127.0.0.1:3000/tasks/
```

```text
HTTP/1.1 401 Unauthorized
```

```bash
curl -i http://127.0.0.1:3000/tasks/ -H 'authorization: Bearer tutorial-secret-token'
```

```text
HTTP/1.1 200 OK
```

`401` means the framework does not know who you are; `403` means it knows and you may not. The
distinction, and what each is allowed to say, is in
[Harden An Application](../how-to/harden-security.md#401-versus-403).

## Test Both Sides

```python
def test_a_request_without_a_token_is_refused(client: AsgiTestClient) -> None:
    assert client.get("/tasks/").status_code == 401


def test_every_response_carries_a_request_id(client, token) -> None:
    assert client.get("/tasks/", headers=token).headers["x-request-id"]


def test_the_probes_are_not_stamped(client: AsgiTestClient) -> None:
    assert "x-request-id" not in client.get("/health/live").headers
```

Add a `token` fixture to `conftest.py` returning
`{"authorization": "Bearer tutorial-secret-token"}`, and give the existing tests that header.

Testing the refusal is the half people skip. A guard that never refuses in a test is a guard nobody
has checked.

## Next

The API works and nothing describes it. Next: [OpenAPI And Swagger UI](openapi-and-swagger-ui.md).
