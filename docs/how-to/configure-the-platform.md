# Configure The Underlying Platform

Bustan serves through an adapter, and the adapter holds a real platform object. This guide covers reaching that object to configure it, and running an application that serves no HTTP at all.

For what the port requires and what each shipped adapter provides, see [the adapter reference](../reference/adapters.md).

## Configure The Underlying Platform

Use `app.get_http_server()` when a transport-specific feature is genuinely the right tool.

```python
from typing import Any, cast

from starlette.middleware.gzip import GZipMiddleware

from bustan import Controller, Get, Module, create_app
from bustan.testing import AsgiTestClient


@Controller("/")
class RootController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[RootController])
class AppModule:
    pass


app = create_app(AppModule)
server = app.get_http_server()
server.add_middleware(GZipMiddleware, minimum_size=1)

with AsgiTestClient(cast(Any, app)) as client:
    response = client.get("/", headers={"accept-encoding": "gzip"})
    print(response.status_code, response.headers.get("content-encoding"))
```

```text
200 gzip
```

The `Application` wrapper also exposes helper methods for common integrations:

- `app.enable_cors(...)`
- `app.enable_swagger(...)`
- `await app.listen(...)`, which serves and drains gracefully; see [reference/lifecycle.md](../reference/lifecycle.md#graceful-shutdown).

## Non-HTTP Bootstrapping

Use `create_app_context()` when you want DI plus lifecycle behavior without an HTTP server. `ApplicationContext` supports `get()`, `resolve()`, `init()`, and `close()` but does not expose `listen()` or HTTP adapter access. It needs no adapter and no web server, so it is the shape a `uv add bustan` with no extra can run.
