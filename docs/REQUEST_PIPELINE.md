# Request Pipeline

`Bustan` runs request-time behavior in a fixed order so cross-cutting logic stays predictable.

## Execution Order

1. Guards
2. Parameter binding
3. Pipes
4. Interceptors
5. Handler
6. Response coercion

Exception filters wrap the downstream path and can translate binding errors, guard rejections, interceptor failures, or handler exceptions into application responses.

## Choosing The Right Hook

- Use a guard to allow or block request execution.
- Use a pipe to transform or validate already bound parameter values.
- Use an interceptor to wrap handler execution and shape results.
- Use an exception filter to convert exceptions into responses or structured payloads.

## Example

```python
from collections.abc import Awaitable, Callable

from bustan import Controller, Get, Guard, Interceptor, Pipe, UseGuards, UseInterceptors, UsePipes
from bustan.pipeline.context import HandlerContext, ParameterContext, RequestContext


class AuthGuard(Guard):
    async def can_activate(self, context: RequestContext) -> bool:
        return context.request.headers.get("x-user-id") is not None


class TrimPipe(Pipe):
    async def transform(self, value: object, context: ParameterContext) -> object:
        return value.strip() if isinstance(value, str) else value


class EnvelopeInterceptor(Interceptor):
    async def intercept(
        self,
        context: HandlerContext,
        call_next: Callable[[], Awaitable[object]],
    ) -> object:
        return {"data": await call_next()}


@UseGuards(AuthGuard())
@UseInterceptors(EnvelopeInterceptor())
@Controller("/messages")
class MessagesController:
    @UsePipes(TrimPipe())
    @Get("/{name}")
    def read_message(self, name: str) -> dict[str, str]:
        return {"message": f"hello {name}"}
```

## Operational Notes

- Request-scoped pipeline components can inject `Request` and other request-scoped providers.
- If no exception filter handles a `ParameterBindingError`, the framework returns HTTP `400`.
- If no exception filter handles a `GuardRejectedError`, the framework returns HTTP `403`.