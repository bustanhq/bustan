# Escape Hatches

`bustan` is opinionated about structure, not about hiding Starlette.

## Inject The Raw Request

Handlers and request-scoped providers can depend on `starlette.requests.Request` directly:

```python
from starlette.requests import Request


@get("/{user_id}")
def read_user(self, request: Request, user_id: int) -> dict[str, object]:
    return {"path": request.url.path, "user_id": user_id}
```

## Return A Starlette Response

If the default response coercion is not what you want, return any Starlette `Response` subclass directly:

```python
from starlette.responses import PlainTextResponse


@get("/health")
def health(self) -> PlainTextResponse:
    return PlainTextResponse("ok", status_code=200)
```

## Configure The Starlette App After Bootstrap

`create_app()` returns a normal Starlette application, so you can keep using Starlette features such as middleware, mounts, and application state:

```python
app = create_app(AppModule)
app.add_middleware(...)
app.mount("/static", static_app)
```

## Reach Bootstrap Artifacts Through `app.state`

`create_app()` stores bootstrap artifacts on the Starlette application state:

- `app.state.bustan_container`
- `app.state.bustan_module_graph`
- `app.state.bustan_root_module`

Those values are useful for advanced tests, graph inspection, and framework-level integrations.