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

## Operational Notes

- If no exception filter handles a `ParameterBindingError`, Bustan returns HTTP `400` with a structured payload.
- If no exception filter handles a `GuardRejectedError`, Bustan returns HTTP `403`.
- Request-scoped pipeline components can inject `starlette.requests.Request` and other request-scoped providers.
- Interceptors execute in declaration order on the way in and unwind in reverse order on the way out.

See [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md) for the rules that make request-local guards, interceptors, and controllers safe.