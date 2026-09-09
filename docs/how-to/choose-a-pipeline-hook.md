# Choose A Pipeline Hook

Guards, pipes, interceptors and filters all sit on the request path, and the first question is which one a piece of work belongs in. This guide answers that, then walks one request through every stage.

For the order they run in and what each one receives, see [the request pipeline reference](../reference/request-pipeline.md).

## Choose The Right Hook

- Use route middleware to wrap the entire request, including the guards, and to see the response on the way out.
- Use a guard to allow or block request execution before anything is constructed for it.
- Use a pipe to transform or validate already bound parameter values.
- Use an interceptor to wrap handler execution and shape the result.
- Use an exception filter to convert exceptions into a response payload or platform response.

## Example

```python
from typing import Any, cast

from bustan import (
    CallHandler,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    HttpResponse,
    Interceptor,
    Module,
    Pipe,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
    create_app,
)
from bustan.testing import AsgiTestClient


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
        return HttpResponse.json(
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


app = create_app(AppModule)
with AsgiTestClient(cast(Any, app)) as client:
    identified = {"x-user-id": "ada"}
    print(client.get("/messages/ada?excited=true", headers=identified).json())
    print(client.get("/messages/Error", headers=identified).status_code)
    print(client.get("/messages/ada").status_code)
```

```text
{'path': '/messages/ada', 'data': {'message': 'hello Ada', 'excited': True}}
422
403
```

The interceptor wrapped the handler's dictionary, the pipe title-cased the bound `name` before the handler saw it, the filter turned a `ValueError` into a `422`, and the guard refused the request that carried no identity - the last of these without constructing the controller at all.

## Resolving Providers Inside a Handler

`ApplicationContext.get()` resolves as though no request were being served, so it
refuses anything request-scoped. To reach a request-scoped provider from inside a
handler, a guard or an interceptor, inject `ModuleRef` and call its `get()`: it resolves
against the request currently in flight and returns the same instance the rest of that
request sees.

`ModuleRef` is an ordinary provider, so a module that injects it declares it, either in
its own `providers` or by importing `DiscoveryModule`, which exports it. A class that
asks for one without either is refused while the application is built, in the same words
as any other unreachable dependency.

```python
from typing import Any, cast

from bustan import (
    Controller,
    Get,
    HttpRequest,
    Injectable,
    Module,
    ModuleRef,
    Scope,
    create_app,
)
from bustan.testing import AsgiTestClient


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: HttpRequest) -> None:
        self.user = request.headers.get("x-user-id", "anonymous")


@Controller("/orders", scope=Scope.REQUEST)
class OrdersController:
    def __init__(self, module_ref: ModuleRef) -> None:
        self.module_ref = module_ref

    @Get("/")
    def index(self) -> dict[str, str]:
        identity = cast(RequestIdentity, self.module_ref.get(RequestIdentity))
        return {"user": identity.user}


@Module(
    controllers=[OrdersController],
    providers=[RequestIdentity, ModuleRef],
)
class AppModule:
    pass


app = create_app(AppModule)
with AsgiTestClient(cast(Any, app)) as client:
    print(client.get("/orders/", headers={"x-user-id": "ada"}).json())
    print(client.get("/orders/").json())
```

```text
{'user': 'ada'}
{'user': 'anonymous'}
```

`get()` resolves synchronously, which bounds what it can build: a token behind an
asynchronous factory cannot be awaited from inside it and is refused with `is an async
factory and cannot be called during synchronous resolution`. Declare such a dependency
in the constructor instead, where the request path awaits it.

Two more things a reference does. `get(token, strict=False)` widens a lookup its own
module cannot answer into a search of every module in the application, refusing rather
than guessing when more than one declares the token; `for_module(SomeModule)` returns a
reference that resolves through another module instead. Both keep the default - a
reference sees exactly what the class holding it sees - as the thing you have to ask to
leave.
