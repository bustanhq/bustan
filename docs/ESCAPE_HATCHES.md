# Escape Hatches

`Bustan` is opinionated about structure, not about hiding Starlette.

## Inject The Raw Request

Handlers and request-scoped providers can depend on `starlette.requests.Request` directly:

```python
from bustan import Get
from starlette.requests import Request


@Get("/{user_id}")
def read_user(self, request: Request, user_id: int) -> dict[str, object]:
    return {"path": request.url.path, "user_id": user_id}
```

## Return A Starlette Response

If the default response coercion is not what you want, return any Starlette `Response` subclass directly:

```python
from bustan import Get
from starlette.responses import PlainTextResponse


@Get("/health")
def health(self) -> PlainTextResponse:
    return PlainTextResponse("ok", status_code=200)
```

## Configure The Starlette App After Bootstrap

`create_app()` returns a `Bustan` `Application` wrapper. You can access the underlying Starlette instance via `app.get_http_server()` to configure middleware, mounts, and application state:

```python
app = create_app(AppModule)
server = app.get_http_server()

server.add_middleware(...)
server.mount("/static", static_app)
```

## Reach Bootstrap Artifacts Through `Application` Properties

`create_app()` returns an `Application` wrapper that exposes bootstrap artifacts:

- `app.container`
- `app.module_graph`
- `app.root_module`

Those values are useful for advanced tests, graph inspection, and framework-level integrations.