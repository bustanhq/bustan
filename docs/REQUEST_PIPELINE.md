# Request Pipeline

`Bustan` executes request-time behavior in a fixed order so cross-cutting logic stays predictable and debuggable.

## Execution Order

1. Guards
2. Parameter binding
3. Pipes
4. Interceptors
5. Handler
6. Response coercion

Exception filters wrap the downstream path. A filter can translate binding errors, guard rejections, interceptor failures, or handler exceptions into a normal response payload.

## Choose The Right Hook

- Use a guard to allow or block request execution before the handler runs.
- Use a pipe to transform or validate already bound parameter values.
- Use an interceptor to wrap handler execution and shape the result.
- Use an exception filter to convert exceptions into a response payload or platform response.

## Prefer The Public Pipeline Contracts

When building custom pipeline components, stay on the stable exports from `bustan`:

- `ExecutionContext` is the primary request-time context object.
- `CallHandler` is the continuation contract passed into interceptors.
- `Guard`, `Pipe`, `Interceptor`, and `ExceptionFilter` are the public base classes.

Older code may reference compatibility shims from internal modules. Prefer `ExecutionContext` and `CallHandler` for new code.

## Example

```python
from starlette.responses import JSONResponse

from bustan import (
    CallHandler,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    Interceptor,
    Module,
    Pipe,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)


class AuthGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool:
        return context.request.headers.get("x-user-id") is not None


class TrimPipe(Pipe):
    async def transform(self, value: object, context: ExecutionContext) -> object:
        if context.parameter_name == "name" and isinstance(value, str):
            return value.strip().title()
        return value


class EnvelopeInterceptor(Interceptor):
    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        result = await next.handle()
        return {"path": context.request.path, "data": result}


class ValueErrorFilter(ExceptionFilter):
    exception_types = (ValueError,)

    async def catch(self, exc: Exception, context: ExecutionContext) -> object:
        return JSONResponse(
            {"detail": str(exc), "path": context.request.path},
            status_code=422,
        )


@UseGuards(AuthGuard())
@UseInterceptors(EnvelopeInterceptor())
@Controller("/messages")
class MessagesController:
    @UseFilters(ValueErrorFilter())
    @UsePipes(TrimPipe())
    @Get("/{name}")
    def read_message(self, name: str, excited: bool = False) -> dict[str, object]:
        if name == "Error":
            raise ValueError("reserved name")
        return {"message": f"hello {name}", "excited": excited}


@Module(controllers=[MessagesController])
class AppModule:
    pass
```

## What `ExecutionContext` Gives You

`ExecutionContext` carries both request-level and parameter-level information:

- `context.request` exposes the adapter-neutral request wrapper.
- `context.get_handler()` and `context.get_class()` identify the active handler and controller.
- `context.parameter_name`, `context.parameter_source`, and `context.metatype` are populated while pipes run.
- `context.container` and `context.module` expose the active resolution context for advanced integrations.

That is enough for most guards, pipes, interceptors, and filters without reaching into internal modules.

## Automatic Validation

When a controller or route uses `validation_mode="auto"`, Bustan appends `ValidationPipe` automatically for supported Pydantic model parameters unless you have already attached one explicitly.

That means this route rejects invalid payloads before the handler runs:

```python
from pydantic import BaseModel

from bustan import Controller, Module, Post


class CreateUserPayload(BaseModel):
    name: str
    admin: bool


@Controller("/users", validation_mode="auto")
class UsersController:
    @Post("/")
    def create_user(self, payload: CreateUserPayload) -> dict[str, str]:
        return {"name": payload.name}


@Module(controllers=[UsersController])
class AppModule:
    pass
```

## Global Pipeline Components

Use the global provider tokens when a component should apply to every compiled route:

- `APP_GUARD`
- `APP_PIPE`
- `APP_INTERCEPTOR`
- `APP_FILTER`

Example pattern:

```python
from bustan import APP_GUARD, Guard, Module


class RejectAllGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool:
        return False


@Module(
    providers=[{"provide": APP_GUARD, "use_class": RejectAllGuard}],
)
class AppModule:
    pass
```

Global components are resolved through the container **once per request**, not once
while routes are compiled. Three things follow:

- A global component may declare any lifetime a provider can. A request-scoped global
  guard is built for each request and may inject `Request` or any other request-scoped
  provider.
- A global component may be built by an asynchronous factory, because the request path
  awaits every provider it builds.
- A global component registered under a token that an override replaces is built from
  the replacement, because the token is read on the request rather than captured while
  routes are compiled. The override still belongs to bootstrap: register it before the
  application starts, through `bustan.testing`, and every request the application then
  serves runs the replacement.

Register more than one component under one token by binding a list, or by writing a
separate entry for each component. Both spellings run `APP_GUARD`, `APP_PIPE` and
`APP_INTERCEPTOR` components in the order they were declared, and the components of
every declaring module run in the order the modules were registered. `APP_FILTER` is
ordered by the precedence rule below instead:

```python
@Module(
    providers=[{"provide": APP_GUARD, "use_value": [AuditGuard(), RejectAllGuard()]}],
)
class AppModule:
    pass
```

```python
@Module(
    providers=[
        {"provide": APP_GUARD, "use_value": AuditGuard()},
        {"provide": APP_GUARD, "use_class": RejectAllGuard},
    ],
)
class AppModule:
    pass
```

A module may mix the two spellings under one token, and the result is one flat list in
declaration order: an entry that names a list contributes its components in place, and
every other entry contributes its one component.

Exception filters are ordered by how closely each one matches the error, not by where
it was declared. An error is offered to the matching filters one at a time until one
returns a result: a filter that names a type narrower than `Exception` is asked before
any catch-all filter, a filter naming a nearer base class is asked before one naming a
further base class, and two filters that match the error equally closely are asked in
the reverse of declaration order, so the one declared last is asked first. Both
spellings rank the same way, and so do filters contributed by different modules.

## Resolving Providers Inside a Handler

`ApplicationContext.get()` resolves as though no request were being served, so it
refuses anything request-scoped. To reach a request-scoped provider from inside a
handler, a guard or an interceptor, inject `ModuleRef` and call its `get()`: it resolves
against the request currently in flight and returns the same instance the rest of that
request sees.

```python
from bustan import Controller, Get, ModuleRef, Scope


@Controller("/orders", scope=Scope.REQUEST)
class OrdersController:
    def __init__(self, module_ref: ModuleRef) -> None:
        self.module_ref = module_ref

    @Get("/")
    def index(self) -> dict[str, str]:
        identity = self.module_ref.get(RequestIdentity)
        return {"user": identity.user}
```

## Request Limits

Every application serves under finite bounds on what one request may spend, and an
application that configures nothing gets them anyway. There is no setting that turns
limits on: what a deployment chooses is which figures to serve under, not whether to
have any. A request over one of them is refused with the status the bound implies
rather than served.

Five bounds, with the defaults an unconfigured application runs under:

| Bound | Default | What it bounds | What raising it costs |
| --- | --- | --- | --- |
| `max_body_bytes` | `1048576` (1 MiB) | The body read to bind ordinary parameters | Peak memory, at roughly the bound times the number of requests in flight |
| `max_upload_bytes` | `10485760` (10 MiB) | The body read to parse a multipart form | The same memory, on the routes that accept uploads; it is a separate bound so that accepting uploads does not raise the ceiling on every other route |
| `max_upload_files` | `20` | How many parts of a form may bind to one parameter | The length of a list the caller chooses, and whatever the handler does per element |
| `timeout_seconds` | `30.0` | The wall clock one request may take before it is abandoned | How long a caller can hold a worker, so the number of connections it takes to exhaust the process scales with it |
| `sync_handler_threads` | `40` | How many synchronous handlers run at once | One operating-system thread each, and the memory of its stack |

Read the defaults back out of the version you are running rather than trusting this
table:

```python
from bustan import RequestLimits

print(RequestLimits())
```

```text
RequestLimits(max_body_bytes=1048576, max_upload_bytes=10485760, max_upload_files=20, timeout_seconds=30.0, sync_handler_threads=40)
```

### Setting Them

`RequestLimits` is passed to `create_app`, and every bound left unnamed keeps its
default:

```python
from typing import Any, cast

from bustan import Controller, Module, Post, RequestLimits, create_app
from bustan.testing import AsgiTestClient


@Controller("/notes")
class NotesController:
    @Post("/")
    def create(self, title: str) -> dict[str, str]:
        return {"title": title}


@Module(controllers=[NotesController])
class AppModule:
    pass


app = create_app(
    AppModule,
    request_limits=RequestLimits(max_body_bytes=1024, timeout_seconds=60.0),
)

body = b'{"title": "' + b"a" * 4085 + b'"}'
headers = {"content-type": "application/json", "content-length": str(len(body))}

with AsgiTestClient(cast(Any, app)) as client:
    refused = client.post("/notes", content=body, headers=headers)

print(refused.status_code, refused.json()["detail"])
```

```text
413 The request body declares 4098 bytes, over the 1024 byte limit
```

The limits belong to one application rather than to the process, so two applications
assembled in one process serve under their own figures and neither has to agree with
the other. The one exception is `sync_handler_threads`, which is per event loop; see
below.

Four of the five bounds accept `None`, which removes that bound for a deployment that
has measured that it needs to, and `None` is never what an application gets by leaving
a bound out. `sync_handler_threads` is an `int` and has no `None`, because a thread
ceiling is the only thing bounding a synchronous handler that never returns and there
is nothing safe to remove it to. Every bound must be greater than zero; `RequestLimits`
refuses a smaller one where it is written rather than once per request in a log:

```python
from bustan import RequestLimits

print(RequestLimits(max_body_bytes=None, max_upload_bytes=None))

try:
    RequestLimits(timeout_seconds=0)
except ValueError as error:
    print(error)
```

```text
RequestLimits(max_body_bytes=None, max_upload_bytes=None, max_upload_files=20, timeout_seconds=30.0, sync_handler_threads=40)
timeout_seconds must be greater than zero, got 0
```

A body over a byte bound raises `RequestBodyTooLargeError`, and a request over the
budget raises `RequestTimeoutError`. Both are exported from `bustan.errors`, so an
application can catch either in an exception filter and answer it with a status of its
own. What a caller sees for each, and the four message shapes a body refusal takes, are
in [`RequestBodyTooLargeError`](TROUBLESHOOTING.md#requestbodytoolargeerror) and
[`RequestTimeoutError`](TROUBLESHOOTING.md#requesttimeouterror); the problem-details
contract those responses are rendered into is described under
[`HttpException`](TROUBLESHOOTING.md#httpexception).

One property to hold while sizing the byte bounds: a body that declares a
`Content-Length` is refused before it is read, but a body sent without one can only be
judged once it has arrived. For an undeclared body the bound decides what the handler is
handed, not what receiving the request cost, and what that cost is bounded by is
whatever the serving adapter bounds a body at on its own.

### The Timeout Does Not Interrupt A Synchronous Handler

A synchronous handler runs on a thread and Python cannot interrupt a running thread, so
`timeout_seconds` is enforced for one only once it returns. A synchronous handler that
blocks for ten minutes runs for ten minutes whatever the budget says, and the timeout is
observed when it finishes rather than at the deadline. An asynchronous handler is
cancelled at the deadline.

What bounds a synchronous handler that never returns is therefore `sync_handler_threads`
and nothing else. It caps how many of them may occupy threads at the same time, which
makes it the figure deciding how many stuck handlers it takes to stop the application
from serving. Size it with that in mind rather than as a throughput dial, and prefer an
asynchronous handler wherever the work can be awaited.

### The Thread Ceiling Is Per Event Loop

`sync_handler_threads` is the one bound that is not per application. It sets the running
event loop's own default thread limiter rather than a second limiter beside it, because
a private limiter would bound the handlers while the total number of threads stayed
whatever the two limiters happened to add up to, which is not a ceiling anyone set.

Two applications serving on one loop therefore share it, and **the last of them to serve
a request is the one whose figure stands** - including for the other application's later
requests. An application configured for four threads that shares a loop with one
configured for sixty is serving under sixty from the moment that second application
serves a request, and back under four the next time the first one does. A deployment
that needs two different thread ceilings needs two event loops to hold them.

## Operational Notes

- If no exception filter handles a `ParameterBindingError`, Bustan returns HTTP `400` with a structured payload.
- If no exception filter handles a `GuardRejectedError`, Bustan returns HTTP `403`.
- If no exception filter handles a `RequestBodyTooLargeError`, Bustan returns HTTP `413` with a structured payload.
- If no exception filter handles a `RequestTimeoutError`, Bustan returns HTTP `504` with a structured payload.
- Request-scoped pipeline components can inject `starlette.requests.Request` and other request-scoped providers.
- Interceptors execute in declaration order on the way in and unwind in reverse order on the way out.

See [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md) for the rules that make request-local guards, interceptors, and controllers safe.