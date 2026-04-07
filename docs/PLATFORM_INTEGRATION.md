# Platform Integration

`Bustan` is an architecture engine designed to provide structure *on top* of existing web frameworks, not to hide them. While Starlette is the standard default, the framework is decoupled via the **Adapter** pattern.

## The Starlette Adapter

By default, `create_app()` uses the `StarletteAdapter`. This adapter wraps a Starlette application instance and manages the conversion of Bustan's internal request pipeline into Starlette-compatible endpoints.

## Direct Request Access

Handlers and request-scoped providers can depend on the underlying request object directly. When using the `StarletteAdapter`, this is the `starlette.requests.Request` object:

```python
from bustan import Get
from starlette.requests import Request


@Get("/{user_id}")
def read_user(self, request: Request, user_id: int) -> dict[str, object]:
	return {"path": request.url.path, "user_id": user_id}
```

## Direct Response Control

If Bustan's default response coercion (which handles `dict`, `list`, and `dataclass` automatically) is not sufficient, you can return any framework-specific response instance:

```python
from bustan import Get
from starlette.responses import PlainTextResponse


@Get("/health")
def health(self) -> PlainTextResponse:
	return PlainTextResponse("ok", status_code=200)
```

## Accessing The Underlying Instance

`create_app()` returns a `Bustan` `Application` wrapper. You can access the underlying engine (e.g., the Starlette `App`) via `app.get_http_server()` to configure platform-specific features such as middleware or mounts:

```python
app = create_app(AppModule)
server = app.get_http_server()

# Configure the Starlette instance directly
server.add_middleware(...)
server.mount("/static", static_app)
```

## Bootstrap Artifacts

The `Application` wrapper also exposes internal bootstrap artifacts through public properties:

- `app.container`: The dependency injection container.
- `app.module_graph`: The discovered application module graph.
- `app.root_module`: The key of the application's root module.

These values are useful for advanced tests, runtime inspection, and building custom framework-level integrations.